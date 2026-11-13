#!/usr/bin/env python3
"""Analog-partition layout of the non-overlapping clock generator (`clkgen`).

    python3 layout/analog/clkgen/gen_clkgen.py [--pdk-root ROOT] [--check]
                                               [--keep-work DIR] [--no-drc]

Regenerates `clkgen.gds` beside this script from `design/clkgen/clkgen.spice`
plus the pinned PDK (`sim/pdk.json`), and writes the two evidence files the
layout is graded on (`extract-device-count.json`, `drc.report.json`). Nothing
is hand-drawn: every polygon comes from `klt gen mos_array` and the wiring from
`klt gen-compose`, so the layout cannot drift from the schematic without this
script either changing the stream or failing.

`--check` leaves the committed files alone and compares instead:

    exit 0  fresh geometry matches the committed stream
    exit 3  geometry drift (`klt diff`, geometry-level, not raw bytes)
    exit 2  the resolved PDK differs from the `sim/pdk.json` pin
    exit 1  a klt step failed

Geometry-level rather than byte-level: a GDS carries a write timestamp, so two
identical runs are not byte-identical. See `layout/README.md`.

Flow
----
1. `clkgen_netlist` re-derives the device list and recognises the 18 static
   CMOS gates (14 inverters, 4 NOR2) structurally from the channel graph.
2. One `klt gen mos_array` per gate per flavour -- nfet row and pfet row, each
   in its own closed tap/guard ring, so the p-substrate tie sits on `vssa` and
   the n-well tie on `vdda` by construction.
3. One `klt gen-compose` per gate wires that pair into a gate cell on met1 and
   promotes its `in`/`out`/`vdda`/`vssa` ports.
4. One top-level `klt gen-compose` places the 18 gate cells in a row and wires
   the 24 nets, with the four phase outputs taken to pads on the north edge and
   `clk` to a pad on the south edge (the pin-edge contract #29 needs).
5. `klt extract` and `klt drc` produce the committed evidence.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))

from clkgen_netlist import (  # noqa: E402
    VDD,
    VSS,
    Gate,
    NetlistError,
    build_gates,
    check_identifiers,
    device_counts,
    net_names,
    parse_netlist,
    parse_ports,
    size_groups,
)

NETLIST = REPO / "design/clkgen/clkgen.spice"
PDK_PIN = REPO / "sim/pdk.json"
TOP_CELL = "clkgen"
GDS = HERE / "clkgen.gds"
EXTRACT_JSON = HERE / "extract-device-count.json"
DRC_JSON = HERE / "drc.report.json"

# ---------------------------------------------------------------------------
# Routing planes.
#
# sky130 role names are a stack, not a layer list: "metal" is li1, "metal2" is
# met1, "metal3" is met2, and so on. Each level below is a separate plane, so
# two nets that must cross never share one -- `klt gen-compose`'s router is
# point-to-point and rejects a route that crosses an already-routed net on its
# own plane, which is the whole reason the planes are split by role here.
# ---------------------------------------------------------------------------
# Inside a gate cell. `klt gen mos_array` draws nothing above li1, so met1 and
# met2 are both free there; the cell uses only those two and leaves met3, met4
# and met5 entirely to the top level, which is what keeps a top-level route
# from ever meeting a gate cell's own metal.
GATE_PLANE = "metal2"  # met1: inputs and a NOR2's series node
GATE_WIDTH_UM = 0.2
VSS_PLANE_IN_GATE = "metal2"  # met1: the nfet row's rail comb
VDD_PLANE_IN_GATE = "metal3"  # met2: the pfet row's rail comb
OUT_PLANE_IN_GATE = "metal3"  # met2: the output comb, in the channel

# The top level, which sees each gate cell only as a block with li1 ports.
TOP_PLANE = "metal4"  # met3: gate cell to gate cell
TOP_WIDTH_UM = 0.4  # met3.width.1 is 0.3um
LONG_PLANE = "metal5"  # met4: the nets that span most of the row
LONG_WIDTH_UM = 0.4  # met4.width.1 is 0.3um
RAIL_PLANE = "metal6"  # met5: both supply straps
RAIL_WIDTH_UM = 1.8  # met5.width.1 is 1.6um
PIN_LAYER = (70, 20)  # met3, matching TOP_PLANE: the cell's pins are met3
PIN_PAD_UM = 1.0

#: Left-to-right order of the 18 gate cells, by the net each one drives. Chosen
#: so the signal path runs forward along the row and only `clk`, `core1` and
#: `p2d` span a long distance; those three get their own plane below.
ROW_ORDER = [
    "clkb",
    "core1",
    "e1",
    "phi1e",
    "d1_0",
    "d1_1",
    "d1_2",
    "d1_3",
    "n1",
    "phi1",
    "phi1b",
    "p1d_a",
    "p1d",
    "core2",
    "c2a",
    "phi2",
    "p2d_a",
    "p2d",
]

#: Nets that span most of the row; kept off the default signal plane so they
#: cannot collide with the short hops between neighbouring gate cells.
LONG_NETS = ("clk", "core1", "p2d")

GATE_SPACING_UM = 2.0
NFET_PFET_GAP_UM = 3.0
PAD_MARGIN_UM = 4.0

#: The pfet row is flipped about the x axis so its gate and drain pads face the
#: routing channel between the two rows, the way a CMOS cell is normally drawn.
#: Without it both rows' gate pads face north and the channel route has to
#: reach the pfet gate from behind, crossing that block's interior (the
#: `klt gen-compose` #1895 rejection).
PFET_ORIENTATION = "mirror_x"
#: After that flip the array's north tap ring sits at the bottom, in the
#: channel; the rail is taken to the one that ends up furthest from it.
PFET_TAP = "TAP_S"
NFET_TAP = "TAP_S"


class FlowError(RuntimeError):
    """A klt step failed, or returned something this driver cannot use."""


# ---------------------------------------------------------------------------
# klt plumbing
# ---------------------------------------------------------------------------


def run_klt(args: list[str], *, cwd: pathlib.Path) -> dict:
    """Run one klt verb with `--format json` and return its parsed response."""
    proc = subprocess.run(
        ["klt", *args, "--format", "json"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    try:
        response = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise FlowError(
            f"klt {' '.join(args[:2])} produced no JSON (exit {proc.returncode}):\n"
            f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        ) from None
    if "error" in response:
        raise FlowError(f"klt {' '.join(args[:2])}: {json.dumps(response['error'])}")
    # `klt gen-compose` exits 3 when a net stayed unrouted and `klt drc` exits 3
    # when the deck found violations. Both still return a usable report, and
    # both are diagnosed by the caller (report_unrouted / the DRC summary), so
    # the response is handed back rather than collapsed into a bare exit code.
    if proc.returncode not in (0, 3):
        raise FlowError(
            f"klt {' '.join(args[:2])} exited {proc.returncode}:\n{proc.stderr[-2000:]}"
        )
    return response


def pdk_args(pdk_root: str | None) -> list[str]:
    pin = json.loads(PDK_PIN.read_text())
    args = ["--pdk", pin["variant"]]
    if pdk_root:
        args += ["--pdk-root", pdk_root]
    return args


def check_pdk(response: dict, where: str) -> None:
    """Refuse a PDK tree that is not the one `sim/pdk.json` pins."""
    pin = json.loads(PDK_PIN.read_text())
    seen = (response.get("pdk") or {}).get("version")
    if seen is not None and seen != pin["sources_stamp"]:
        raise SystemExit(
            f"REFUSE: {where} resolved PDK {seen!r}, pin is "
            f"{pin['sources_stamp']!r} (sim/pdk.json)"
        )


# ---------------------------------------------------------------------------
# Stage 2+3: one gate cell
# ---------------------------------------------------------------------------


def mos_params(gate: Gate, flavour: str) -> dict:
    """`klt gen mos_array` params for one flavour of one gate.

    `share_sd` abuts the units so neighbours share one contacted diffusion,
    which is how a real cell draws a row of transistors and is what makes this
    cell routable at all: it halves the number of terminal columns and leaves
    the columns that remain alternating between exactly two nets, 0.67um apart
    -- comfortably clear of the fixed 0.42um via landing pad `klt gen-compose`
    drops on each one.

    `mirror` then decides *which* terminals abut, and the two pull-up shapes
    need opposite answers:

    * a parallel group (every pull-down, and an inverter's pull-up) wants
      `mirror=True`, so the shared terminals are like-for-like -- S|S and D|D.
      All the sources are one node and all the drains another, which is what
      parallel devices mean.
    * a NOR2's two-deep pull-up wants `mirror=False`, so `U0_D` and `U1_S`
      become the same diffusion. That *is* the series node: it needs no wiring
      at all, and the generator asserts the two ports really do land on one
      coordinate rather than trusting that.

    `dummy=1` keeps a dummy device at each end for edge matching; `klt extract`
    recognises and drops them (`dummy_devices_dropped`), so they never enter
    the device count the netlist is graded against. The guard ring is closed on
    all four sides -- nothing needs a gap, because every wire is drawn on met1
    or above while the ring is li1.
    """
    devices = gate.pull_down if flavour == "nfet" else gate.pull_up
    units = gate.nfet_units if flavour == "nfet" else gate.pfet_units
    series = flavour == "pfet" and len(gate.pull_up) > 1
    return {
        "w_um": devices[0].w_um,
        "l_um": devices[0].l_um,
        "rows": 1,
        "cols": units,
        "dummy": 1,
        "flavor": flavour,
        "topology": "array",
        "gate_contact": True,
        "add_guard_ring": True,
        "share_sd": True,
        "mirror": not series,
    }


def mirror_x_bbox(box: dict) -> dict:
    """`box` reflected about the x axis, matching gen-compose's `mirror_x`."""
    return {"x0": box["x0"], "x1": box["x1"], "y0": -box["y1"], "y1": -box["y0"]}


def unit_map(devices: list, total: int) -> list[tuple[int, object]]:
    """Assign `m` consecutive array units to each device, in order."""
    assignment: list[tuple[int, object]] = []
    index = 0
    for device in devices:
        for _ in range(device.m):
            assignment.append((index, device))
            index += 1
    if index != total:
        raise FlowError(f"unit assignment covered {index} of {total} units")
    return assignment


def port_abs(report: dict, origin: dict, mirrored: bool, name: str) -> tuple[float, float]:
    """Absolute (x, y) of one block port, after orientation and translation."""
    for port in report.get("ports", []):
        if port["name"] == name:
            y = -port["y_um"] if mirrored else port["y_um"]
            return (port["x_um"] + origin["x"], y + origin["y"])
    raise FlowError(f"block has no port {name!r}")


def gate_nets(
    gate: Gate, coords: dict[tuple[str, str], tuple[float, float]]
) -> dict[str, list[dict]]:
    """Every internal net of one gate cell, as `{block, port}` pin lists.

    Because the rows are abutted (`share_sd`), two port names can name the same
    physical diffusion -- `U0_D` and `U1_D` of a mirrored parallel pair, or
    `U0_D` and `U1_S` of a series pair. Terminals are therefore collected by
    *coordinate*, not by name, so each physical pad is wired exactly once.
    """
    nets: dict[str, list[dict]] = {}

    def add(net: str, block: str, port: str) -> None:
        here = coords[(block, port)]
        entries = nets.setdefault(net, [])
        if any(coords[(e["block"], e["port"])] == here for e in entries):
            return  # same physical diffusion, already wired
        entries.append({"block": block, "port": port})

    for index, device in unit_map(gate.pull_down, gate.nfet_units):
        add(gate.out, "n", f"U{index}_D")
        add(VSS, "n", f"U{index}_S")
        add(device.gate, "n", f"U{index}_G")
    add(VSS, "n", NFET_TAP)

    pull_up = gate.pull_up
    if len(pull_up) == 1:
        for index, device in unit_map(pull_up, gate.pfet_units):
            add(VDD, "p", f"U{index}_S")
            add(gate.out, "p", f"U{index}_D")
            add(device.gate, "p", f"U{index}_G")
    elif len(pull_up) == 2:
        rail_side, out_side = pull_up
        if coords[("p", "U0_D")] != coords[("p", "U1_S")]:
            raise FlowError(
                f"gate {gate.out}: the pull-up's series node is not a shared "
                "diffusion -- `share_sd` did not abut U0_D with U1_S"
            )
        add(VDD, "p", "U0_S")
        add(gate.out, "p", "U1_D")
        add(rail_side.gate, "p", "U0_G")
        add(out_side.gate, "p", "U1_G")
    else:
        raise FlowError(
            f"gate {gate.out}: {len(pull_up)}-deep pull-up stack is not laid out"
        )
    add(VDD, "p", PFET_TAP)
    return nets


def comb_legs(
    pins: list[dict],
    coords: dict[tuple[str, str], tuple[float, float]],
    bus_y: float,
) -> list[dict]:
    """Chain `pins` left-to-right through a horizontal bus at `bus_y`.

    `klt gen-compose` routes a >2-pin net as a nearest-first spanning tree,
    which for a transistor row means a backbone running straight along the row,
    over every other net's pad and over the 0.42um via landing pad any route to
    those pads drops. A comb instead gives each terminal its own riser out to a
    bus no other net uses, so the only thing left at the row's own y is each
    terminal's own landing pad -- and with the rows abutted, the pads that
    remain are a clear 0.67um apart.
    """
    ordered = sorted(pins, key=lambda pin: coords[(pin["block"], pin["port"])][0])
    return [
        {
            "from_pin": first,
            "to_pin": second,
            "waypoints_um": [
                [coords[(first["block"], first["port"])][0], bus_y],
                [coords[(second["block"], second["port"])][0], bus_y],
            ],
        }
        for first, second in zip(ordered, ordered[1:])
    ]


def gate_connectivity(
    gate: Gate,
    nets: dict[str, list[dict]],
    coords: dict[tuple[str, str], tuple[float, float]],
    buses: dict[str, float],
) -> tuple[list[dict], list[dict]]:
    """Wire one gate cell, as `connectivity[]` entries plus promoted `pins[]`.

    Four buses, each in a band nothing else occupies:

    * `vssa` on met1, between the nfet row and its own tap ring;
    * `vdda` on met1, likewise above the flipped pfet row;
    * the output on met2, on a bus in the channel between the two rows;
    * every input on met1, on a second channel bus.

    The output and the inputs share the channel but not a plane, and their
    risers leave pads that sit 3.7um apart in y (a gate contact is lifted clear
    of its own S/D row), so their via landing pads never meet either.
    """
    connectivity: list[dict] = []
    for net, pins in nets.items():
        if len(pins) < 2:
            raise FlowError(
                f"gate {gate.out}: net {net!r} has a single terminal {pins}"
            )
        if net == VSS:
            plane, bus = VSS_PLANE_IN_GATE, buses["vss"]
        elif net == VDD:
            plane, bus = VDD_PLANE_IN_GATE, buses["vdd"]
        elif net == gate.out:
            plane, bus = OUT_PLANE_IN_GATE, buses["out"]
        else:
            plane, bus = GATE_PLANE, buses["in"]
        connectivity.append(
            {
                "net": net,
                "pins": pins,
                "layer_role": plane,
                "width_um": GATE_WIDTH_UM,
                "legs": comb_legs(pins, coords, bus),
            }
        )

    # Promoted ports. Each is a terminal this cell's own wiring already covers,
    # so the top level's via drop lands on that net's own metal rather than
    # beside it: the output on its left-most drain, an input on its first gate
    # pad, and each rail on its tap ring's west bar -- outside the array and
    # clear of every bus above.
    def first_of(net: str) -> dict:
        pin = min(nets[net], key=lambda e: coords[(e["block"], e["port"])][0])
        return {"net": net, "block": pin["block"], "port": pin["port"]}

    promoted = [first_of(gate.out)]
    promoted += [first_of(net) for net in gate.inputs]
    promoted.append({"net": VSS, "block": "n", "port": "TAP_W"})
    promoted.append({"net": VDD, "block": "p", "port": "TAP_W"})
    return connectivity, promoted


def build_gate_cell(gate: Gate, work: pathlib.Path, pdk: list[str]) -> dict:
    """Generate the two device arrays of one gate and wire them into a cell."""
    cell = f"clkgen_{gate.out}"
    reports: dict[str, dict] = {}
    for key, flavour in (("n", "nfet"), ("p", "pfet")):
        reports[key] = run_klt(
            [
                "gen",
                "mos_array",
                *pdk,
                "--cell-name",
                f"{cell}_{flavour}",
                "--params",
                json.dumps(mos_params(gate, flavour)),
                "-o",
                str(work / f"{cell}_{flavour}.gds"),
            ],
            cwd=work,
        )
        check_pdk(reports[key], f"gen mos_array {cell}_{flavour}")

    n_box = reports["n"]["bbox_um"]
    # The pfet block is placed in its *oriented* frame: gen-compose applies
    # blocks[].orientation to the block's own bbox/ports before translating it,
    # so the origin below is computed against the flipped box, not the one
    # `klt gen` reported.
    p_box = mirror_x_bbox(reports["p"]["bbox_um"])
    origins = {
        "n": {"x": -n_box["x0"], "y": -n_box["y0"]},
        "p": {
            "x": -p_box["x0"],
            "y": (n_box["y1"] - n_box["y0"]) + NFET_PFET_GAP_UM - p_box["y0"],
        },
    }

    coords: dict[tuple[str, str], tuple[float, float]] = {}
    for key, mirrored in (("n", False), ("p", True)):
        for port in reports[key]["ports"]:
            coords[(key, port["name"])] = port_abs(
                reports[key], origins[key], mirrored, port["name"]
            )

    # Bus heights. Each rail bus sits between the *edge* of its own row's
    # devices and that row's tap ring -- a band that holds nothing else,
    # because `klt gen mos_array` draws no metal above li1 at all (checked: it
    # emits 65/20, 65/44, 66/20, 66/44, 67/20, 83/20, 93/44, 94/20, 95/20 and
    # nothing higher). A unit device's active spans `w_um` centred on its own
    # S/D pads, so the edge is half a device width off the pad row -- not the
    # pad row itself, which for the W=12 output pfets is 6um away from it.
    n_row_y = coords[("n", "U0_S")][1]
    p_row_y = coords[("p", "U0_S")][1]
    n_edge = n_row_y - gate.pull_down[0].w_um / 2  # nfet row's south edge
    p_edge = p_row_y + gate.pull_up[0].w_um / 2  # pfet row's north edge (flipped)
    channel_bottom = n_box["y1"] - n_box["y0"]
    buses = {
        "vss": (coords[("n", NFET_TAP)][1] + n_edge) / 2,
        "vdd": (coords[("p", PFET_TAP)][1] + p_edge) / 2,
        # Two buses in the channel between the rows, on different planes.
        "out": channel_bottom + NFET_PFET_GAP_UM * 0.35,
        "in": channel_bottom + NFET_PFET_GAP_UM * 0.70,
    }

    nets = gate_nets(gate, coords)
    connectivity, promoted = gate_connectivity(gate, nets, coords, buses)
    request = {
        "schema": "klt.gen_compose.request/1",
        "pdk": {"variant": json.loads(PDK_PIN.read_text())["variant"]},
        "blocks": [
            {"id": "n", "generator_report": reports["n"]},
            {
                "id": "p",
                "generator_report": reports["p"],
                "orientation": PFET_ORIENTATION,
            },
        ],
        "placement": {
            "strategy": "explicit",
            "order": ["n", "p"],
            "origins_um": origins,
        },
        "connectivity": connectivity,
        "routing": {
            "layer_role": GATE_PLANE,
            "width_um": GATE_WIDTH_UM,
            "cross_block_layer_role": OUT_PLANE_IN_GATE,
        },
        "pins": promoted,
        "options": {"cell_name": cell, "output": str(work / f"{cell}.gds")},
    }
    path = work / f"{cell}.request.json"
    path.write_text(json.dumps(request, indent=1))
    response = run_klt(["gen-compose", str(path)], cwd=work)
    report_unrouted(response, cell)
    return response


# ---------------------------------------------------------------------------
# Stage 4: the top cell
# ---------------------------------------------------------------------------


def report_unrouted(response: dict, where: str) -> None:
    """Fail loudly on any net the router could not draw."""
    problems = []
    for net in response.get("nets", []):
        if net.get("status") == "routed":
            continue
        reasons = [
            (leg.get("reason") or "no reason reported")
            for leg in net.get("legs", [])
            if not leg.get("routed")
        ]
        problems.append(f"  {net['net']}: {net.get('status')}: {'; '.join(reasons)}")
    if problems:
        raise FlowError(f"{where}: unrouted net(s)\n" + "\n".join(problems))


def pad_block(
    name: str, x_um: float, y_um: float, facing: int, work: pathlib.Path
) -> dict:
    """A bare met2 landing pad, used to put a cell pin on a chosen edge."""
    half = PIN_PAD_UM / 2
    response = run_klt(
        [
            "draw",
            "--cell-name",
            name,
            "-o",
            str(work / f"{name}.gds"),
            "--params",
            json.dumps(
                {
                    "shapes": [
                        {
                            "layer": list(PIN_LAYER),
                            "rect_um": [
                                x_um - half,
                                y_um - half,
                                x_um + half,
                                y_um + half,
                            ],
                        }
                    ]
                }
            ),
        ],
        cwd=work,
    )
    return {
        "id": name,
        "cell": {
            "gds_path": response["gds_path"],
            "cell_name": name,
            "bbox_um": response["bbox_um"],
            "ports": [
                {
                    "name": "P",
                    "layer": {"layer": PIN_LAYER[0], "datatype": PIN_LAYER[1]},
                    "x_um": x_um,
                    "y_um": y_um,
                    "width_um": PIN_PAD_UM,
                    "direction_deg": facing,
                }
            ],
        },
    }


def build_top(
    gates: dict[str, Gate],
    cells: dict[str, dict],
    ports: list[str],
    work: pathlib.Path,
    out_gds: pathlib.Path,
) -> dict:
    """Place the 18 gate cells in a row and wire the netlist's 24 nets."""
    blocks: list[dict] = []
    origins: dict[str, dict] = {}
    order: list[str] = []
    cursor = 0.0
    bottom = 0.0
    top = 0.0
    for net in ROW_ORDER:
        block_id = f"g_{net}"
        box = cells[net]["bbox_um"]
        blocks.append({"id": block_id, "generator_report": cells[net]})
        origins[block_id] = {"x": cursor - box["x0"], "y": -box["y0"]}
        order.append(block_id)
        cursor += (box["x1"] - box["x0"]) + GATE_SPACING_UM
        top = max(top, box["y1"] - box["y0"])
    row_width = cursor - GATE_SPACING_UM

    # Pin pads: the four phase outputs on the north edge (the edge #29 puts
    # against the integrators), `clk` on the south edge opposite them, and the
    # two supplies on the west edge.
    outputs = ["phi1e", "phi1", "phi1b", "phi2"]
    pads: dict[str, dict] = {}
    for index, net in enumerate(outputs):
        x = row_width * (index + 1) / (len(outputs) + 1)
        pad = pad_block(f"pad_{net}", x, top + PAD_MARGIN_UM, 270, work)
        pads[net] = pad
    pads["clk"] = pad_block("pad_clk", row_width / 2, bottom - PAD_MARGIN_UM, 90, work)
    pads[VDD] = pad_block("pad_vdda", -PAD_MARGIN_UM, top * 0.66, 0, work)
    pads[VSS] = pad_block("pad_vssa", -PAD_MARGIN_UM, top * 0.33, 0, work)
    for net, pad in pads.items():
        blocks.append(pad)
        origins[pad["id"]] = {"x": 0.0, "y": 0.0}
        order.append(pad["id"])

    # Connectivity: one entry per net of the netlist, gathering the gate cells
    # that drive it or read it, plus its pad when it is a cell port.
    pins_by_net: dict[str, list[dict]] = {}
    for net, gate in gates.items():
        pins_by_net.setdefault(net, []).append({"block": f"g_{net}", "port": net})
        for source in gate.inputs:
            pins_by_net.setdefault(source, []).append(
                {"block": f"g_{net}", "port": source}
            )
    for rail in (VDD, VSS):
        for net in ROW_ORDER:
            pins_by_net.setdefault(rail, []).append(
                {"block": f"g_{net}", "port": rail}
            )
    for net, pad in pads.items():
        pins_by_net.setdefault(net, []).append({"block": pad["id"], "port": "P"})

    connectivity = []
    for net, pins in pins_by_net.items():
        if len(pins) < 2:
            raise FlowError(f"net {net!r} has a single connection: {pins}")
        entry: dict = {"net": net, "pins": pins}
        if net in (VDD, VSS):
            entry |= {"layer_role": RAIL_PLANE, "width_um": RAIL_WIDTH_UM}
        elif net in LONG_NETS:
            entry |= {"layer_role": LONG_PLANE, "width_um": LONG_WIDTH_UM}
        connectivity.append(entry)

    request = {
        "schema": "klt.gen_compose.request/1",
        "pdk": {"variant": json.loads(PDK_PIN.read_text())["variant"]},
        "blocks": blocks,
        "placement": {
            "strategy": "explicit",
            "order": order,
            "origins_um": origins,
        },
        "connectivity": connectivity,
        "routing": {
            "layer_role": TOP_PLANE,
            "width_um": TOP_WIDTH_UM,
            "cross_block_layer_role": LONG_PLANE,
        },
        "pins": [
            {"net": net, "block": pads[net]["id"], "port": "P"} for net in ports
        ],
        "options": {"cell_name": TOP_CELL, "output": str(out_gds)},
    }
    path = work / "clkgen.request.json"
    path.write_text(json.dumps(request, indent=1))
    response = run_klt(["gen-compose", str(path)], cwd=work)
    report_unrouted(response, TOP_CELL)
    return response


# ---------------------------------------------------------------------------
# Stage 5: evidence
# ---------------------------------------------------------------------------


def run_extract(gds: pathlib.Path, work: pathlib.Path, pdk: list[str]) -> dict:
    return run_klt(
        [
            "extract",
            str(gds),
            "--deck",
            "sky130",
            "--top",
            TOP_CELL,
            *pdk,
            "--no-netlist",
        ],
        cwd=work,
    )


def run_drc(gds: pathlib.Path, work: pathlib.Path, pdk: list[str]) -> dict:
    return run_klt(
        ["drc", str(gds), "--deck", "sky130", "--top", TOP_CELL, *pdk],
        cwd=work,
    )


def device_count_evidence(
    extract: dict, devices: list, expected: dict[str, dict[str, int]]
) -> dict:
    """The committed device-count record, and whether it matches the netlist."""
    seen = extract.get("device_counts") or {}
    drawn = {model: counts["drawn"] for model, counts in expected.items()}
    lines = {model: counts["lines"] for model, counts in expected.items()}
    match = {model: seen.get(model, 0) == count for model, count in drawn.items()}
    return {
        "schema_version": 1,
        "top": TOP_CELL,
        "netlist": str(NETLIST.relative_to(REPO)),
        "comparison": "extracted vs netlist device lines expanded by SPICE m=",
        "netlist_device_lines": lines,
        "netlist_devices_drawn": drawn,
        "extracted_device_counts": seen,
        "dummy_devices_dropped": extract.get("dummy_devices_dropped"),
        "match": match,
        "matches_netlist": all(match.values()),
        "size_groups": [
            {"model": model, "l_um": l_um, "w_um": w_um, "units": units}
            for (model, l_um, w_um), units in sorted(size_groups(devices).items())
        ],
        "provenance": extract.get("provenance"),
        "pdk": extract.get("pdk"),
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def generate(work: pathlib.Path, pdk: list[str], out_gds: pathlib.Path) -> dict:
    text = NETLIST.read_text()
    ports = parse_ports(text)
    check_identifiers(net_names(text) + ports)
    devices = parse_netlist(text)
    gate_list = build_gates(devices)
    gates = {gate.out: gate for gate in gate_list}

    missing = sorted(set(gates) ^ set(ROW_ORDER))
    if missing:
        raise FlowError(
            f"ROW_ORDER does not match the netlist's gates (symmetric difference "
            f"{missing}) -- the netlist changed; update ROW_ORDER"
        )
    for port in ports:
        if port not in (VDD, VSS) and port not in gates and port != "clk":
            raise FlowError(f"port {port!r} is neither a rail, `clk`, nor a gate output")

    cells: dict[str, dict] = {}
    for net in ROW_ORDER:
        cells[net] = build_gate_cell(gates[net], work, pdk)
    top = build_top(gates, cells, ports, work, out_gds)
    check_pdk(top, "gen-compose clkgen")
    return {"top": top, "devices": devices, "ports": ports}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk-root", help="explicit PDK install root")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare against the committed stream, write nothing",
    )
    parser.add_argument("--keep-work", help="keep intermediates in this directory")
    parser.add_argument(
        "--no-drc", action="store_true", help="skip the DRC step (generation only)"
    )
    args = parser.parse_args()
    pdk = pdk_args(args.pdk_root)

    with tempfile.TemporaryDirectory(prefix="clkgen-") as tmp:
        work = pathlib.Path(args.keep_work) if args.keep_work else pathlib.Path(tmp)
        work.mkdir(parents=True, exist_ok=True)
        fresh = work / "clkgen.gds"
        try:
            built = generate(work, pdk, fresh)
        except (FlowError, NetlistError) as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1

        extract = run_extract(fresh, work, pdk)
        check_pdk(extract, "extract")
        evidence = device_count_evidence(
            extract, built["devices"], device_counts(built["devices"])
        )
        drc = None
        if not args.no_drc:
            drc = run_drc(fresh, work, pdk)
            check_pdk(drc, "drc")

        print(f"top cell      : {TOP_CELL}")
        print(f"pins          : {', '.join(built['ports'])}")
        print(
            "devices       : extracted "
            f"{extract.get('device_counts')} vs netlist drawn "
            f"{evidence['netlist_devices_drawn']} -> "
            f"{'MATCH' if evidence['matches_netlist'] else 'MISMATCH'}"
        )
        print(f"dummies dropped: {extract.get('dummy_devices_dropped')}")
        if drc is not None:
            print(
                f"drc           : {drc.get('status')}, "
                f"{drc.get('violation_count')} violation(s)"
            )

        if not evidence["matches_netlist"]:
            print("FAILED: extracted device count differs from the netlist", file=sys.stderr)
            return 1

        if args.check:
            if not GDS.exists():
                print(f"FAILED: {GDS} is missing", file=sys.stderr)
                return 3
            diff = run_klt(["diff", str(GDS), str(fresh)], cwd=work)
            same = diff.get("identical")
            print(f"geometry diff : {'identical' if same else 'DIFFERS'}")
            if not same:
                print(json.dumps(diff, indent=1)[:4000], file=sys.stderr)
            return 0 if same else 3

        shutil.copyfile(fresh, GDS)
        EXTRACT_JSON.write_text(json.dumps(evidence, indent=1) + "\n")
        if drc is not None:
            DRC_JSON.write_text(json.dumps(drc, indent=1) + "\n")
        print(f"wrote         : {GDS.relative_to(REPO)}")
        return 0


if __name__ == "__main__":
    sys.exit(main())

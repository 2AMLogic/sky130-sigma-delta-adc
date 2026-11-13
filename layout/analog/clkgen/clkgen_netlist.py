"""Read `design/clkgen/clkgen.spice` and recognise its CMOS gates.

The netlist is the reference for this layout (issue #121): the generator never
carries a transcribed device list, it re-derives one here on every run, so a
schematic change shows up as a changed layout (or a loud failure) rather than
as silent drift.

Two stages:

1. :func:`parse_netlist` -- flatten SPICE continuation lines and read every
   `X...` device line into a :class:`Device` (channel terminals `ta`/`tb`,
   gate, bulk, model, `L`, `W`, and the parallel multiplicity `m`).
2. :func:`build_gates` -- recognise static CMOS gates structurally, by walking
   the channel graph from each output net to the rails. Nothing is matched by
   instance name, so a renamed device still lands in the right gate.

`m` matters: eight of the 42 device lines carry `m=2`/`m=3`/`m=4` (the four
phase-output inverters), which SPICE reads as that many devices in parallel.
The layout draws them, so the drawn device count is 56, not 42 -- see
`DEVICE-COUNT.md` beside this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

VDD = "vdda"
VSS = "vssa"

#: SPICE prefix every `sky130_fd_pr` model token in this netlist carries.
_MODEL_PREFIX = "sky130_fd_pr__"


class NetlistError(RuntimeError):
    """The netlist does not have the shape this generator can lay out."""


@dataclass(frozen=True)
class Device:
    """One `X...` device line, with its channel terminals unordered.

    `ta`/`tb` are the two channel terminals as written (SPICE orders a MOSFET
    `D G S B`, but D and S are interchangeable and xschem writes the pfets of
    this netlist source-at-the-output). Which one is the source is decided by
    the rail each gate walk reaches, never by the column it sits in.
    """

    name: str
    ta: str
    tb: str
    gate: str
    bulk: str
    model: str  # "nfet" or "pfet"
    l_um: float
    w_um: float
    m: int

    def other(self, net: str) -> str:
        """The channel terminal that is not `net`."""
        if net == self.ta:
            return self.tb
        if net == self.tb:
            return self.ta
        raise NetlistError(f"{self.name}: {net!r} is not a channel terminal")

    @property
    def size(self) -> tuple[str, float, float]:
        return (self.model, self.l_um, self.w_um)


@dataclass
class Gate:
    """One static CMOS gate, named by the net it drives."""

    out: str
    #: Pull-down nfets, all in parallel between `out` and VSS.
    pull_down: list[Device]
    #: Pull-up pfets, VDD -> ... -> `out`, in series order from the rail.
    pull_up: list[Device]
    #: Input nets, in a stable order (pull-down order, then any pull-up-only).
    inputs: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return {1: "inv", 2: "nor2"}.get(len(self.pull_down), f"nor{len(self.pull_down)}")

    @property
    def m(self) -> int:
        return self.pull_down[0].m

    @property
    def nfet_units(self) -> int:
        return sum(d.m for d in self.pull_down)

    @property
    def pfet_units(self) -> int:
        return sum(d.m for d in self.pull_up)


def _flatten(text: str) -> list[str]:
    """Join SPICE `+` continuation lines onto the line they continue."""
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("+"):
            if not lines:
                raise NetlistError("continuation line before any statement")
            lines[-1] += " " + stripped[1:].strip()
        else:
            lines.append(stripped)
    return lines


def parse_ports(text: str) -> list[str]:
    """The `.subckt` port list, in declaration order."""
    for line in _flatten(text):
        if line.lower().startswith(".subckt"):
            tokens = line.split()
            if len(tokens) < 2:
                raise NetlistError(".subckt line has no name")
            return tokens[2:]
    raise NetlistError("no .subckt line found")


def parse_netlist(text: str) -> list[Device]:
    """Every `X...` device line of `text`, as :class:`Device` records."""
    devices: list[Device] = []
    for line in _flatten(text):
        if not line or not line.startswith(("X", "x")):
            continue
        tokens = line.split()
        if len(tokens) < 6:
            raise NetlistError(f"{tokens[0]}: too few tokens for a MOSFET line")
        name, ta, gate, tb, bulk, model = tokens[:6]
        params: dict[str, str] = {}
        for token in tokens[6:]:
            if "=" in token:
                key, _, value = token.partition("=")
                params[key.lower()] = value
        if not model.startswith(_MODEL_PREFIX):
            raise NetlistError(f"{name}: unexpected model {model!r}")
        flavour = model[len(_MODEL_PREFIX) :]
        if flavour not in ("nfet_01v8", "pfet_01v8"):
            raise NetlistError(f"{name}: unsupported model {flavour!r}")
        for required in ("l", "w"):
            if required not in params:
                raise NetlistError(f"{name}: missing {required.upper()}=")
        if params.get("nf", "1") != "1":
            raise NetlistError(f"{name}: nf={params['nf']} -- only nf=1 is laid out")
        m = int(float(params.get("m", params.get("mult", "1"))))
        if m < 1:
            raise NetlistError(f"{name}: m={m} must be >= 1")
        mult = int(float(params.get("mult", str(m))))
        if mult != m:
            raise NetlistError(f"{name}: mult={mult} disagrees with m={m}")
        devices.append(
            Device(
                name=name,
                ta=ta,
                gate=gate,
                tb=tb,
                bulk=bulk,
                model="nfet" if flavour.startswith("nfet") else "pfet",
                l_um=float(params["l"]),
                w_um=float(params["w"]),
                m=m,
            )
        )
    if not devices:
        raise NetlistError("no device lines found")
    return devices


def _walk(out: str, pool: list[Device], rail: str) -> list[Device]:
    """Devices of `pool` on the conducting path from `out` down to `rail`.

    Returned in series order from the rail to `out`, so a NOR2's pull-up comes
    back `[rail-side device, output-side device]` and the layout can place the
    stack left-to-right without re-deriving the order.
    """
    found: list[Device] = []
    seen: set[str] = set()
    frontier = [out]
    while frontier:
        net = frontier.pop()
        for device in pool:
            if device.name in seen or net not in (device.ta, device.tb):
                continue
            seen.add(device.name)
            found.append(device)
            nxt = device.other(net)
            if nxt != rail:
                frontier.append(nxt)
    if not found:
        return []
    # Order from the rail outward: a device touching the rail comes first.
    ordered: list[Device] = []
    remaining = list(found)
    reached = {rail}
    while remaining:
        step = [d for d in remaining if d.ta in reached or d.tb in reached]
        if not step:
            raise NetlistError(
                f"net {out!r}: devices {[d.name for d in remaining]} do not "
                f"connect back to {rail!r}"
            )
        for device in step:
            reached.add(device.ta)
            reached.add(device.tb)
            remaining.remove(device)
        ordered.extend(step)
    return ordered


def build_gates(devices: list[Device]) -> list[Gate]:
    """Recognise the netlist's static CMOS gates, one per driven net.

    A gate's output is any non-rail net that is a channel terminal of at least
    one nfet *and* at least one pfet -- that is what distinguishes a driven
    node from an internal series node (a NOR2's `*_m`, which only ever touches
    pfets). Raises :class:`NetlistError` unless every device lands in exactly
    one gate.
    """
    nfets = [d for d in devices if d.model == "nfet"]
    pfets = [d for d in devices if d.model == "pfet"]
    nfet_terminals = {t for d in nfets for t in (d.ta, d.tb)}
    pfet_terminals = {t for d in pfets for t in (d.ta, d.tb)}
    outputs = sorted((nfet_terminals & pfet_terminals) - {VDD, VSS})

    gates: list[Gate] = []
    for out in outputs:
        pull_down = _walk(out, nfets, VSS)
        pull_up = _walk(out, pfets, VDD)
        if not pull_down or not pull_up:
            raise NetlistError(f"net {out!r}: incomplete CMOS gate")
        gate = Gate(out=out, pull_down=pull_down, pull_up=pull_up)
        gate.inputs = _gate_inputs(gate)
        _validate(gate)
        gates.append(gate)

    assigned = [d.name for g in gates for d in (*g.pull_down, *g.pull_up)]
    if len(assigned) != len(set(assigned)):
        duplicated = sorted({n for n in assigned if assigned.count(n) > 1})
        raise NetlistError(f"devices claimed by more than one gate: {duplicated}")
    missing = sorted({d.name for d in devices} - set(assigned))
    if missing:
        raise NetlistError(f"devices in no gate: {missing}")
    return gates


def _gate_inputs(gate: Gate) -> list[str]:
    """Input nets, pull-down order first so a NOR2's A/B order is stable."""
    inputs: list[str] = []
    for device in (*gate.pull_down, *gate.pull_up):
        if device.gate not in inputs:
            inputs.append(device.gate)
    return inputs


def _validate(gate: Gate) -> None:
    """Reject any gate shape the layout builder cannot draw."""
    for device in gate.pull_down:
        # A parallel pull-down device touches the output on one channel
        # terminal and the rail on the other. A device that touches neither --
        # or touches the output but not the rail -- is one link of a series
        # stack (a NAND), which this generator does not lay out.
        touches_output = gate.out in (device.ta, device.tb)
        if not touches_output or device.other(gate.out) != VSS:
            raise NetlistError(
                f"gate {gate.out!r}: nfet {device.name} is in a series stack -- "
                "only parallel pull-downs are laid out"
            )
    sizes = {d.size for d in gate.pull_down}
    if len(sizes) != 1:
        raise NetlistError(f"gate {gate.out!r}: mixed pull-down sizes {sorted(sizes)}")
    sizes = {d.size for d in gate.pull_up}
    if len(sizes) != 1:
        raise NetlistError(f"gate {gate.out!r}: mixed pull-up sizes {sorted(sizes)}")
    multiplicities = {d.m for d in (*gate.pull_down, *gate.pull_up)}
    if len(multiplicities) != 1:
        raise NetlistError(
            f"gate {gate.out!r}: devices disagree on m {sorted(multiplicities)}"
        )
    if gate.m != 1 and len(gate.pull_up) != 1:
        raise NetlistError(
            f"gate {gate.out!r}: m={gate.m} with a {len(gate.pull_up)}-deep pull-up "
            "stack -- the series stack is only laid out at m=1"
        )
    if len(gate.pull_down) != len(gate.pull_up):
        raise NetlistError(
            f"gate {gate.out!r}: {len(gate.pull_down)} pull-down vs "
            f"{len(gate.pull_up)} pull-up devices -- not a NOR/inverter shape"
        )
    for device in (*gate.pull_down, *gate.pull_up):
        want = VSS if device.model == "nfet" else VDD
        if device.bulk != want:
            raise NetlistError(
                f"{device.name}: bulk {device.bulk!r}, expected {want!r}"
            )


def device_counts(devices: list[Device]) -> dict[str, dict[str, int]]:
    """Per-model `{lines, drawn}` counts: `X` lines, and lines x `m`."""
    counts: dict[str, dict[str, int]] = {}
    for device in devices:
        entry = counts.setdefault(device.model, {"lines": 0, "drawn": 0})
        entry["lines"] += 1
        entry["drawn"] += device.m
    return counts


def size_groups(devices: list[Device]) -> dict[tuple[str, float, float], int]:
    """Drawn unit count per distinct `(model, L, W)`."""
    groups: dict[tuple[str, float, float], int] = {}
    for device in devices:
        groups[device.size] = groups.get(device.size, 0) + device.m
    return groups


def net_names(text: str) -> list[str]:
    """Every net the netlist mentions, sorted, rails first."""
    devices = parse_netlist(text)
    nets = {t for d in devices for t in (d.ta, d.tb, d.gate, d.bulk)}
    rails = [n for n in (VDD, VSS) if n in nets]
    return rails + sorted(nets - set(rails))


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def check_identifiers(names: list[str]) -> None:
    """Refuse a net name that cannot be written as a GDS cell/label token."""
    bad = [n for n in names if not _IDENT.match(n)]
    if bad:
        raise NetlistError(f"net names unusable as layout identifiers: {bad}")

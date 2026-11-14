#!/usr/bin/env python3
"""layout/analog/ota_fd/gen_ota_fd.py -- generate the OTA cell's GDS (issue #118).

The single reviewable source for ``layout/analog/ota_fd/ota_fd.gds``: every
polygon in that stream is either emitted by ``klt gen`` (one call per device
group) or by this script's own floorplan/router through ``klt draw``.  Nothing
is hand-drawn and nothing is edited in a GUI.

    python3 layout/analog/ota_fd/gen_ota_fd.py            # regenerate + verify + emit
    python3 layout/analog/ota_fd/gen_ota_fd.py --check    # regenerate into a temp
                                                          # dir and byte-compare

Reference netlist: ``design/ota/ota_fd.spice`` (29 device lines: 14
``nfet_01v8``, 9 ``pfet_01v8``, 3 ``cap_mim_m3_1``, 1 ``res_high_po_0p35``,
2 ``res_xhigh_po_0p35``), ports
``vdda vssa inp inn outp outn vcm ibias``.  Sizing rationale:
``design/ota/SIZING.md``.  PDK pin: ``sim/pdk.json`` (sky130A, open_pdks
``f6eeac7``), resolved from ``~/.ciel`` unless ``--pdk-root`` says otherwise.

Method (the pinned sibling ``2AMLogic/sky130-comparator`` at
``a0767fa5a4bedc9128a7e95b8b512075536522c8``, ``layout/gen_comparator.py``, is
the pattern):

* **Devices** are 100% ``klt gen`` geometry.  A matched pair is one
  ``diff_pair`` block drawn as a common-centroid cross-quad; a single device
  is a ``mos_array``; the resistors and MiM capacitors are ``res_array`` /
  ``cap_array``.  A netlist device with ``mult=M`` is drawn as ``splits=M``
  interleaved unit instances of the netlist's own ``W`` (so the drawn total
  width equals the schematic's), except for the two ``mult=1`` matched pairs,
  which are drawn as ``splits=2`` half-width units so that they too get a
  cross-quad -- the same trade the sibling's input pair makes.
* **Body ties** are two ``guard_ring`` blocks: an ``add_well=false`` ring
  (p+ tap in the p-substrate, ``psdm``) around the nFET rows tied to ``vssa``,
  and an ``add_well=true`` ring (n+ tap in an n-well, ``nsdm``) around the
  pFET row tied to ``vdda``.  The second ring's own n-well is a solid box over
  its whole extent, so it merges with each pFET block's local well.
* **Placement and every wire** come from this script: blocks are packed into
  five rows, and the router emits a ``klt draw`` shape document that
  ``klt gen-compose`` merges in as a placement-only block
  (``placement.strategy: "explicit"``, no ``routing`` block).  ``gen-compose``
  is a placer here, never a router -- the same split the sibling documents.
* **Routing discipline** (two layers plus a cap riser):
  ``met1`` carries every horizontal run and the short vertical jogs onto a
  pad; ``met2`` carries per-anchor vertical trunks and nothing else; every
  trunk gets its own global x column on a 0.5 um grid, so two trunks can never
  share one.  MiM capacitor terminals sit on ``met3``/``met4``, so each gets a
  short same-layer run out of the block followed by a via stack down to met2.

Determinism: no randomness, every iteration order is sorted or table-driven,
so a re-run at the same klt build reproduces the stream byte for byte --
which is what ``--check`` asserts.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

# --- sky130A GDS layer numbers ------------------------------------------------
L_LI1 = (67, 20)
L_MCON = (67, 44)
L_MET1 = (68, 20)
L_MET1_PIN = (68, 5)
L_VIA = (68, 44)
L_MET2 = (69, 20)
L_VIA2 = (69, 44)
L_MET3 = (70, 20)
L_VIA3 = (70, 44)
L_MET4 = (71, 20)

# --- rule-derived geometry (sky130 deck minimums plus margin) -----------------
DBU = 1000
GRID_UM = 0.005          # manufacturing grid (*.ongrid.1)
MCON_UM = 0.17           # ct.1 exact size
VIA_UM = 0.15            # via.1a exact size
VIA2_UM = 0.20           # via2.1a exact size
VIA3_UM = 0.20           # via3.1a exact size
WIRE_UM = 0.34           # met1/met2 wire width: m1.1/m2.1 minimum is 0.14,
                         # but met1/met2 must enclose a via1 by 0.085 on
                         # two adjacent edges, so 0.15 + 2*0.085 = 0.32 is
                         # the real floor (0.34 leaves 0.16 at 0.50 pitch)
MET1_SPACE_UM = 0.14     # m1.2
MET34_W_UM = 0.60        # met3/met4 wire width: m3.1/m4.1 want 0.30, but
                         # a run narrower than its own via pad leaves a
                         # notch at the corner that m3.2/m4.2 then flag
MET34_SPACE_UM = 0.30    # m3.2/m4.2
PAD34_UM = 0.60          # met2/met3/met4 landing pad for a via2/via3
                         # (0.60^2 = 0.36um2 clears met3/met4 min area 0.24)
PAD_MARGIN_UM = 0.12     # keep an mcon this far inside its li1 pad's own edge
TRUNK_PITCH_UM = 0.50    # x grid for met2 trunks (0.30 wire + 0.20 gap)
TRACK_PITCH_UM = 0.50    # y grid for met1 spines
JOG_REACH_UM = 6.0       # how far a met1 jog may climb off a strap's own y
BUCKET_NM = 2000         # y bucket for the met1 overlap index

# --- PDK pin (mirrors sim/pdk.json) -------------------------------------------
PDK_VARIANT = "sky130A"
PDK_ROOT_DEFAULT = "~/.ciel"
TOP_CELL = "ota_fd"

# --- device groups ------------------------------------------------------------
# (block id, klt gen generator, cell name, params).  One entry per matched
# group or single device of design/ota/ota_fd.spice.  `dummy` is 0 on every
# mos_array/res_array: klt's dummy elements are drawn without a contacted
# terminal, so they do not extract as devices, but they do double the
# res_array row length, and at 350um per Rcm body that is not a trade worth
# making (layout/analog/ota_fd/README.md records the choice).
BLOCKS: list[tuple[str, str, str, dict]] = [
    # -- nFET bias row ---------------------------------------------------------
    ("mb1", "mos_array", "MB1", {
        "w_um": 2.0, "l_um": 0.5, "fingers": 1, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "nfet", "gate_contact": True}),
    ("mbn1", "mos_array", "MBN1", {
        "w_um": 2.0, "l_um": 0.5, "fingers": 1, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "nfet", "gate_contact": True}),
    ("mbn2", "mos_array", "MBN2", {
        "w_um": 2.0, "l_um": 0.5, "fingers": 1, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "nfet", "gate_contact": True}),
    ("mbcn", "mos_array", "MBCN", {
        "w_um": 0.42, "l_um": 1.0, "fingers": 1, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "nfet", "gate_contact": True}),
    ("mct", "mos_array", "MCT", {
        "w_um": 2.0, "l_um": 0.5, "fingers": 2, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "nfet", "gate_contact": True}),
    ("mtail", "mos_array", "MTAIL", {
        "w_um": 2.0, "l_um": 0.5, "fingers": 16, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "nfet", "gate_contact": True}),
    ("nsink", "diff_pair", "NSINK", {
        "w_um": 2.0, "l_um": 0.5, "splits": 8, "flavor": "nfet",
        "add_guard_ring": False, "gate_contact": True, "mirror": True}),
    ("cmfbin", "diff_pair", "CMFBIN", {
        "w_um": 2.0, "l_um": 0.5, "splits": 2, "flavor": "nfet",
        "add_guard_ring": False, "gate_contact": True}),
    # -- nFET signal row -------------------------------------------------------
    ("inpair", "diff_pair", "INPAIR", {
        "w_um": 8.0, "l_um": 0.5, "splits": 2, "flavor": "nfet",
        "add_guard_ring": False, "gate_contact": True}),
    ("ncasc", "diff_pair", "NCASC", {
        "w_um": 7.0, "l_um": 0.5, "splits": 2, "flavor": "nfet",
        "add_guard_ring": False, "gate_contact": True}),
    # -- pFET row --------------------------------------------------------------
    ("ptop", "diff_pair", "PTOP", {
        "w_um": 10.0, "l_um": 0.5, "splits": 8, "flavor": "pfet",
        "add_guard_ring": False, "gate_contact": True, "mirror": True}),
    ("pcasc", "diff_pair", "PCASC", {
        "w_um": 10.0, "l_um": 0.5, "splits": 4, "flavor": "pfet",
        "add_guard_ring": False, "gate_contact": True}),
    ("cmfbld", "diff_pair", "CMFBLD", {
        "w_um": 2.5, "l_um": 0.5, "splits": 2, "flavor": "pfet",
        "add_guard_ring": False, "gate_contact": True, "mirror": True}),
    ("mbp1", "mos_array", "MBP1", {
        "w_um": 5.0, "l_um": 0.5, "fingers": 1, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "pfet", "gate_contact": True}),
    ("mbp2", "mos_array", "MBP2", {
        "w_um": 5.0, "l_um": 0.5, "fingers": 1, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "pfet", "gate_contact": True}),
    ("mbcp", "mos_array", "MBCP", {
        "w_um": 0.42, "l_um": 0.6, "fingers": 1, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "pfet", "gate_contact": True}),
    # -- passives --------------------------------------------------------------
    ("rcm", "res_array", "RCM", {
        "length_um": 350.0, "width_um": 0.35, "num": 2, "rows": 2,
        "dummy": 0, "flavor": "xhigh"}),
    ("rz", "res_array", "RZ", {
        "length_um": 4.5, "width_um": 0.35, "num": 1, "dummy": 0,
        "flavor": "high"}),
    ("cff", "cap_array", "CFF", {
        "plate_w_um": 7.07, "plate_h_um": 7.07, "num": 2, "spacing_um": 1.5}),
    ("ccm", "cap_array", "CCM", {
        "plate_w_um": 44.2, "plate_h_um": 44.2, "num": 1}),
]

#: Body-tie rings, sized in `build()` from the rows they enclose.
RING_BLOCKS = ("ptapring", "ntapring")

# --- schematic connectivity ---------------------------------------------------
# Transcribed device by device from design/ota/ota_fd.spice (D G S B order).
# `legs` maps a generated leg prefix to {terminal suffix: net}.  diff_pair legs
# expand to <leg>_<1..splits>_<suffix>; everything else is <leg>_<suffix>.
#
#   XM1   fa   inp   tail  -> inpair.Q1     XMBP1 vbpd vbpd  vdda -> mbp1.U0
#   XM2   fb   inn   tail  -> inpair.Q2     XMBN1 vbpd ibias vssa -> mbn1.U0
#   XMT   tail ibias vssa  -> mtail.U0      XMBP2 vcn  vbpd  vdda -> mbp2.U0
#   XMP1  fa   cr    vdda  -> ptop.M1       XMBCN vcn  vcn   vssa -> mbcn.U0
#   XMP2  fb   cr    vdda  -> ptop.M2       XMBCP vcp  vcp   vdda -> mbcp.U0
#   XMPC1 outn vcp   fa    -> pcasc.Q1      XMBN2 vcp  ibias vssa -> mbn2.U0
#   XMPC2 outp vcp   fb    -> pcasc.Q2      XMCS  cs   cmx   ct   -> cmfbin.Q1
#   XMNC1 outn vcn   sa    -> ncasc.Q1      XMCR  cr   vcm   ct   -> cmfbin.Q2
#   XMNC2 outp vcn   sb    -> ncasc.Q2      XMCT  ct   ibias vssa -> mct.U0
#   XMN1  sa   ibias vssa  -> nsink.M1      XMCPS cs   cs    vdda -> cmfbld.M1
#   XMN2  sb   ibias vssa  -> nsink.M2      XMCPR cr   cs    vdda -> cmfbld.M2
#   XMB1  ibias ibias vssa -> mb1.U0
#   XRcm1 cmx outp -> rcm.R0 (A=cmx, B=outp)   XCff1 outp cmx -> cff.C0
#   XRcm2 cmx outn -> rcm.R1 (B=cmx, A=outn)   XCff2 outn cmx -> cff.C1
#   XRz   nz  cr   -> rz.R0  (A=nz,  B=cr)     XCcm  nz   vdda -> ccm.C0
#
# rcm's R1 is bound B-to-cmx / A-to-outn on purpose: res_array lays its rows
# boustrophedon, so R1_B is the left-hand end like R0_A.  A resistor is
# symmetric, so this keeps both cmx ends on one side and both output ends on
# the other instead of routing cmx 350um across the strip.
LEG_NETS: dict[str, dict[str, dict[str, str]]] = {
    "inpair": {"Q1": {"D": "fa", "G": "inp", "S": "tail"},
               "Q2": {"D": "fb", "G": "inn", "S": "tail"}},
    "mtail": {"U0": {"D": "tail", "G": "ibias", "S": "vssa"}},
    "ptop": {"M1": {"D": "fa", "G": "cr", "S": "vdda"},
             "M2": {"D": "fb", "G": "cr", "S": "vdda"}},
    "pcasc": {"Q1": {"D": "outn", "G": "vcp", "S": "fa"},
              "Q2": {"D": "outp", "G": "vcp", "S": "fb"}},
    "ncasc": {"Q1": {"D": "outn", "G": "vcn", "S": "sa"},
              "Q2": {"D": "outp", "G": "vcn", "S": "sb"}},
    "nsink": {"M1": {"D": "sa", "G": "ibias", "S": "vssa"},
              "M2": {"D": "sb", "G": "ibias", "S": "vssa"}},
    "mb1": {"U0": {"D": "ibias", "G": "ibias", "S": "vssa"}},
    "mbn1": {"U0": {"D": "vbpd", "G": "ibias", "S": "vssa"}},
    "mbn2": {"U0": {"D": "vcp", "G": "ibias", "S": "vssa"}},
    "mbcn": {"U0": {"D": "vcn", "G": "vcn", "S": "vssa"}},
    "mbp1": {"U0": {"D": "vbpd", "G": "vbpd", "S": "vdda"}},
    "mbp2": {"U0": {"D": "vcn", "G": "vbpd", "S": "vdda"}},
    "mbcp": {"U0": {"D": "vcp", "G": "vcp", "S": "vdda"}},
    "cmfbin": {"Q1": {"D": "cs", "G": "cmx", "S": "ct"},
               "Q2": {"D": "cr", "G": "vcm", "S": "ct"}},
    "mct": {"U0": {"D": "ct", "G": "ibias", "S": "vssa"}},
    "cmfbld": {"M1": {"D": "cs", "G": "cs", "S": "vdda"},
               "M2": {"D": "cr", "G": "cs", "S": "vdda"}},
    "rcm": {"R0": {"A": "cmx", "B": "outp"},
            "R1": {"A": "outn", "B": "cmx"}},
    "rz": {"R0": {"A": "nz", "B": "cr"}},
    "cff": {"C0": {"BOT": "outp", "TOP": "cmx"},
            "C1": {"BOT": "outn", "TOP": "cmx"}},
    "ccm": {"C0": {"BOT": "vdda", "TOP": "nz"}},
    # Only one tap port per ring is wired: all four sit on the same closed
    # li1 ring, so one stands for the conductor (and a second would ask the
    # router to cross the ring's own interior).
    "ptapring": {"TAP": {"W": "vssa"}},
    "ntapring": {"TAP": {"W": "vdda"}},
}

#: The eight `.subckt` ports, labelled on met1.pin in the composed cell.
PIN_NETS = ("vdda", "vssa", "inp", "inn", "outp", "outn", "vcm", "ibias")

#: Net routing order.  Gate-fed and high-impedance nets first (least freedom),
#: the two supplies last (most anchors, most freedom to detour).
NET_ORDER = (
    "inp", "inn", "vcm", "cmx", "vcn", "vcp", "vbpd", "cr", "cs", "nz",
    "fa", "fb", "sa", "sb", "tail", "ct", "outp", "outn", "ibias",
    "vssa", "vdda",
)

#: Device-count expectation, by extracted model family (design/ota/ota_fd.spice).
EXPECTED_DEVICES = {
    "nfet_01v8": 14,
    "pfet_01v8": 9,
    "cap_mim_m3_1": 3,
    "res_high_po": 1,
    "res_xhigh_po": 2,
}


def nm(value_um: float) -> int:
    return int(round(value_um * DBU))


def snap(value_um: float) -> float:
    """Round onto the PDK manufacturing grid (*.ongrid.1)."""
    return round(round(value_um / GRID_UM) * GRID_UM, 6)


class Rect:
    """An axis-aligned rectangle in integer nanometres."""

    __slots__ = ("x0", "y0", "x1", "y1")

    def __init__(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1

    @classmethod
    def um(cls, x0: float, y0: float, x1: float, y1: float) -> "Rect":
        return cls(nm(min(x0, x1)), nm(min(y0, y1)), nm(max(x0, x1)), nm(max(y0, y1)))

    @classmethod
    def centred(cls, cx: float, cy: float, w: float, h: float) -> "Rect":
        return cls.um(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    @classmethod
    def hwire(cls, xa: float, xb: float, y: float, w: float) -> "Rect":
        lo, hi = sorted((xa, xb))
        return cls.um(lo - w / 2, y - w / 2, hi + w / 2, y + w / 2)

    @classmethod
    def vwire(cls, x: float, ya: float, yb: float, w: float) -> "Rect":
        lo, hi = sorted((ya, yb))
        return cls.um(x - w / 2, lo - w / 2, x + w / 2, hi + w / 2)

    def as_um(self) -> list[float]:
        return [self.x0 / DBU, self.y0 / DBU, self.x1 / DBU, self.y1 / DBU]

    def clashes(self, other: "Rect", clearance: int) -> bool:
        return (self.x0 - clearance < other.x1 and other.x0 < self.x1 + clearance
                and self.y0 - clearance < other.y1 and other.y0 < self.y1 + clearance)


class RouteError(RuntimeError):
    """The floorplan/router could not place a wire."""


def run(cmd: list[str], cwd: Path | None = None, check: bool = True):
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed (rc={result.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


# --- port expansion -----------------------------------------------------------
def expand_ports(block_id: str, generator: str, params: dict) -> dict[str, str]:
    """{generated port name: net}, from LEG_NETS plus the generator's own
    port-naming convention (diff_pair numbers each leg's sub-instances)."""
    out: dict[str, str] = {}
    for leg, terminals in LEG_NETS[block_id].items():
        for suffix, net in terminals.items():
            if generator == "diff_pair":
                for i in range(1, int(params["splits"]) + 1):
                    out[f"{leg}_{i}_{suffix}"] = net
            else:
                out[f"{leg}_{suffix}"] = net
    return out


def gen_blocks(klt: str, pdk_args: list[str], out_dir: Path,
               blocks: list[tuple[str, str, str, dict]]) -> dict[str, dict]:
    reports: dict[str, dict] = {}
    for block_id, generator, cell_name, params in blocks:
        r = run([klt, "gen", generator, "--params", json.dumps(params, sort_keys=True)]
                + pdk_args + ["--cell-name", cell_name, "-o", f"{block_id}.gds",
                              "--format", "json"], cwd=out_dir)
        report = json.loads(r.stdout)
        if report.get("error"):
            raise RuntimeError(f"klt gen {block_id}: {report['error']}")
        (out_dir / f"{block_id}.json").write_text(r.stdout)
        reports[block_id] = report
    return reports


def size_of(report: dict) -> tuple[float, float]:
    bb = report["bbox_um"]
    return bb["x1"] - bb["x0"], bb["y1"] - bb["y0"]


# --- floorplan ----------------------------------------------------------------
#: Rows, bottom to top; each is (row id, left margin, inter-block gap, members).
#: Member order is signal flow left to right.  The long Rcm strip gets its own
#: row at the bottom; the MiM caps sit above it; the two nFET rows and the
#: pFET row stack above that, so the fa/fb and sa/sb trunks are short.
ROWS: list[tuple[str, float, float, tuple[str, ...]]] = [
    ("res", 2.0, 4.0, ("rcm",)),
    ("caps", 2.0, 6.0, ("ccm", "cff", "rz")),
    ("nbias", 6.0, 4.0, ("mb1", "mbn1", "mbn2", "mbcn", "mct", "cmfbin",
                         "mtail", "nsink")),
    ("nsig", 6.0, 6.0, ("inpair", "ncasc")),
    ("pfet", 6.0, 4.0, ("ptop", "pcasc", "cmfbld", "mbp1", "mbp2", "mbcp")),
]

#: Vertical gap (um) between a row's top and the next row's bottom.  Each gap
#: is a routing channel: met1 spines run here, clear of every block's own
#: in-block straps.
ROW_GAP_UM = {"res": 9.0, "caps": 11.0, "nbias": 11.0, "nsig": 11.0}

#: Rows the two body-tie rings enclose, and the padding they leave.
RING_ROWS = {"ptapring": ("nbias", "nsig"), "ntapring": ("pfet",)}
RING_PAD_UM = 2.0
RING_WIDTH_UM = 0.42


def place_rows(reports: dict[str, dict]) -> tuple[dict[str, dict[str, float]],
                                                  dict[str, tuple[float, float, float, float]]]:
    """Pack the blocks into ROWS.  Returns (origins, row extents)."""
    origins: dict[str, dict[str, float]] = {}
    extents: dict[str, tuple[float, float, float, float]] = {}
    y = 0.0
    for row_id, left, gap, members in ROWS:
        heights = [size_of(reports[b])[1] for b in members]
        row_h = max(heights)
        x = left
        for block_id in members:
            w, _h = size_of(reports[block_id])
            bb = reports[block_id]["bbox_um"]
            # Place by bbox corner, not by the generator's own origin.
            origins[block_id] = {"x": snap(x - bb["x0"]), "y": snap(y - bb["y0"])}
            x += w + gap
        extents[row_id] = (left, y, x - gap, y + row_h)
        y = snap(y + row_h + ROW_GAP_UM.get(row_id, 0.0))
    return origins, extents


def ring_params(extents: dict[str, tuple[float, float, float, float]],
                ring_id: str) -> tuple[dict, dict[str, float]]:
    """guard_ring params + origin enclosing this ring's rows."""
    rows = [extents[r] for r in RING_ROWS[ring_id]]
    x0 = min(r[0] for r in rows) - RING_PAD_UM
    y0 = min(r[1] for r in rows) - RING_PAD_UM
    x1 = max(r[2] for r in rows) + RING_PAD_UM
    y1 = max(r[3] for r in rows) + RING_PAD_UM
    params = {
        "inner_width_um": snap(x1 - x0),
        "inner_height_um": snap(y1 - y0),
        "ring_width_um": RING_WIDTH_UM,
        "contacts_per_side_ns": max(4, int((x1 - x0) / 4.0)),
        "contacts_per_side_ew": max(4, int((y1 - y0) / 4.0)),
        "add_well": ring_id == "ntapring",
    }
    # guard_ring draws its inner area starting at (ring_width, ring_width).
    origin = {"x": snap(x0 - RING_WIDTH_UM), "y": snap(y0 - RING_WIDTH_UM)}
    return params, origin


# --- anchors ------------------------------------------------------------------
class Anchor:
    """One place a net can be reached inside one block.

    ``plane`` is the layer a met2 trunk drops onto: ``met1`` for an li1 pad or
    an in-block met1 strap, ``cap3``/``cap4`` for a MiM terminal that needs a
    same-layer run out of the block first.  ``x0``/``x1`` bound the x where a
    via may land with no extra metal; a column outside that range costs one
    met1 jog.
    """

    __slots__ = ("net", "block", "plane", "y", "x0", "x1", "ports", "port_dir",
                 "block_y0", "block_y1", "pad_xs", "jog_um")

    def __init__(self, net, block, plane, y, x0, x1, ports,
                 port_dir=0, block_y0=0.0, block_y1=0.0, pad_xs=(), jog_um=0.0):
        self.net, self.block, self.plane = net, block, plane
        self.y, self.x0, self.x1 = y, x0, x1
        self.ports = ports
        self.port_dir = port_dir
        self.block_y0, self.block_y1 = block_y0, block_y1
        #: x of each li1 pad this anchor straps (a vertical met1 jog off the
        #: strap may start at any of them).
        self.pad_xs = tuple(pad_xs) if pad_xs else (x0,)
        #: how far off the strap's own y a jog may climb before it leaves the
        #: pads it is allowed to shadow.
        self.jog_um = jog_um

    @property
    def xmid(self) -> float:
        return (self.x0 + self.x1) / 2


def collect_anchors(blocks, reports, origins, port_nets):
    """Turn every block's ports into anchors, one per (block, net, pad row).

    S/D-style li1 pads (``direction`` 0/180) are tall, so several nets share
    one pad row: each net present in a row gets its own y offset on a 0.5um
    ladder inside the pads, and every pad of that net in that row is tied by
    one horizontal met1 strap.  Gate-style pads (``direction`` 90/270) are
    0.42um square, so their y is pinned: a row holding more than one net there
    must hold exactly one pad per net, and each becomes its own anchor.
    """
    anchors: list[Anchor] = []
    straps: list[tuple[str, Rect]] = []
    mcons: list[tuple[float, float]] = []
    for block_id, generator, _cell, _params in blocks:
        report = reports[block_id]
        dx, dy = origins[block_id]["x"], origins[block_id]["y"]
        bb = report["bbox_um"]
        nets = port_nets[block_id]
        # -- bucket the ports -------------------------------------------------
        flat: dict[tuple, list[tuple[str, float, float, float, int]]] = defaultdict(list)
        for p in report["ports"]:
            if p["name"] not in nets:
                continue
            layer = (p["layer"]["layer"], p["layer"]["datatype"])
            key = (layer, round(p["y_um"] + dy, 4), p["direction_deg"] in (0, 180))
            flat[key].append((p["name"], p["x_um"] + dx, p["y_um"] + dy,
                              p["width_um"], p["direction_deg"]))
        for (layer, row_y, is_sd), ports in sorted(flat.items(), key=lambda kv: str(kv[0])):
            by_net: dict[str, list] = defaultdict(list)
            for name, px, py, pw, pdir in ports:
                by_net[nets[name]].append((name, px, py, pw, pdir))
            ordered = sorted(by_net)
            if layer == L_MET3:
                for net in ordered:
                    for name, px, py, pw, pdir in sorted(by_net[net]):
                        anchors.append(Anchor(net, block_id, "cap3", py, px, px,
                                              [name], pdir, bb["y0"] + dy, bb["y1"] + dy))
                continue
            if layer == L_MET4:
                for net in ordered:
                    for name, px, py, pw, pdir in sorted(by_net[net]):
                        anchors.append(Anchor(net, block_id, "cap4", py, px, px,
                                              [name], pdir, bb["y0"] + dy, bb["y1"] + dy))
                continue
            if layer != L_LI1:
                raise RouteError(f"{block_id}: unexpected port layer {layer}")
            if is_sd:
                half = min(p[3] for p in ports) / 2 - PAD_MARGIN_UM - WIRE_UM / 2
                k = len(ordered)
                # Only a net with several pads in this row needs a horizontal
                # strap, and only a strap can cross another net's pad -- so a
                # row where every net has a single pad needs no ladder at all
                # (that is the only way a 0.42um-wide S/D pad row can work).
                spread = k > 1 and (k - 1) * TRACK_PITCH_UM / 2 <= half + 1e-9
                if not spread and any(len(by_net[n]) > 1 for n in ordered) and k > 1:
                    raise RouteError(
                        f"{block_id}: {k} nets share a {2 * (half + PAD_MARGIN_UM):.2f}um "
                        f"pad row at y={row_y} and one of them needs a strap -- "
                        "no room for a ladder")
                for i, net in enumerate(ordered):
                    off = snap((i - (k - 1) / 2) * TRACK_PITCH_UM) if spread else 0.0
                    y = snap(row_y + off)
                    xs = sorted(p[1] for p in by_net[net])
                    rect = Rect.hwire(xs[0], xs[-1], y, WIRE_UM)
                    straps.append((net, rect))
                    for x in xs:
                        mcons.append((x, y))
                    anchors.append(Anchor(net, block_id, "met1", y, xs[0], xs[-1],
                                          [p[0] for p in by_net[net]],
                                          pad_xs=xs, jog_um=JOG_REACH_UM))
            else:
                for net in ordered:
                    members = sorted(by_net[net])
                    # sorted by x, never by port name: diff_pair numbers its
                    # top row in the mirrored order, so name order would leave
                    # the row's outermost gate outside the strap (and float it)
                    xs = sorted(m[1] for m in members)
                    if len(ordered) > 1 and len(members) > 1:
                        raise RouteError(
                            f"{block_id}: gate row y={row_y} holds {len(ordered)} nets "
                            f"and net {net} has {len(members)} pads -- cannot strap")
                    rect = Rect.hwire(xs[0], xs[-1], row_y, WIRE_UM)
                    straps.append((net, rect))
                    for x in xs:
                        mcons.append((x, row_y))
                    anchors.append(Anchor(net, block_id, "met1", row_y, xs[0], xs[-1],
                                          [m[0] for m in members],
                                          pad_xs=xs, jog_um=JOG_REACH_UM))
    return anchors, straps, mcons


# --- router -------------------------------------------------------------------
class Router:
    """met1 horizontal + met2 vertical, one global x column per trunk.

    Every trunk owns its x column outright (``used_cols``), so two met2 runs
    can never come within one pitch of each other and no met2-met2 spacing
    search is needed; met1 is the only layer the greedy search has to keep
    clear, and met3/met4 only carry the MiM risers.
    """

    def __init__(self, x_lo: float, x_hi: float, y_lo: float, y_hi: float) -> None:
        self.x_lo, self.x_hi, self.y_lo, self.y_hi = x_lo, x_hi, y_lo, y_hi
        self.shapes: list[tuple[tuple[int, int], Rect]] = []
        self.labels: list[tuple[tuple[int, int], str, float, float]] = []
        self.met1: list[tuple[str, Rect]] = []
        self.met1_index: dict[int, list[tuple[str, Rect]]] = defaultdict(list)
        self.met3: list[tuple[str, Rect]] = []
        self.met4: list[tuple[str, Rect]] = []
        self.used_cols: set[int] = set()
        self.trunk_y: dict[tuple[str, float], list[float]] = defaultdict(list)
        self.via1_y: dict[tuple[str, float], list[float]] = defaultdict(list)
        self.wire_um: dict[str, float] = defaultdict(float)

    # -- geometry bookkeeping -------------------------------------------------
    def add_shape(self, layer, rect: Rect) -> None:
        self.shapes.append((layer, rect))

    def add_met1(self, net: str, rects: list[Rect]) -> None:
        for rect in rects:
            self.met1.append((net, rect))
            for b in range(rect.y0 // BUCKET_NM, rect.y1 // BUCKET_NM + 1):
                self.met1_index[b].append((net, rect))
            self.add_shape(L_MET1, rect)
            self.wire_um[net] += max(rect.x1 - rect.x0, rect.y1 - rect.y0) / DBU

    def add_met(self, layer, store, net: str, rects: list[Rect]) -> None:
        for rect in rects:
            store.append((net, rect))
            self.add_shape(layer, rect)
            self.wire_um[net] += (rect.x1 - rect.x0 + rect.y1 - rect.y0) / DBU

    def add_mcon(self, x: float, y: float) -> None:
        rect = Rect.centred(x, y, MCON_UM, MCON_UM)
        self.add_shape(L_MCON, rect)

    def add_trunk_via(self, net: str, col: float, y: float) -> None:
        """Drop a met1<->met2 via1 on this net's column, and grow the trunk.

        A second via1 within a wire width of an existing *via1* would merge
        into one oversized cut (via.width.1) and breach via.space.1 -- but the
        two met1 runs that close together already overlap (see `_ok`), so the
        connection survives without it.  The comparison is deliberately
        against `via1_y` and not `trunk_y`: a MiM riser contributes a via2 at
        its own y and no met1 at all, and suppressing a via1 near it would
        leave the met1 spine with nothing to reach the trunk through.
        """
        self.trunk_y[(net, col)].append(y)
        if any(abs(y - prev) < WIRE_UM for prev in self.via1_y[(net, col)]):
            return
        self.add_shape(L_VIA, Rect.centred(col, y, VIA_UM, VIA_UM))
        self.via1_y[(net, col)].append(y)

    @staticmethod
    def _ok(rect: Rect, placed: Rect, same_net: bool, gap: int) -> bool:
        if not rect.clashes(placed, gap):
            return True
        # Same net: a real overlap merges the two into one polygon, which is
        # fine.  A near miss does not -- it leaves a notch whose own edges are
        # closer than the minimum spacing, which the deck flags exactly like a
        # two-net violation.
        return same_net and rect.clashes(placed, 0)

    @classmethod
    def _free(cls, store, net: str, rects: list[Rect], clearance: float) -> bool:
        gap = nm(clearance)
        for owner, placed in store:
            for rect in rects:
                if not cls._ok(rect, placed, owner == net, gap):
                    return False
        return True

    def met1_free(self, net: str, rects: list[Rect]) -> bool:
        gap = nm(MET1_SPACE_UM)
        for rect in rects:
            lo = (rect.y0 - gap) // BUCKET_NM
            hi = (rect.y1 + gap) // BUCKET_NM
            for b in range(lo, hi + 1):
                for owner, placed in self.met1_index.get(b, ()):
                    if not self._ok(rect, placed, owner == net, gap):
                        return False
        return True

    # -- candidate orders ------------------------------------------------------
    def columns(self, x0: float, x1: float, pref: float):
        k0 = int((self.x_lo - 2.0) // TRUNK_PITCH_UM)
        k1 = int((self.x_hi + 2.0) // TRUNK_PITCH_UM) + 1
        cands = [snap(k * TRUNK_PITCH_UM) for k in range(k0, k1 + 1)]
        cands.sort(key=lambda c: (0 if x0 - 1e-9 <= c <= x1 + 1e-9 else 1,
                                  abs(c - pref), c))
        return [c for c in cands if nm(c) not in self.used_cols]

    def neighbours_free(self, col: float) -> bool:
        return not any(nm(snap(col + d * TRUNK_PITCH_UM)) in self.used_cols
                       for d in (-1, 1))

    def reserve_column(self, col: float, neighbours: bool = False) -> None:
        self.used_cols.add(nm(col))
        if neighbours:
            self.used_cols.add(nm(snap(col - TRUNK_PITCH_UM)))
            self.used_cols.add(nm(snap(col + TRUNK_PITCH_UM)))

    def tracks(self, pref: float):
        k0 = int((self.y_lo - 2.0) // TRACK_PITCH_UM)
        k1 = int((self.y_hi + 2.0) // TRACK_PITCH_UM) + 1
        cands = [snap(k * TRACK_PITCH_UM) for k in range(k0, k1 + 1)]
        cands.sort(key=lambda y: (abs(y - pref), y))
        return cands

    # -- the three ways a net reaches a block ---------------------------------
    def connect_met1(self, a: Anchor, col_budget: int = 24) -> tuple[float, float]:
        """Drop a met2 trunk onto this anchor.

        Cheapest first: a column that already lies inside the strap, so the
        via lands on metal that exists.  Failing that the jog climbs off the
        strap on a free met1 track (``jog_um`` bounds how far) and reaches
        sideways -- the freedom a 0.42um-wide S/D pad row needs, where every
        net sits on the strap's own y and only a different y can get past a
        neighbour's pad.
        """
        cols = self.columns(a.x0, a.x1, a.xmid)[:col_budget]
        for y in self.jog_tracks(a):
            for col in cols:
                if nm(col) in self.used_cols:
                    continue
                pad_x = min(a.pad_xs, key=lambda px: (abs(px - col), px))
                extra: list[Rect] = []
                if abs(y - a.y) > 1e-9:
                    extra.append(Rect.vwire(pad_x, a.y, y, WIRE_UM))
                    if abs(col - pad_x) > 1e-9:
                        extra.append(Rect.hwire(pad_x, col, y, WIRE_UM))
                elif not (a.x0 - 1e-9 <= col <= a.x1 + 1e-9):
                    extra.append(Rect.hwire(min(a.x0, col), max(a.x1, col), y,
                                            WIRE_UM))
                if extra and not self.met1_free(a.net, extra):
                    continue
                self.used_cols.add(nm(col))
                if extra:
                    self.add_met1(a.net, extra)
                self.add_trunk_via(a.net, col, y)
                return col, y
        raise RouteError(f"no free met2 column for {a.net} at {a.block} y={a.y}")

    def jog_tracks(self, a: Anchor) -> list[float]:
        if a.jog_um <= 0:
            return [a.y]
        n = int(a.jog_um / TRACK_PITCH_UM)
        ys = {a.y}
        for i in range(1, n + 1):
            ys.add(snap(a.y + i * TRACK_PITCH_UM))
            ys.add(snap(a.y - i * TRACK_PITCH_UM))
        return sorted(ys, key=lambda y: (abs(y - a.y), y))

    def connect_cap3(self, a: Anchor) -> tuple[float, float]:
        x_run = snap(a.x0 + (0.3 if a.port_dir == 180 else -0.3))
        y_drop = snap(a.block_y0 - 1.2)
        vert = Rect.vwire(x_run, a.y, y_drop, MET34_W_UM)
        for col in self.columns(x_run - 2.0, x_run + 2.0, x_run):
            if not self.neighbours_free(col):
                continue
            horiz = Rect.hwire(x_run, col, y_drop, MET34_W_UM)
            pad3 = Rect.centred(col, y_drop, PAD34_UM, PAD34_UM)
            if not self._free(self.met3, a.net, [vert, horiz, pad3], MET34_SPACE_UM):
                continue
            self.reserve_column(col, neighbours=True)
            self.add_met(L_MET3, self.met3, a.net, [vert, horiz, pad3])
            self.add_shape(L_VIA2, Rect.centred(col, y_drop, VIA2_UM, VIA2_UM))
            self.add_shape(L_MET2, Rect.centred(col, y_drop, PAD34_UM, PAD34_UM))
            self.trunk_y[(a.net, col)].append(y_drop)
            return col, y_drop
        raise RouteError(f"no met3 riser for {a.net} at {a.block}")

    def connect_cap4(self, a: Anchor) -> tuple[float, float]:
        x_run = snap(a.x0)
        y_drop = snap(a.block_y1 + 1.2)
        vert = Rect.vwire(x_run, a.y, y_drop, MET34_W_UM)
        for col in self.columns(x_run - 2.0, x_run + 2.0, x_run):
            if not self.neighbours_free(col):
                continue
            horiz = Rect.hwire(x_run, col, y_drop, MET34_W_UM)
            pad3 = Rect.centred(col, y_drop, PAD34_UM, PAD34_UM)
            if not self._free(self.met4, a.net, [vert, horiz], MET34_SPACE_UM):
                continue
            if not self._free(self.met3, a.net, [pad3], MET34_SPACE_UM):
                continue
            self.reserve_column(col, neighbours=True)
            self.add_met(L_MET4, self.met4, a.net, [vert, horiz])
            self.add_met(L_MET3, self.met3, a.net, [pad3])
            self.add_shape(L_VIA3, Rect.centred(col, y_drop, VIA3_UM, VIA3_UM))
            self.add_shape(L_VIA2, Rect.centred(col, y_drop, VIA2_UM, VIA2_UM))
            self.add_shape(L_MET2, Rect.centred(col, y_drop, PAD34_UM, PAD34_UM))
            self.trunk_y[(a.net, col)].append(y_drop)
            return col, y_drop
        raise RouteError(f"no met4 riser for {a.net} at {a.block}")

    def connect(self, a: Anchor) -> tuple[float, float]:
        if a.plane == "met1":
            return self.connect_met1(a)
        if a.plane == "cap3":
            return self.connect_cap3(a)
        return self.connect_cap4(a)

    # -- trunk-to-trunk spine --------------------------------------------------
    def route_spine(self, net: str, ca: float, ya: float,
                    cb: float, yb: float) -> float:
        for y in self.tracks((ya + yb) / 2):
            rect = Rect.hwire(ca, cb, y, WIRE_UM)
            if not self.met1_free(net, [rect]):
                continue
            self.add_met1(net, [rect])
            self.add_trunk_via(net, ca, y)
            self.add_trunk_via(net, cb, y)
            return y
        raise RouteError(f"no free met1 track for {net} spine {ca} <-> {cb}")

    def finish_trunks(self) -> None:
        for (net, col), ys in sorted(self.trunk_y.items()):
            lo, hi = min(ys), max(ys)
            rect = Rect.vwire(col, lo, hi, WIRE_UM)
            self.add_shape(L_MET2, rect)
            self.wire_um[net] += (hi - lo)


# --- build --------------------------------------------------------------------
def build(blocks, reports, origins, port_nets):
    """Strap every block, route every net, return (draw params, compose
    request, route summary)."""
    anchors, straps, mcons = collect_anchors(blocks, reports, origins, port_nets)
    xs: list[float] = []
    ys: list[float] = []
    for block_id, _g, _c, _p in blocks:
        bb = reports[block_id]["bbox_um"]
        o = origins[block_id]
        xs += [bb["x0"] + o["x"], bb["x1"] + o["x"]]
        ys += [bb["y0"] + o["y"], bb["y1"] + o["y"]]
    router = Router(min(xs), max(xs), min(ys), max(ys))
    for net, rect in straps:
        router.add_met1(net, [rect])
    for x, y in mcons:
        router.add_mcon(x, y)

    by_net: dict[str, list[Anchor]] = defaultdict(list)
    for a in anchors:
        by_net[a.net].append(a)
    missing = sorted(set(by_net) - set(NET_ORDER))
    unrouted = sorted(set(NET_ORDER) - set(by_net))
    if missing or unrouted:
        raise RouteError(f"net table mismatch: not in NET_ORDER {missing}, "
                         f"no anchors {unrouted}")

    summary: dict[str, dict] = {}
    for net in NET_ORDER:
        group = sorted(by_net[net], key=lambda a: (a.block, a.plane, a.y, a.x0))
        placed = [(*router.connect(a), a) for a in group]
        placed.sort(key=lambda t: (t[0], t[1]))
        spines = []
        for (ca, ya, _a), (cb, yb, _b) in zip(placed, placed[1:]):
            spines.append(router.route_spine(net, ca, ya, cb, yb))
        summary[net] = {
            "anchors": [{"block": a.block, "plane": a.plane, "ports": a.ports,
                         "column_x_um": col, "y_um": y}
                        for col, y, a in placed],
            "spine_y_um": spines,
        }
        if net in PIN_NETS:
            # The label must land on met1 that actually exists, so a net whose
            # first anchor is a MiM riser (met2/met3/met4) is labelled at its
            # first met1 anchor instead.
            on_met1 = [t for t in placed if t[2].plane == "met1"]
            if not on_met1:
                raise RouteError(f"port net {net} has no met1 anchor to label")
            col, y, _a = on_met1[0]
            router.labels.append((L_MET1_PIN, net, col, y))
    router.finish_trunks()

    for net, info in summary.items():
        info["wire_length_um"] = round(router.wire_um[net], 3)

    draw_params = {
        "shapes": [{"layer": list(layer), "rect_um": rect.as_um()}
                   for layer, rect in router.shapes],
        "labels": [{"layer": list(layer), "text": text, "at_um": [x, y]}
                   for layer, text, x, y in router.labels],
    }
    order = [b for b, _g, _c, _p in blocks] + ["route"]
    compose_request = {
        "schema": "klt.gen_compose.request/1",
        "pdk": {"variant": PDK_VARIANT},
        "blocks": [{"id": b, "generator_report": f"{b}.json"}
                   for b, _g, _c, _p in blocks]
        + [{"id": "route", "generator_report": "draw.json"}],
        "placement": {
            "strategy": "explicit",
            "order": order,
            "origins_um": {**origins, "route": {"x": 0.0, "y": 0.0}},
        },
        # No `routing` block on purpose: gen-compose is a placer here; every
        # wire is in the `route` block this script drew.
        "connectivity": [],
        "options": {"cell_name": TOP_CELL, "output": f"{TOP_CELL}.gds"},
    }
    route_summary = {
        "block_origins_um": origins,
        "met2_columns": len(router.used_cols),
        "nets": summary,
    }
    return draw_params, compose_request, route_summary


# --- device-count evidence ----------------------------------------------------
def _symmetric_terminals(terminals: tuple[str, ...]) -> tuple[str, ...]:
    """Normalise a device's terminal order over the terminals it is symmetric in.

    A MOSFET's source and drain are interchangeable, and a multi-finger device
    extracts with them alternating finger by finger (half the fingers come out
    D-G-S-B, half S-G-D-B).  Without this they look like two different
    devices and never combine, so a `fingers=16` tail current source would
    count as two.  Resistors and capacitors are symmetric in both terminals.
    """
    if len(terminals) == 4:          # D G S B
        d, g, src, b = terminals
        lo, hi = sorted((d, src))
        return (lo, g, hi, b)
    if len(terminals) == 3:          # A B bulk (res)
        a, b, bulk = terminals
        lo, hi = sorted((a, b))
        return (lo, hi, bulk)
    return tuple(sorted(terminals))  # 2-terminal (cap)


def parse_extract_devices(netlist_text: str) -> tuple[Counter, Counter]:
    """Count extracted devices by model, merging parallel same-net devices.

    One drawn transistor is one line, so a ``splits=8`` leg appears as eight
    W=10 devices where the schematic declares one ``mult=8`` device, and a
    16-finger ``mos_array`` appears as 16.  Counting therefore merges devices
    sharing a model and all terminals -- what an LVS "combine parallel
    devices" pass does -- and reports the raw counts beside the merged ones so
    the merge is visible rather than silent.
    """
    raw: Counter = Counter()
    groups: set[tuple[str, tuple[str, ...]]] = set()
    for line in netlist_text.splitlines():
        tok = line.split()
        if not tok or not tok[0].startswith("X"):
            continue
        model = next((t for t in tok if "sky130_fd_pr__" in t), None)
        if model is None:
            continue
        terminals = tuple(tok[1:tok.index(model)])
        raw[model] += 1
        groups.add((model, _symmetric_terminals(terminals)))
    combined: Counter = Counter()
    for model, _terminals in groups:
        combined[model] += 1
    return raw, combined


def extract_nets(netlist_text: str) -> list[str]:
    """Every distinct net name appearing on an extracted device terminal."""
    nets: set[str] = set()
    for line in netlist_text.splitlines():
        tok = line.split()
        if not tok or not tok[0].startswith("X"):
            continue
        model = next((t for t in tok if "sky130_fd_pr__" in t), None)
        if model is None:
            continue
        nets.update(tok[1:tok.index(model)])
    return sorted(nets)


def count_check(combined: Counter) -> tuple[bool, dict]:
    found: dict[str, int] = {}
    other = dict(combined)
    for family in EXPECTED_DEVICES:
        hits = [k for k in combined if k.endswith(family)]
        found[family] = sum(combined[k] for k in hits)
        for k in hits:
            other.pop(k, None)
    ok = found == EXPECTED_DEVICES and not other
    return ok, {
        "expected": {**EXPECTED_DEVICES, "total": sum(EXPECTED_DEVICES.values())},
        "found": {**found, "total": sum(found.values())},
        "unexpected_models": other,
    }


# --- flow ---------------------------------------------------------------------
def klt_pin(klt: str) -> dict:
    """The exact klt build, recorded with the evidence.

    The stream is byte-reproducible at *this* build: a generator change
    upstream moves geometry, so `--check` is an assertion about one klt, and
    the reader has to be told which one.
    """
    r = run([klt, "version", "--format", "json"], check=False)
    try:
        d = json.loads(r.stdout)
    except Exception:
        return {"klt": "unknown"}
    return {
        "klt": d.get("version"),
        "git_commit": d.get("git_commit"),
        "reinstall_spec": d.get("reinstall_spec"),
        "klayout": d.get("klayout_version"),
    }


def flow(klt: str, pdk_root: Path, out_dir: Path, verbose: bool = True) -> dict:
    pdk_args = ["--pdk", PDK_VARIANT, "--pdk-root", str(pdk_root)]
    out_dir.mkdir(parents=True, exist_ok=True)

    def say(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    say("[1/6] klt gen device blocks")
    reports = gen_blocks(klt, pdk_args, out_dir, BLOCKS)

    say("[2/6] floorplan + body-tie rings")
    origins, extents = place_rows(reports)
    ring_blocks = []
    for ring_id in RING_BLOCKS:
        params, origin = ring_params(extents, ring_id)
        ring_blocks.append((ring_id, "guard_ring", ring_id.upper(), params))
        origins[ring_id] = origin
    reports.update(gen_blocks(klt, pdk_args, out_dir, ring_blocks))
    blocks = BLOCKS + ring_blocks
    port_nets = {b: expand_ports(b, g, p) for b, g, _c, p in blocks}
    for block_id, _g, _c, _p in blocks:
        have = {p["name"] for p in reports[block_id]["ports"]}
        want = set(port_nets[block_id])
        if not want <= have:
            raise RouteError(f"{block_id}: net table names ports the generator "
                             f"did not emit: {sorted(want - have)}")

    say("[3/6] strap + route")
    draw_params, compose_request, route_summary = build(
        blocks, reports, origins, port_nets)
    (out_dir / "draw.request.json").write_text(
        json.dumps(draw_params, indent=1) + "\n")
    (out_dir / "compose.request.json").write_text(
        json.dumps(compose_request, indent=2) + "\n")
    (out_dir / "route.summary.json").write_text(
        json.dumps(route_summary, indent=2) + "\n")
    say(f"  {len(draw_params['shapes'])} routing shapes, "
        f"{route_summary['met2_columns']} met2 columns")

    say("[4/6] klt draw (routing cell) + klt gen-compose (explicit placement)")
    r = run([klt, "draw", "--params", "draw.request.json", "--cell-name", "ROUTE",
             "-o", "route.gds", "--format", "json"], cwd=out_dir)
    (out_dir / "draw.json").write_text(r.stdout)
    run([klt, "gen-compose", "compose.request.json", "--format", "json"], cwd=out_dir)
    gds = out_dir / f"{TOP_CELL}.gds"
    if not gds.exists():
        raise RuntimeError(f"gen-compose did not write {gds}")

    say("[5/6] klt drc (sky130 deck)")
    r = run([klt, "drc", f"{TOP_CELL}.gds", "--deck", "sky130", "--top", TOP_CELL]
            + pdk_args + ["--format", "json"], cwd=out_dir, check=False)
    drc = json.loads(r.stdout) if r.stdout.strip() else {"error": r.stderr}
    (out_dir / "drc.report.json").write_text(json.dumps(drc, indent=2) + "\n")
    say(f"  drc: status={drc.get('status')!r} violations={drc.get('violation_count')}")

    say("[6/6] klt extract (device-count evidence)")
    run([klt, "extract", f"{TOP_CELL}.gds", "--deck", "sky130", "--top", TOP_CELL]
        + pdk_args + ["-o", f"{TOP_CELL}.extract.spice", "--format", "json"],
        cwd=out_dir)
    netlist = (out_dir / f"{TOP_CELL}.extract.spice").read_text()
    raw, combined = parse_extract_devices(netlist)
    ok, tally = count_check(combined)
    # The eight .subckt ports must come back out of the extractor as named
    # pins: that is what the met1.pin labels are for, and a label that landed
    # on metal the net does not own would silently go missing here.
    pins_found = sorted(line.split()[-1] for line in netlist.splitlines()
                        if line.startswith("* pin "))
    if pins_found != sorted(PIN_NETS):
        raise RuntimeError(
            f"extracted pins {pins_found} != the eight .subckt ports "
            f"{sorted(PIN_NETS)}")
    # Every schematic net must come back as exactly one extracted node.  A
    # terminal the router left dangling still extracts -- as an extra node on
    # an otherwise correct device -- so the device count alone cannot see it;
    # this count can.
    schematic_nets = {net for legs in LEG_NETS.values()
                      for terms in legs.values() for net in terms.values()}
    extracted_nets = extract_nets(netlist)
    if len(extracted_nets) != len(schematic_nets):
        raise RuntimeError(
            f"extracted {len(extracted_nets)} distinct device-terminal nets, "
            f"schematic has {len(schematic_nets)}: a terminal is dangling or "
            f"two nets merged. extracted={extracted_nets} "
            f"schematic={sorted(schematic_nets)}")
    evidence = {
        "tool": {**klt_pin(klt), "deck": "sky130", "top_cell": TOP_CELL,
                 "pdk": PDK_VARIANT,
                 "pdk_sources": "open_pdks f6eeac7 (sim/pdk.json)"},
        "reference_netlist": "design/ota/ota_fd.spice",
        "method": (
            "klt extract over layout/analog/ota_fd/ota_fd.gds; devices counted "
            "by model from the extracted netlist. Two bases are recorded: "
            "raw_counts is one entry per drawn unit device (a mult=M netlist "
            "device is drawn as M interleaved units, so it appears M times), "
            "and merged_counts merges devices sharing a model and all "
            "terminals, mirroring an LVS combine-parallel-devices pass. "
            "merged_counts is the basis compared against the netlist's 29 "
            "instance lines; the mult-expanded unit count is raw_counts."),
        "comparison_basis": "merged_counts vs the 29 X-lines of the netlist",
        "extracted_pins": pins_found,
        "net_count": {"schematic": len(schematic_nets),
                      "extracted": len(extracted_nets)},
        "raw_counts": dict(sorted(raw.items())),
        "merged_counts": dict(sorted(combined.items())),
        "check": tally,
        "pass": ok,
    }
    (out_dir / "extract-device-count.json").write_text(
        json.dumps(evidence, indent=2) + "\n")
    say(f"  extract device count (merged): {tally['found']} "
        f"{'PASS' if ok else 'FAIL'}")
    if not ok:
        raise RuntimeError(f"extract device count check FAILED: {tally}")
    return {"drc": drc, "extract": evidence, "route": route_summary}


def emit(out_dir: Path, cell_dir: Path) -> None:
    shutil.copyfile(out_dir / f"{TOP_CELL}.gds", cell_dir / f"{TOP_CELL}.gds")
    for name in ("extract-device-count.json", "drc.report.json"):
        shutil.copyfile(out_dir / name, cell_dir / name)
    shutil.copyfile(out_dir / "route.summary.json", cell_dir / "route-summary.json")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and verify layout/analog/ota_fd/ota_fd.gds and "
                    "its committed evidence; see this directory's README.md.")
    parser.add_argument("--check", action="store_true",
                        help="regenerate into a temp dir and byte-compare the "
                             "GDS against the committed stream; write nothing")
    parser.add_argument("--klt", default="klt")
    parser.add_argument("--pdk-root", default=PDK_ROOT_DEFAULT)
    parser.add_argument("--keep-scratch", action="store_true",
                        help="with --check, leave the scratch directory in place")
    args = parser.parse_args()

    cell_dir = Path(__file__).resolve().parent
    pdk_root = Path(args.pdk_root).expanduser()

    if args.check:
        committed = cell_dir / f"{TOP_CELL}.gds"
        if not committed.exists():
            print(f"--check: {committed} does not exist yet", file=sys.stderr)
            return 1
        tmp = Path(tempfile.mkdtemp(prefix="ota-fd-check-"))
        try:
            flow(args.klt, pdk_root, tmp, verbose=False)
            a, b = committed.read_bytes(), (tmp / f"{TOP_CELL}.gds").read_bytes()
            if a == b:
                print("gen_ota_fd.py --check: PASS -- regenerated GDS is "
                      f"byte-identical to {committed.name} ({len(a)} bytes)")
                return 0
            print("gen_ota_fd.py --check: FAIL -- regenerated GDS differs "
                  f"(committed {len(a)} bytes, fresh {len(b)} bytes)",
                  file=sys.stderr)
            return 1
        finally:
            if args.keep_scratch:
                print(f"scratch kept at {tmp}", file=sys.stderr)
            else:
                shutil.rmtree(tmp, ignore_errors=True)

    result = flow(args.klt, pdk_root, cell_dir / "_gen")
    emit(cell_dir / "_gen", cell_dir)
    drc = result["drc"]
    print(f"gen_ota_fd.py: wrote {TOP_CELL}.gds + evidence to {cell_dir} "
          f"(drc status={drc.get('status')!r}, "
          f"violations={drc.get('violation_count')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

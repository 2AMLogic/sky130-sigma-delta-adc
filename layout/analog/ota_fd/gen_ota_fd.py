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

import json
import sys
from collections import Counter
from pathlib import Path

# layout_common is the shared plumbing module one directory up (issue #176);
# the path insert is what lets `python3 layout/analog/ota_fd/gen_ota_fd.py`
# run from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from layout_common import (BUCKET_NM, DBU, GRID_UM, L_MET1, L_MET1_PIN,
                           L_MET2, L_MET3, L_MET4, L_VIA2, L_VIA3,
                           MET34_SPACE_UM, MET34_W_UM, PAD34_UM, PDK_VARIANT,
                           TRACK_PITCH_UM, TRUNK_PITCH_UM, VIA2_UM, VIA3_UM,
                           Anchor, Rect, RouteError,
                           Router as RouterBase, WIRE_UM, assert_drc_clean,
                           collect_anchors as collect_cell_anchors,
                           compose_request, draw_compose_and_drc,
                           extract_nets, finalize_routing, finish_net,
                           gen_blocks, group_anchors_by_net, klt_pin, nm,
                           parse_extract_devices, ring_params, run, run_cli,
                           snap)

# --- sky130A GDS layer numbers ------------------------------------------------
# The router core's layers (L_MCON/L_MET1/L_MET2/L_VIA), the anchor
# collection's port layers, the MiM-riser geometry constants
# (L_MET1_PIN/L_VIA2/L_VIA3, VIA2_UM/VIA3_UM/MET34_*_UM/PAD34_UM, issue #377)
# and the net-finishing/compose/DRC helpers all come from layout_common,
# imported here so the shared-table tests can pin that both generators carry
# the one definition.

# --- PDK pin (mirrors sim/pdk.json) -------------------------------------------
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

#: Rows the two body-tie rings enclose (`ring_params` in layout_common sizes
#: each ring from them).
RING_ROWS = {"ptapring": ("nbias", "nsig"), "ntapring": ("pfet",)}


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


# --- anchors ------------------------------------------------------------------
def collect_anchors(blocks, reports, origins, port_nets):
    """Turn every block's ports into anchors, one per (block, net, pad row).

    Thin adapter over the shared collector (``layout_common.collect_anchors``,
    issue #347): this cell's blocks are ``klt gen`` reports placed by
    ``origins``, so each block's ports and bbox are projected into placed
    cell-frame coordinates here (report ports carry ``layer`` as a
    ``{"layer": .., "datatype": ..}`` dict; the shared collector wants the
    tuple form) and the bucketing, pad-row ladders and strapping are the
    shared code's.  Block order is the floorplan order of ``blocks``.
    """
    cells = []
    for block_id, _generator, _cell, _params in blocks:
        report = reports[block_id]
        dx, dy = origins[block_id]["x"], origins[block_id]["y"]
        bb = report["bbox_um"]
        placed = [{"name": p["name"],
                   "layer": (p["layer"]["layer"], p["layer"]["datatype"]),
                   "x_um": p["x_um"] + dx, "y_um": p["y_um"] + dy,
                   "width_um": p["width_um"],
                   "direction_deg": p["direction_deg"]}
                  for p in report["ports"]]
        cells.append((block_id, bb["y0"] + dy, bb["y1"] + dy,
                      placed, port_nets[block_id]))
    return collect_cell_anchors(cells)


# --- router -------------------------------------------------------------------
class Router(RouterBase):
    """met1 horizontal + met2 vertical, one global x column per trunk.

    Every trunk owns its x column outright (``used_cols``), so two met2 runs
    can never come within one pitch of each other and no met2-met2 spacing
    search is needed; met1 is the only layer the greedy search has to keep
    clear, and met3/met4 only carry the MiM risers.  The shared core lives in
    layout_common.Router; the overrides below are the parts this generator
    does differently -- bare ``add_met1``/``add_met`` that tag no shape with
    its net, the unrestricted column proposal, and this cell's own MiM
    risers.  The met2 search budget is the shared ``connect_met1`` reading
    ``COL_BUDGET`` (24 here), and ``finish_trunks`` is the shared one (this
    cell measured zero zero-height trunks, so the shared skip never fires).
    """

    COL_BUDGET = 24

    # -- geometry bookkeeping -------------------------------------------------
    def add_met1(self, net: str, rects: list[Rect]) -> None:
        for rect in rects:
            for b in range(rect.y0 // BUCKET_NM, rect.y1 // BUCKET_NM + 1):
                self.met1_index[b].append((net, rect))
            self.add_shape(L_MET1, rect)
            self.wire_um[net] += max(rect.x1 - rect.x0, rect.y1 - rect.y0) / DBU

    def add_met(self, layer, store, net: str, rects: list[Rect]) -> None:
        for rect in rects:
            store.append((net, rect))
            self.add_shape(layer, rect)
            self.wire_um[net] += (rect.x1 - rect.x0 + rect.y1 - rect.y0) / DBU

    # -- candidate orders ------------------------------------------------------
    def columns(self, x0: float, x1: float, pref: float):
        k0 = int((self.x_lo - 2.0) // TRUNK_PITCH_UM)
        k1 = int((self.x_hi + 2.0) // TRUNK_PITCH_UM) + 1
        cands = [snap(k * TRUNK_PITCH_UM) for k in range(k0, k1 + 1)]
        cands.sort(key=lambda c: (0 if x0 - 1e-9 <= c <= x1 + 1e-9 else 1,
                                  abs(c - pref), c))
        return [c for c in cands if nm(c) not in self.used_cols]

    # -- the three ways a net reaches a block ---------------------------------
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
    # route_spine and finish_trunks are both the shared base's now: this cell
    # drew every trunk unconditionally, but measured (issue #201) to hold zero
    # zero-height trunks, so the shared zero-height skip never fires here.


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

    by_net = group_anchors_by_net(anchors, NET_ORDER)

    summary: dict[str, dict] = {}
    for net in NET_ORDER:
        group = sorted(by_net[net], key=lambda a: (a.block, a.plane, a.y, a.x0))
        placed = [(*router.connect(a), a) for a in group]
        finish_net(router, summary, net, placed, PIN_NETS)
    draw_params = finalize_routing(router, summary)
    compose_req = compose_request(
        TOP_CELL,
        [{"id": b, "generator_report": f"{b}.json"}
         for b, _g, _c, _p in blocks],
        [b for b, _g, _c, _p in blocks], origins)
    route_summary = {
        "block_origins_um": origins,
        # used_cols holds trunks plus the MiM risers' ±1-pitch keep-outs, so
        # this counts reserved columns, not columns that carry a met2 trunk.
        "met2_columns_reserved": len(router.used_cols),
        "nets": summary,
    }
    return draw_params, compose_req, route_summary


# --- device-count evidence ----------------------------------------------------
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
def flow(klt_cmd: list[str], pdk_root: Path, out_dir: Path,
         verbose: bool = True) -> dict:
    pdk_args = ["--pdk", PDK_VARIANT, "--pdk-root", str(pdk_root)]
    out_dir.mkdir(parents=True, exist_ok=True)

    def say(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    say("[1/6] klt gen device blocks")
    reports = gen_blocks(klt_cmd, pdk_args, out_dir, BLOCKS)

    say("[2/6] floorplan + body-tie rings")
    origins, extents = place_rows(reports)
    ring_blocks = []
    for ring_id in RING_BLOCKS:
        params, origin = ring_params([extents[r] for r in RING_ROWS[ring_id]],
                                     ring_id == "ntapring")
        ring_blocks.append((ring_id, "guard_ring", ring_id.upper(), params))
        origins[ring_id] = origin
    reports.update(gen_blocks(klt_cmd, pdk_args, out_dir, ring_blocks))
    blocks = BLOCKS + ring_blocks
    port_nets = {b: expand_ports(b, g, p) for b, g, _c, p in blocks}
    for block_id, _g, _c, _p in blocks:
        have = {p["name"] for p in reports[block_id]["ports"]}
        want = set(port_nets[block_id])
        if not want <= have:
            raise RouteError(f"{block_id}: net table names ports the generator "
                             f"did not emit: {sorted(want - have)}")

    say("[3/6] strap + route")
    draw_params, compose_req, route_summary = build(
        blocks, reports, origins, port_nets)
    # Per-row footprints, keyed by the ROWS ids the README's floorplan table
    # quotes: the authoritative row spans, emitted so the README does not have
    # to hand-transcribe them (a ring's span is not a row's span).
    route_summary["row_extents_um"] = {
        row_id: {"x0": round(e[0], 3), "y0": round(e[1], 3),
                 "x1": round(e[2], 3), "y1": round(e[3], 3)}
        for row_id, e in extents.items()
    }
    say(f"  {len(draw_params['shapes'])} routing shapes, "
        f"{route_summary['met2_columns_reserved']} met2 columns reserved")
    drc = draw_compose_and_drc(
        klt_cmd, pdk_args, out_dir, TOP_CELL, draw_params, compose_req,
        route_summary, say=say,
        draw_step="[4/6] klt draw (routing cell) + klt gen-compose "
                  "(explicit placement)",
        drc_step="[5/6] klt drc (sky130 deck)")

    say("[6/6] klt extract (device-count evidence)")
    run([*klt_cmd, "extract", f"{TOP_CELL}.gds", "--deck", "sky130", "--top", TOP_CELL]
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
        "tool": {**klt_pin(klt_cmd), "deck": "sky130", "top_cell": TOP_CELL,
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


def main() -> int:
    return run_cli("gen_ota_fd.py", Path(__file__).resolve().parent,
                   TOP_CELL, flow)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""layout/analog/integrator/gen_integrator.py -- generate the SC integrator
cell's GDS (issue #119).

The single reviewable source for ``layout/analog/integrator/integrator.gds``:
every polygon in that stream is either emitted by ``klt gen`` (one call per
unique device geometry), copied in from the **committed** OTA cell
``layout/analog/ota_fd/ota_fd.gds`` (#118) as a placed instance, or emitted by
this script's own floorplan/router through ``klt draw``.  Nothing is hand-drawn
and nothing is edited in a GUI.

    python3 layout/analog/integrator/gen_integrator.py          # regenerate + emit
    python3 layout/analog/integrator/gen_integrator.py --check  # regenerate into a
                                                                # temp dir, compare

Reference netlist: ``design/integrator/integrator.spice`` -- 44 primitive
device lines (9 ``nfet_01v8``, 12 ``nfet_01v8_lvt``, 9 ``pfet_01v8``, 8
``pfet_01v8_lvt``, 6 ``cap_mim_m3_1``) plus the ``xota`` instance of
``ota_fd``.  Ports: ``vdda vssa vinp vinn vrefp vrefn vcm ibias phi1 phi1b
phi1e phi2 dp dn voutp voutn``.  Sizing rationale:
``design/integrator/SIZING.md``.  PDK pin: ``sim/pdk.json`` (sky130A, open_pdks
``f6eeac7``), resolved from ``~/.ciel`` unless ``--pdk-root`` says otherwise.

Method (the sibling ``layout/analog/ota_fd/gen_ota_fd.py`` is the pattern, and
it in turn follows the pinned ``2AMLogic/sky130-comparator`` at
``a0767fa5a4bedc9128a7e95b8b512075536522c8``):

* **Devices** are 100% ``klt gen`` geometry: one ``mos_array`` per netlist
  transistor and one ``cap_array`` unit per netlist capacitor, so the drawn
  device count equals the netlist's line for line.  Blocks that share a
  geometry share one ``klt gen`` call (the report is referenced by several
  ``blocks[]`` entries) -- 9 calls cover all 44 devices.
* **The OTA is instantiated, never redrawn**: a ``blocks[].cell`` entry naming
  ``layout/analog/ota_fd/ota_fd.gds`` / cell ``ota_fd``, whose sha256 this
  script asserts before it runs.  Its eight ports are recovered with
  ``cell.ports_from_labels`` over the ``met1.pin`` (68/5) labels #118 drew,
  each with an ``access`` landing search that picks a point where a via1/via2
  ladder up to met3 clears the OTA's own geometry.
* **Mirror symmetry.** The cell has a horizontal axis.  The p-side device rows
  sit above it and the n-side rows are the same blocks at mirrored y with the
  mirrored ``orientation``, so each capacitor group (``Csi``, ``Csr``, ``Ci``)
  is a true mirror pair about that axis.  The OTA is placed so that its own
  ``inn``/``inp`` (= ``sump``/``sumn``) labels straddle the axis.
* **Low-Vth markers.** ``klt gen mos_array``'s ``voltage_flavor`` draws no
  sky130 low-Vth marker (see README), so this script draws the ``lvtn``
  (125/44) rectangle over each ``_lvt`` device itself, through ``klt draw``,
  and asserts no marker reaches a non-``_lvt`` device.
* **Placement and every wire** come from this script: ``klt gen-compose`` is
  used as a placer only (``placement.strategy: "explicit"``, no ``routing``
  block).  met1 carries horizontal runs and pad jogs, met2 per-anchor vertical
  trunks, met3/met4 the MiM risers and the eight OTA escapes.  No met1/met2 of
  this script's is ever placed over the OTA instance -- the router's x window
  stops short of it -- so only met3, which the OTA does not use above y=62 in
  its own frame, crosses it.

Determinism: no randomness, every iteration order is sorted or table-driven,
so a re-run at the same klt build reproduces the stream byte for byte --
which is what ``--check`` asserts.
"""
from __future__ import annotations

import argparse
import hashlib
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
L_LVTN = (125, 44)

# --- rule-derived geometry (sky130 deck minimums plus margin) -----------------
# Identical to the sibling OTA generator's table; see
# layout/analog/ota_fd/gen_ota_fd.py for the per-constant derivation.
DBU = 1000
GRID_UM = 0.005          # manufacturing grid (*.ongrid.1)
MCON_UM = 0.17           # ct.1 exact size
VIA_UM = 0.15            # via.1a exact size
VIA2_UM = 0.20           # via2.1a exact size
VIA3_UM = 0.20           # via3.1a exact size
WIRE_UM = 0.34           # met1/met2 wire width (via1 enclosure sets the floor)
MET1_SPACE_UM = 0.14     # m1.2
MET34_W_UM = 0.60        # met3/met4 wire width
MET34_SPACE_UM = 0.30    # m3.2/m4.2
PAD34_UM = 0.60          # met2/met3/met4 landing pad for a via2/via3
#: Pad sides of the via1+via2 ladder drawn at an OTA landing point.  The
#: **minimum legal** side on each layer, deliberately -- not klt's own landing
#: pad (0.42/0.42/0.49), which is larger:
#:
#:   met1  max(via1 0.15 + 2 x met1.enclosing_adjacent.via.1 0.085,
#:            sqrt(met1.area.1 0.083))            = 0.32 -> 0.34
#:   met2  max(via2 0.20 + 2 x met2.enclosing.via2.1 0.085,
#:            sqrt(met2.area.1 0.14))             = 0.374 -> 0.38
#:   met3  max(via2 0.20 + 2 x 0.085, met3.width.1 0.30,
#:            sqrt(met3.area.1 0.24))             = 0.49
#:
#: Minimum matters because `access`'s clearance search ignores the port net's
#: **own** shapes: a pad that protrudes past the OTA's own 0.34um wire on that
#: net leaves a sub-minimum notch against the OTA's *other* metal, which the
#: deck flags exactly like a two-net violation and the search does not see.
#: 0.42um pads did precisely that on `outn` (met1.space.1 + met2.space.1, a
#: 0.13um gap).  met1 is set to the OTA's own wire width so a landing pad can
#: never stick out of the run it lands on at all.  Filed upstream -- see the
#: README.
LANDING_MET1_UM = 0.34
LANDING_MET2_UM = 0.38
LANDING_MET3_UM = 0.49
PAD_MARGIN_UM = 0.12     # keep an mcon this far inside its li1 pad's own edge
TRUNK_PITCH_UM = 0.50    # x grid for met2 trunks
TRACK_PITCH_UM = 0.50    # y grid for met1 spines
JOG_REACH_UM = 6.0       # how far a met1 jog may climb off a strap's own y
BUCKET_NM = 2000         # y bucket for the met1 overlap index

#: `lvtn` enclosure of the device it marks.  sky130's own lvtn rules are not in
#: klt's curated deck (the layer comes back under
#: `layers_in_stream_without_rules`), so this is the PDK's documented 0.38um
#: enclosure applied to the whole drawn device box, not a deck-checked number.
LVTN_ENCLOSE_UM = 0.38

# --- PDK pin (mirrors sim/pdk.json) -------------------------------------------
PDK_VARIANT = "sky130A"
PDK_ROOT_DEFAULT = "~/.ciel"
TOP_CELL = "integrator"

# --- the instantiated OTA cell (#118) -----------------------------------------
#: Relative to this file.  The hash is asserted before anything is generated:
#: this cell's geometry is only valid against the OTA it was floorplanned
#: around, so a re-sized OTA (#143) must fail loudly rather than silently
#: produce a stale stream.
OTA_GDS_REL = "../ota_fd/ota_fd.gds"
OTA_CELL = "ota_fd"
OTA_GDS_SHA256 = "27ace056b255428e05c0fd6293dd08239fe97ba67379f6a330c30a94eeefe976"

#: The reference netlist, and its hash, pinned for the same reason: #129/#147
#: can re-size the switches drawn here and #143 the OTA, and a drawn cell whose
#: netlist moved underneath it is stale, not merely out of date.  Same
#: `integrator_netlist_sha256` convention the `sim/` records use.
NETLIST_REL = "../../../design/integrator/integrator.spice"
NETLIST_SHA256 = "18fc51475f667eea993fbef4e9a3abe7eaa35863ae88f86c25bfb56bc4074d53"

#: The OTA's eight `.subckt` ports, as `met1.pin` label text in its stream, and
#: the integrator net each one is.  `inp`/`inn` are the OTA's *inputs*: the OTA
#: inverts inn->outp, so the p-side summing node `sump` lands on the OTA's
#: `inn` (design/integrator/SIZING.md, "Integrating cap").
OTA_PORT_NETS: dict[str, str] = {
    "vdda": "vdda",
    "vssa": "vssa",
    "inp": "sumn",
    "inn": "sump",
    "outp": "voutp",
    "outn": "voutn",
    "vcm": "vcm",
    "ibias": "ibias",
}

#: Landing-search grid for `ports_from_labels`, per OTA port.  Measured
#: against #118's committed geometry, which this script hash-pins, so these
#: are facts about that stream rather than free knobs:
#:
#: * 0.5um finds no legal via1/via2 ladder for `inp`;
#: * 0.05um resolves seven of the eight;
#: * `vcm` needs 0.01um -- inside the OTA it is one 0.42um gate strap that
#:   already carries its own via1, so the only legal cut sits 0.32um off the
#:   label and a 0.05um grid steps over it.
#:
#: The coarse default is kept for the other seven because the search cost is
#: quadratic in the net's own area and `vdda`/`vssa` span the whole cell.
OTA_ACCESS_GRID_UM = 0.05
OTA_ACCESS_GRID_OVERRIDE_UM = {"vcm": 0.01}
OTA_ACCESS_MAX_CANDIDATES = 20000

#: The OTA label this script places the cell by.  Its `inn`/`inp` labels are
#: 9.52um apart in the OTA's own frame; the cell's mirror axis is put at their
#: midpoint so the two summing nodes are symmetric about it.
OTA_AXIS_LABELS = ("inn", "inp")


# --- device geometries --------------------------------------------------------
#: (generator, params) per distinct drawn geometry.  Several netlist devices
#: share one entry -- the generated report is referenced by each of their
#: `blocks[]` entries, so 44 devices cost 9 `klt gen` calls.
#:
#: `dummy` is 0 everywhere, as in the sibling OTA cell: klt's dummy elements do
#: not extract as devices, but they widen every row and nothing here needs
#: them (the matched groups that matter are the capacitors, which `cap_array`
#: draws without dummies either way).
GEOMETRIES: dict[str, tuple[str, dict]] = {
    # 1.8V core nFET half of a transmission gate (W=4, L=0.15)
    "n4": ("mos_array", {
        "w_um": 4.0, "l_um": 0.15, "fingers": 1, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "nfet", "gate_contact": True}),
    # 1.8V core pFET half of a transmission gate (W=8, L=0.15)
    "p8": ("mos_array", {
        "w_um": 8.0, "l_um": 0.15, "fingers": 1, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "pfet", "gate_contact": True}),
    # low-Vth nFET switch (W=12, L=0.15) -- needs the lvtn marker
    "nl12": ("mos_array", {
        "w_um": 12.0, "l_um": 0.15, "fingers": 1, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "nfet", "gate_contact": True}),
    # low-Vth pFET bottom-plate switch (W=24, L=0.35) -- needs the lvtn marker
    "pl24": ("mos_array", {
        "w_um": 24.0, "l_um": 0.35, "fingers": 1, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "pfet", "gate_contact": True}),
    # low-Vth pFET top-plate switch (W=4, L=0.35) -- needs the lvtn marker
    "pl4": ("mos_array", {
        "w_um": 4.0, "l_um": 0.35, "fingers": 1, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "pfet", "gate_contact": True}),
    # phi2b inverter, mult=4 drawn as 4 fingers of the netlist's own W
    "inv_n": ("mos_array", {
        "w_um": 2.0, "l_um": 0.15, "fingers": 4, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "nfet", "gate_contact": True}),
    "inv_p": ("mos_array", {
        "w_um": 4.0, "l_um": 0.15, "fingers": 4, "rows": 1, "cols": 1,
        "dummy": 0, "flavor": "pfet", "gate_contact": True}),
    # 1.000 pF sampling capacitor (22.17 x 22.17 um, SIZING.md:62)
    "cap1p": ("cap_array", {
        "plate_w_um": 22.17, "plate_h_um": 22.17, "num": 1}),
    # 2.000 pF integrating capacitor (31.43 x 31.43 um, SIZING.md:63)
    "cap2p": ("cap_array", {
        "plate_w_um": 31.43, "plate_h_um": 31.43, "num": 1}),
}

#: Geometries whose devices are the netlist's `_lvt` models, and so carry a
#: hand-drawn `lvtn` marker.
LVT_GEOMETRIES = ("nl12", "pl24", "pl4")

# --- schematic connectivity ---------------------------------------------------
# Transcribed device by device from design/integrator/integrator.spice.  The
# block id is the netlist instance name, lower-cased without its leading `X`;
# MOS terminals are the netlist's own D G S B order (B is the well/substrate,
# tied by this row's guard ring rather than routed), and a capacitor's two
# terminals are the netlist's own order: first terminal -> TOP, which is what
# binds the amplifier-side plate to the MiM top plate (`c0`) per
# design/integrator/SIZING.md:72-74.
#
# `p` blocks carry the p-side suffix, `n` blocks the n-side one; every entry
# below has a mirror-image partner except the phi2b inverter, which is single
# ended and sits in its own row outside the mirrored field.
DEVICES: dict[str, tuple[str, dict[str, str]]] = {
    # -- p side, nFET ----------------------------------------------------------
    "sin_p_n":  ("n4",   {"D": "vinp", "G": "phi1", "S": "bpi_p"}),
    "mra_p_n":  ("n4",   {"D": "vrefp", "G": "dn", "S": "rsel_p"}),
    "mrb_p_n":  ("n4",   {"D": "vrefn", "G": "dp", "S": "rsel_p"}),
    "sr_p_n":   ("n4",   {"D": "rsel_p", "G": "phi1", "S": "bpr_p"}),
    "sbi_p":    ("nl12", {"D": "bpi_p", "G": "phi2", "S": "vcm"}),
    "sbr_p":    ("nl12", {"D": "bpr_p", "G": "phi2", "S": "vcm"}),
    "sci_p":    ("nl12", {"D": "tpi_p", "G": "phi1e", "S": "vcm"}),
    "scr_p":    ("nl12", {"D": "tpr_p", "G": "phi1e", "S": "vcm"}),
    "sti_p":    ("nl12", {"D": "tpi_p", "G": "phi2", "S": "sump"}),
    "str_p":    ("nl12", {"D": "tpr_p", "G": "phi2", "S": "sump"}),
    # -- p side, pFET ----------------------------------------------------------
    "sin_p_p":  ("p8",   {"D": "vinp", "G": "phi1b", "S": "bpi_p"}),
    "mra_p_p":  ("p8",   {"D": "vrefp", "G": "dp", "S": "rsel_p"}),
    "mrb_p_p":  ("p8",   {"D": "vrefn", "G": "dn", "S": "rsel_p"}),
    "sr_p_p":   ("p8",   {"D": "rsel_p", "G": "phi1b", "S": "bpr_p"}),
    "sbi_p_p":  ("pl24", {"D": "bpi_p", "G": "phi2b", "S": "vcm"}),
    "sbr_p_p":  ("pl24", {"D": "bpr_p", "G": "phi2b", "S": "vcm"}),
    "sti_p_p":  ("pl4",  {"D": "tpi_p", "G": "phi2b", "S": "sump"}),
    "str_p_p":  ("pl4",  {"D": "tpr_p", "G": "phi2b", "S": "sump"}),
    # -- p side, capacitors ----------------------------------------------------
    "csi_p":    ("cap1p", {"TOP": "tpi_p", "BOT": "bpi_p"}),
    "csr_p":    ("cap1p", {"TOP": "tpr_p", "BOT": "bpr_p"}),
    "ci_p":     ("cap2p", {"TOP": "sump", "BOT": "voutp"}),
    # -- n side, nFET ----------------------------------------------------------
    "sin_n_n":  ("n4",   {"D": "vinn", "G": "phi1", "S": "bpi_n"}),
    "mra_n_n":  ("n4",   {"D": "vrefn", "G": "dn", "S": "rsel_n"}),
    "mrb_n_n":  ("n4",   {"D": "vrefp", "G": "dp", "S": "rsel_n"}),
    "sr_n_n":   ("n4",   {"D": "rsel_n", "G": "phi1", "S": "bpr_n"}),
    "sbi_n":    ("nl12", {"D": "bpi_n", "G": "phi2", "S": "vcm"}),
    "sbr_n":    ("nl12", {"D": "bpr_n", "G": "phi2", "S": "vcm"}),
    "sci_n":    ("nl12", {"D": "tpi_n", "G": "phi1e", "S": "vcm"}),
    "scr_n":    ("nl12", {"D": "tpr_n", "G": "phi1e", "S": "vcm"}),
    "sti_n":    ("nl12", {"D": "tpi_n", "G": "phi2", "S": "sumn"}),
    "str_n":    ("nl12", {"D": "tpr_n", "G": "phi2", "S": "sumn"}),
    # -- n side, pFET ----------------------------------------------------------
    "sin_n_p":  ("p8",   {"D": "vinn", "G": "phi1b", "S": "bpi_n"}),
    "mra_n_p":  ("p8",   {"D": "vrefn", "G": "dp", "S": "rsel_n"}),
    "mrb_n_p":  ("p8",   {"D": "vrefp", "G": "dn", "S": "rsel_n"}),
    "sr_n_p":   ("p8",   {"D": "rsel_n", "G": "phi1b", "S": "bpr_n"}),
    "sbi_n_p":  ("pl24", {"D": "bpi_n", "G": "phi2b", "S": "vcm"}),
    "sbr_n_p":  ("pl24", {"D": "bpr_n", "G": "phi2b", "S": "vcm"}),
    "sti_n_p":  ("pl4",  {"D": "tpi_n", "G": "phi2b", "S": "sumn"}),
    "str_n_p":  ("pl4",  {"D": "tpr_n", "G": "phi2b", "S": "sumn"}),
    # -- n side, capacitors ----------------------------------------------------
    "csi_n":    ("cap1p", {"TOP": "tpi_n", "BOT": "bpi_n"}),
    "csr_n":    ("cap1p", {"TOP": "tpr_n", "BOT": "bpr_n"}),
    "ci_n":     ("cap2p", {"TOP": "sumn", "BOT": "voutn"}),
    # -- the phi2b inverter (single ended, mult=4 each) ------------------------
    "iphi2b_n": ("inv_n", {"D": "phi2b", "G": "phi2", "S": "vssa"}),
    "iphi2b_p": ("inv_p", {"D": "vdda", "G": "phi2", "S": "phi2b"}),
}

#: Body-tie rings, keyed the same as :data:`RING_ROWS`: ``(add_well, net)``.
#: ``add_well`` draws the n+-tap-in-an-nwell ring whose tap ties a pFET row's
#: bulk to ``vdda``; without it the ring is a p+ tap in the p-substrate tying
#: an nFET row's bulk to ``vssa``.  Each is sized in ``build_floorplan()``
#: from the row it encloses.
RINGS: dict[str, tuple[bool, str]] = {
    "ptap_swn_p": (False, "vssa"), "ntap_swp_p": (True, "vdda"),
    "ptap_swn_n": (False, "vssa"), "ntap_swp_n": (True, "vdda"),
    "ptap_p": (False, "vssa"), "ntap_p": (True, "vdda"),
    "ptap_n": (False, "vssa"), "ntap_n": (True, "vdda"),
    "ptap_inv": (False, "vssa"), "ntap_inv": (True, "vdda"),
}
RING_PAD_UM = 2.0
RING_WIDTH_UM = 0.42

# --- floorplan ----------------------------------------------------------------
#: Half-rows, listed from the mirror axis outward.  Each is
#: ``(row id, gap from the previous row's outer edge, alignment, members)``.
#: The p-side instance of a row is ``p_<id>`` and the n-side one ``n_<id>``;
#: the n-side block is the same geometry at the mirrored orientation, placed
#: so that its outer edge is the mirror image of the p-side row's.
#:
#: The first two rows exist to keep the summing node short.  ``sump``/``sumn``
#: are the nodes DR-004 names as the most sensitive on the die, and every
#: device on them -- the four ``Sti``/``Str`` switch halves per side and the
#: integrating capacitor's top plate -- is pulled to the rows nearest the
#: mirror axis, right-aligned against the OTA's own ``inn``/``inp`` escapes,
#: which sit 4.8um either side of that axis.  The nFET and pFET halves need
#: separate body-tie rings, hence two rows rather than one.  Everything whose
#: placement the summing node does not care about is further out.
#:
#: Alignment is ``"right"`` for those two rows (flush with the device field's
#: right edge, i.e. as close to the OTA as the floorplan gets) and ``"left"``
#: for the rest.
HALF_ROWS: list[tuple[str, float, str, tuple[str, ...]]] = [
    ("swn", 3.0, "right", ("sti_{s}", "str_{s}")),
    ("swp", 10.0, "right", ("sti_{s}_p", "str_{s}_p")),
    ("cap", 10.0, "left", ("csr_{s}", "csi_{s}", "ci_{s}")),
    ("nfet", 11.0, "left", ("mra_{s}_n", "mrb_{s}_n", "sin_{s}_n", "sr_{s}_n",
                            "sbi_{s}", "sbr_{s}", "sci_{s}", "scr_{s}")),
    ("pfet", 13.0, "left", ("mra_{s}_p", "mrb_{s}_p", "sin_{s}_p", "sr_{s}_p",
                            "sbi_{s}_p", "sbr_{s}_p")),
]

#: The two inverter rows, beyond the p-side `pfet` row, outside the mirrored
#: field (the inverter is single ended, so it has no mirror partner).
INV_ROWS: list[tuple[str, float, str, tuple[str, ...]]] = [
    ("inv_n", 13.0, "left", ("iphi2b_n",)),
    ("inv_p", 9.0, "left", ("iphi2b_p",)),
]

#: Which rows each ring encloses.  One ring per (flavour, half-row, side),
#: plus one per inverter device: `add_well` picks the n+-tap-in-an-nwell ring
#: (pFET bulk -> vdda) over the p+-tap ring (nFET bulk -> vssa).
RING_ROWS: dict[str, tuple[str, ...]] = {
    "ptap_swn_p": ("p_swn",), "ntap_swp_p": ("p_swp",),
    "ptap_swn_n": ("n_swn",), "ntap_swp_n": ("n_swp",),
    "ptap_p": ("p_nfet",), "ntap_p": ("p_pfet",),
    "ptap_n": ("n_nfet",), "ntap_n": ("n_pfet",),
    "ptap_inv": ("inv_n",), "ntap_inv": ("inv_p",),
}

ROW_LEFT_UM = 4.0        # x of the leftmost block in every row
#: Inter-block gap inside a row.  Wider than a DRC minimum on purpose: the
#: router gives every met2 trunk its own global x column on a 0.5um grid, so
#: the device field has to be wide enough to hold one column per anchor
#: (about 150 of them) plus the three a MiM riser reserves.  14um per gap
#: leaves roughly 40% of the columns free at the end of a run.
ROW_GAP_UM = 14.0
CAP_GAP_UM = 14.0        # inter-block gap inside a capacitor row
ESCAPE_CHANNEL_UM = 26.0  # between the device field's right edge and the OTA
ESCAPE_PITCH_UM = 1.0     # x pitch of the eight OTA escape columns

#: The sixteen `.subckt` ports, labelled on met1.pin in the composed cell.
PIN_NETS = ("vdda", "vssa", "vinp", "vinn", "vrefp", "vrefn", "vcm", "ibias",
            "phi1", "phi1b", "phi1e", "phi2", "dp", "dn", "voutp", "voutn")

#: Net routing order.  The two summing nodes go first -- they are the nodes
#: DR-004 names as the most sensitive on the die, and routing them before
#: anything else is what makes their runs the shortest the floorplan allows.
#: Then the other high-impedance plate nets, then the clocks, then the
#: boundary signals, and the two supplies last (most anchors, most freedom).
NET_ORDER = (
    "sump", "sumn",
    "tpi_p", "tpi_n", "tpr_p", "tpr_n",
    "bpi_p", "bpi_n", "bpr_p", "bpr_n",
    "rsel_p", "rsel_n",
    "voutp", "voutn",
    "phi1e", "phi2b", "phi1", "phi1b", "phi2",
    "dp", "dn", "vinp", "vinn", "vrefp", "vrefn",
    "vcm", "ibias", "vssa", "vdda",
)

#: Device-count expectation for *this* cell's own devices: the netlist's own
#: model names and counts, one entry per `design/integrator/integrator.spice`
#: model.  The OTA's devices are subtracted out by extracting the committed
#: `ota_fd.gds` on its own in the same run.
#:
#: The low-Vth split IS asserted here.  Issue #119's acceptance criterion was
#: weakened to a flavour-blind 21 nfet / 17 pfet total on the strength of a
#: curator probe that found `klt extract --deck sky130` ignoring an `lvtn`
#: marker; on this cell's geometry it does not -- the extracted netlist names
#: `sky130_fd_pr__nfet_01v8_lvt` and `sky130_fd_pr__pfet_01v8_lvt` and gets
#: all twenty right.  See this directory's README for the difference between
#: the two probes.  Asserting the stronger thing is the point of the check, so
#: it asserts the stronger thing.
EXPECTED_DEVICES = {
    "sky130_fd_pr__nfet_01v8": 9,
    "sky130_fd_pr__nfet_01v8_lvt": 12,
    "sky130_fd_pr__pfet_01v8": 9,
    "sky130_fd_pr__pfet_01v8_lvt": 8,
    "sky130_fd_pr__cap_mim_m3_1": 6,
}

#: The flavour-blind totals the issue's own acceptance criterion asks for,
#: recorded beside the per-model counts so the committed evidence answers the
#: criterion as written as well as the stronger question.
EXPECTED_FLAVOUR_BLIND = {"nfet": 21, "pfet": 17, "cap_mim": 6}


def nm(value_um: float) -> int:
    return int(round(value_um * DBU))


def snap(value_um: float) -> float:
    """Round onto the PDK manufacturing grid (*.ongrid.1)."""
    return round(round(value_um / GRID_UM) * GRID_UM, 6)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


# --- orientation --------------------------------------------------------------
#: `klt gen-compose`'s own `blocks[].orientation` point transforms, mirrored
#: here so the floorplan can reason about a block's placed bbox and ports
#: without a round trip.  Kept identical to gen_compose's `_apply_orientation_um`
#: /`_ORIENTATION_DIRECTION_MAP`; `check_orientation_agrees()` asserts it.
_DIR_MAP = {
    "none": {0: 0, 90: 90, 180: 180, 270: 270},
    "mirror_x": {0: 180, 90: 90, 180: 0, 270: 270},
    "mirror_y": {0: 0, 90: 270, 180: 180, 270: 90},
    "rotate_180": {0: 180, 90: 270, 180: 0, 270: 90},
}
#: The orientation an n-side block takes, given its p-side partner's -- the
#: reflection about a horizontal axis (`mirror_y` composed with it).
_MIRROR_OF = {"none": "mirror_y", "mirror_y": "none",
              "rotate_180": "mirror_x", "mirror_x": "rotate_180"}


def orient_xy(x: float, y: float, orientation: str) -> tuple[float, float]:
    if orientation == "mirror_x":
        return -x, y
    if orientation == "mirror_y":
        return x, -y
    if orientation == "rotate_180":
        return -x, -y
    return x, y


def orient_bbox(bb: dict, orientation: str) -> dict:
    x0, y0 = orient_xy(bb["x0"], bb["y0"], orientation)
    x1, y1 = orient_xy(bb["x1"], bb["y1"], orientation)
    return {"x0": min(x0, x1), "y0": min(y0, y1),
            "x1": max(x0, x1), "y1": max(y0, y1)}


# --- blocks -------------------------------------------------------------------
class Block:
    """One placed `blocks[]` entry: a geometry, an orientation and an origin."""

    __slots__ = ("block_id", "geometry", "orientation", "origin", "report",
                 "is_ring", "nets")

    def __init__(self, block_id: str, geometry: str, orientation: str,
                 nets: dict[str, str], is_ring: bool = False) -> None:
        self.block_id = block_id
        self.geometry = geometry
        self.orientation = orientation
        self.nets = nets
        self.is_ring = is_ring
        self.origin = {"x": 0.0, "y": 0.0}
        self.report: dict = {}

    @property
    def bbox(self) -> dict:
        """Placed bbox: oriented, then translated by the origin."""
        bb = orient_bbox(self.report["bbox_um"], self.orientation)
        return {"x0": bb["x0"] + self.origin["x"], "y0": bb["y0"] + self.origin["y"],
                "x1": bb["x1"] + self.origin["x"], "y1": bb["y1"] + self.origin["y"]}

    def size(self) -> tuple[float, float]:
        bb = orient_bbox(self.report["bbox_um"], self.orientation)
        return bb["x1"] - bb["x0"], bb["y1"] - bb["y0"]

    def ports(self) -> list[dict]:
        """Placed ports: oriented x/y/direction, then translated."""
        out = []
        for p in self.report["ports"]:
            x, y = orient_xy(p["x_um"], p["y_um"], self.orientation)
            out.append({
                "name": p["name"],
                "layer": (p["layer"]["layer"], p["layer"]["datatype"]),
                "x_um": x + self.origin["x"], "y_um": y + self.origin["y"],
                "width_um": p["width_um"],
                "direction_deg": _DIR_MAP[self.orientation][p["direction_deg"]],
            })
        return out


def port_nets_of(block: Block) -> dict[str, str]:
    """{generated port name: net} for one block.

    A `mos_array` unit exposes `U0_S`/`U0_D`/`U0_G`; a `cap_array` unit
    `C0_BOT`/`C0_TOP`; a `guard_ring` one `TAP_<side>` per side, of which only
    the west one is wired (all four sit on the same closed li1 ring, so one
    stands for the conductor and a second would ask the router to cross the
    ring's own interior).
    """
    if block.is_ring:
        return {"TAP_W": block.nets["TAP"]}
    generator = GEOMETRIES[block.geometry][0]
    prefix = "C0_" if generator == "cap_array" else "U0_"
    return {prefix + suffix: net for suffix, net in sorted(block.nets.items())}


def gen_geometries(klt: str, pdk_args: list[str], out_dir: Path,
                   wanted: list[str]) -> dict[str, dict]:
    """One `klt gen` call per distinct geometry, keyed by its id."""
    reports: dict[str, dict] = {}
    for key in sorted(wanted):
        generator, params = GEOMETRIES[key]
        r = run([klt, "gen", generator, "--params", json.dumps(params, sort_keys=True)]
                + pdk_args + ["--cell-name", key.upper(), "-o", f"{key}.gds",
                              "--format", "json"], cwd=out_dir)
        report = json.loads(r.stdout)
        if report.get("error"):
            raise RuntimeError(f"klt gen {key}: {report['error']}")
        (out_dir / f"{key}.json").write_text(r.stdout)
        reports[key] = report
    return reports


def gen_rings(klt: str, pdk_args: list[str], out_dir: Path,
              ring_params: dict[str, dict]) -> dict[str, dict]:
    reports: dict[str, dict] = {}
    for ring_id in sorted(ring_params):
        r = run([klt, "gen", "guard_ring", "--params",
                 json.dumps(ring_params[ring_id], sort_keys=True)]
                + pdk_args + ["--cell-name", ring_id.upper(), "-o", f"{ring_id}.gds",
                              "--format", "json"], cwd=out_dir)
        report = json.loads(r.stdout)
        if report.get("error"):
            raise RuntimeError(f"klt gen {ring_id}: {report['error']}")
        (out_dir / f"{ring_id}.json").write_text(r.stdout)
        reports[ring_id] = report
    return reports


# --- floorplan ----------------------------------------------------------------
def row_members(row_id: str, side: str) -> list[str]:
    for base, _gap, _align, members in HALF_ROWS + INV_ROWS:
        if base == row_id:
            return [m.format(s=side) for m in members]
    raise KeyError(row_id)


def build_floorplan(reports: dict[str, dict]) -> tuple[dict[str, Block],
                                                       dict[str, tuple],
                                                       float, float]:
    """Place every device block.

    Returns ``(blocks, row extents, mirror-axis y, x of the OTA's left edge)``.
    """
    blocks: dict[str, Block] = {}

    def p_orientation(block_id: str) -> str:
        """A p-side block's own orientation.

        The capacitors are turned so their MiM top plate -- the amplifier-side
        plate, ``design/integrator/SIZING.md:72-74`` -- faces the mirror axis,
        which is what keeps the two summing-node runs short.  Everything else
        is placed as generated.
        """
        return "rotate_180" if GEOMETRIES[DEVICES[block_id][0]][0] == "cap_array" \
            else "none"

    def make(block_id: str, orientation: str) -> Block:
        geometry, nets = DEVICES[block_id]
        b = Block(block_id, geometry, orientation, nets)
        b.report = reports[geometry]
        blocks[block_id] = b
        return b

    # -- measure the p-side half: each member's width, and each row's height --
    half: list[tuple[str, float, float, str, list[tuple[str, float]]]] = []
    offset = 0.0
    for base, gap, align, _members in HALF_ROWS:
        members = row_members(base, "p")
        offset += gap
        widths: list[tuple[str, float]] = []
        row_h = 0.0
        for block_id in members:
            probe = Block(block_id, DEVICES[block_id][0], p_orientation(block_id),
                          DEVICES[block_id][1])
            probe.report = reports[probe.geometry]
            w, h = probe.size()
            widths.append((block_id, w))
            row_h = max(row_h, h)
        half.append((base, offset, row_h, align, widths))
        offset += row_h
    half_height = offset

    def row_width(widths: list[tuple[str, float]], base: str) -> float:
        inner_gap = CAP_GAP_UM if base == "cap" else ROW_GAP_UM
        return sum(w for _b, w in widths) + inner_gap * (len(widths) - 1)

    # The device field is as wide as its widest row.  A `"right"` row is then
    # flushed against that edge, which is the edge the OTA sits beyond.
    field_w = max(row_width(widths, base) for base, _o, _h, _a, widths in half)

    def row_x_positions(widths, base, align) -> list[tuple[str, float]]:
        inner_gap = CAP_GAP_UM if base == "cap" else ROW_GAP_UM
        x = ROW_LEFT_UM + (field_w - row_width(widths, base)
                           if align == "right" else 0.0)
        out = []
        for block_id, w in widths:
            out.append((block_id, snap(x)))
            x += w + inner_gap
        return out

    # The axis has to clear two things: half the mirrored device field, and the
    # OTA's own `inn` label, which sits about 102.6um above the instance's
    # origin.  Pick the larger, with a margin, so the composed cell starts at a
    # positive y whichever one wins.
    axis_y = snap(max(half_height, 110.0) + 6.0)

    # -- place both halves ----------------------------------------------------
    extents: dict[str, tuple[float, float, float, float]] = {}
    for base, offset_in, _row_h, align, widths in half:
        placed = row_x_positions(widths, base, align)
        for side in ("p", "n"):
            boxes = []
            for p_block_id, x in placed:
                orientation = p_orientation(p_block_id)
                if side == "p":
                    block = make(p_block_id, orientation)
                else:
                    block = make(n_partner(p_block_id), _MIRROR_OF[orientation])
                bb = orient_bbox(block.report["bbox_um"], block.orientation)
                if side == "p":
                    block.origin = {"x": snap(x - bb["x0"]),
                                    "y": snap(axis_y + offset_in - bb["y0"])}
                else:
                    block.origin = {"x": snap(x - bb["x0"]),
                                    "y": snap(axis_y - offset_in - bb["y1"])}
                boxes.append(block.bbox)
            extents[f"{side}_{base}"] = (
                min(b["x0"] for b in boxes), min(b["y0"] for b in boxes),
                max(b["x1"] for b in boxes), max(b["y1"] for b in boxes))

    # -- the two inverter rows, above the p-side field ------------------------
    # The phi2b inverter is single ended, so it has no mirror partner and sits
    # outside the mirrored field rather than unbalancing one of its rows.
    inv_offset = half_height
    for base, gap, _align, members in INV_ROWS:
        inv_offset += gap
        x = ROW_LEFT_UM
        boxes = []
        row_h = 0.0
        for block_id in members:
            block = make(block_id, "none")
            bb = orient_bbox(block.report["bbox_um"], block.orientation)
            block.origin = {"x": snap(x - bb["x0"]),
                            "y": snap(axis_y + inv_offset - bb["y0"])}
            w, h = block.size()
            boxes.append(block.bbox)
            row_h = max(row_h, h)
            x += w + ROW_GAP_UM
        extents[base] = (min(b["x0"] for b in boxes), min(b["y0"] for b in boxes),
                         max(b["x1"] for b in boxes), max(b["y1"] for b in boxes))
        inv_offset += row_h

    field_x1 = max(e[2] for e in extents.values())
    ota_x = snap(field_x1 + ESCAPE_CHANNEL_UM)
    return blocks, extents, axis_y, ota_x


def n_partner(p_block_id: str) -> str:
    """The n-side block id of a p-side one (`sti_p` -> `sti_n`,
    `sin_p_p` -> `sin_n_p`, `csi_p` -> `csi_n`)."""
    parts = p_block_id.split("_")
    for i, part in enumerate(parts):
        if part == "p":
            parts[i] = "n"
            return "_".join(parts)
    raise KeyError(f"{p_block_id} has no p-side marker to mirror")


def ring_request(extents: dict[str, tuple], ring_id: str) -> tuple[dict, dict]:
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
        "add_well": RINGS[ring_id][0],
    }
    # guard_ring draws its inner area starting at (ring_width, ring_width).
    origin = {"x": snap(x0 - RING_WIDTH_UM), "y": snap(y0 - RING_WIDTH_UM)}
    return params, origin


# --- anchors ------------------------------------------------------------------
class Anchor:
    """One place a net can be reached inside one block.

    ``plane`` is how a met2 trunk gets onto it: ``met1`` for an li1 pad or an
    in-block met1 strap, ``cap3``/``cap4`` for a MiM terminal that needs a
    same-layer run out of the block first, and ``ota`` for one of the eight
    landing points inside the placed OTA instance.
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
        self.pad_xs = tuple(pad_xs) if pad_xs else (x0,)
        self.jog_um = jog_um

    @property
    def xmid(self) -> float:
        return (self.x0 + self.x1) / 2


def collect_anchors(blocks: dict[str, Block]):
    """Turn every block's ports into anchors, one per (block, net, pad row).

    Identical in shape to the sibling OTA generator's: S/D-style li1 pads
    (direction 0/180) are tall, so several nets can share one pad row on a
    0.5um ladder inside the pads; gate-style pads (90/270) are 0.42um square,
    so their y is pinned.
    """
    anchors: list[Anchor] = []
    straps: list[tuple[str, Rect]] = []
    mcons: list[tuple[float, float]] = []
    for block_id in sorted(blocks):
        block = blocks[block_id]
        nets = port_nets_of(block)
        bb = block.bbox
        flat: dict[tuple, list[tuple[str, float, float, float, int]]] = defaultdict(list)
        for p in block.ports():
            if p["name"] not in nets:
                continue
            key = (p["layer"], round(p["y_um"], 4), p["direction_deg"] in (0, 180))
            flat[key].append((p["name"], p["x_um"], p["y_um"],
                              p["width_um"], p["direction_deg"]))
        for (layer, row_y, is_sd), ports in sorted(flat.items(), key=lambda kv: str(kv[0])):
            by_net: dict[str, list] = defaultdict(list)
            for name, px, py, pw, pdir in ports:
                by_net[nets[name]].append((name, px, py, pw, pdir))
            ordered = sorted(by_net)
            if layer in (L_MET3, L_MET4):
                plane = "cap3" if layer == L_MET3 else "cap4"
                for net in ordered:
                    for name, px, py, pw, pdir in sorted(by_net[net]):
                        anchors.append(Anchor(net, block_id, plane, py, px, px,
                                              [name], pdir, bb["y0"], bb["y1"]))
                continue
            if layer != L_LI1:
                raise RouteError(f"{block_id}: unexpected port layer {layer}")
            if is_sd:
                half = min(p[3] for p in ports) / 2 - PAD_MARGIN_UM - WIRE_UM / 2
                k = len(ordered)
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
                    straps.append((net, Rect.hwire(xs[0], xs[-1], y, WIRE_UM)))
                    for x in xs:
                        mcons.append((x, y))
                    anchors.append(Anchor(net, block_id, "met1", y, xs[0], xs[-1],
                                          [p[0] for p in by_net[net]],
                                          pad_xs=xs, jog_um=JOG_REACH_UM))
            else:
                for net in ordered:
                    members = sorted(by_net[net])
                    xs = sorted(m[1] for m in members)
                    if len(ordered) > 1 and len(members) > 1:
                        raise RouteError(
                            f"{block_id}: gate row y={row_y} holds {len(ordered)} nets "
                            f"and net {net} has {len(members)} pads -- cannot strap")
                    straps.append((net, Rect.hwire(xs[0], xs[-1], row_y, WIRE_UM)))
                    for x in xs:
                        mcons.append((x, row_y))
                    anchors.append(Anchor(net, block_id, "met1", row_y, xs[0], xs[-1],
                                          [m[0] for m in members],
                                          pad_xs=xs, jog_um=JOG_REACH_UM))
    return anchors, straps, mcons


# --- router -------------------------------------------------------------------
class Router:
    """met1 horizontal + met2 vertical, one global x column per trunk.

    Same discipline as the sibling OTA generator: every trunk owns its x column
    outright, so no met2-met2 spacing search is needed; met1 is the only layer
    the greedy search has to keep clear; met3/met4 carry only the MiM risers
    and the eight OTA escapes.
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
        #: Every routed rectangle, keyed by (net, layer).  Only used after the
        #: fact, by `summing_node_report()`.
        self.by_net: dict[tuple[str, tuple[int, int]], list[Rect]] = defaultdict(list)
        self.trunk_y: dict[tuple[str, float], list[float]] = defaultdict(list)
        self.via1_y: dict[tuple[str, float], list[float]] = defaultdict(list)
        self.wire_um: dict[str, float] = defaultdict(float)

    # -- geometry bookkeeping -------------------------------------------------
    def add_shape(self, layer, rect: Rect, net: str | None = None) -> None:
        self.shapes.append((layer, rect))
        if net is not None:
            self.by_net[(net, layer)].append(rect)

    def add_met1(self, net: str, rects: list[Rect]) -> None:
        for rect in rects:
            self.met1.append((net, rect))
            for b in range(rect.y0 // BUCKET_NM, rect.y1 // BUCKET_NM + 1):
                self.met1_index[b].append((net, rect))
            self.add_shape(L_MET1, rect, net)
            self.wire_um[net] += max(rect.x1 - rect.x0, rect.y1 - rect.y0) / DBU

    def add_met(self, layer, store, net: str, rects: list[Rect]) -> None:
        for rect in rects:
            store.append((net, rect))
            self.add_shape(layer, rect, net)
            self.wire_um[net] += (rect.x1 - rect.x0 + rect.y1 - rect.y0) / DBU

    def add_mcon(self, x: float, y: float) -> None:
        rect = Rect.centred(x, y, MCON_UM, MCON_UM)
        self.add_shape(L_MCON, rect)

    def add_trunk_via(self, net: str, col: float, y: float) -> None:
        """Drop a met1<->met2 via1 on this net's column, and grow the trunk."""
        self.trunk_y[(net, col)].append(y)
        if any(abs(y - prev) < WIRE_UM for prev in self.via1_y[(net, col)]):
            return
        self.add_shape(L_VIA, Rect.centred(col, y, VIA_UM, VIA_UM))
        self.via1_y[(net, col)].append(y)

    @staticmethod
    def _ok(rect: Rect, placed: Rect, same_net: bool, gap: int) -> bool:
        if not rect.clashes(placed, gap):
            return True
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
        cands = [snap(k * TRUNK_PITCH_UM) for k in range(k0, k1 + 1)
                 if self.x_lo - 2.0 <= k * TRUNK_PITCH_UM <= self.x_hi + 2.0]
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

    # -- the ways a net reaches a block ---------------------------------------
    def connect_met1(self, a: Anchor, col_budget: int = 48) -> tuple[float, float]:
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
        raise RouteError(
            f"no free met2 column for {a.net} at {a.block} y={a.y}: "
            f"{len(self.used_cols)} columns already taken, "
            f"{len(cols)} free within the budget")

    def jog_tracks(self, a: Anchor) -> list[float]:
        if a.jog_um <= 0:
            return [a.y]
        n = int(a.jog_um / TRACK_PITCH_UM)
        ys = {a.y}
        for i in range(1, n + 1):
            ys.add(snap(a.y + i * TRACK_PITCH_UM))
            ys.add(snap(a.y - i * TRACK_PITCH_UM))
        return sorted(ys, key=lambda y: (abs(y - a.y), y))

    def connect_cap(self, a: Anchor) -> tuple[float, float]:
        """A MiM terminal: a same-layer run out of the block, then a via stack
        down to met2.  The run leaves by whichever block edge the port already
        faces, so a mirrored capacitor escapes on its own mirrored side."""
        if a.plane == "cap3":
            layer, store, space = L_MET3, self.met3, MET34_SPACE_UM
            x_run = snap(a.x0 + (0.3 if a.port_dir == 180 else -0.3))
        else:
            layer, store, space = L_MET4, self.met4, MET34_SPACE_UM
            x_run = snap(a.x0)
        y_drop = snap(a.block_y1 + 1.2 if a.port_dir == 90 or
                      (a.port_dir not in (90, 270) and a.y > (a.block_y0 + a.block_y1) / 2)
                      else a.block_y0 - 1.2)
        vert = Rect.vwire(x_run, a.y, y_drop, MET34_W_UM)
        for col in self.columns(x_run - 2.0, x_run + 2.0, x_run):
            if not self.neighbours_free(col):
                continue
            horiz = Rect.hwire(x_run, col, y_drop, MET34_W_UM)
            pad = Rect.centred(col, y_drop, PAD34_UM, PAD34_UM)
            if not self._free(store, a.net, [vert, horiz, pad], space):
                continue
            if layer == L_MET4 and not self._free(self.met3, a.net, [pad], space):
                continue
            self.reserve_column(col, neighbours=True)
            self.add_met(layer, store, a.net, [vert, horiz])
            if layer == L_MET4:
                self.add_met(L_MET3, self.met3, a.net, [pad])
                self.add_shape(L_VIA3, Rect.centred(col, y_drop, VIA3_UM, VIA3_UM))
            else:
                self.add_met(L_MET3, self.met3, a.net, [pad])
            self.add_shape(L_VIA2, Rect.centred(col, y_drop, VIA2_UM, VIA2_UM))
            self.add_shape(L_MET2, Rect.centred(col, y_drop, PAD34_UM, PAD34_UM), a.net)
            self.trunk_y[(a.net, col)].append(y_drop)
            return col, y_drop
        raise RouteError(f"no met3/met4 riser for {a.net} at {a.block}")

    def connect_ota(self, a: Anchor, col: float) -> tuple[float, float]:
        """One of the eight OTA escapes, on a column this net owns outright.

        The via1/via2 ladder at the landing point is exactly the one
        ``ports_from_labels``'s ``access`` search validated against #118's own
        geometry.  From there a met3 run leaves the OTA westward at the
        landing's own y -- the OTA draws no met3 above y=61.82 in its own
        frame, and every landing is above that -- and the stack back down to
        met1 is drawn clear of the instance, on this net's trunk column.
        """
        y = a.y
        # The validated ladder, at the landing point, inside the instance --
        # drawn at the pad sizes the access search itself cleared, never
        # larger (LANDING_*_UM).
        self.add_met1(a.net,
                      [Rect.centred(a.x0, y, LANDING_MET1_UM, LANDING_MET1_UM)])
        self.add_shape(L_VIA, Rect.centred(a.x0, y, VIA_UM, VIA_UM))
        self.add_shape(L_MET2, Rect.centred(a.x0, y, LANDING_MET2_UM,
                                           LANDING_MET2_UM), a.net)
        self.add_shape(L_VIA2, Rect.centred(a.x0, y, VIA2_UM, VIA2_UM))
        self.add_met(L_MET3, self.met3, a.net,
                     [Rect.centred(a.x0, y, LANDING_MET3_UM, LANDING_MET3_UM)])
        # The westward met3 run, and the stack back down outside the instance.
        self.add_met(L_MET3, self.met3, a.net,
                     [Rect.hwire(col, a.x0, y, MET34_W_UM),
                      Rect.centred(col, y, PAD34_UM, PAD34_UM)])
        self.add_shape(L_VIA2, Rect.centred(col, y, VIA2_UM, VIA2_UM))
        self.add_shape(L_MET2, Rect.centred(col, y, PAD34_UM, PAD34_UM), a.net)
        self.reserve_column(col)
        self.add_met1(a.net, [Rect.centred(col, y, WIRE_UM, WIRE_UM)])
        self.add_trunk_via(a.net, col, y)
        return col, y

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
            if hi - lo < 1e-9:
                continue
            rect = Rect.vwire(col, lo, hi, WIRE_UM)
            self.add_shape(L_MET2, rect, net)
            self.wire_um[net] += (hi - lo)


# --- capacitor evidence -------------------------------------------------------
#: The three differential capacitor groups, p-side block first.
CAP_GROUPS = (("Csi", "csi_p", "csi_n"), ("Csr", "csr_p", "csr_n"),
              ("Ci", "ci_p", "ci_n"))


def capacitor_report(blocks: dict[str, Block], axis_y: float) -> dict:
    """Acceptance evidence for the six MiM capacitors.

    Two claims, both read back off the placed geometry rather than asserted:

    * each group's two halves are a **mirror pair about the cell's axis** --
      same x, mirrored orientation, and placed-bbox edges that reflect into
      each other to the nanometre;
    * each capacitor's **amplifier-side terminal is on the MiM top plate**,
      i.e. the netlist's first terminal is bound to the generator's ``_TOP``
      port, which ``cap_array`` reports on met4 (71/20) over the capm plate.

    The second one cannot be read back out of ``klt extract``: it normalises a
    two-terminal device's terminal order, so the extracted netlist names the
    plates ``a``/``b`` and says nothing about which metal they landed on.  It
    is therefore asserted here, from the generator's own layer choice, and the
    assertion is what this block records.
    """
    groups = []
    for name, p_id, n_id in CAP_GROUPS:
        bp, bn = blocks[p_id], blocks[n_id]
        boxp, boxn = bp.bbox, bn.bbox
        mirrored = (abs(boxp["x0"] - boxn["x0"]) < 1e-9
                    and abs(boxp["x1"] - boxn["x1"]) < 1e-9
                    and abs((axis_y - boxp["y0"]) - (boxn["y1"] - axis_y)) < 1e-9
                    and abs((axis_y - boxp["y1"]) - (boxn["y0"] - axis_y)) < 1e-9
                    and bn.orientation == _MIRROR_OF[bp.orientation])
        if not mirrored:
            raise RouteError(
                f"capacitor group {name} is not mirror-symmetric about "
                f"y={axis_y}: {p_id} {boxp} ({bp.orientation}) vs "
                f"{n_id} {boxn} ({bn.orientation})")
        params = GEOMETRIES[bp.geometry][1]
        groups.append({
            "group": name,
            "plate_um": [params["plate_w_um"], params["plate_h_um"]],
            "arrangement": "mirror-symmetric about the cell axis",
            "blocks": {p_id: {"bbox_um": boxp, "orientation": bp.orientation,
                              "top_plate_net": bp.nets["TOP"],
                              "bottom_plate_net": bp.nets["BOT"]},
                       n_id: {"bbox_um": boxn, "orientation": bn.orientation,
                              "top_plate_net": bn.nets["TOP"],
                              "bottom_plate_net": bn.nets["BOT"]}},
        })
    return {
        "mirror_axis_y_um": axis_y,
        "plate_binding": (
            "The netlist's first terminal of every capacitor is bound to the "
            "cap_array _TOP port (met4 71/20 over capm), uniformly across all "
            "six -- design/integrator/SIZING.md:72-74's amplifier-side plate "
            "on the MIM top plate (c0). This cell is that line's 'to be "
            "confirmed in layout' step. klt extract cannot read the binding "
            "back (it normalises a two-terminal device and names the plates "
            "a/b), so it is asserted by the generator's layer choice and "
            "recorded here. If klayout-tools#146's open question concludes "
            "that c0 is the sky130 model's *bottom* plate, SIZING.md:72 is "
            "what changes, not this binding."),
        "plate_binding_uniform": True,
        "groups": groups,
    }


# --- summing-node evidence ----------------------------------------------------
#: The two nodes DR-004 names as the most sensitive on the die.
SUMMING_NETS = ("sump", "sumn")
#: Every net that carries a clock edge in this cell, including the internally
#: inverted `phi2b`.
CLOCK_NETS = ("phi1", "phi1b", "phi1e", "phi2", "phi2b")
#: How close a clock run may come to a summing-node run, on the same layer,
#: before this script calls it "beside" and the README has to name it.
SHIELD_CLEARANCE_UM = 1.0


def _gap_um(a: Rect, b: Rect) -> float:
    """Minimum edge-to-edge distance between two rectangles (0 if they touch
    or overlap)."""
    dx = max(0, a.x0 - b.x1, b.x0 - a.x1)
    dy = max(0, a.y0 - b.y1, b.y0 - a.y1)
    if dx and dy:
        return round((dx * dx + dy * dy) ** 0.5 / DBU, 4)
    return round(max(dx, dy) / DBU, 4)


def _overlap_um2(a: Rect, b: Rect) -> float:
    w = min(a.x1, b.x1) - max(a.x0, b.x0)
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    return round(w * h / (DBU * DBU), 4) if w > 0 and h > 0 else 0.0


def summing_node_report(router: "Router", summary: dict) -> dict:
    """Acceptance evidence for the two summing nodes.

    Two questions, both answered from the drawn geometry rather than asserted:

    * how long each of ``sump``/``sumn`` is, and how that compares with every
      other net in the cell;
    * where a clock run comes within ``SHIELD_CLEARANCE_UM`` of one on the
      same layer ("beside"), or crosses one on a different layer ("over").
      Nothing in this cell is shielded, so every such place is listed and the
      README names them -- which is the disclosure the acceptance criterion
      asks for in place of a shield.
    """
    layers = (L_MET1, L_MET2, L_MET3, L_MET4)
    lengths = {net: summary[net]["wire_length_um"] for net in summary}
    ranked = sorted(lengths, key=lambda n: (lengths[n], n))
    beside: list[dict] = []
    over: list[dict] = []
    for net in SUMMING_NETS:
        for clock in CLOCK_NETS:
            for layer in layers:
                for ra in router.by_net.get((net, layer), ()):
                    for rb in router.by_net.get((clock, layer), ()):
                        gap = _gap_um(ra, rb)
                        if gap <= SHIELD_CLEARANCE_UM:
                            beside.append({
                                "summing_net": net, "clock_net": clock,
                                "layer": f"{layer[0]}/{layer[1]}",
                                "gap_um": gap,
                                "summing_rect_um": ra.as_um(),
                                "clock_rect_um": rb.as_um()})
            for layer_a in layers:
                for layer_b in layers:
                    if layer_a == layer_b:
                        continue
                    for ra in router.by_net.get((net, layer_a), ()):
                        for rb in router.by_net.get((clock, layer_b), ()):
                            area = _overlap_um2(ra, rb)
                            if area > 0:
                                over.append({
                                    "summing_net": net, "clock_net": clock,
                                    "summing_layer": f"{layer_a[0]}/{layer_a[1]}",
                                    "clock_layer": f"{layer_b[0]}/{layer_b[1]}",
                                    "overlap_um2": area,
                                    "at_um": [max(ra.x0, rb.x0) / DBU,
                                              max(ra.y0, rb.y0) / DBU]})
    beside.sort(key=lambda d: (d["gap_um"], d["summing_net"], d["clock_net"],
                               d["layer"], d["summing_rect_um"]))
    over.sort(key=lambda d: (-d["overlap_um2"], d["summing_net"], d["clock_net"],
                             d["at_um"]))
    return {
        "wire_length_um": {net: lengths[net] for net in SUMMING_NETS},
        "length_rank_of_all_nets": ranked,
        "shortest_net": ranked[0],
        "shield_clearance_um": SHIELD_CLEARANCE_UM,
        "shielded": False,
        "beside_count": len(beside),
        "beside": beside,
        "crossings_count": len(over),
        "crossings": over,
    }


# --- build --------------------------------------------------------------------
def lvtn_markers(blocks: dict[str, Block]) -> list[Rect]:
    """One `lvtn` (125/44) rectangle per low-Vth device, and the assertion that
    none of them reaches a device that is not low-Vth.

    `klt gen mos_array`'s own `voltage_flavor` draws nothing on sky130 (it
    resolves no marker layer for the family and says so in `drc_hints`), so the
    marker is this script's to draw.  Filed upstream -- see the README.
    """
    rects: list[Rect] = []
    marked: list[tuple[str, Rect]] = []
    for block_id in sorted(blocks):
        block = blocks[block_id]
        if block.is_ring or block.geometry not in LVT_GEOMETRIES:
            continue
        bb = block.bbox
        rect = Rect.um(bb["x0"] - LVTN_ENCLOSE_UM, bb["y0"] - LVTN_ENCLOSE_UM,
                       bb["x1"] + LVTN_ENCLOSE_UM, bb["y1"] + LVTN_ENCLOSE_UM)
        rects.append(rect)
        marked.append((block_id, rect))
    for block_id in sorted(blocks):
        block = blocks[block_id]
        if block.is_ring or block.geometry in LVT_GEOMETRIES:
            continue
        if GEOMETRIES[block.geometry][0] != "mos_array":
            continue
        bb = block.bbox
        box = Rect.um(bb["x0"], bb["y0"], bb["x1"], bb["y1"])
        for owner, rect in marked:
            if rect.clashes(box, 0):
                raise RouteError(
                    f"lvtn marker of {owner} reaches {block_id}, which the "
                    "netlist declares as a standard-Vth device")
    return rects


def build(blocks: dict[str, Block], ota: dict, axis_y: float, ota_x: float):
    """Strap every block, route every net, return (draw params, route summary)."""
    anchors, straps, mcons = collect_anchors(blocks)

    xs: list[float] = []
    ys: list[float] = []
    for block in blocks.values():
        bb = block.bbox
        xs += [bb["x0"], bb["x1"]]
        ys += [bb["y0"], bb["y1"]]
    # The router's x window stops a clear pitch short of the OTA instance, so
    # no met1 or met2 of this script's can ever land on top of it.  The eight
    # escape columns are carved out of the last few pitches of that window.
    escape_hi = snap(ota_x - 1.0)
    router = Router(min(xs) - 1.0, snap(escape_hi - 9 * ESCAPE_PITCH_UM),
                    min(ys) - 2.0, max(ys) + 2.0)
    for net, rect in straps:
        router.add_met1(net, [rect])
    for x, y in mcons:
        router.add_mcon(x, y)

    # -- the eight OTA escapes, and the columns they own ----------------------
    # Ordered by landing y, highest first, each column one pitch further west
    # than the last: a column then never lies under a higher landing's own
    # westward met3 run, so the eight runs cannot cross one another.
    ota_anchors: dict[str, tuple[Anchor, float]] = {}
    by_y = sorted(ota["ports"], key=lambda p: (-p["y_um"], p["name"]))
    for i, port in enumerate(by_y):
        net = OTA_PORT_NETS[port["name"]]
        col = snap(escape_hi - i * ESCAPE_PITCH_UM)
        if col > port["x_um"]:
            raise RouteError(
                f"OTA escape column {col} for {net} is east of its landing "
                f"{port['x_um']}: widen ESCAPE_CHANNEL_UM")
        ota_anchors[net] = (
            Anchor(net, "ota", "ota", port["y_um"], port["x_um"], port["x_um"],
                   [port["name"]]), col)
        anchors.append(ota_anchors[net][0])

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
        placed = []
        for a in group:
            if a.plane == "ota":
                placed.append((*router.connect_ota(a, ota_anchors[net][1]), a))
            elif a.plane in ("cap3", "cap4"):
                placed.append((*router.connect_cap(a), a))
            else:
                placed.append((*router.connect_met1(a), a))
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
            on_met1 = [t for t in placed if t[2].plane in ("met1", "ota")]
            if not on_met1:
                raise RouteError(f"port net {net} has no met1 anchor to label")
            col, y, _a = on_met1[0]
            router.labels.append((L_MET1_PIN, net, col, y))
    router.finish_trunks()

    for net, info in summary.items():
        info["wire_length_um"] = round(router.wire_um[net], 3)

    markers = lvtn_markers(blocks)
    draw_params = {
        "shapes": [{"layer": list(layer), "rect_um": rect.as_um()}
                   for layer, rect in router.shapes]
        + [{"layer": list(L_LVTN), "rect_um": rect.as_um()} for rect in markers],
        "labels": [{"layer": list(layer), "text": text, "at_um": [x, y]}
                   for layer, text, x, y in router.labels],
    }
    route_summary = {
        "capacitors": capacitor_report(blocks, axis_y),
        "summing_nodes": summing_node_report(router, summary),
        "mirror_axis_y_um": axis_y,
        "ota_origin_x_um": ota_x,
        "block_origins_um": {b: dict(blocks[b].origin) for b in sorted(blocks)},
        "block_orientation": {b: blocks[b].orientation for b in sorted(blocks)},
        "met2_columns": len(router.used_cols),
        "lvtn_markers": [r.as_um() for r in markers],
        "nets": summary,
    }
    return draw_params, route_summary


# --- device-count evidence ----------------------------------------------------
def _symmetric_terminals(terminals: tuple[str, ...]) -> tuple[str, ...]:
    """Normalise a device's terminal order over the terminals it is symmetric
    in: a MOSFET's source and drain are interchangeable and alternate finger by
    finger, so without this a 4-finger device counts as two."""
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
    """Count extracted devices by model, and by model with parallel same-net
    devices merged (what an LVS combine-parallel-devices pass does)."""
    raw: Counter = Counter()
    groups: set[tuple[str, tuple[str, ...]]] = set()
    for line in netlist_text.splitlines():
        tok = line.split()
        if not tok or not tok[0].startswith("X"):
            continue
        model = next((t for t in tok if t.startswith("sky130_fd_pr__")
                      or t in ("nfet", "pfet")), None)
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
    nets: set[str] = set()
    for line in netlist_text.splitlines():
        tok = line.split()
        if not tok or not tok[0].startswith("X"):
            continue
        model = next((t for t in tok if t.startswith("sky130_fd_pr__")
                      or t in ("nfet", "pfet")), None)
        if model is None:
            continue
        nets.update(tok[1:tok.index(model)])
    return sorted(nets)


def extracted_pins(netlist_text: str) -> list[list[str]]:
    """The extracted pin list, one entry per *pin*, each a list of the label
    texts that resolved to it.

    `klt extract` joins several labels on one node with commas (`outn,voutn`),
    which is itself the evidence that two differently-named labels landed on
    the same net -- so the names are kept grouped rather than flattened.
    """
    groups = [line.split()[-1].split(",") for line in netlist_text.splitlines()
              if line.startswith("* pin ")]
    return sorted(sorted(g) for g in groups)


def flavour_blind(counts: dict[str, int]) -> dict[str, int]:
    """Per-model counts collapsed onto the three flavour-blind families issue
    #119's acceptance criterion names."""
    out = {"nfet": 0, "pfet": 0, "cap_mim": 0}
    for model, count in counts.items():
        if "nfet" in model:
            out["nfet"] += count
        elif "pfet" in model:
            out["pfet"] += count
        elif "cap_mim" in model:
            out["cap_mim"] += count
    return out


# --- flow ---------------------------------------------------------------------
def klt_pin(klt: str) -> dict:
    """The exact klt build, recorded with the evidence: the stream is
    byte-reproducible at *this* build, so the reader has to be told which."""
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


def _ota_access(grid_um: float) -> dict:
    """One `ports_from_labels` `access` block.

    `up_to: "metal4"` is the sky130 **role** name for met3 -- the family's
    routing roles start at `metal1` == li1 -- so the validated ladder is
    via1 + via2, which is exactly the stack `Router.connect_ota()` draws.
    """
    return {"up_to": "metal4", "via_array": [1, 1], "keepout_layers": [],
            "grid_um": grid_um, "max_candidates": OTA_ACCESS_MAX_CANDIDATES}


def translate_ota(probe: dict, origin: dict) -> dict:
    """``ota_port_report``'s source-frame report, moved to a placed origin."""
    return {
        "source_digest": probe["source_digest"],
        "bbox_um": {k: probe["bbox_um"][k] + origin["x" if k[0] == "x" else "y"]
                    for k in ("x0", "y0", "x1", "y1")},
        "ports": [{**p,
                   "x_um": snap(p["x_um"] + origin["x"]),
                   "y_um": snap(p["y_um"] + origin["y"]),
                   "label_um": {"x": p["label_um"]["x"] + origin["x"],
                                "y": p["label_um"]["y"] + origin["y"]}}
                  for p in probe["ports"]],
    }


def ota_port_report(klt: str, pdk_args: list[str], out_dir: Path,
                    ota_gds: Path) -> dict:
    """Place the OTA on its own and recover its eight ports' landing points.

    Reported in the OTA's **own** frame: `derived_ports` is not moved by
    `offset_um`, so the caller translates with `translate_ota()`.

    A placement-only `gen-compose` run whose single `blocks[].cell` entry asks
    for `ports_from_labels` over #118's `met1.pin` labels, with the `access`
    landing search that finds, for each, a point where a via1/via2 ladder up to
    met3 clears the OTA's own geometry.  The composed stream is discarded; only
    the report is used.
    """
    request = {
        "schema": "klt.gen_compose.request/1",
        "pdk": {"variant": PDK_VARIANT},
        "blocks": [{"id": "ota", "cell": {
            "gds_path": str(ota_gds),
            "cell_name": OTA_CELL,
            "ports_from_labels": {
                "layers": [{"layer": L_MET1_PIN[0], "datatype": L_MET1_PIN[1]}],
                "names": [
                    {"name": name, "access": _ota_access(
                        OTA_ACCESS_GRID_OVERRIDE_UM[name])}
                    if name in OTA_ACCESS_GRID_OVERRIDE_UM else name
                    for name in sorted(OTA_PORT_NETS)],
                "access": _ota_access(OTA_ACCESS_GRID_UM),
            }}}],
        "placement": {"strategy": "explicit", "order": ["ota"],
                      "origins_um": {"ota": {"x": 0.0, "y": 0.0}}},
        "connectivity": [],
        "options": {"cell_name": "ota_probe", "output": "ota_probe.gds"},
    }
    (out_dir / "ota-ports.request.json").write_text(json.dumps(request, indent=2) + "\n")
    r = run([klt, "gen-compose", "ota-ports.request.json", "--format", "json"],
            cwd=out_dir)
    report = json.loads(r.stdout)
    if report.get("error"):
        raise RuntimeError(f"OTA port recovery: {report['error']}")
    block = report["blocks"][0]
    ports = []
    for p in sorted(block["derived_ports"], key=lambda p: p["name"]):
        landing = p.get("landing")
        if landing is None:
            raise RuntimeError(
                f"OTA port {p['name']}: no landing point -- the access search "
                "found no legal via ladder; see this directory's README")
        ports.append({"name": p["name"], "net": OTA_PORT_NETS[p["name"]],
                      "x_um": landing["x_um"], "y_um": landing["y_um"],
                      "label_um": p["label_um"], "via_count": landing["via_count"]})
    return {"ports": ports, "bbox_um": block["bbox_um"],
            "source_digest": block["source_digest"]}


def check_orientation_agrees(klt: str, pdk_args: list[str], out_dir: Path,
                             reports: dict[str, dict]) -> None:
    """Assert this script's own orientation maths matches `klt gen-compose`'s.

    The floorplan places mirrored blocks by transforming their reported bbox
    here rather than round-tripping through the composer, so a divergence
    between the two would move geometry silently.  One throwaway compose with
    every orientation in use pins them together.
    """
    key = sorted(reports)[0]
    orientations = ["none", "mirror_x", "mirror_y", "rotate_180"]
    request = {
        "schema": "klt.gen_compose.request/1",
        "pdk": {"variant": PDK_VARIANT},
        "blocks": [{"id": f"o{i}", "generator_report": f"{key}.json",
                    "orientation": o} for i, o in enumerate(orientations)],
        "placement": {"strategy": "explicit",
                      "order": [f"o{i}" for i in range(len(orientations))],
                      "origins_um": {f"o{i}": {"x": 40.0 * i, "y": 40.0 * i}
                                     for i in range(len(orientations))}},
        "connectivity": [],
        "options": {"cell_name": "orient_probe", "output": "orient_probe.gds"},
    }
    (out_dir / "orient.request.json").write_text(json.dumps(request, indent=2) + "\n")
    r = run([klt, "gen-compose", "orient.request.json", "--format", "json"],
            cwd=out_dir)
    report = json.loads(r.stdout)
    if report.get("error"):
        raise RuntimeError(f"orientation check: {report['error']}")
    for i, o in enumerate(orientations):
        want = orient_bbox(reports[key]["bbox_um"], o)
        got = report["blocks"][i]["bbox_um"]
        for axis in ("x0", "x1"):
            if abs(want[axis] + 40.0 * i - got[axis]) > 1e-6:
                raise RuntimeError(
                    f"orientation '{o}': this script computes {want}, "
                    f"klt gen-compose placed {got}")
        for axis in ("y0", "y1"):
            if abs(want[axis] + 40.0 * i - got[axis]) > 1e-6:
                raise RuntimeError(
                    f"orientation '{o}': this script computes {want}, "
                    f"klt gen-compose placed {got}")


def flow(klt: str, pdk_root: Path, out_dir: Path, cell_dir: Path,
         verbose: bool = True) -> dict:
    pdk_args = ["--pdk", PDK_VARIANT, "--pdk-root", str(pdk_root)]
    out_dir.mkdir(parents=True, exist_ok=True)

    def say(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    # -- 0. the two pinned inputs ---------------------------------------------
    ota_gds = (cell_dir / OTA_GDS_REL).resolve()
    netlist = (cell_dir / NETLIST_REL).resolve()
    for path, want, what in ((ota_gds, OTA_GDS_SHA256, "OTA cell GDS"),
                             (netlist, NETLIST_SHA256, "reference netlist")):
        if not path.exists():
            raise RuntimeError(f"{what} is missing: {path}")
        got = sha256_of(path)
        if got != want:
            raise RuntimeError(
                f"{what} {path} has sha256 {got}, this cell was generated "
                f"against {want}. The geometry here is stale: regenerate it "
                "against the new input and refresh the recorded hash.")
    say(f"[0/7] inputs pinned: ota_fd.gds {OTA_GDS_SHA256[:12]}..., "
        f"integrator.spice {NETLIST_SHA256[:12]}...")

    # -- 1. devices ------------------------------------------------------------
    say("[1/7] klt gen device geometries")
    wanted = sorted({g for g, _n in DEVICES.values()})
    reports = gen_geometries(klt, pdk_args, out_dir, wanted)
    check_orientation_agrees(klt, pdk_args, out_dir, reports)

    # -- 2. floorplan ----------------------------------------------------------
    say("[2/7] floorplan + body-tie rings + OTA placement")
    blocks, extents, axis_y, ota_x = build_floorplan(reports)
    params_by_ring: dict[str, dict] = {}
    origins_by_ring: dict[str, dict] = {}
    for ring_id in sorted(RINGS):
        params, origin = ring_request(extents, ring_id)
        params_by_ring[ring_id] = params
        origins_by_ring[ring_id] = origin
    ring_reports = gen_rings(klt, pdk_args, out_dir, params_by_ring)
    for ring_id in sorted(RINGS):
        block = Block(ring_id, ring_id, "none", {"TAP": RINGS[ring_id][1]},
                      is_ring=True)
        block.report = ring_reports[ring_id]
        block.origin = origins_by_ring[ring_id]
        blocks[ring_id] = block

    # The OTA sits so its own `inn`/`inp` labels straddle the mirror axis.
    # `derived_ports` is reported in the *source* cell's own frame, never the
    # composed one, so the probe is run once at the origin and this script
    # translates -- which is also what lets the axis be chosen from the same
    # report that supplies the landing points.
    probe = ota_port_report(klt, pdk_args, out_dir, ota_gds)
    label_ys = {p["name"]: p["label_um"]["y"] for p in probe["ports"]}
    axis_in_ota = sum(label_ys[n] for n in OTA_AXIS_LABELS) / len(OTA_AXIS_LABELS)
    ota_origin = {"x": snap(ota_x), "y": snap(axis_y - axis_in_ota)}
    ota = translate_ota(probe, ota_origin)
    say(f"  axis y={axis_y}um, OTA at {ota_origin}, "
        f"{len(blocks)} blocks ({len(wanted)} klt gen geometries)")

    # -- 3. strap + route ------------------------------------------------------
    say("[3/7] strap + route")
    draw_params, route_summary = build(blocks, ota, axis_y, ota_x + 0.7)
    result_markers = route_summary["lvtn_markers"]
    route_summary["ota"] = {
        "gds": OTA_GDS_REL, "cell": OTA_CELL, "sha256": OTA_GDS_SHA256,
        "source_digest": ota["source_digest"], "origin_um": ota_origin,
        "ports": ota["ports"],
    }
    (out_dir / "draw.request.json").write_text(json.dumps(draw_params, indent=1) + "\n")
    (out_dir / "route.summary.json").write_text(
        json.dumps(route_summary, indent=2) + "\n")
    say(f"  {len(draw_params['shapes'])} routing shapes, "
        f"{route_summary['met2_columns']} met2 columns, "
        f"{len(route_summary['lvtn_markers'])} lvtn markers")

    # -- 4. draw + compose -----------------------------------------------------
    say("[4/7] klt draw (routing + lvtn cell) + klt gen-compose (explicit placement)")
    r = run([klt, "draw", "--params", "draw.request.json", "--cell-name", "ROUTE",
             "-o", "route.gds", "--format", "json"], cwd=out_dir)
    (out_dir / "draw.json").write_text(r.stdout)
    order = sorted(b for b in blocks) + ["ota", "route"]
    compose_request = {
        "schema": "klt.gen_compose.request/1",
        "pdk": {"variant": PDK_VARIANT},
        "blocks": [{"id": b, "generator_report":
                    f"{blocks[b].geometry}.json" if not blocks[b].is_ring
                    else f"{b}.json",
                    "orientation": blocks[b].orientation}
                   for b in sorted(blocks)]
        + [{"id": "ota", "cell": {"gds_path": str(ota_gds),
                                  "cell_name": OTA_CELL}},
           {"id": "route", "generator_report": "draw.json"}],
        "placement": {
            "strategy": "explicit",
            "order": order,
            "origins_um": {**{b: dict(blocks[b].origin) for b in sorted(blocks)},
                           "ota": ota_origin,
                           "route": {"x": 0.0, "y": 0.0}},
        },
        # No `routing` block on purpose: gen-compose is a placer here; every
        # wire is in the `route` block this script drew.
        "connectivity": [],
        "options": {"cell_name": TOP_CELL, "output": f"{TOP_CELL}.gds"},
    }
    (out_dir / "compose.request.json").write_text(
        json.dumps(compose_request, indent=2) + "\n")
    run([klt, "gen-compose", "compose.request.json", "--format", "json"], cwd=out_dir)
    gds = out_dir / f"{TOP_CELL}.gds"
    if not gds.exists():
        raise RuntimeError(f"gen-compose did not write {gds}")

    # -- 5. drc ----------------------------------------------------------------
    say("[5/7] klt drc (sky130 deck)")
    r = run([klt, "drc", f"{TOP_CELL}.gds", "--deck", "sky130", "--top", TOP_CELL]
            + pdk_args + ["--format", "json"], cwd=out_dir, check=False)
    drc = json.loads(r.stdout) if r.stdout.strip() else {"error": r.stderr}
    (out_dir / "drc.report.json").write_text(json.dumps(drc, indent=2) + "\n")
    say(f"  drc: status={drc.get('status')!r} violations={drc.get('violation_count')}")

    # -- 6. extract: this cell, and the OTA alone to subtract ------------------
    say("[6/7] klt extract (device-count evidence)")
    run([klt, "extract", f"{TOP_CELL}.gds", "--deck", "sky130", "--top", TOP_CELL]
        + pdk_args + ["-o", f"{TOP_CELL}.extract.spice", "--format", "json"],
        cwd=out_dir)
    whole = (out_dir / f"{TOP_CELL}.extract.spice").read_text()
    run([klt, "extract", str(ota_gds), "--deck", "sky130", "--top", OTA_CELL]
        + pdk_args + ["-o", "ota_only.extract.spice", "--format", "json"],
        cwd=out_dir)
    ota_only = (out_dir / "ota_only.extract.spice").read_text()

    raw_all, merged_all = parse_extract_devices(whole)
    raw_ota, merged_ota = parse_extract_devices(ota_only)
    own = {m: merged_all.get(m, 0) - merged_ota.get(m, 0)
           for m in sorted(set(merged_all) | set(merged_ota))}
    own = {m: c for m, c in own.items() if c}
    ok = own == EXPECTED_DEVICES
    blind = flavour_blind(own)

    nets_all = extract_nets(whole)
    nets_ota = extract_nets(ota_only)
    schematic_nets = {net for _g, terms in DEVICES.values() for net in terms.values()}
    schematic_nets |= set(PIN_NETS) | set(OTA_PORT_NETS.values())
    # Every schematic net of this cell, plus every OTA-internal net that is not
    # one of the OTA's eight ports, must come back as exactly one node.
    expected_nets = len(schematic_nets) + len(nets_ota) - len(OTA_PORT_NETS)
    # The OTA's own met1.pin labels ride in through the instance.  Four of them
    # (inp/inn/outp/outn) name nets this cell calls something else, so the
    # parent's pin list is this cell's sixteen plus those four -- and the two
    # output labels must come back *sharing* a pin with this cell's own
    # voutp/voutn label, which is the check that the OTA's outputs really are
    # the nets the integrating capacitors sit on.
    pins = extracted_pins(whole)
    expected_pins = sorted(
        sorted(g) for g in
        [[n] for n in PIN_NETS if n not in ("voutp", "voutn")]
        + [["inp"], ["inn"], ["outp", "voutp"], ["outn", "voutn"]])

    evidence = {
        "tool": {**klt_pin(klt), "deck": "sky130", "top_cell": TOP_CELL,
                 "pdk": PDK_VARIANT,
                 "pdk_sources": "open_pdks f6eeac7 (sim/pdk.json)"},
        "reference_netlist": "design/integrator/integrator.spice",
        "integrator_netlist_sha256": NETLIST_SHA256,
        "ota_gds": "layout/analog/ota_fd/ota_fd.gds",
        "ota_gds_sha256": OTA_GDS_SHA256,
        "method": (
            "klt extract over layout/analog/integrator/integrator.gds, which "
            "the extractor flattens through the placed ota_fd instance, minus "
            "klt extract over the committed layout/analog/ota_fd/ota_fd.gds on "
            "its own in the same run. The difference is this cell's own 44 "
            "devices. Counts are merged first (devices sharing a model and all "
            "terminals, after normalising the terminals a device is symmetric "
            "in), which is what an LVS combine-parallel-devices pass does and "
            "what makes the 4-finger phi2b inverter devices count once each."),
        "comparison_basis": (
            "merged_counts(integrator) - merged_counts(ota_fd) vs the 44 "
            "primitive X-lines of design/integrator/integrator.spice"),
        "expected_own_devices": {**EXPECTED_DEVICES,
                                 "total": sum(EXPECTED_DEVICES.values())},
        "found_own_devices": {**own, "total": sum(own.values())},
        "lvt_split_confirmed_by_extraction": (
            own.get("sky130_fd_pr__nfet_01v8_lvt") ==
            EXPECTED_DEVICES["sky130_fd_pr__nfet_01v8_lvt"]
            and own.get("sky130_fd_pr__pfet_01v8_lvt") ==
            EXPECTED_DEVICES["sky130_fd_pr__pfet_01v8_lvt"]),
        "lvt_split_note": (
            "Issue #119's acceptance criterion was weakened to a flavour-blind "
            "21 nfet / 17 pfet / 6 cap_mim total, on the strength of a curator "
            "probe that found klt extract --deck sky130 ignoring an lvtn "
            "(125/44) marker drawn over a two-column mos_array. On this cell's "
            "geometry it does not ignore it: the extracted netlist names "
            "sky130_fd_pr__nfet_01v8_lvt and sky130_fd_pr__pfet_01v8_lvt and "
            "gets all twenty right. The marker here covers a whole "
            "single-finger device plus a 0.38um enclosure, which is the "
            "condition klayout-tools#5301 says the deck needs (a marker that "
            "ends inside a shared source/drain diffusion mis-classifies). Both "
            "the stronger per-model result and the criterion as written are "
            "recorded below; the generator asserts the stronger one."),
        "flavour_blind_check": {
            "expected": EXPECTED_FLAVOUR_BLIND,
            "found": blind,
            "basis": "issue #119's acceptance criterion as written"},
        "merged_counts": {"integrator": dict(sorted(merged_all.items())),
                          "ota_fd": dict(sorted(merged_ota.items()))},
        "raw_counts": {"integrator": dict(sorted(raw_all.items())),
                       "ota_fd": dict(sorted(raw_ota.items()))},
        "lvtn_markers_drawn": len(result_markers),
        "extracted_pins": pins,
        "expected_pins": expected_pins,
        "extracted_pins_note": (
            "Twenty label texts on eighteen pins. The four beyond this cell's "
            "sixteen .subckt ports (inp, inn, outp, outn) are the OTA cell's "
            "own met1.pin labels, carried in through the instance. outp/outn "
            "share a pin with this cell's voutp/voutn -- which is what shows "
            "the OTA's outputs are the nets Ci_p/Ci_n sit on -- while inp/inn "
            "stand alone on sumn/sump, which this cell does not export."),
        "net_count": {"schematic_integrator": len(schematic_nets),
                      "ota_internal_extracted": len(nets_ota),
                      "expected_total": expected_nets,
                      "extracted_total": len(nets_all)},
        "pass": ok,
    }
    (out_dir / "extract-device-count.json").write_text(
        json.dumps(evidence, indent=2) + "\n")
    say(f"  own device count: {own} {'PASS' if ok else 'FAIL'}")
    if pins != expected_pins:
        raise RuntimeError(
            f"extracted pins {pins} != expected {expected_pins}: a met1.pin "
            "label landed on metal its net does not own")
    if len(nets_all) != expected_nets:
        raise RuntimeError(
            f"extracted {len(nets_all)} distinct device-terminal nets, expected "
            f"{expected_nets} ({len(schematic_nets)} schematic + "
            f"{len(nets_ota)} OTA-internal - {len(OTA_PORT_NETS)} shared): a "
            f"terminal is dangling or two nets merged. extracted={nets_all}")
    if blind != EXPECTED_FLAVOUR_BLIND:
        raise RuntimeError(
            f"flavour-blind device count {blind} != {EXPECTED_FLAVOUR_BLIND}")
    if not ok:
        raise RuntimeError(
            f"extract device count check FAILED: own={own} "
            f"expected={EXPECTED_DEVICES}")

    say("[7/7] done")
    return {"drc": drc, "extract": evidence, "route": route_summary}


def emit(out_dir: Path, cell_dir: Path) -> None:
    shutil.copyfile(out_dir / f"{TOP_CELL}.gds", cell_dir / f"{TOP_CELL}.gds")
    for name in ("extract-device-count.json", "drc.report.json"):
        shutil.copyfile(out_dir / name, cell_dir / name)
    shutil.copyfile(out_dir / "route.summary.json", cell_dir / "route-summary.json")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and verify layout/analog/integrator/integrator.gds "
                    "and its committed evidence; see this directory's README.md.")
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
        tmp = Path(tempfile.mkdtemp(prefix="integrator-check-"))
        try:
            flow(args.klt, pdk_root, tmp, cell_dir, verbose=False)
            a, b = committed.read_bytes(), (tmp / f"{TOP_CELL}.gds").read_bytes()
            if a == b:
                print("gen_integrator.py --check: PASS -- regenerated GDS is "
                      f"byte-identical to {committed.name} ({len(a)} bytes)")
                return 0
            print("gen_integrator.py --check: FAIL -- regenerated GDS differs "
                  f"(committed {len(a)} bytes, fresh {len(b)} bytes)",
                  file=sys.stderr)
            return 1
        finally:
            if args.keep_scratch:
                print(f"scratch kept at {tmp}", file=sys.stderr)
            else:
                shutil.rmtree(tmp, ignore_errors=True)

    result = flow(args.klt, pdk_root, cell_dir / "_gen", cell_dir)
    emit(cell_dir / "_gen", cell_dir)
    drc = result["drc"]
    print(f"gen_integrator.py: wrote {TOP_CELL}.gds + evidence to {cell_dir} "
          f"(drc status={drc.get('status')!r}, "
          f"violations={drc.get('violation_count')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Switch probes: on-state Ron, off-state leakage, and pass-gate Ron vs input.

Every number this writes is a single DC operating point, run locally. It is
simulated (ngspice, sky130 device models), not measured, and it is not a record
and not a performance claim: it is the testbench behind the switch-resistance
arguments in design/integrator/SIZING.md -> "Switch sizes" and "Why the `vcm`
switches need a PMOS half".

Three probe kinds, in three point sets:

  i92 set, one device per row:
    ron       the switch passes vcm = 0.9 V with a 10 mV drain-source bias and
              its gate fully on; Ron = bias / I. The cell's phi2 switches do
              exactly this job, so this is the quantity that collapses at
              Vdda = 1.620 V.
    leakage   the switch is off (gate at its own off rail) with 0.3 V across it;
              the current is the droop the summing node sees in one phase.

  i106 set, the complementary pass gate (both halves in parallel):
    tg        the as-built `Sin_*` gate (`nfet_01v8` W 4 + `pfet_01v8` W 8,
              L 0.15, no low-Vth half) passes a swept input voltage with a 10 mV
              bias; Ron = bias / I, and each half's share of the current is
              reported too. Near vcm at Vdda = 1.620 V neither half has
              overdrive, which is the mechanism issue #106 filed.

  i147 set, the top-plate hold switch, same tg kind on a generalized deck:
    tg        the as-built `Sci_*`/`Scr_*` switch is a LONE `nfet_01v8_lvt`
              (W 12, L 0.15) with no PMOS half, and during phi1e it must sink
              the bottom-plate-coupled charge to vcm -- so on the side driven
              up it holds a voltage ABOVE vcm, where its Vgs = Vdda - Vin
              collapses. That is 98 % of the fs/1.620 V/-40 C sampling error
              in sim/integrator-ci/record-i106.json. The set probes the
              as-built NMOS alone, the two PMOS-half precedents already in the
              cell (Sti W 4 / Sbi W 24) added to it, and a widened-NMOS-only
              counterfactual, over the same condition grid as i106.

    python3 -I sim/switch-probe/run_probe.py                       # print all sets
    python3 -I sim/switch-probe/run_probe.py --set i106 --write     # probe-i106.json
    python3 -I sim/switch-probe/run_probe.py --set i92  --write     # probe-i92.json
    python3 -I sim/switch-probe/run_probe.py --set i147 --write     # probe-i147.json
"""
import argparse, hashlib, json, pathlib, re, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from settling_common import join_continuations, ngspice_version, pdk_stamp

VCM = 0.9
RON_BIAS = 0.010      # 10 mV across the closed switch
GMIN_FLOOR = 1e-15    # the decks' `option gmin`; currents at/below it are "effectively open"


def ron_from_current(i_dev):
    """Ron = bias / I, with the gmin floor made explicit.

    The runner (not the deck) computes Ron, so a point where the branch
    current underflows to the gmin floor reports honestly: `None`, plus the
    row's `current_at_gmin_floor` flag -- at or below 1e-15 A the switch is
    effectively open (Ron >= bias/gmin = 1e13 ohm), and a finite number there
    would be the floor, not a measurement.
    """
    if i_dev > GMIN_FLOOR:
        return RON_BIAS / i_dev
    return None
LEAK_BIAS = 0.300     # 0.3 V across the open switch


def geom(w, l):
    """The per-device geometry `klt netlist` emits for a W x L switch.

    Reproduces the committed netlist's own rule (checked against
    design/integrator/integrator.spice by --self-check): ad = as = 0.29*W,
    pd = ps = 2*W + 0.58, nrd = nrs = 0.29/W.
    """
    return (f"L={l} W={w:g} nf=1 ad={0.29*w:g} as={0.29*w:g} pd={2*w+0.58:g} ps={2*w+0.58:g} "
            f"nrd={0.29/w:.8g} nrs={0.29/w:.8g} sa=0 sb=0 sd=0 mult=1 m=1")


def kv(s):
    """Parse a device parameter string into {name: float}."""
    return {k: float(v) for k, v in re.findall(r"([A-Za-z]+)=([-+0-9.eE]+)", s)}


def self_check():
    """Assert geom() matches how the committed cell actually declares its switches."""
    joined = join_continuations((REPO / "design/integrator/integrator.spice").read_text())
    checked = 0
    for ln in joined:
        m = re.match(r"XS\S+ \S+ \S+ \S+ \S+ (sky130_fd_pr__\S+) (.*)$", ln)
        if not m:
            continue
        got = kv(m.group(2))
        w, l = got["W"], got["L"]
        want = kv(geom(w, l))
        # Numeric, not textual: xschem's own float formatting is not uniform
        # (nrd prints 7 significant digits at W 12 and 8 at W 24), so compare to 1 ppm
        # the values the simulator actually sees.
        bad = [k for k in want
               if k not in got or abs(got[k] - want[k]) > 1e-6 * max(1.0, abs(want[k]))]
        if bad:
            sys.exit(f"REFUSE: geom() disagrees with the committed netlist for W={w:g} L={l:g} "
                     f"on {bad}\n  netlist: {got}\n  geom():  {want}")
        checked += 1
    if not checked:
        sys.exit("REFUSE: found no XS switch lines to self-check against")
    return checked


# (key, model, W, L, corner, temp, vdda, kind)  -- one row = one ngspice .op
POINTS = [
    # --- Ron table: SIZING.md "Switch Ron at Vdda = 1.620 V, passing 0.9 V, -40 C"
    *[(f"ron_nfet_w12_{c}", "sky130_fd_pr__nfet_01v8", 12, 0.15, c, -40, 1.620, "ron")
      for c in ("fs", "sf", "ss", "ff", "tt")],
    *[(f"ron_nfet_lvt_w12_{c}", "sky130_fd_pr__nfet_01v8_lvt", 12, 0.15, c, -40, 1.620, "ron")
      for c in ("fs", "sf", "ss", "ff", "tt")],
    *[(f"ron_pfet_lvt_w48_{c}", "sky130_fd_pr__pfet_01v8_lvt", 48, 0.35, c, -40, 1.620, "ron")
      for c in ("fs", "sf", "ss", "ff", "tt")],
    # --- PMOS Ron scales as 1/W (SIZING.md: 755 / 378 / 189 ohm at W 12 / 24 / 48, fs)
    *[(f"ron_pfet_lvt_w{w}_fs", "sky130_fd_pr__pfet_01v8_lvt", w, 0.35, "fs", -40, 1.620, "ron")
      for w in (12, 24, 48)],
    # --- widening the NMOS alone does not rescue it (SIZING.md: 456 k -> 180 k)
    ("ron_nfet_w96_fs", "sky130_fd_pr__nfet_01v8", 96, 0.15, "fs", -40, 1.620, "ron"),
    # --- off-state leakage at the hot/fast corner (SIZING.md: 129 pA / 129 pA / 23 pA)
    ("leak_nfet_w12_ff", "sky130_fd_pr__nfet_01v8", 12, 0.15, "ff", 125, 1.980, "leakage"),
    ("leak_nfet_lvt_w12_ff", "sky130_fd_pr__nfet_01v8_lvt", 12, 0.15, "ff", 125, 1.980, "leakage"),
    ("leak_pfet_lvt_w16_ff", "sky130_fd_pr__pfet_01v8_lvt", 16, 0.35, "ff", 125, 1.980, "leakage"),
]

# ---------------------------------------------- issue #106: the pass gate ----
# The as-built transmission gate, read off design/integrator/integrator.spice
# (`XSin_p_n` / `XSin_p_p`, and identically `Sin_n`, `Sr_*`, `Mra_*`, `Mrb_*`).
# Neither half is low-Vth, unlike the phi2 `vcm` switches issue #92 fixed.
TG_NMOS = ("sky130_fd_pr__nfet_01v8", 4, 0.15)
TG_PMOS = ("sky130_fd_pr__pfet_01v8", 8, 0.15)

# The voltage the gate has to pass. spec row 11 caps the peak differential
# input at 0.5*VREF = 0.6 V, which spec section 5.4 spells out as each side
# within +/-0.3 V of vcm = 0.9 V, so 0.6 .. 1.2 V is the range that matters and is
# resolved at 50 mV or finer across it; 0.3 V and 1.5 V are the DR-005
# reference rails the same gate family passes (`Sr_*`, `Mra_*`, `Mrb_*`), and
# 0.45 / 1.35 V fill in between.
TG_VIN = (0.3, 0.45, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15,
          1.2, 1.35, 1.5)
# (corner, temperature_C, Vdda): the low-supply cold condition issue #106
# reported, over all five process skews -- plus `tt`/27 C/1.800 V, the condition
# design/integrator/SIZING.md's existing "Probe Ron" column was taken at (that
# file's "Labelling" paragraph), so the committed row can be qualified against
# a reproduction instead of from prose.
TG_CONDITIONS = tuple([(c, -40, 1.620) for c in ("tt", "ss", "ff", "sf", "fs")]
                      + [("tt", 27, 1.800)])


def vtag(x):
    """A filename/key-safe tag for a voltage or temperature (0.45 -> 0p45)."""
    return f"{x:g}".replace("-", "m").replace(".", "p")


def tg_points():
    """The pass-gate sweep rows, one ngspice .op each.

    Pure: no PDK, no simulator. `test_run_probe.py` pins the sweep against the
    range spec row 11 asks for, so a later edit that drops the 0.6 .. 1.2 V
    coverage fails a test rather than quietly narrowing the evidence.
    """
    return [(f"tg_sin_{corner}_{vtag(temp)}c_{vtag(vdda)}v_{vtag(vin)}v",
             corner, temp, vdda, vin)
            for corner, temp, vdda in TG_CONDITIONS for vin in TG_VIN]


TG_POINTS = tg_points()


# --------------------------------------- issue #147: the top-plate hold ----
# The as-built top-plate hold switch, read off design/integrator/integrator.spice
# (`XSci_p` / `XSci_n`, and identically `Scr_p` / `Scr_n`): a lone low-Vth NMOS,
# no PMOS half. Unlike `Sin` it does not pass a voltage FROM somewhere -- during
# phi1e it must SINK the bottom-plate-coupled charge to vcm, so on the side
# driven up it holds a voltage ABOVE vcm, where its Vgs = Vdda - Vin falls
# toward and below threshold. Issue #92 found the same mechanism on the phi2
# `vcm` switches and gave those PMOS halves; `Sci`/`Scr` were left out.
SCI_NMOS = ("sky130_fd_pr__nfet_01v8_lvt", 12, 0.15)

# The two PMOS-half precedents already in the cell, at their #92 sizes: the
# top-plate-to-summing-node half (`XSti_*_p`, the nearer precedent -- same
# top plate, but `Sci` additionally carries the coupled charge) and the
# bottom-plate half (`XSbi_*_p`). Both `pfet_01v8_lvt` L 0.35.
SCI_PMOS_STI = ("sky130_fd_pr__pfet_01v8_lvt", 4, 0.35)
SCI_PMOS_SBI = ("sky130_fd_pr__pfet_01v8_lvt", 24, 0.35)

# Widened-NMOS-only counterfactual: SIZING.md records that widening the NMOS
# alone does not rescue the sibling gate (`ron_nfet_w96_fs`: 456 k -> 180 k);
# this set re-derives that for `Sci` so the decision cites its own evidence.
SCI_NMOS_WIDE = ("sky130_fd_pr__nfet_01v8_lvt", 96, 0.15)

# variant -> (NMOS pair, PMOS pair or None, what the row names itself as in the
# record). Pure data; `sci_points()` and the runner read this.
SCI_VARIANTS = {
    "as_built": (SCI_NMOS, None,
                 "Sci/Scr as built: a lone nfet_01v8_lvt, no PMOS half"),
    "p_sti4": (SCI_NMOS, SCI_PMOS_STI,
               "Sci + a PMOS half at the Sti precedent (pfet_01v8_lvt W 4 L 0.35)"),
    "p_sbi24": (SCI_NMOS, SCI_PMOS_SBI,
                "Sci + a PMOS half at the Sbi precedent (pfet_01v8_lvt W 24 L 0.35)"),
    "n96": (SCI_NMOS_WIDE, None,
            "Sci widened-NMOS-only counterfactual (nfet_01v8_lvt W 96, no PMOS half)"),
}
# The two candidate remedies the decision must compare get the whole condition
# grid; the size cross-check (`p_sbi24`) and the widened-NMOS counterfactual
# (`n96`) are decision evidence at the binding corner only -- fs/-40 C/1.620 V,
# where record-i106.json pins the 78.9 mV top-plate offset.
SCI_FULL_CONDITION_VARIANTS = ("as_built", "p_sti4")


def sci_points():
    """The `Sci` top-plate-hold sweep rows, one ngspice .op each.

    Pure: no PDK, no simulator. Same measurement grid and condition list as the
    i106 pass-gate sweep (TG_VIN / TG_CONDITIONS, reused verbatim so the two
    curves read side by side); only the device under probe differs.
    """
    rows = []
    for name, (nmos, pmos, switch) in SCI_VARIANTS.items():
        conds = (TG_CONDITIONS if name in SCI_FULL_CONDITION_VARIANTS
                 else (("fs", -40, 1.620),))
        for corner, temp, vdda in conds:
            for vin in TG_VIN:
                rows.append((f"tg_sci_{name}_{corner}_{vtag(temp)}c_{vtag(vdda)}v_{vtag(vin)}v",
                             name, corner, temp, vdda, vin))
    return rows


SCI_POINTS = sci_points()


def run(key, model, w, l, corner, temp, vdda, kind, ng, pdk_lib, tmp):
    pmos = "pfet" in model
    bias = RON_BIAS if kind == "ron" else LEAK_BIAS
    # Source at vcm; drain biased above it. A PMOS half sits in an n-well tied
    # to vdda, an NMOS half in the p-substrate at vssa.
    vs, vd = VCM, VCM + bias
    if kind == "ron":
        vg = 0.0 if pmos else vdda          # fully on
    else:
        vg = vdda if pmos else 0.0          # fully off
    vb = vdda if pmos else 0.0
    deck = ((HERE / "switch_probe.cir.tmpl").read_text()
            .replace("{{PDK_LIB}}", f'"{pdk_lib}"').replace("{{CORNER}}", corner)
            .replace("{{TEMP}}", str(temp)).replace("{{VDDA}}", str(vdda))
            .replace("{{VS}}", f"{vs:g}").replace("{{VD}}", f"{vd:g}")
            .replace("{{VG}}", f"{vg:g}").replace("{{VB}}", f"{vb:g}")
            .replace("{{MODEL}}", model).replace("{{GEOM}}", geom(w, l))
            .replace("{{BIAS}}", f"{bias:g}"))
    d = tmp / f"probe-{key}.cir"
    d.write_text(deck)
    r = subprocess.run(["ngspice", "-b", str(d)], capture_output=True, text=True, cwd=ng)
    log = r.stdout + r.stderr
    vals = {k: float(x) for k, x in
            re.findall(r"^([a-z_0-9]+)\s*=\s*([-+0-9.eE]+)\s*$", log, re.M)}
    if r.returncode or "i_dev" not in vals:
        print(log[-3000:], file=sys.stderr)
        sys.exit(f"REFUSE: ngspice did not produce the probe scalars for '{key}'")
    out = {"model": model, "W_um": w, "L_um": l, "corner": corner, "temperature_c": temp,
           "vdda_V": vdda, "kind": kind, "bias_V": bias, "current_A": vals["i_dev"]}
    if kind == "ron":
        out["ron_ohm"] = vals["r_on"]
    return out


def run_tg(key, corner, temp, vdda, vin, ng, pdk_lib, tmp, *,
           switch="Sin (and Sr, Mra, Mrb -- same device pair)",
           nmos=TG_NMOS, pmos=TG_PMOS, tmpl="tg_probe.cir.tmpl"):
    """One pass-gate operating point: both halves in parallel, Ron = bias / I.

    Generalized for issue #147: the device pair is a parameter and the PMOS
    half may be `None` (the as-built `Sci` has none). `tmpl` selects the deck:
    the i106 template substitutes the PMOS model/geometry in place, the i147
    template takes the whole PMOS line as one `{{PMOS_LINE}}` placeholder so it
    can be absent.
    """
    nmodel, nw, nl = nmos
    deck = ((HERE / tmpl).read_text()
            .replace("{{PDK_LIB}}", f'"{pdk_lib}"').replace("{{CORNER}}", corner)
            .replace("{{TEMP}}", str(temp)).replace("{{VDDA}}", str(vdda))
            .replace("{{VS}}", f"{vin:.6g}").replace("{{VD}}", f"{vin + RON_BIAS:.6g}")
            .replace("{{VGN}}", f"{vdda:g}").replace("{{VGP}}", "0")
            .replace("{{NMODEL}}", nmodel).replace("{{NGEOM}}", geom(nw, nl))
            .replace("{{BIAS}}", f"{RON_BIAS:g}"))
    if "{{PMOS_LINE}}" in deck:
        if pmos is None:
            deck = deck.replace("{{PMOS_LINE}}",
                                "* (as built: no PMOS half on this gate)")
        else:
            pmodel, pw, pl = pmos
            deck = deck.replace("{{PMOS_LINE}}",
                                f"X2 dp gp s vdda {pmodel} {geom(pw, pl)}")
    else:
        pmodel, pw, pl = pmos
        deck = deck.replace("{{PMODEL}}", pmodel).replace("{{PGEOM}}", geom(pw, pl))
    left = sorted({w for w in deck.split() if w.startswith("{{") and w.endswith("}}")})
    if left:
        sys.exit(f"REFUSE: unsubstituted placeholder(s) in the tg deck for '{key}': {left}")
    d = tmp / f"probe-{key}.cir"
    d.write_text(deck)
    r = subprocess.run(["ngspice", "-b", str(d)], capture_output=True, text=True, cwd=ng)
    log = r.stdout + r.stderr
    vals = {k: float(x) for k, x in
            re.findall(r"^([a-z_0-9]+)\s*=\s*([-+0-9.eE]+)\s*$", log, re.M)}
    need = ("i_dev", "i_nmos", "i_pmos")
    if r.returncode or any(k not in vals for k in need):
        print(log[-3000:], file=sys.stderr)
        sys.exit(f"REFUSE: ngspice did not produce the pass-gate scalars for '{key}'")
    # The deck takes abs() of each half's current independently; if the halves
    # ever ran counter to one another their currents would be summed rather
    # than cancelled and the shares could exceed 1 (README.md, "What validates
    # the split"). Every committed i106 row holds the sum to 1e-6; a row that
    # does not is the halves fighting, and it refuses instead of measuring.
    if abs(vals["i_nmos"] + vals["i_pmos"] - vals["i_dev"]) > 1e-6 * max(vals["i_dev"], 1e-15):
        sys.exit(f"REFUSE: half currents do not sum to the gate current for '{key}' "
                 f"({vals['i_nmos']:.6g} + {vals['i_pmos']:.6g} != {vals['i_dev']:.6g})")
    # Which half carries the current decides what a remedy should change: a
    # low-Vth NMOS half, or a wider PMOS half. Reported, never interpreted here.
    share = vals["i_nmos"] / vals["i_dev"] if vals["i_dev"] else None
    return {"kind": "tg", "switch": switch,
            "nmos": {"model": nmodel, "W_um": nw, "L_um": nl},
            "pmos": ({"model": pmodel, "W_um": pw, "L_um": pl} if pmos else None),
            "corner": corner, "temperature_c": temp, "vdda_V": vdda,
            "vin_V": vin, "bias_V": RON_BIAS,
            "current_A": vals["i_dev"],
            "ron_ohm": ron_from_current(vals["i_dev"]),
            "current_at_gmin_floor": vals["i_dev"] <= GMIN_FLOOR,
            "current_nmos_A": vals["i_nmos"], "current_pmos_A": vals["i_pmos"],
            "nmos_current_share": share}


# (set name) -> (what the rows are, the metadata the set contributes)
POINT_SETS = ("i92", "i106", "i147")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdk-root", default=None)
    ap.add_argument("--set", choices=POINT_SETS + ("all",), default="all",
                    help="which point set to run: i92 (single-device ron/leakage), "
                         "i106 (pass-gate Ron vs input), i147 (Sci top-plate hold vs "
                         "top-plate voltage), or all (default; print only)")
    ap.add_argument("--out", default=None,
                    help="result file name (default: probe-<set>.json)")
    ap.add_argument("--write", action="store_true", help="save the result file")
    a = ap.parse_args()
    sets = POINT_SETS if a.set == "all" else (a.set,)
    if a.write and a.set == "all":
        print("REFUSE: --write needs one point set, because each set has its own "
              "result file; use --set i92, --set i106 or --set i147", file=sys.stderr)
        return 2

    pin = json.load(open(REPO / "sim/pdk.json"))
    root, stamp = pdk_stamp(pin["variant"], a.pdk_root)
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'", file=sys.stderr)
        return 2
    out = HERE / (a.out or f"probe-{a.set}.json")
    if a.write and out.exists():
        print(f"REFUSE: {out.name} exists; results are append-only (use --out)", file=sys.stderr)
        return 2
    checked = self_check()
    ng = root / pin["variant"] / "libs.tech/ngspice"
    pdk_lib = ng / "sky130.lib.spice"

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="switch-probe-"))
    fixture = {
        "i92": "Single-switch DC probes: on-state Ron and off-state leakage (issue #92)",
        "i106": "Transmission-gate DC probe: `Sin` pass-gate Ron versus the voltage it "
                "passes, over the five process skews at Vdda = 1.620 V / -40 C (issue #106)",
        "i147": "Top-plate hold switch DC probe: the as-built `Sci` NMOS (a lone "
                "nfet_01v8_lvt, no PMOS half) Ron versus the top-plate voltage it must "
                "hold to vcm, with the #92-precedent PMOS halves and a widened-NMOS "
                "counterfactual as variants, over the same condition grid (issue #147)",
    }
    purpose = {
        "i92": "give the switch-resistance and leakage numbers in "
               "design/integrator/SIZING.md a committed testbench",
        "i106": "give the `Sin` sampling-resistance finding in issue #106 a committed "
                "testbench: Ron versus input for the as-built pass gate, which the "
                "single-device `ron` kind cannot show",
        "i147": "give the `Sci` top-plate-hold finding (98 % of the fs/1.620 V/-40 C "
                "0.6 V-input sampling error in sim/integrator-ci/record-i106.json) a "
                "committed mechanism testbench, and the change-or-accept decision its "
                "own evidence",
    }
    method = {}
    if "i92" in sets:
        method["ron"] = (f"source at vcm = {VCM} V, drain {RON_BIAS*1e3:g} mV above it, "
                         "gate fully on; Ron = bias / I")
        method["leakage"] = (f"gate at its off rail, {LEAK_BIAS} V across the device; "
                             "I is the leakage")
    if "i106" in sets:
        method["tg"] = (f"both halves in parallel between the swept voltage and "
                        f"{RON_BIAS*1e3:g} mV above it, NMOS gate at Vdda and PMOS gate at "
                        "vssa (fully on), bulks on their static rails; Ron = bias / I, and "
                        "each half's share of I is reported separately")
    if "i147" in sets:
        method["sci_tg"] = ("the tg measurement on the top-plate hold switch: the swept "
                            "terminal is the TOP PLATE, and during phi1e the switch sinks "
                            "the coupled charge to vcm, so the informative half of the "
                            "sweep is the half ABOVE vcm = 0.9 V -- the opposite half from "
                            "the `Sin` gate's, whose binding half is below it. The whole "
                            "range is swept anyway so both gates read on one grid. The "
                            "10 mV probe bias is direction-agnostic; the physical hold "
                            "current flows top plate -> vcm. Variants in "
                            f"{', '.join(SCI_VARIANTS)}: as_built and p_sti4 over every "
                            "TG_CONDITIONS condition, p_sbi24 and n96 at the binding "
                            "fs/-40 C/1.620 V corner only. NMOS gate at Vdda (phi1e's "
                            "high rail); a PMOS half, when present, gates at 0 (the low "
                            "rail a local phi1eb inverter would deliver) with its n-well "
                            "at vdda")
        method["ron"] = ("derived by the runner as bias / I from the deck's printed "
                         "branch currents, not in the deck: on NMOS-only rows the "
                         "current underflows to the deck's 1e-15 gmin floor at the top "
                         "of the sweep, and a row there reports ron_ohm = null with "
                         "current_at_gmin_floor = true -- effectively open (>= 1e13 "
                         "ohm at the 10 mV bias), not a floored finite number")
    method["geometry"] = ("ad = as = 0.29*W, pd = ps = 2*W + 0.58, nrd = nrs = 0.29/W -- the "
                          "rule the committed netlist itself uses")
    method["geometry_self_check"] = (f"{checked} switch lines in "
                                     "design/integrator/integrator.spice reproduce under that "
                                     "rule")
    res = {
        "fixture": " + ".join(fixture[s] for s in sets),
        "result_kind": "simulated (ngspice, sky130 device models); one DC operating point per "
                       "row, run locally; not measured, not a record, not a performance claim",
        "purpose": " + ".join(purpose[s] for s in sets),
        "method": method,
        "pdk_sources_stamp": stamp,
        "pdk_pin": {"file": "sim/pdk.json", "open_pdks_revision": pin["open_pdks_revision"]},
        "ngspice": ngspice_version(),
    }
    if "i92" in sets:
        res["deck_sha256"] = hashlib.sha256(
            (HERE / "switch_probe.cir.tmpl").read_bytes()).hexdigest()
    if "i106" in sets:
        res["tg_deck_sha256"] = hashlib.sha256(
            (HERE / "tg_probe.cir.tmpl").read_bytes()).hexdigest()
    if "i147" in sets:
        res["sci_deck_sha256"] = hashlib.sha256(
            (HERE / "sci_probe.cir.tmpl").read_bytes()).hexdigest()
    res["integrator_netlist_sha256"] = hashlib.sha256(
        (REPO / "design/integrator/integrator.spice").read_bytes()).hexdigest()
    res["points"] = {}
    if "i92" in sets:
        for key, model, w, l, corner, temp, vdda, kind in POINTS:
            res["points"][key] = run(key, model, w, l, corner, temp, vdda, kind, ng, pdk_lib, tmp)
            p = res["points"][key]
            print(f"  {key:28s} {kind:8s} "
                  + (f"Ron = {p['ron_ohm']:.4g} ohm" if kind == "ron"
                     else f"I = {p['current_A']:.4g} A"), file=sys.stderr)
    if "i106" in sets:
        for key, corner, temp, vdda, vin in TG_POINTS:
            res["points"][key] = run_tg(key, corner, temp, vdda, vin, ng, pdk_lib, tmp)
            p = res["points"][key]
            print(f"  {key:34s} tg       Ron = {p['ron_ohm']:10.4g} ohm   "
                  f"(NMOS {100 * p['nmos_current_share']:5.1f} % of I)", file=sys.stderr)
    if "i147" in sets:
        for key, variant, corner, temp, vdda, vin in SCI_POINTS:
            nmos, pmos, switch = SCI_VARIANTS[variant]
            res["points"][key] = run_tg(key, corner, temp, vdda, vin, ng, pdk_lib, tmp,
                                        switch=switch, nmos=nmos, pmos=pmos,
                                        tmpl="sci_probe.cir.tmpl")
            p = res["points"][key]
            share = (f"(NMOS {100 * p['nmos_current_share']:5.1f} % of I)"
                     if p["pmos"] else "(NMOS only, as built)")
            ron = (f"{p['ron_ohm']:10.4g} ohm" if p["ron_ohm"] is not None
                   else "   open (>=1e13)")
            print(f"  {key:46s} tg       Ron = {ron}   {share}",
                  file=sys.stderr)

    txt = json.dumps(res, indent=2) + "\n"
    if a.write:
        out.write_text(txt)
        print(f"wrote {out.name}")
    else:
        print(txt)
        print("re-run with --write to save", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

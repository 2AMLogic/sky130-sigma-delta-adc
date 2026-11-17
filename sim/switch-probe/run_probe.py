#!/usr/bin/env python3
"""Switch probes: on-state Ron, off-state leakage, and pass-gate Ron vs input.

Every number this writes is a single DC operating point, run locally. It is
simulated (ngspice, sky130 device models), not measured, and it is not a record
and not a performance claim: it is the testbench behind the switch-resistance
arguments in design/integrator/SIZING.md -> "Switch sizes" and "Why the `vcm`
switches need a PMOS half".

Three probe kinds, in two point sets:

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

  i129 set, the low-Vth sizing sweep (issue #129):
    tg        each candidate low-Vth replacement for `Sin` -- NMOS
              `nfet_01v8_lvt` L 0.15 in parallel with PMOS `pfet_01v8_lvt`
              L 0.35 (that model's minimum length), at a small set of width
              pairs starting at the phi2 `vcm` switches' geometry (issue #92's
              remedy) and going down -- passes the same swept input under the
              same bias. The record's `derived` block reduces each candidate x
              condition sweep to its peak Ron, the input it peaks at, and the
              NMOS share at the peak, which is what design/integrator/SIZING.md
              reads the chosen size off.

    python3 -I sim/switch-probe/run_probe.py                       # print all sets
    python3 -I sim/switch-probe/run_probe.py --set i106 --write     # probe-i106.json
    python3 -I sim/switch-probe/run_probe.py --set i92  --write     # probe-i92.json
    python3 -I sim/switch-probe/run_probe.py --set i129 --write     # probe-i129.json
"""
import argparse, hashlib, json, pathlib, re, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from settling_common import join_continuations, ngspice_version, pdk_stamp

VCM = 0.9
RON_BIAS = 0.010      # 10 mV across the closed switch
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


def i129_derived(points):
    """Reduce each candidate's sweep to its peak Ron per condition (issue #129).

    Pure: points in, summary out. SIZING.md reads the chosen size from here:
    for every candidate and condition, the worst Ron over the swept input, the
    input it occurs at, and the NMOS share there (which half is limiting at
    the peak). `overall_worst` names the condition that binds the candidate.
    """
    out = {}
    for nw, pw in I129_CANDIDATES:
        prefix = f"tg129_lvt_n{nw:g}_p{pw:g}_"
        per_cond = {}
        for corner, temp, vdda in TG_CONDITIONS:
            tag = f"{corner}_{vtag(temp)}c_{vtag(vdda)}v"
            rows = [(p["ron_ohm"], p["vin_V"], p["nmos_current_share"])
                    for k, p in points.items() if k.startswith(prefix + tag + "_")]
            if not rows:
                continue
            ron, vin, share = max(rows)
            per_cond[tag] = {"peak_ron_ohm": ron, "peak_at_vin_V": vin,
                             "nmos_current_share_at_peak": share}
        worst_key, worst = max(per_cond.items(), key=lambda kv: kv[1]["peak_ron_ohm"])
        out[f"nmos_w{nw:g}_pmos_w{pw:g}"] = {
            "nmos": {"model": I129_NMOS[0], "W_um": nw, "L_um": I129_NMOS[1]},
            "pmos": {"model": I129_PMOS[0], "W_um": pw, "L_um": I129_PMOS[1]},
            "per_condition": per_cond,
            "overall_worst_condition": worst_key,
            "overall_worst_peak_ron_ohm": worst["peak_ron_ohm"],
            "overall_worst_peak_at_vin_V": worst["peak_at_vin_V"],
        }
    return out


# -------------------------------- issue #129: the low-Vth sizing sweep ----
# Candidate replacements for the `Sin` gate, in the same flavours issue #92
# gave the phi2 `vcm` switches: an `nfet_01v8_lvt` half at L 0.15 and a
# `pfet_01v8_lvt` half at L 0.35 -- the lvt PMOS model's own minimum length,
# and the length every lvt PMOS half in the committed cell already sits at
# (the standard-Vth `Sin` PMOS at L 0.15 cannot simply be re-flavoured).
# Width pairs start at the phi2 `vcm` switches' geometry (NMOS W 12, PMOS
# W 24) and go DOWN, because unlike those switches `Sin` sits directly on the
# input: every micron of width is gate area the input drives and channel the
# phi1 turn-off injects onto. The chosen size is read from the committed
# sweep, never from a calculation -- `derived` reduces each sweep below.
I129_NMOS = ("sky130_fd_pr__nfet_01v8_lvt", 0.15)
I129_PMOS = ("sky130_fd_pr__pfet_01v8_lvt", 0.35)
I129_CANDIDATES = ((4, 8), (6, 12), (8, 16), (12, 24))
# The same input range the i106 sweep resolves, re-pointed at where a
# low-Vth pair can actually peak: the full 0.3 .. 1.5 V span for context,
# with the 0.7 .. 1.1 V window (around vcm, where every i106 skew peaked)
# resolved at 50 mV. i106's probes of the old gate peaked at 0.80-1.00 V;
# the coarse steps outside that window do not straddle it.
I129_VIN = (0.3, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2, 1.5)


def i129_points():
    """The sizing-sweep rows: one ngspice .op per candidate x condition x Vin.

    Pure: no PDK, no simulator. `test_run_probe.py` pins the candidate set
    against the phi2 `vcm` switches' geometry and the condition set against
    the i106 conditions, so a later edit that quietly narrows either fails a
    test rather than shrinking the evidence.
    """
    nmodel, nl = I129_NMOS
    pmodel, pl = I129_PMOS
    return [(f"tg129_lvt_n{nw:g}_p{pw:g}_{corner}_{vtag(temp)}c_{vtag(vdda)}v_{vtag(vin)}v",
             nw, pw, nmodel, nl, pmodel, pl, corner, temp, vdda, vin)
            for nw, pw in I129_CANDIDATES
            for corner, temp, vdda in TG_CONDITIONS
            for vin in I129_VIN]


I129_POINTS = i129_points()


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


def run_tg(key, corner, temp, vdda, vin, ng, pdk_lib, tmp, nmos=None, pmos=None,
           switch="Sin (and Sr, Mra, Mrb -- same device pair)"):
    """One pass-gate operating point: both halves in parallel, Ron = bias / I."""
    nmodel, nw, nl = nmos or TG_NMOS
    pmodel, pw, pl = pmos or TG_PMOS
    deck = ((HERE / "tg_probe.cir.tmpl").read_text()
            .replace("{{PDK_LIB}}", f'"{pdk_lib}"').replace("{{CORNER}}", corner)
            .replace("{{TEMP}}", str(temp)).replace("{{VDDA}}", str(vdda))
            .replace("{{VS}}", f"{vin:.6g}").replace("{{VD}}", f"{vin + RON_BIAS:.6g}")
            .replace("{{VGN}}", f"{vdda:g}").replace("{{VGP}}", "0")
            .replace("{{NMODEL}}", nmodel).replace("{{NGEOM}}", geom(nw, nl))
            .replace("{{PMODEL}}", pmodel).replace("{{PGEOM}}", geom(pw, pl))
            .replace("{{BIAS}}", f"{RON_BIAS:g}"))
    left = sorted({w for w in deck.split() if w.startswith("{{") and w.endswith("}}")})
    if left:
        sys.exit(f"REFUSE: unsubstituted placeholder(s) in the tg deck for '{key}': {left}")
    d = tmp / f"probe-{key}.cir"
    d.write_text(deck)
    r = subprocess.run(["ngspice", "-b", str(d)], capture_output=True, text=True, cwd=ng)
    log = r.stdout + r.stderr
    vals = {k: float(x) for k, x in
            re.findall(r"^([a-z_0-9]+)\s*=\s*([-+0-9.eE]+)\s*$", log, re.M)}
    need = ("i_dev", "i_nmos", "i_pmos", "r_on")
    if r.returncode or any(k not in vals for k in need):
        print(log[-3000:], file=sys.stderr)
        sys.exit(f"REFUSE: ngspice did not produce the pass-gate scalars for '{key}'")
    # Which half carries the current decides what a remedy should change: a
    # low-Vth NMOS half, or a wider PMOS half. Reported, never interpreted here.
    share = vals["i_nmos"] / vals["i_dev"] if vals["i_dev"] else None
    return {"kind": "tg", "switch": switch,
            "nmos": {"model": nmodel, "W_um": nw, "L_um": nl},
            "pmos": {"model": pmodel, "W_um": pw, "L_um": pl},
            "corner": corner, "temperature_c": temp, "vdda_V": vdda,
            "vin_V": vin, "bias_V": RON_BIAS,
            "current_A": vals["i_dev"], "ron_ohm": vals["r_on"],
            "current_nmos_A": vals["i_nmos"], "current_pmos_A": vals["i_pmos"],
            "nmos_current_share": share}


# (set name) -> (what the rows are, the metadata the set contributes)
POINT_SETS = ("i92", "i106", "i129")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdk-root", default=None)
    ap.add_argument("--set", choices=POINT_SETS + ("all",), default="all",
                    help="which point set to run: i92 (single-device ron/leakage), "
                         "i106 (pass-gate Ron vs input), or all (default; print only)")
    ap.add_argument("--out", default=None,
                    help="result file name (default: probe-<set>.json)")
    ap.add_argument("--write", action="store_true", help="save the result file")
    a = ap.parse_args()
    sets = POINT_SETS if a.set == "all" else (a.set,)
    if a.write and a.set == "all":
        print("REFUSE: --write needs one point set, because each set has its own "
              "result file; use --set i92 or --set i106", file=sys.stderr)
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
        "i129": "Low-Vth transmission-gate sizing sweep: candidate `nfet_01v8_lvt` + "
                "`pfet_01v8_lvt` replacements for the `Sin` gate, Ron versus the voltage "
                "each passes, over the same six conditions as i106 (issue #129)",
    }
    purpose = {
        "i92": "give the switch-resistance and leakage numbers in "
               "design/integrator/SIZING.md a committed testbench",
        "i106": "give the `Sin` sampling-resistance finding in issue #106 a committed "
                "testbench: Ron versus input for the as-built pass gate, which the "
                "single-device `ron` kind cannot show",
        "i129": "give issue #129's cell decision a committed testbench: rank the "
                "candidate low-Vth `Sin` sizes by measured peak Ron so the chosen "
                "size is read from a record, not from a calculation",
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
    if "i129" in sets:
        method["tg129"] = (method.get("tg", "") + " Identical bench and bias on each "
                           "candidate pair; the candidates differ only in the two "
                           "halves' widths.")
        method["i129_candidates"] = {
            f"nmos_w{nw:g}_pmos_w{pw:g}": {
                "nmos": {"model": I129_NMOS[0], "W_um": nw, "L_um": I129_NMOS[1]},
                "pmos": {"model": I129_PMOS[0], "W_um": pw, "L_um": I129_PMOS[1]},
            } for nw, pw in I129_CANDIDATES}
        method["i129_candidates_note"] = (
            "width pairs from the phi2 `vcm` switches' geometry (n 12 / p 24, the "
            "issue #92 remedy) downward; the lvt PMOS sits at its L = 0.35 minimum")
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
    if "i129" in sets:
        for (key, nw, pw, nmodel, nl, pmodel, pl,
             corner, temp, vdda, vin) in I129_POINTS:
            res["points"][key] = run_tg(
                key, corner, temp, vdda, vin, ng, pdk_lib, tmp,
                nmos=(nmodel, nw, nl), pmos=(pmodel, pw, pl),
                switch=(f"candidate low-Vth Sin pair: NMOS {nmodel} W {nw:g} / "
                        f"L {nl:g} in parallel with PMOS {pmodel} W {pw:g} / L {pl:g}"))
            p = res["points"][key]
            print(f"  {key:48s} tg129    Ron = {p['ron_ohm']:10.4g} ohm   "
                  f"(NMOS {100 * p['nmos_current_share']:5.1f} % of I)", file=sys.stderr)
        res["derived"] = i129_derived(res["points"])

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

#!/usr/bin/env python3
"""Issue #92 switch probes: on-state Ron and off-state leakage, one point each.

Every number this writes is a single DC operating point of a *single device*,
run locally. It is simulated (ngspice, sky130 device models), not measured, and
it is not a record and not a performance claim: it is the testbench behind the
switch-resistance and leakage arguments in design/integrator/SIZING.md ->
"Why the `vcm` switches need a PMOS half".

Two probe kinds:

  ron       the switch passes vcm = 0.9 V with a 10 mV drain-source bias and
            its gate fully on; Ron = bias / I. The cell's phi2 switches do
            exactly this job, so this is the quantity that collapses at
            Vdda = 1.620 V.
  leakage   the switch is off (gate at its own off rail) with 0.3 V across it;
            the current is the droop the summing node sees in one phase.

    python3 -I sim/switch-probe/run_probe.py            # print
    python3 -I sim/switch-probe/run_probe.py --write    # save probe-i92.json
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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdk-root", default=None)
    ap.add_argument("--out", default="probe-i92.json")
    ap.add_argument("--write", action="store_true", help="save the result file")
    a = ap.parse_args()

    pin = json.load(open(REPO / "sim/pdk.json"))
    root, stamp = pdk_stamp(pin["variant"], a.pdk_root)
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'", file=sys.stderr)
        return 2
    out = HERE / a.out
    if a.write and out.exists():
        print(f"REFUSE: {out.name} exists; results are append-only (use --out)", file=sys.stderr)
        return 2
    checked = self_check()
    ng = root / pin["variant"] / "libs.tech/ngspice"
    pdk_lib = ng / "sky130.lib.spice"

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="switch-probe-"))
    res = {
        "fixture": "Single-switch DC probes: on-state Ron and off-state leakage (issue #92)",
        "result_kind": "simulated (ngspice, sky130 device models); one DC operating point per "
                       "row, run locally; not measured, not a record, not a performance claim",
        "purpose": "give the switch-resistance and leakage numbers in "
                   "design/integrator/SIZING.md a committed testbench",
        "method": {
            "ron": f"source at vcm = {VCM} V, drain {RON_BIAS*1e3:g} mV above it, gate fully on; "
                   "Ron = bias / I",
            "leakage": f"gate at its off rail, {LEAK_BIAS} V across the device; I is the leakage",
            "geometry": "ad = as = 0.29*W, pd = ps = 2*W + 0.58, nrd = nrs = 0.29/W -- the rule "
                        "the committed netlist itself uses",
            "geometry_self_check": f"{checked} switch lines in design/integrator/integrator.spice "
                                   "reproduce under that rule",
        },
        "pdk_sources_stamp": stamp,
        "pdk_pin": {"file": "sim/pdk.json", "open_pdks_revision": pin["open_pdks_revision"]},
        "ngspice": ngspice_version(),
        "deck_sha256": hashlib.sha256((HERE / "switch_probe.cir.tmpl").read_bytes()).hexdigest(),
        "integrator_netlist_sha256": hashlib.sha256(
            (REPO / "design/integrator/integrator.spice").read_bytes()).hexdigest(),
        "points": {},
    }
    for key, model, w, l, corner, temp, vdda, kind in POINTS:
        res["points"][key] = run(key, model, w, l, corner, temp, vdda, kind, ng, pdk_lib, tmp)
        p = res["points"][key]
        print(f"  {key:28s} {kind:8s} "
              + (f"Ron = {p['ron_ohm']:.4g} ohm" if kind == "ron"
                 else f"I = {p['current_A']:.4g} A"), file=sys.stderr)

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

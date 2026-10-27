#!/usr/bin/env python3
"""Integrator netlist load check (not a performance claim). See README.md."""
import argparse, json, pathlib, re, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
VCM, VREFP, VREFN, VINP, VINN = 0.9, 1.5, 0.3, 1.05, 0.75
TOL = 0.020  # volts; switch-level nodes are driven by ideal sources through on switches


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    a = ap.parse_args()
    pin = json.load(open(REPO / "sim/pdk.json"))
    if a.pdk_root:
        root = pathlib.Path(a.pdk_root).expanduser()
    else:
        out = subprocess.run(["klt", "pdk", "find", "--pdk", pin["variant"], "--format", "json"],
                             capture_output=True, text=True)
        if out.returncode:
            sys.exit(f"REFUSE: klt pdk find failed: {out.stderr.strip()}")
        root = pathlib.Path(json.loads(out.stdout)["root"])
    root = root / pin["variant"]
    src = root / "SOURCES"
    stamp = src.read_text().strip() if src.exists() else "<missing SOURCES>"
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'", file=sys.stderr)
        return 2
    ng = root / "libs.tech/ngspice"
    deck = ((HERE / "integrator_load.cir").read_text()
            .replace("{{PDK_LIB}}", f'"{ng / "sky130.lib.spice"}"')
            .replace("{{OTA}}", f'"{REPO / "design/ota/ota_fd.spice"}"')
            .replace("{{NETLIST}}", f'"{REPO / "design/integrator/integrator.spice"}"'))
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td) / "deck.cir"
        d.write_text(deck)
        r = subprocess.run(["ngspice", "-b", str(d)], capture_output=True, text=True, cwd=ng)
    log = r.stdout + r.stderr
    v = {k: float(x) for k, x in re.findall(r"^(s[abc]_\w+)\s*=\s*([-+0-9.e]+)\s*$", log, re.M)}
    if r.returncode or len(v) != 36:
        print(log[-2000:], file=sys.stderr)
        return 1
    near = lambda k, want: abs(v[k] - want) <= TOL
    checks = {}
    for tag, yp in (("a", VREFN), ("b", VREFP)):  # sample phase: a = dp (y=+1), b = dn (y=-1)
        yn = VREFP + VREFN - yp
        checks[f"{tag}_input_bottom_plates_follow_vinp_vinn"] = near(f"s{tag}_bpi_p", VINP) and near(f"s{tag}_bpi_n", VINN)
        checks[f"{tag}_top_plates_at_vcm"] = all(near(f"s{tag}_{n}", VCM) for n in ("tpi_p", "tpi_n", "tpr_p", "tpr_n"))
        checks[f"{tag}_dac_p_side_samples_{'VREFN' if yp == VREFN else 'VREFP'}"] = near(f"s{tag}_bpr_p", yp) and near(f"s{tag}_rsel_p", yp)
        checks[f"{tag}_dac_n_side_samples_the_other_rail"] = near(f"s{tag}_bpr_n", yn) and near(f"s{tag}_rsel_n", yn)
    checks["c_integrate_bottom_plates_to_vcm"] = all(near(f"sc_{n}", VCM) for n in ("bpi_p", "bpi_n", "bpr_p", "bpr_n"))
    checks["c_integrate_top_plates_on_sum_nodes"] = all(
        abs(v[f"sc_tp{x}_{s}"] - v[f"sc_sum{s}"]) <= 1e-6 for x in "ir" for s in "pn")
    checks["c_dac_mux_holds_rsel_with_phi1_off"] = near("sc_rsel_p", VREFN) and near("sc_rsel_n", VREFP)
    ok = all(checks.values())
    print(json.dumps({"checks": checks, "pass": ok}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

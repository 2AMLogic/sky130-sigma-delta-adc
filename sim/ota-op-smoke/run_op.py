#!/usr/bin/env python3
"""OTA operating-point smoke runner (smoke check, not a performance claim). See README.md."""
import argparse, hashlib, json, pathlib, re, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
VCM = 0.9
CM_TOL = 0.050    # output common mode within 50 mV of VCM
SYM_TOL = 0.001   # outp - outn within 1 mV at zero differential input
# total VDDA current incl. the 5 uA ibias, sanity band. Raised from (50, 150) uA in
# issue #51: tail and output-branch currents were doubled so the step settles in
# the 97.66 ns phase (SIZING.md). 250 uA is ~0.45 mW per OTA, under half of spec row 13.
IVDD_BAND = (100e-6, 250e-6)
NODES = ("outp", "outn", "xota.cr", "xota.vcn", "xota.vcp", "xota.tail",
         "xota.fa", "xota.fb", "xota.sa", "xota.sb")


def sha256(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def resolve_root(variant, pdk_root):
    if pdk_root:
        return pathlib.Path(pdk_root).expanduser()
    out = subprocess.run(["klt", "pdk", "find", "--pdk", variant, "--format", "json"],
                         capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"REFUSE: klt pdk find failed: {out.stderr.strip()}")
    return pathlib.Path(json.loads(out.stdout)["root"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--record", action="store_true", help="overwrite record.json")
    a = ap.parse_args()
    pin = json.load(open(REPO / "sim/pdk.json"))
    root = resolve_root(pin["variant"], a.pdk_root) / pin["variant"]
    src = root / "SOURCES"
    stamp = src.read_text().strip() if src.exists() else "<missing SOURCES>"
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'", file=sys.stderr)
        return 2
    ng = root / "libs.tech/ngspice"
    lib = ng / "sky130.lib.spice"
    netlist = REPO / "design/ota/ota_fd.spice"
    deck = ((HERE / "ota_fd_op.cir").read_text()
            .replace("{{PDK_LIB}}", f'"{lib}"').replace("{{NETLIST}}", f'"{netlist}"'))
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td) / "deck.cir"
        d.write_text(deck)
        r = subprocess.run(["ngspice", "-b", str(d)], capture_output=True, text=True, cwd=ng)
    log = r.stdout + r.stderr
    vals = {k.lower(): float(v) for k, v in
            re.findall(r"^([@\w.()\[\]]+)\s*=\s*([-+0-9.e]+)\s*$", log, re.M)}
    dev = {}
    for k, v in vals.items():
        m = re.fullmatch(r"@m\.xota\.x(\w+)\.msky130_fd_pr__[np]fet_01v8\[(\w+)\]", k)
        if m:
            dev.setdefault(m.group(1), {})[m.group(2)] = v
    node = {k: vals.get(f"v({k})") for k in NODES}
    ivdd = vals.get("ivdd")
    if r.returncode or ivdd is None or None in node.values() or len(dev) != 23:
        print(log[-2000:], file=sys.stderr)
        return 1
    margins = {n: abs(p["vds"]) - p["vdsat"] for n, p in dev.items()}
    cm = 0.5 * (node["outp"] + node["outn"])
    checks = {
        "output_cm_within_50mV_of_vcm": abs(cm - VCM) <= CM_TOL,
        "outputs_symmetric_within_1mV": abs(node["outp"] - node["outn"]) <= SYM_TOL,
        "all_23_transistors_saturated": all(m > 0 for m in margins.values()),
        "ivdda_within_sanity_band": IVDD_BAND[0] <= ivdd <= IVDD_BAND[1],
    }
    ok = all(checks.values())
    ver = re.search(r"ngspice-\d+", log) or re.search(
        r"ngspice-\d+", subprocess.run(["ngspice", "-v"], capture_output=True, text=True).stdout)
    rec = {
        "fixture": "operating-point smoke check, not a performance claim",
        "result_kind": "simulated (ngspice, transistor-level, single operating point)",
        "conditions": {"corner": "tt", "temp_C": 27, "vdda_V": 1.8, "vcm_V": VCM,
                       "ibias_uA": 5, "vin_diff_V": 0.0},
        "ngspice": ver.group(0) if ver else "unknown",
        "pdk_sources_stamp": stamp,
        "model_sha256": {str(p.relative_to(root)): sha256(p) for p in [
            lib, ng / "corners/tt.spice",
            ng / "capacitors/sky130_fd_pr__model__cap_mim.model.spice",
            root / "libs.ref/sky130_fd_pr/spice/sky130_fd_pr__nfet_01v8__tt.pm3.spice",
            root / "libs.ref/sky130_fd_pr/spice/sky130_fd_pr__pfet_01v8__tt.pm3.spice"]},
        "deck_sha256": sha256(HERE / "ota_fd_op.cir"),
        "netlist_sha256": sha256(netlist),
        "nodes_V": {k: round(v, 4) for k, v in node.items()},
        "output_cm_V": round(cm, 4),
        "ivdda_uA": round(ivdd * 1e6, 2),
        "devices": {n: {"id_uA": round(p["id"] * 1e6, 2), "vds_V": round(p["vds"], 4),
                        "vdsat_V": round(p["vdsat"], 4), "sat_margin_V": round(margins[n], 4),
                        "gm_uS": round(p["gm"] * 1e6, 1)} for n, p in sorted(dev.items())},
        "checks": checks,
        "pass": ok,
    }
    print(json.dumps({k: rec[k] for k in ("output_cm_V", "ivdda_uA", "checks", "pass")}, indent=2))
    if a.record:
        (HERE / "record.json").write_text(json.dumps(rec, indent=2) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

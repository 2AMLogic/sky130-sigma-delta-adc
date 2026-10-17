#!/usr/bin/env python3
"""Analog smoke runner (smoke fixture, not design). See README.md."""
import argparse, hashlib, json, pathlib, re, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
VIN, TOL = 0.6, 0.020  # hold voltage must be within 20 mV of the 0.6 V input


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
    assert re.fullmatch(r"[0-9a-f]{40}", pin["open_pdks_revision"]), "pin is not a 40-hex SHA"
    root = resolve_root(pin["variant"], a.pdk_root) / pin["variant"]
    src = root / "SOURCES"
    stamp = src.read_text().strip() if src.exists() else "<missing SOURCES>"
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'", file=sys.stderr)
        return 2
    ng = root / "libs.tech/ngspice"
    lib = ng / "sky130.lib.spice"
    deck = (HERE / "sampler_smoke.cir").read_text().replace("{{PDK_LIB}}", f'"{lib}"')
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td) / "deck.cir"
        d.write_text(deck)
        r = subprocess.run(["ngspice", "-b", str(d)], capture_output=True, text=True, cwd=ng)
    log = r.stdout + r.stderr
    m = {k: float(v) for k, v in re.findall(r"^(vtrack|vhold)\s*=\s*([-+0-9.e]+)", log, re.M)}
    if r.returncode or set(m) != {"vtrack", "vhold"}:
        print(log[-2000:], file=sys.stderr)
        return 1
    ver = re.search(r"ngspice-\d+", log) or re.search(
        r"ngspice-\d+", subprocess.run(["ngspice", "-v"], capture_output=True, text=True).stdout)
    err = abs(m["vhold"] - VIN)
    ok = err <= TOL
    rec = {
        "fixture": "smoke fixture, not design",
        "result_kind": "simulated (ngspice, transistor-level, single point)",
        "conditions": {"corner": "tt", "temp_C": 27, "vdd_V": 1.8, "vin_V": VIN},
        "ngspice": ver.group(0) if ver else "unknown",
        "pdk_sources_stamp": stamp,
        "model_sha256": {str(p.relative_to(root)): sha256(p) for p in [
            lib, ng / "corners/tt.spice", ng / "capacitors/sky130_fd_pr__model__cap_mim.model.spice",
            root / "libs.ref/sky130_fd_pr/spice/sky130_fd_pr__nfet_01v8__tt.pm3.spice"]},
        "deck_sha256": sha256(HERE / "sampler_smoke.cir"),
        "measured": {"v_track_at_19ns_V": m["vtrack"], "v_hold_at_50ns_V": m["vhold"]},
        "check": {"abs_error_V": err, "tolerance_V": TOL, "pass": ok},
    }
    print(json.dumps(rec, indent=2))
    if ok and a.record:
        (HERE / "record.json").write_text(json.dumps(rec, indent=2) + "\n")
    return 0 if ok else 1


sys.exit(main())

#!/usr/bin/env python3
"""Digital-partition place-and-route: rtl/netlist/decimator_synth.v -> routed GDS.

    python3 layout/digital/run_pnr.py [--pdk-root ROOT] [--check]

Runs `klt place-and-route` on layout/digital/pnr_request.json against the pinned PDK
(sim/pdk.json) and copies the routed GDS, DEF and as-built netlist next to the request.
--check leaves the committed files alone and exits 3 if the fresh GDS differs from the
committed one (raw bytes), else 0. The flow takes tens of minutes (detailed routing).
Exit 2 = PDK tree differs from the pin; 1 = flow failed.
"""
import argparse, hashlib, json, pathlib, shutil, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = {"gds_path": "decimator.gds", "def_path": "decimator.def", "verilog_path": "decimator_pnr.v"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--check", action="store_true", help="compare, do not overwrite")
    a = ap.parse_args()
    pin = json.load(open(REPO / "sim/pdk.json"))
    cmd = ["klt", "place-and-route", str((HERE / "pnr_request.json").relative_to(REPO)),
           "--pdk", pin["variant"], "--format", "json"]
    if a.pdk_root:
        cmd += ["--pdk-root", a.pdk_root]
    # cwd = repo root: a containerised openroad only mounts $PWD, and the netlist is under rtl/
    o = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    if o.returncode:
        print(o.stdout + o.stderr, file=sys.stderr)
        return 1
    rep = json.loads(o.stdout)
    if rep.get("pdk", {}).get("version", pin["sources_stamp"]) != pin["sources_stamp"]:
        print("REFUSE: PDK differs from sim/pdk.json pin", file=sys.stderr)
        return 2
    drift = False
    for key, name in OUT.items():
        v = rep[key]
        src = pathlib.Path(v["path"] if isinstance(v, dict) else v)
        src = src if src.is_absolute() else REPO / src
        dst = HERE / name
        h = hashlib.sha256(src.read_bytes()).hexdigest()
        have = hashlib.sha256(dst.read_bytes()).hexdigest() if dst.exists() else None
        print(f"{name}: fresh {h}{'' if have is None else ' (committed matches)' if have == h else ' (committed DIFFERS)'}")
        if a.check:
            drift |= key == "gds_path" and have != h
        else:
            shutil.copyfile(src, dst)
    return 3 if drift else 0


sys.exit(main())

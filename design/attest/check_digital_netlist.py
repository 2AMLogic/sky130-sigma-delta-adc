#!/usr/bin/env python3
"""Freshness check for rtl/netlist/decimator_synth.v (T1 item 1, digital partition).

    python3 design/attest/check_digital_netlist.py [--pdk-root ROOT] [--update]

Re-runs `klt synthesize` on verification/decimator/synth_request.json (the request the
verification record uses) and exits 0 only if the committed netlist is byte-identical to
the fresh one. Exit 3 = stale netlist; --update rewrites it. Needs the pinned PDK
(sim/pdk.json) and Yosys, so the inventory marks it local_only.
"""
import argparse, hashlib, json, pathlib, shutil, subprocess, sys

REPO = pathlib.Path(__file__).resolve().parents[2]
REQ = REPO / "verification/decimator/synth_request.json"
NETLIST = REPO / "rtl/netlist/decimator_synth.v"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--update", action="store_true", help="overwrite the committed netlist")
    a = ap.parse_args()
    pin = json.load(open(REPO / "sim/pdk.json"))
    cmd = ["klt", "synthesize", str(REQ), "--pdk", pin["variant"], "--format", "json"]
    if a.pdk_root:
        cmd += ["--pdk-root", a.pdk_root]
    o = subprocess.run(cmd, capture_output=True, text=True)
    if o.returncode:
        print(o.stdout + o.stderr, file=sys.stderr)
        return 1
    rep = json.loads(o.stdout)
    fresh = REPO / rep["netlist_path"]["path"]
    assert hashlib.sha256(fresh.read_bytes()).hexdigest() == rep["netlist_sha256"]
    if a.update:
        NETLIST.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fresh, NETLIST)
        print(f"updated {NETLIST.relative_to(REPO)}")
        return 0
    have = hashlib.sha256(NETLIST.read_bytes()).hexdigest() if NETLIST.exists() else None
    if have != rep["netlist_sha256"]:
        print(f"STALE: committed netlist sha256 {have} != fresh {rep['netlist_sha256']}; "
              "run with --update", file=sys.stderr)
        return 3
    print(f"fresh: {rep['netlist_sha256']}")
    return 0


sys.exit(main())

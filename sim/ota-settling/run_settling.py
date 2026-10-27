#!/usr/bin/env python3
"""OTA step-settling runner (simulated, transistor-level). See README.md.

Default: submit request.json (45-point DR-002 grid) through `klt sim`, which
sends it to the batch fleet; never falls back to a local grid.
--probe: one tt/27C/1.8V corner, run locally (bench debugging, no record).
"""
import argparse, json, pathlib, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from settling_common import grid_complete, pdk_stamp, run_klt, sha256, summarize


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--probe", action="store_true", help="one tt/27C/1.8V corner, local, no record")
    ap.add_argument("--record", action="store_true",
                    help="write record.json (refuses to overwrite: records are append-only)")
    ap.add_argument("--record-name", default="record.json",
                    help="record file name, for a re-run after a sizing change (new file)")
    a = ap.parse_args()
    pin = json.load(open(REPO / "sim/pdk.json"))
    root, stamp = pdk_stamp(pin["variant"], a.pdk_root)
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'", file=sys.stderr)
        return 2
    req = json.load(open(HERE / "request.json"))
    out = HERE / a.record_name
    if a.record and out.exists():
        print(f"REFUSE: {out.name} exists; records are append-only (use --record-name)", file=sys.stderr)
        return 2
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ota-settling-"))
    res = run_klt(HERE / "request.json", a.probe, tmp, "ota", HERE / "probe_request.json")
    if res is None:
        return 1
    rep, corners = res
    env = rep.get("environment", {})
    summary = summarize(corners)
    print(json.dumps({"status": rep.get("status"), **summary}, indent=2))
    if a.probe:
        print(json.dumps(corners, indent=2))
        return 0
    if a.record and not grid_complete([corners]):
        return 1
    rec = {
        "fixture": "OTA step-settling bench (issue #48): closed-loop integrate phase, 0.45 V per-side output step",
        "result_kind": "simulated (ngspice, transistor-level netlist of design/ota/ota_fd; not the behavioural model)",
        "conditions": {"ibias_uA": 5, "vcm_V": 0.9, "Cs_pF": 1, "Ci_pF": 2, "Cp_fF": 35, "load_pF_per_side": 1.1,
                       "step_V_per_side_input": 0.9, "phase_ns": 97.66, "sample_after_step_ns": 97.66,
                       "tran": req["analysis"]["args"], "corner_set": "DR-002 full grid, 5 process x 3 T x 3 Vdda"},
        "pass_criterion": "err_phase <= 1e-4 (residual error at 97.66 ns after the step, relative to the "
                          "settled differential step) at every corner, plus the two reference-validity gates",
        "pdk_sources_stamp": stamp,
        "pdk_pin": {"file": "sim/pdk.json", "open_pdks_revision": pin["open_pdks_revision"]},
        "ngspice": env.get("engine_version", "unknown"),
        "klt": subprocess.run(["klt", "--version"], capture_output=True, text=True).stdout.strip(),
        "engine_host": env.get("engine_host"),
        "remote": env.get("remote"),
        "request_sha256": sha256(HERE / "request.json"),
        "deck_sha256": sha256(HERE / "ota_fd_step.cir"),
        "netlist_sha256": sha256(REPO / "design/ota/ota_fd.spice"),
        "summary": summary,
        "corners": corners,
        "pass": rep.get("status") == "pass",
    }
    if a.record:
        out.write_text(json.dumps(rec, indent=2) + "\n")
    return 0 if rec["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

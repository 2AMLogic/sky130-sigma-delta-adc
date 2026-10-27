#!/usr/bin/env python3
"""OTA step-settling runner (simulated, transistor-level). See README.md.

Default: submit request.json (45-point DR-002 grid) through `klt sim`, which
sends it to the batch fleet; never falls back to a local grid.
--probe: one tt/27C/1.8V corner, run locally (bench debugging, no record).
"""
import argparse, hashlib, json, pathlib, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
KEYS = ("vod_pre", "vod_end", "step_dv", "vod_phase", "err_phase", "t_1e4", "t_1e3", "t_1e2",
        "slope_pk", "t_slew", "slew_frac", "end_ripple_rel", "step_err_vs_ideal")


def sha256(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def pdk_stamp(variant, pdk_root):
    if pdk_root:
        root = pathlib.Path(pdk_root).expanduser()
    else:
        out = subprocess.run(["klt", "pdk", "find", "--pdk", variant, "--format", "json"],
                             capture_output=True, text=True)
        if out.returncode:
            sys.exit(f"REFUSE: klt pdk find failed: {out.stderr.strip()}")
        root = pathlib.Path(json.loads(out.stdout)["root"])
    src = root / variant / "SOURCES"
    return root, (src.read_text().strip() if src.exists() else "<missing SOURCES>")


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
    cmd = ["klt", "sim", str(HERE / "request.json"), "--format", "json", "-o", str(tmp / "out")]
    if a.probe:
        req["corners"] = {"process": ["tt"], "supply_v": {"vdda": [1.8]}, "temperature_c": [27]}
        req["backend"] = "local"
        (HERE / "probe_request.json").write_text(json.dumps(req))
        cmd[2] = str(HERE / "probe_request.json")
        cmd += ["--backend", "local"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if a.probe:
        (HERE / "probe_request.json").unlink()
    try:
        rep = json.loads(r.stdout)
        rep["corners"]
    except (ValueError, KeyError):
        print(r.stdout[-2000:] + r.stderr[-2000:], file=sys.stderr)
        return 1
    env = rep.get("environment", {})
    corners = {}
    for c in rep["corners"]:
        m = {x["name"]: x.get("value") for x in c["measurements"]}
        corners[c["corner_id"]] = {"status": c["status"], **{k: m.get(k) for k in KEYS},
                                   "diagnostics": [d["code"] for d in c.get("diagnostics", [])]}
    ok = [k for k, v in corners.items() if v["status"] == "pass"]
    worst = sorted((v["err_phase"], k) for k, v in corners.items() if v["err_phase"] is not None)[-1:]
    summary = {"corner_count": len(corners), "pass": len(ok), "fail": len(corners) - len(ok),
               "worst_err_phase": worst[0] if worst else None}
    print(json.dumps({"status": rep.get("status"), **summary}, indent=2))
    if a.probe:
        print(json.dumps(corners, indent=2))
        return 0
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

#!/usr/bin/env python3
"""Integrator settling runner (simulated, transistor-level). See README.md.

Default: submit request_int1.json and request_int2.json (45-point DR-002 grid
each) through `klt sim`, which sends them to the batch fleet; never falls back
to a local grid.
--probe: one tt/27C/1.8V corner of one variant, run locally (bench debugging,
no record).
"""
import argparse, hashlib, json, pathlib, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
VARIANTS = ("int1", "int2")
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


def run_variant(v, probe, tmpdir):
    req = json.load(open(HERE / f"request_{v}.json"))
    path = HERE / f"request_{v}.json"
    cmd = ["klt", "sim", str(path), "--format", "json", "-o", str(tmpdir / f"out-{v}")]
    if probe:
        req["corners"] = {"process": ["tt"], "supply_v": {"vdda": [1.8]}, "temperature_c": [27]}
        req["backend"] = "local"
        path = HERE / f"probe_request_{v}.json"
        path.write_text(json.dumps(req))
        cmd[2] = str(path)
        cmd += ["--backend", "local"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if probe:
        path.unlink()
    try:
        rep = json.loads(r.stdout)
        rep["corners"]
    except (ValueError, KeyError):
        print(r.stdout[-2000:] + r.stderr[-2000:], file=sys.stderr)
        return None
    corners = {}
    for c in rep["corners"]:
        m = {x["name"]: x.get("value") for x in c["measurements"]}
        corners[c["corner_id"]] = {"status": c["status"], **{k: m.get(k) for k in KEYS},
                                   "diagnostics": [d["code"] for d in c.get("diagnostics", [])]}
    return rep, corners


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--probe", choices=VARIANTS, help="one tt/27C/1.8V corner of a variant, local, no record")
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
    out = HERE / a.record_name
    if a.record and out.exists():
        print(f"REFUSE: {out.name} exists; records are append-only (use --record-name)", file=sys.stderr)
        return 2
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="integrator-settling-"))
    variants = (a.probe,) if a.probe else VARIANTS
    results, env = {}, {}
    for v in variants:
        res = run_variant(v, bool(a.probe), tmp)
        if res is None:
            return 1
        rep, corners = res
        ok = [k for k, c in corners.items() if c["status"] == "pass"]
        worst = sorted((c["err_phase"], k) for k, c in corners.items() if c["err_phase"] is not None)[-1:]
        summary = {"corner_count": len(corners), "pass": len(ok), "fail": len(corners) - len(ok),
                   "worst_err_phase": worst[0] if worst else None}
        print(v, json.dumps({"status": rep.get("status"), **summary}, indent=2))
        e = rep.get("environment", {})
        env[v] = {"ngspice": e.get("engine_version", "unknown"), "engine_host": e.get("engine_host"),
                  "remote": e.get("remote")}
        results[v] = {"summary": summary, "corners": corners, "pass": rep.get("status") == "pass",
                      "request_sha256": sha256(HERE / f"request_{v}.json"),
                      "deck_sha256": sha256(HERE / f"integrator_settling_{v}.cir"), **env[v]}
    if a.probe:
        print(json.dumps(results[a.probe]["corners"], indent=2))
        return 0
    if any(len(r["corners"]) != 45 for r in results.values()):
        print("REFUSE: not all 45 grid points returned; no record written", file=sys.stderr)
        return 1
    rec = {
        "fixture": "Integrator settling bench (issue #53): full integrator cell + ota_fd, integrate phase, 0.45 V per-side output step",
        "result_kind": "simulated (ngspice, transistor-level netlists of design/integrator + design/ota/ota_fd; not the behavioural model)",
        "conditions": {"ibias_uA": 5, "vcm_V": 0.9, "vrefp_V": 1.5, "vrefn_V": 0.3, "vin_diff_V": 0.6, "dn": 1,
                       "phase_ns": 97.66, "sample_after_phi2_midedge_ns": 97.66,
                       "reset": "bench-only ideal 1 ohm switches across Ci until 31 ns (cell has none)",
                       "clocks": "behavioural rail-to-rail on Vdda, 200 ps edges, no non-overlap generator",
                       "loads_per_side": {"int1": "0.1 pF (stage phasing case B)", "int2": "1.1 pF (case A bound)"},
                       "corner_set": "DR-002 full grid, 5 process x 3 T x 3 Vdda"},
        "pass_criterion": "err_phase <= 1e-4 (residual error at 97.66 ns after the phi2 edge, relative to the "
                          "settled differential step) at every corner, plus the two reference-validity gates",
        "pdk_sources_stamp": stamp,
        "pdk_pin": {"file": "sim/pdk.json", "open_pdks_revision": pin["open_pdks_revision"]},
        "klt": subprocess.run(["klt", "--version"], capture_output=True, text=True).stdout.strip(),
        "integrator_netlist_sha256": sha256(REPO / "design/integrator/integrator.spice"),
        "ota_netlist_sha256": sha256(REPO / "design/ota/ota_fd.spice"),
        "variants": results,
        "pass": all(r["pass"] for r in results.values()),
    }
    out.write_text(json.dumps(rec, indent=2) + "\n")
    return 0 if rec["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

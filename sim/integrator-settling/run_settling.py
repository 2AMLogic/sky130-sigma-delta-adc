#!/usr/bin/env python3
"""Integrator settling runner (simulated, transistor-level). See README.md.

Default: submit request_int1.json and request_int2.json (45-point DR-002 grid
each) through `klt sim`, which sends them to the batch fleet; never falls back
to a local grid.
--variant: run one variant only. Each completed variant is saved under
.partials/, so a fleet capacity refusal on one variant does not discard the
other's 45 corners: re-run the missing variant later and --record assembles
record.json from both.
--probe: one tt/27C/1.8V corner of one variant, run locally (bench debugging,
no record).
"""
import argparse, json, pathlib, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from settling_common import (grid_complete, measurements_present, pdk_stamp, run_klt,
                             sha256, summarize)

VARIANTS = ("int1", "int2")
PARTIALS = HERE / ".partials"      # per-variant results, gitignored (see README)
ARTIFACTS = HERE / ".artifacts"    # raw klt report / batch receipt, gitignored


def shas(v):
    return {"request_sha256": sha256(HERE / f"request_{v}.json"),
            "deck_sha256": sha256(HERE / f"integrator_settling_{v}.cir")}


def load_partial(v):
    """A previously-run variant, if it matches the current request and deck."""
    p = PARTIALS / f"{v}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except ValueError:
        return None
    cur = shas(v)
    if {k: d.get(k) for k in cur} != cur:
        print(f"NOTE: ignoring stale .partials/{v}.json (request or deck changed since it ran)",
              file=sys.stderr)
        return None
    return d


def save_partial(v, result):
    PARTIALS.mkdir(exist_ok=True)
    (PARTIALS / f"{v}.json").write_text(json.dumps(result, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--variant", choices=VARIANTS, action="append",
                    help="run only this variant (repeatable); default: both")
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
    if a.probe:
        run = (a.probe,)
    elif a.variant:
        run = tuple(dict.fromkeys(a.variant))
    else:
        run = VARIANTS

    results, failed = {}, []
    for v in VARIANTS if not a.probe else run:
        if v not in run:                       # not asked for this time
            saved = load_partial(v)
            if saved:
                print(f"{v}: reusing .partials/{v}.json ({saved['summary']})")
                results[v] = saved
            continue
        res = run_klt(HERE / f"request_{v}.json", bool(a.probe), tmp, v,
                      HERE / f"probe_request_{v}.json", artifacts_dir=None if a.probe else ARTIFACTS)
        if res is None:
            print(f"{v}: no usable report (see .artifacts/klt-{v}.stderr.txt); "
                  "not falling back to a local grid", file=sys.stderr)
            failed.append(v)
            saved = load_partial(v)
            if saved:
                print(f"{v}: falling back to the saved .partials/{v}.json from an earlier run")
                results[v] = saved
            continue
        rep, corners = res
        summary = summarize(corners)
        print(v, json.dumps({"status": rep.get("status"), **summary}, indent=2))
        e = rep.get("environment", {})
        result = {"summary": summary, "corners": corners, "pass": rep.get("status") == "pass",
                  "ngspice": e.get("engine_version", "unknown"), "engine_host": e.get("engine_host"),
                  "remote": e.get("remote"), **shas(v)}
        results[v] = result
        if not a.probe:
            save_partial(v, result)

    if a.probe:
        print(json.dumps(results[a.probe]["corners"], indent=2))
        return 0
    missing = [v for v in VARIANTS if v not in results]
    if missing:
        print(f"REFUSE: no result for {', '.join(missing)}; no record written. "
              f"Re-run with --variant {missing[0]} when the fleet has capacity.", file=sys.stderr)
        return 1
    corner_sets = [results[v]["corners"] for v in VARIANTS]
    if not grid_complete(corner_sets) or not measurements_present(corner_sets):
        return 1
    if not a.record:
        print("all variants complete; re-run with --record to write the record")
        return 0
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
    print(f"wrote {out.name}: pass={rec['pass']}")
    return 0 if rec["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

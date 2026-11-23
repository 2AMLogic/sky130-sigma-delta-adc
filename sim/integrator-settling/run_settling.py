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
import argparse, json, pathlib, shutil, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
import settling_common as sc
from settling_common import (grid_complete, measurements_present,
                             pdk_stamp, run_klt, sha256, summarize)

VARIANTS = ("int1", "int2")
PARTIALS = HERE / ".partials"      # per-variant results, gitignored (see README)
ARTIFACTS = HERE / ".artifacts"    # raw klt report / batch receipt, gitignored


def shas(v):
    return sc.shas(HERE / f"request_{v}.json", HERE / f"integrator_settling_{v}.cir")


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
    try:
        if a.probe:
            res = sc.run_probe(
                a.probe, tmp, run_klt_fn=run_klt, artifacts_dir=ARTIFACTS,
                request_fn=lambda v: HERE / f"request_{v}.json",
                probe_request_fn=lambda v: HERE / f"probe_request_{v}.json",
                tag_fn=lambda v: v,
                summarize_fn=lambda v, c: summarize(c), shas_fn=shas,
                status_line=True)
            if res is None:
                return 1
            print(json.dumps(res["corners"], indent=2))
            return 0

        run = tuple(dict.fromkeys(a.variant)) if a.variant else VARIANTS
        results = sc.run_variant_set(
            VARIANTS, run, tmp, run_klt_fn=run_klt, artifacts_dir=ARTIFACTS,
            request_fn=lambda v: HERE / f"request_{v}.json",
            probe_request_fn=lambda v: HERE / f"probe_request_{v}.json",
            tag_fn=lambda v: v,
            partial_fn=lambda v: PARTIALS / f"{v}.json",
            reuse_label_fn=lambda v: f".partials/{v}.json",
            shas_fn=shas, summarize_fn=lambda v, c: summarize(c),
            status_line=True)
        if sc.refuse_missing_variants(VARIANTS, results):
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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

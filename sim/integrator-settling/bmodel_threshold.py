#!/usr/bin/env python3
"""Largest B-model `settling_error` that still keeps peak SNDR >= 80 dB.

The transistor-level grid in record.json gives a settling error per PVT point;
this gives the budget to compare it against. Behavioural model B
(`sim/bmodel/model.py`) applies `settling_error` as a gain factor
`(1 - settling_error)` on both integrator inputs, so this extracts the
*linear* tolerance only -- see the limitation note in README.md.

    python3 -I sim/integrator-settling/bmodel_threshold.py            # scan + summary
    python3 -I sim/integrator-settling/bmodel_threshold.py --records  # + canonical run.py records

Writes bmodel-threshold-i107.json (committed evidence). The superseded
bmodel-threshold.json, taken before the issue #107 estimator fix, is kept in the
tree unmodified: every peak_sndr_db in it reads 3.02 dB high. --records additionally runs
`sim/bmodel/run.py` on the bracketing points so a canonical append-only record
lands in sim/bmodel/records/.
"""
import argparse, datetime, json, pathlib, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
BMODEL = REPO / "sim/bmodel"
sys.path.insert(0, str(BMODEL))

import numpy as np  # noqa: E402
import model  # noqa: E402
import run as bmodel_run  # noqa: E402

TARGET_DB = 80.0      # spec: 80 dB in 20 kHz (CLAUDE.md); 70 dB fallback, 90 dB stretch
N_OUT = 2 ** 16       # >= 2^16 for evidence (CLAUDE.md record-length rule)
COARSE = [0.0, 0.1, 0.2, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]
STEP = 0.01           # resolution the threshold is quoted to
# Issue #107 fixed a 3.02 dB ENBW error in sndr_db. Results are append-only, so
# this writes a new file and leaves the superseded bmodel-threshold.json alone.
OUT_NAME = "bmodel-threshold-i107.json"


def peak_sndr(settling_error, n_out=N_OUT):
    p = dict(model.PARAM_DEFAULTS)
    p["settling_error"] = settling_error
    table, best, det, cycles = bmodel_run.sweep(p, n_out)
    return best, det, cycles, table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", action="store_true",
                    help="also write canonical sim/bmodel/records/ entries for the bracketing points")
    ap.add_argument("--record-len", type=int, default=N_OUT)
    a = ap.parse_args()

    scan, det, cycles = [], None, None
    for se in COARSE:
        best, det, cycles, _ = peak_sndr(se, a.record_len)
        scan.append({"settling_error": se, "peak_sndr_db": best["sndr_db"],
                     "amplitude_dbfs": best["amplitude_dbfs"]})
        print(f"  settling_error={se:<5g} peak {best['sndr_db']:6.2f} dB @ {best['amplitude_dbfs']} dBFS")

    ok = [r for r in scan if r["peak_sndr_db"] >= TARGET_DB]
    if not ok:
        sys.exit(f"REFUSE: no scanned settling_error meets {TARGET_DB} dB; nothing to bracket")
    lo = max(r["settling_error"] for r in ok)
    above = [r["settling_error"] for r in scan if r["peak_sndr_db"] < TARGET_DB]
    if not above:
        sys.exit(f"REFUSE: every scanned settling_error meets {TARGET_DB} dB; widen COARSE")
    hi = min(above)

    # Walk the 0.01 grid up from the last passing coarse point.
    print(f"  refining on the {STEP} grid in [{lo}, {hi}]")
    threshold, thr_best = lo, None
    se = round(lo + STEP, 4)
    while se < hi - 1e-12:
        best, det, cycles, _ = peak_sndr(se, a.record_len)
        scan.append({"settling_error": se, "peak_sndr_db": best["sndr_db"],
                     "amplitude_dbfs": best["amplitude_dbfs"]})
        print(f"  settling_error={se:<5g} peak {best['sndr_db']:6.2f} dB @ {best['amplitude_dbfs']} dBFS")
        if best["sndr_db"] >= TARGET_DB:
            threshold, thr_best = se, best
        else:
            break
        se = round(se + STEP, 4)
    if thr_best is None:
        thr_best, det, cycles, _ = peak_sndr(threshold, a.record_len)
    first_fail = min((r["settling_error"] for r in scan
                      if r["settling_error"] > threshold and r["peak_sndr_db"] < TARGET_DB), default=None)

    scan.sort(key=lambda r: r["settling_error"])
    out = {
        "question": f"largest B-model settling_error keeping peak SNDR >= {TARGET_DB} dB",
        "source": "B",
        "result_kind": "simulated (behavioural model B, uncross-checked)",
        "threshold_settling_error": threshold,
        "threshold_peak_sndr_db": thr_best["sndr_db"],
        "threshold_amplitude_dbfs": thr_best["amplitude_dbfs"],
        "first_failing_settling_error": first_fail,
        "resolution": STEP,
        "target_sndr_db": TARGET_DB,
        "record_len": a.record_len,
        "window": det["window"],
        "bin_bw_hz": det["bin_bw_hz"],
        "band_hz": [0, 20000.0],
        "tone_cycles": cycles,
        "model_limitation": (
            "settling_error is a linear gain factor (1 - settling_error) applied equally to both "
            "integrator inputs, constant over the record. It models the signal-independent part of "
            "incomplete settling only. Slew-limited settling is signal-dependent and generates "
            "distortion this parameter cannot represent, so this threshold is NOT a licence to accept "
            "a transistor-level err_phase of the same size."),
        "scan": scan,
        "numpy": np.__version__,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **bmodel_run.git_state(),
        **bmodel_run.code_state(extra=[__file__]),
    }
    (HERE / OUT_NAME).write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nthreshold settling_error = {threshold} "
          f"(peak SNDR {thr_best['sndr_db']:.2f} dB); first failing = {first_fail}")
    print(f"wrote {HERE.name}/{OUT_NAME}")

    if a.records:
        with tempfile.TemporaryDirectory() as td:
            for se in [x for x in (threshold, first_fail) if x is not None]:
                p = dict(model.PARAM_DEFAULTS)
                p["settling_error"] = se
                f = pathlib.Path(td) / f"settling-{se}.json"
                f.write_text(json.dumps(p, indent=2) + "\n")
                r = subprocess.run([sys.executable, "-I", str(BMODEL / "run.py"), "--params", str(f),
                                    "--record-len", str(a.record_len)], text=True)
                if r.returncode:
                    return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())

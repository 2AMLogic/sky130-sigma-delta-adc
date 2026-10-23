#!/usr/bin/env python3
"""Run behavioural model B: amplitude sweep -> peak SNDR -> append-only record.

    python3 -I sim/bmodel/run.py --params sim/bmodel/ideal.json

Needs numpy (sim/bmodel/requirements.txt). Single process, sequential loop.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python -I does not add the script directory

import numpy as np  # noqa: E402

import model  # noqa: E402
import sndr  # noqa: E402

REPO = HERE.parents[1]
RECORDS = HERE / "records"
AMPLITUDES_DBFS = [-60, -50, -40, -30, -24, -18, -14, -12, -10, -8, -7, -6]
CEILING_DBFS = -6  # spec row 11: peak differential input <= 0.5*VREF
WARMUP_OUT = 8     # output samples discarded for loop and filter start-up
LOOP = {"a1": model.C1, "a2": model.C2, "feedback_to_integrator_2": 1.0, "structure": "delaying integrators"}


def run_point(params, amp_dbfs, n_out, cycles):
    amp = 10.0 ** (amp_dbfs / 20.0)
    rng = np.random.default_rng(params["seed"])
    u = model.tone_input(amp, cycles, n_out, sndr.DECIM, WARMUP_OUT, params, rng=rng)
    y = model.modulate(u, params, rng=rng)
    out = sndr.sinc3_decimate(y)
    rec = out[WARMUP_OUT : WARMUP_OUT + n_out]
    return sndr.sndr_db(rec, cycles)


def sweep(params, n_out, amplitudes=AMPLITUDES_DBFS):
    cycles = sndr.odd_cycles(n_out)
    table, det = [], None
    for a in amplitudes:
        val, det = run_point(params, a, n_out, cycles)
        table.append({"amplitude_dbfs": a, "sndr_db": val})
    best = max(table, key=lambda r: r["sndr_db"])
    return table, best, det, cycles


def write_record(path, rec):
    """Exclusive create: an existing record is never overwritten."""
    with open(path, "x") as f:
        json.dump(rec, f, indent=2)
        f.write("\n")


def git_state():
    def g(*a):
        r = subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    return {"git_commit": g("rev-parse", "HEAD"), "git_dirty": bool(g("status", "--porcelain"))}


def build_record(params, params_sha, n_out, table, best, det, cycles):
    return {
        "source": "B",
        "result_kind": "simulated (behavioural model B, uncross-checked)",
        "corner": "none (ideal parameters)" if params == model.PARAM_DEFAULTS else "none (parameters not tied to a corner)",
        "cross_check": "none (ideal parameters)" if params == model.PARAM_DEFAULTS else "none (not cross-checked against T)",
        "record_len": n_out,
        "window": det["window"],
        "bin_bw_hz": det["bin_bw_hz"],
        "band_hz": [0, sndr.BW_HZ],
        "excluded_bins": det["excluded_bins"],
        "band_edge_bin": det["band_edge_bin"],
        "enbw_bins": det["enbw_bins"],
        "tone_cycles": cycles,
        "tone_hz": cycles * sndr.FOUT_HZ / n_out,
        "amplitude_dbfs": best["amplitude_dbfs"],
        "peak_sndr_db": best["sndr_db"],
        "peak_at_sweep_ceiling": best["amplitude_dbfs"] >= CEILING_DBFS,
        "sweep": table,
        "oversampling_ratio": 128,
        "fs_hz": model.FS_HZ,
        "fout_hz": sndr.FOUT_HZ,
        "decimation": {"filter": "sinc^3 float64", "factor": sndr.DECIM},
        "modulator_clocks": n_out * sndr.DECIM,
        "warmup_clocks_discarded": WARMUP_OUT * sndr.DECIM,
        "loop": LOOP,
        "params": params,
        "params_sha256": params_sha,
        "numpy": np.__version__,
        **git_state(),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--params", required=True, help="JSON parameter file (see ideal.json)")
    ap.add_argument("--record-len", type=int, default=2**16, help="output samples (power of two, >= 2^16 for evidence)")
    ap.add_argument("--out-dir", default=str(RECORDS))
    a = ap.parse_args(argv)
    if a.record_len & (a.record_len - 1):
        ap.error("--record-len must be a power of two")
    params = model.load_params(a.params)
    canon = json.dumps(params, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(canon.encode()).hexdigest()
    table, best, det, cycles = sweep(params, a.record_len)
    rec = build_record(params, sha, a.record_len, table, best, det, cycles)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = pathlib.Path(a.out_dir) / f"{ts}-{sha[:8]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_record(path, rec)
    print(f"B peak SNDR {best['sndr_db']:.2f} dB at {best['amplitude_dbfs']} dBFS "
          f"(N={a.record_len}, bin {det['bin_bw_hz']:.3f} Hz) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

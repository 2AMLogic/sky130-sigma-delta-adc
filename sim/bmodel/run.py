#!/usr/bin/env python3
"""Run behavioural model B: amplitude sweep -> peak SNDR -> append-only record.

    python3 -I sim/bmodel/run.py --params sim/bmodel/ideal.json
    python3 -I sim/bmodel/run.py --corner-file sim/bmodel/corners/tt-1.800V-27C.json \
        --xcheck-record sim/bmodel/xcheck-record.json
    python3 -I sim/bmodel/run.py --xcheck \
        --corner-file sim/bmodel/corners/tt-1.800V-27C.json \
        --t-samples sim/modulator-tran/samples/tt-1.800V-27C.json \
        --out /tmp/b-tt.json

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
FS_VOLTS = 1.2     # 1 model-B unit = the 1.2 V differential reference


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


# The files whose contents determine a B-model number. git_commit/git_dirty
# cannot identify them: a record is written before the commit that contains it,
# so the tree is dirty on every run (issue #110).
CODE_FILES = (HERE / "model.py", HERE / "sndr.py", HERE / "run.py")


def _sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def code_state(extra=()):
    """Content hash of the code that determines the result.

    Returns {"code_sha256": {repo-relative path: sha256 of the file bytes}}
    for the three B-model source files plus any `extra` paths, so a caller that
    adds its own model code (or its own file) stamps it the same way.
    """
    paths = [pathlib.Path(p).resolve() for p in (*CODE_FILES, *extra)]
    return {"code_sha256": {str(p.relative_to(REPO)): _sha256(p) for p in paths}}


def build_record(params, params_sha, n_out, table, best, det, cycles,
                 corner=None, xcheck_path=None):
    ideal = params == model.PARAM_DEFAULTS
    rec = {
        "source": "B",
        "result_kind": ("simulated (behavioural model B, uncross-checked)"
                        if ideal else
                        "simulated (behavioural model B loaded with T-extracted corner parameters)"),
        "corner": ("none (ideal parameters)" if ideal else
                   "none (parameters not tied to a corner)" if corner is None else
                   corner["corner_id"]),
        "cross_check": ("none (ideal parameters)" if ideal else
                        cross_check_status(xcheck_path, corner["corner_id"]) if corner else
                        "none (not cross-checked against T)"),
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
        **code_state(),
    }
    if corner is not None:
        rec["corner_params_file"] = {
            "path": str(pathlib.Path(corner["_path"]).relative_to(REPO))
                    if "_path" in corner else None,
            "sha256": "sha256:" + _sha256(corner["_path"]) if "_path" in corner else None,
            "sources": corner["sources"],
            "no_t_source": corner["no_t_source"],
        }
    return rec


def load_corner(path):
    """Load one sim/bmodel/corners/<anchor>.json parameter file.

    Validates the wrapper structure, not just the parameters: every model-B
    parameter must be covered by a T source ("sources") or explicitly listed
    under "no_t_source" -- a parameter with neither is an error, never a
    silent default (issue #128). Each source's record must exist and hash to
    the sha256 the corner file names, so a T record edited after the corner
    file was written fails loudly here.
    """
    with open(path) as f:
        doc = json.load(f)
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: corner file must be a JSON object")
    for key in ("schema", "corner_id", "params", "sources", "no_t_source"):
        if key not in doc:
            raise ValueError(f"{path}: corner file missing required key {key!r}")
    params = model.validate_params(doc["params"])
    covered = set(doc["sources"]) | set(doc["no_t_source"])
    uncovered = sorted(set(params) - covered - {"seed"})
    if uncovered:
        raise ValueError(f"{path}: parameter(s) {uncovered} have neither a T "
                         "source nor a no_t_source entry")
    stale = []
    for pname, s in doc["sources"].items():
        rec = REPO / s["record"]
        if not rec.is_file():
            stale.append(f"{pname}: record {s['record']} does not exist")
            continue
        got = "sha256:" + hashlib.sha256(rec.read_bytes()).hexdigest()
        if got != s.get("record_sha256"):
            stale.append(f"{pname}: {s['record']} hashes to {got[:19]}..., "
                         f"corner file names {str(s.get('record_sha256'))[:19]}...")
    if stale:
        raise ValueError(f"{path}: stale T record binding: " + "; ".join(stale))
    return doc


def cross_check_status(xcheck_path, corner_id):
    """The committed cross-check verdict for `corner_id`, or the honest
    absence statement. Read from the record, never hand-typed."""
    if xcheck_path is None:
        return "none (no cross-check record passed; DR-001 cross-check not run)"
    with open(xcheck_path) as f:
        rec = json.load(f)
    for entry in rec.get("corners", []):
        if entry.get("corner_id") == corner_id:
            return entry.get("cross_check_status",
                             "unresolved (corner present in the cross-check record without a status)")
    return "none (corner absent from the cross-check record)"


def run_xcheck_side(corner_path, t_samples_path, out_path):
    """Cross-check mode: run B on the T transient's own input sequence.

    Loads the corner parameter file and the committed per-clock T samples
    (sim/modulator-tran/samples/), feeds B the same 1024 input samples
    (u_diff_v / FS_VOLTS, same clock count, no resampling) from B's own zero
    initial state, and writes the B-side per-clock samples for xcheck.py to
    compare. Nothing here reads the T bitstream: the comparison and the
    record are xcheck.py's, so this mode cannot tune itself toward the
    answer.
    """
    corner = load_corner(corner_path)
    with open(t_samples_path) as f:
        t = json.load(f)
    n = int(t["n_clocks"])
    u = np.asarray(t["u_diff_v"], dtype=np.float64) / FS_VOLTS
    if len(u) != n:
        raise ValueError(f"{t_samples_path}: n_clocks {n} but {len(u)} input samples")
    params = corner["params"]
    y, x1, x2 = model.modulate_with_states(u, params)
    doc = {
        "source": "B (cross-check side)",
        "result_kind": "simulated (behavioural model B on the transistor-level transient's committed input sequence)",
        "corner_id": corner["corner_id"],
        "corner_params_file": str(pathlib.Path(corner_path).resolve().relative_to(REPO)),
        "corner_params_sha256": "sha256:" + _sha256(corner_path),
        "t_samples_file": str(pathlib.Path(t_samples_path).resolve().relative_to(REPO)),
        "t_samples_sha256": "sha256:" + _sha256(t_samples_path),
        "n_clocks": n,
        "fs_hz": model.FS_HZ,
        "fs_volts": FS_VOLTS,
        "initial_state": "zero (model B's own start-up; the T window itself starts 64 clocks in -- both facts recorded, sample-wise comparison is reported-not-gated in xcheck.py)",
        "input": "u[n] = u_diff_v[n] / 1.2 from the T samples file, unmodified",
        "y": [int(v) for v in y],
        "x1_fs": [round(float(v), 9) for v in x1],
        "x2_fs": [round(float(v), 9) for v in x2],
        "numpy": np.__version__,
        **git_state(),
        **code_state(),
    }
    write_record(out_path, doc)
    print(f"B cross-check side: {n} clocks -> {out_path}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--params", help="JSON parameter file (see ideal.json)")
    ap.add_argument("--corner-file", help="sim/bmodel/corners/<anchor>.json parameter file")
    ap.add_argument("--xcheck-record", help="cross-check record consulted for the corner's cross-check status")
    ap.add_argument("--record-len", type=int, default=2**16, help="output samples (power of two, >= 2^16 for evidence)")
    ap.add_argument("--out-dir", default=str(RECORDS))
    ap.add_argument("--xcheck", action="store_true",
                    help="cross-check mode: run B on the T transient's input sequence (--corner-file, --t-samples, --out)")
    ap.add_argument("--t-samples", help="sim/modulator-tran/samples/<anchor>.json (xcheck mode)")
    ap.add_argument("--out", help="output path for the B-side samples (xcheck mode)")
    a = ap.parse_args(argv)

    if a.xcheck:
        if not (a.corner_file and a.t_samples and a.out):
            ap.error("--xcheck needs --corner-file, --t-samples and --out")
        return run_xcheck_side(a.corner_file, a.t_samples, a.out)

    if bool(a.params) == bool(a.corner_file):
        ap.error("give exactly one of --params or --corner-file")
    if a.record_len & (a.record_len - 1):
        ap.error("--record-len must be a power of two")
    corner = load_corner(a.corner_file) if a.corner_file else None
    if corner is not None:
        corner["_path"] = str(pathlib.Path(a.corner_file).resolve())
    params = corner["params"] if corner else model.load_params(a.params)
    canon = json.dumps(params, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(canon.encode()).hexdigest()
    table, best, det, cycles = sweep(params, a.record_len)
    rec = build_record(params, sha, a.record_len, table, best, det, cycles,
                       corner=corner, xcheck_path=a.xcheck_record)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = pathlib.Path(a.out_dir) / f"{ts}-{sha[:8]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_record(path, rec)
    print(f"B peak SNDR {best['sndr_db']:.2f} dB at {best['amplitude_dbfs']} dBFS "
          f"(N={a.record_len}, bin {det['bin_bw_hz']:.3f} Hz) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

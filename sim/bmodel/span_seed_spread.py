#!/usr/bin/env python3
"""Seed-realisation spread of the span_10pct leg's B-side statistics (#311).

    python3 -I sim/bmodel/span_seed_spread.py

The DR-001 cross-check gates on |p2p_B - p2p_T| / p2p_T <= 0.10 for both
integrators (sim/bmodel/xcheck.py, SPAN_REL_LIMIT). The B side's peak-to-peak
is itself a draw from the model's seeded kT/C + jitter noise, so a
near-threshold span verdict is not separable from the seed draw unless the
draw's own spread is recorded beside it. This script characterises that
spread: at every DR-002 anchor, on the committed 1024-clock input sequences,
it holds everything fixed -- the corner file's parameters, the estimator, the
window -- and varies ONLY the model's seed, reporting min/max/spread of
ptp(x1), ptp(x2) and duty, plus two alternative statistics (the
1st/99th-percentile span and the RMS) whose seed behaviour tests the
extreme-order-statistic hypothesis on why the p2p spread is so wide.

Nothing here changes the gated statistic, SPAN_REL_LIMIT, or any DR-001 text:
the gate values are quoted, never modified (ratified spec; a change is a
decision record, out of scope for this record). The output is one append-only
record under sim/bmodel/records/ naming the record length, window, seed list
and the side that produced every number: the B-side behavioural model
(model.modulate_with_states); no transistor-level run is involved anywhere.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python -I does not add the script directory

import numpy as np  # noqa: E402

import model  # noqa: E402
import run as brun  # noqa: E402
from xcheck import DUTY_LIMIT, SPAN_REL_LIMIT, rel_path, sha256  # noqa: E402

REPO = HERE.parents[1]
SEED_COUNT = 20                # issue #311 asks for >= 20 seed values
SEEDS = list(range(1, SEED_COUNT + 1))
STAT_KEYS = ("ptp_x1_fs", "ptp_x2_fs", "p1p99_x1_fs", "p1p99_x2_fs",
             "rms_x1_fs", "rms_x2_fs", "duty")
INTEGRATORS = (("o1", "ptp_x1_fs", "p1p99_x1_fs", "rms_x1_fs"),
               ("o2", "ptp_x2_fs", "p1p99_x2_fs", "rms_x2_fs"))
WINDOW_NOTE = ("Blackman-Harris 4-term (the cross-check's spectral window, "
               "named per the record contract; span, percentile span, RMS and "
               "duty are time-domain statistics and do not apply it)")
STAT_DEFINITIONS = {
    "ptp_x*_fs": "peak-to-peak of the integrator state, max - min: the gated "
                 "statistic, verbatim as xcheck.py waveform_stats computes it",
    "p1p99_x*_fs": "1st/99th-percentile span of the integrator state "
                   "(numpy.percentile linear interpolation): alternative "
                   "statistic, robust to the extreme order statistic",
    "rms_x*_fs": "sqrt(mean(x^2)) of the integrator state: alternative "
                 "variance-like statistic",
    "duty": "mean of the +/-1 bitstream: the duty_0p05 leg's statistic",
    "spread": "(max - min) / midrange, midrange = (max + min) / 2, over the "
              "seed draw -- the definition behind issue #311's tt figures "
              "(o1 5.77 %, o2 13.39 % on the long input)",
}
LONG_INPUTS_DIR = HERE / "xcheck-sides-long"


def anchor_inputs(corner_path, b_side_dir):
    """Resolve one anchor's inputs: corner file, committed B-side file, and
    the committed T record it names for the input sequence. Loud on any
    missing piece, never skipped (issue #128 convention)."""
    corner = brun.load_corner(corner_path)
    b_path = pathlib.Path(b_side_dir) / f"bx-{corner['sample_slug']}.json"
    if not b_path.is_file():
        raise FileNotFoundError(f"no committed B-side samples at {b_path}")
    with open(b_path) as f:
        b = json.load(f)
    t_path = REPO / b["t_samples_file"]
    if not t_path.is_file():
        raise FileNotFoundError(f"no committed T record at {t_path} "
                                f"(named by {b_path})")
    with open(t_path) as f:
        t = json.load(f)
    u = np.asarray(t["u_diff_v"], dtype=np.float64) / float(b["fs_volts"])
    n = int(t["n_clocks"])
    if u.size != n:
        raise ValueError(f"{t_path}: u_diff_v has {u.size} samples, "
                         f"n_clocks {n}")
    return {"corner": corner, "corner_path": pathlib.Path(corner_path),
            "b_path": b_path, "t_path": t_path, "t": t, "u": u,
            "n_clocks": n, "fs_volts": float(b["fs_volts"])}


def seed_rows(u, base_params, seeds):
    """One row per seed: everything but seed held fixed, per seed_values."""
    rows = []
    for sd in seeds:
        p = model.validate_params({**base_params, "seed": int(sd)})
        y, x1, x2 = model.modulate_with_states(u, p)
        rows.append({
            "seed": int(sd),
            "ptp_x1_fs": float(np.ptp(x1)),
            "ptp_x2_fs": float(np.ptp(x2)),
            "p1p99_x1_fs": float(np.percentile(x1, 99) - np.percentile(x1, 1)),
            "p1p99_x2_fs": float(np.percentile(x2, 99) - np.percentile(x2, 1)),
            "rms_x1_fs": float(np.sqrt(np.mean(np.square(x1)))),
            "rms_x2_fs": float(np.sqrt(np.mean(np.square(x2)))),
            "duty": float(np.mean(y)),
        })
    return rows


def spread_of(values):
    """min/max/spread over the seed draw; spread = (max - min) / midrange."""
    lo, hi = float(min(values)), float(max(values))
    mid = 0.5 * (lo + hi)
    return {"min": lo, "max": hi, "spread_abs": hi - lo,
            "spread_rel": (hi - lo) / mid if mid != 0.0 else None}


def gate_statement(key, sp):
    """A spread block plus the explicit exceeds-gate statement the record
    contract asks for (#311 AC: a near-threshold span verdict must be
    readable with its error bar). The gates are quoted, never changed."""
    st = dict(sp)
    if key.startswith("ptp_"):
        st["exceeds_span_10pct_gate"] = bool(
            st["spread_rel"] is not None and st["spread_rel"] > SPAN_REL_LIMIT)
        st["gate_rel"] = SPAN_REL_LIMIT
    elif key == "duty":
        st["exceeds_duty_0p05_gate"] = bool(st["spread_abs"] > DUTY_LIMIT)
        st["gate_abs"] = DUTY_LIMIT
    return st


def verdict_range_for(rows, key, t_p2p):
    """What the span gate would read across the seed draw, the committed T
    peak-to-peak as reference."""
    rels = [abs(r[key] - t_p2p) / t_p2p for r in rows]
    return {"min_rel": float(min(rels)), "max_rel": float(max(rels)),
            "n_seeds_within_gate": sum(1 for v in rels
                                       if v <= SPAN_REL_LIMIT),
            "n_seeds": len(rels)}


def summarize_anchor(corner_path, b_side_dir, seeds):
    """Full per-anchor result: rows, spreads, gate statements, verdict range."""
    inp = anchor_inputs(corner_path, b_side_dir)
    corner, t = inp["corner"], inp["t"]
    rows = seed_rows(inp["u"], corner["params"], seeds)
    spread = {k: gate_statement(k, spread_of([r[k] for r in rows]))
              for k in STAT_KEYS}
    fv = inp["fs_volts"]
    t_p2p = {"o1": float(np.ptp(np.asarray(t["o1d_v"], dtype=np.float64) / fv)),
             "o2": float(np.ptp(np.asarray(t["o2d_v"], dtype=np.float64) / fv))}
    return {
        "corner_id": corner["corner_id"],
        "corner_params_file": rel_path(inp["corner_path"]),
        "corner_params_sha256": sha256(inp["corner_path"]),
        "b_side_file": rel_path(inp["b_path"]),
        "b_side_sha256": sha256(inp["b_path"]),
        "t_samples_file": rel_path(inp["t_path"]),
        "t_samples_sha256": sha256(inp["t_path"]),
        "n_clocks": inp["n_clocks"],
        "bin_bw_hz": model.FS_HZ / inp["n_clocks"],
        "seed_values": rows,
        "spread": spread,
        "span_verdict_range_against_committed_t": {
            "o1": verdict_range_for(rows, "ptp_x1_fs", t_p2p["o1"]),
            "o2": verdict_range_for(rows, "ptp_x2_fs", t_p2p["o2"]),
            "what": ("the range of |p2p_B - p2p_T| / p2p_T the span_10pct "
                     "gate would read across this seed draw, the committed T "
                     "peak-to-peak as reference; a range straddling the "
                     "0.10 limit means the leg's verdict is a property of "
                     "the seed draw, not of the model"),
        },
    }


def input_sets():
    """The committed 1024-clock set always; the long-record set repeats the
    same driver once #306 lands its inputs on main."""
    sets = [{"name": "committed-1024-clock",
             "b_side_dir": HERE / "xcheck-sides"}]
    if LONG_INPUTS_DIR.is_dir():
        sets.append({"name": "long-record", "b_side_dir": LONG_INPUTS_DIR})
    return sets


def mechanism_summary(anchors):
    """Test the extreme-order-statistic hypothesis (#311): a peak-to-peak is
    set by the window's extreme noise excursion, so its seed-to-seed variance
    falls with record length far slower than a central statistic's would."""
    out = {}
    for integ, ptp_k, p1p99_k, rms_k in INTEGRATORS:
        per = {}
        for k in (ptp_k, p1p99_k, rms_k):
            rels = [a["spread"][k]["spread_rel"] for a in anchors
                    if a["spread"][k]["spread_rel"] is not None]
            per[k] = {"min": min(rels), "max": max(rels)}
        out[integ] = {"spread_of": per,
                      "rms_tighter_than_p2p": bool(per[rms_k]["max"]
                                                   < per[ptp_k]["min"]),
                      "p1p99_tighter_than_p2p": bool(per[p1p99_k]["max"]
                                                     < per[ptp_k]["min"])}
    keys = [i for i, *_ in INTEGRATORS]
    rms_all = all(out[i]["rms_tighter_than_p2p"] for i in keys)
    p1p99_all = all(out[i]["p1p99_tighter_than_p2p"] for i in keys)
    out["hypothesis"] = ("a peak-to-peak statistic is dominated by the "
                         "extreme order statistic of the seeded noise, so "
                         "its realisation spread falls far more slowly with "
                         "record length than a variance-like statistic's "
                         "(issue #311, unverified hypothesis)")
    if rms_all and p1p99_all:
        out["finding"] = ("at every anchor and both integrators both "
                          "alternative statistics have strictly smaller "
                          "seed spread than the peak-to-peak: consistent "
                          "with the extreme-order-statistic hypothesis. The "
                          "gated statistic is NOT changed here; if this "
                          "evidence motivates a different one, that is a "
                          "DR-001 decision record (issue #311 out of "
                          "scope).")
    elif rms_all:
        out["finding"] = ("the RMS is strictly tighter than the "
                          "peak-to-peak at every anchor and both "
                          "integrators, consistent with the "
                          "extreme-order-statistic hypothesis for a "
                          "variance-like statistic; the 1st/99th-percentile "
                          "span is NOT uniformly tighter -- at these record "
                          "lengths its tails still rest on ~1 % of the "
                          "window, so it inherits part of the same "
                          "exposure. The gated statistic is NOT changed "
                          "here; if this evidence motivates a different "
                          "one, that is a DR-001 decision record (issue "
                          "#311 out of scope).")
    else:
        out["finding"] = ("NOT uniformly consistent with the "
                          "extreme-order-statistic hypothesis at these "
                          "record lengths: see spread_of above for the "
                          "anchor-level spreads (issue #311 allows a "
                          "measured refutation).")
    return out


def definition_sha(entries, seeds):
    """Content-address the sweep definition (inputs, seeds, statistics) for
    the record filename, the way run.py content-addresses its params."""
    canon = json.dumps({
        "input_sets": [{"name": name,
                        "anchors": [[a["corner_params_sha256"],
                                     a["b_side_sha256"],
                                     a["t_samples_sha256"]]
                                    for a in anchors]}
                       for name, anchors in entries],
        "seeds": list(seeds),
        "statistics": list(STAT_KEYS),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def build_record(entries, seeds):
    """The append-only record. Names record length, window, seed list, and
    the producing side on every number (DR-001 item 5; issue #311 AC)."""
    sets_payload = []
    mech = {}
    for name, anchors in entries:
        n_set = sorted({a["n_clocks"] for a in anchors})
        sets_payload.append({
            "name": name,
            "n_clocks": n_set,
            "bin_bw_hz": [model.FS_HZ / n for n in n_set],
            "b_side_dir": rel_path(HERE / "xcheck-sides"
                                   if name == "committed-1024-clock"
                                   else LONG_INPUTS_DIR),
            "anchors": anchors,
        })
        mech[name] = mechanism_summary(anchors)
    long_done = any(name == "long-record" for name, _ in entries)
    long_leg = {
        "status": "swept (long-record inputs present on main)" if long_done
        else "pending #306",
        "why": ("the long-record inputs (sim/bmodel/xcheck-sides-long/) and "
                "the long cross-check record come from PR #306, which had "
                "not merged onto main when this record was written; the "
                "filer's tt o2 13.39 % figure was on that long input. The "
                "same sweep repeats verbatim on the long set once #306 "
                "lands -- the committed 1024-clock numbers below are the "
                "form computable on main today.")
        if not long_done else
        ("swept from sim/bmodel/xcheck-sides-long/ with the identical "
         "driver, seeds and statistics"),
    }
    return {
        "source": "B (seed-realisation spread characterisation)",
        "result_kind": ("simulated (behavioural model B with T-extracted "
                        "corner parameters; only the model's seed parameter "
                        "was varied)"),
        "method_basis": "issue #311; the DR-001 item 3 span_10pct leg "
                        "(sim/bmodel/xcheck.py SPAN_REL_LIMIT)",
        "which_side": ("B-side behavioural model (model.modulate_with_states); "
                       "no transistor-level simulation is involved anywhere "
                       "in this record"),
        "what_varied": ("only model parameter 'seed', over the seed list "
                        "below; every other parameter is exactly the corner "
                        "file's value and the input sequence is the "
                        "committed T record's u_diff_v, unmodified"),
        "window": WINDOW_NOTE,
        "seeds": list(seeds),
        "statistics": STAT_DEFINITIONS,
        "gates_quoted_not_changed": {
            "span_10pct": ("xcheck.py SPAN_REL_LIMIT = %.2f, quoted, not "
                           "modified; changing the gated statistic or the "
                           "limit is a DR-001 decision record (issue #311 "
                           "out of scope)" % SPAN_REL_LIMIT),
            "duty_0p05": ("xcheck.py DUTY_LIMIT = %.2f (absolute); the duty "
                          "leg's seed spread is recorded beside it for "
                          "comparison" % DUTY_LIMIT),
        },
        "input_sets": sets_payload,
        "long_record_leg": long_leg,
        "mechanism_check": mech,
        "record_len_note": ("per DR-001 item 5: record length (per anchor, "
                            "under input_sets[].n_clocks), window, bin "
                            "bandwidth and the producing side are named on "
                            "every number; every number here is simulated, "
                            "nothing measured"),
        "numpy": np.__version__,
        **brun.git_state(),
        **brun.code_state(extra=(HERE / "span_seed_spread.py",)),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=SEED_COUNT,
                    help="sweep seeds 1..N (default %d; issue #311 asks "
                         ">= 20)" % SEED_COUNT)
    ap.add_argument("--record-dir", default=str(HERE / "records"))
    ap.add_argument("--record", default=None,
                    help="explicit output path (default "
                         "records/<UTC>-<def8>.json, exclusive create)")
    a = ap.parse_args(argv)
    seeds = list(range(1, a.seeds + 1))

    entries = []
    for st in input_sets():
        corners = sorted(HERE.glob("corners/*.json"))
        anchors = [summarize_anchor(c, st["b_side_dir"], seeds)
                   for c in corners]
        entries.append((st["name"], anchors))
    rec = build_record(entries, seeds)

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = (pathlib.Path(a.record) if a.record else
            pathlib.Path(a.record_dir) / f"{ts}-{definition_sha(entries, seeds)[:8]}.json")
    brun.write_record(path, rec)

    for name, anchors in entries:
        print(f"input set {name}:")
        for anch in anchors:
            sp = anch["spread"]
            vr = anch["span_verdict_range_against_committed_t"]
            print(f"  {anch['corner_id']}: n={anch['n_clocks']} "
                  f"ptp o1 {sp['ptp_x1_fs']['spread_rel'] * 100:.2f} % "
                  f"o2 {sp['ptp_x2_fs']['spread_rel'] * 100:.2f} % "
                  f"(gate {SPAN_REL_LIMIT * 100:.0f} %; "
                  f"o1 {'EXCEEDS' if sp['ptp_x1_fs']['exceeds_span_10pct_gate'] else 'within'}"
                  f", o2 {'EXCEEDS' if sp['ptp_x2_fs']['exceeds_span_10pct_gate'] else 'within'}"
                  f") | verdict range o1 {vr['o1']['min_rel']:.3f}..{vr['o1']['max_rel']:.3f}"
                  f" o2 {vr['o2']['min_rel']:.3f}..{vr['o2']['max_rel']:.3f}"
                  f" | duty spread {sp['duty']['spread_abs']:.5f} "
                  f"(gate {DUTY_LIMIT})")
    for name, anchors in entries:
        print(f"mechanism [{name}]: "
              f"{mechanism_summary(anchors)['finding']}")
    print(f"record -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Short full-modulator transient runner (simulated, transistor-level).

See README.md. Submits request.json (DR-002 anchor set, 7 points) through
`klt sim` to the batch fleet; never falls back to a local grid.

    python3 -I sim/modulator-tran/run_tran.py --probe    # 1 local corner, no record
    python3 -I sim/modulator-tran/run_tran.py            # the 7 anchors
    python3 -I sim/modulator-tran/run_tran.py --record   # write record.json + samples/

A completed run is saved under .partials/, so --record can be run later without
re-simulating. A run requested in this invocation is NEVER served from
.partials/: a failed submit must not be reported as a result (issue #94's rule,
as in run_settling.py and run_ci.py).
"""
import argparse
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from settling_common import pdk_stamp, run_klt, sha256  # noqa: E402

sys.path.insert(0, str(HERE))
import make_request as mk  # noqa: E402

PARTIALS = HERE / ".partials"     # gitignored
ARTIFACTS = HERE / ".artifacts"   # raw klt report / batch receipt, gitignored
# klt's own scratch (shard map, per-job receipts), gitignored under .partials.
# It is NOT a fresh mkdtemp on purpose: --resume re-launches only the shards a
# previous run left unfinished, and the shard map it reads lives here.
SCRATCH = PARTIALS / "klt-run"
SAMPLES = HERE / "samples"        # committed per-anchor per-clock samples

# The scalar measurements carried into the per-corner summary. The per-clock
# sample cards (sb_/s1_/s2_) are read straight off the report instead: there
# are 3*N_REC of them and they belong in the samples file, not the summary.
KEYS = ("vdda_v", "p_ana", "p_vdda", "p_ref", "p_vcm",
        "e_vdda", "e_vrefp", "e_vrefn", "e_vvcm",
        "o1_max", "o1_min", "o1_swing_pp", "o2_max", "o2_min", "o2_swing_pp",
        "o1p_max", "o1p_min", "o2p_max", "o2p_min",
        "phi1_edges", "bs_edges", "bs_mean")

# The two independent routes to average power (a cycle-aligned time-weighted
# mean of v*i, and klt's own integration of the same source's energy over the
# same window) must agree to this relative tolerance. They are computed by
# different code on different vectors, so a disagreement means one of them is
# not measuring what the record says it measures.
POWER_ROUTE_TOL = 1e-3

NETLISTS = {
    "modulator_netlist_sha256": "design/modulator/modulator.spice",
    "ota_netlist_sha256": "design/ota/ota_fd.spice",
    "comparator_netlist_sha256": "design/modulator/comparator/comparator.spice",
}


def shas():
    return {"request_sha256": sha256(HERE / "request.json"),
            "deck_sha256": sha256(HERE / mk.DECK)}


def corner_slug(c):
    """Stable file name for a corner: process, Vdda, temperature.

    `m` rather than a minus sign below zero, so the name never starts a shell
    option or collides with the field separator.
    """
    t = c["temperature_c"]
    temp = f"m{abs(t):g}" if t < 0 else f"{t:g}"
    return f"{c['process']}-{c['supply_v']['vdda']:.3f}V-{temp}C"


def measurement_map(corner):
    return {m["name"]: m for m in corner["measurements"]}


# ------------------------------------------------------------ record gates --
def anchors_complete(corners, expected=len(mk.ANCHOR_POINTS)):
    """True if the report holds one entry per DR-002 anchor; else print REFUSE."""
    if len(corners) != expected:
        print(f"REFUSE: {len(corners)} of {expected} anchor points returned; "
              "no record written", file=sys.stderr)
        return False
    return True


def scalars_present(corners):
    """True if every anchor produced every scalar measurement.

    A fleet job that dies still returns one entry per point, so a count gate
    alone lets an empty grid become a "record". A corner that merely misses a
    limit still produces values, so requiring a non-null value everywhere
    separates "simulated and failing" from "never simulated".
    """
    bad = []
    for cid, c in sorted(corners.items()):
        for k in KEYS:
            if c.get(k) is None:
                bad.append((cid, k))
    if bad:
        names = ", ".join(f"{cid}:{k}" for cid, k in bad[:8])
        print(f"REFUSE: {len(bad)} missing scalar measurement(s) ({names}"
              f"{', ...' if len(bad) > 8 else ''}); nothing was simulated "
              "there, so no record is written", file=sys.stderr)
        return False
    return True


def samples_present(samples, n_rec=None):
    """True if every anchor returned a full per-clock sample set."""
    n_rec = mk.N_REC if n_rec is None else n_rec
    bad = [(cid, len(s["bs_v"]), len(s["o1d_v"]), len(s["o2d_v"]))
           for cid, s in sorted(samples.items())
           if not (len(s["bs_v"]) == len(s["o1d_v"]) == len(s["o2d_v"]) == n_rec)]
    if bad:
        print(f"REFUSE: {len(bad)} anchor(s) returned an incomplete per-clock "
              f"sample set (want {n_rec} of each): {bad[:4]}; no record written",
              file=sys.stderr)
        return False
    return True


def clock_ran_at_fs(corners, n_rec=None):
    """True if phi1 rose exactly once per recorded clock at every anchor.

    This is the row 5 admission gate, not a limit restatement: a record whose
    clock generator did not run for the whole window is not a record of
    N_REC modulator clocks whatever else it measured.
    """
    n_rec = mk.N_REC if n_rec is None else n_rec
    bad = {cid: c["phi1_edges"] for cid, c in sorted(corners.items())
           if c["phi1_edges"] != n_rec}
    if bad:
        print(f"REFUSE: phi1 did not rise exactly {n_rec} times in the record "
              f"window at {bad}; the loop was not clocked at fs for the whole "
              "record, so no record is written", file=sys.stderr)
        return False
    return True


def power_routes_agree(corners, window_s, tol=POWER_ROUTE_TOL):
    """True if the cycle-mean and energy-integral routes to P(VDDA) agree."""
    bad = {}
    for cid, c in sorted(corners.items()):
        from_energy = c["e_vdda"] / window_s
        ref = max(abs(c["p_vdda"]), 1e-12)
        rel = abs(from_energy - c["p_vdda"]) / ref
        if rel > tol:
            bad[cid] = {"p_vdda_cycle_mean_W": c["p_vdda"],
                        "p_vdda_from_energy_W": from_energy, "rel": rel}
    if bad:
        print(f"REFUSE: the cycle-mean and energy routes to the VDDA power "
              f"disagree by more than {tol:g} at {json.dumps(bad, indent=2)}; "
              "no record written", file=sys.stderr)
        return False
    return True


# ------------------------------------------------------------- extraction --
def extract(rep, rec_clocks=None, n_rec=None):
    """(summary corners, per-clock samples) from a klt sim report."""
    rec_clocks = mk.REC_CLOCKS if rec_clocks is None else rec_clocks
    corners, samples = {}, {}
    for c in rep["corners"]:
        m = measurement_map(c)
        cid = c["corner_id"]
        entry = {"status": c["status"],
                 "process": c["process"], "supply_v": c["supply_v"],
                 "temperature_c": c["temperature_c"],
                 "slug": corner_slug(c),
                 # Kept because the record's record-length justification is a
                 # cost argument: this is what the run actually cost, beside
                 # the estimate that chose the length.
                 "runtime_s": c.get("runtime_s"),
                 "peak_rss_bytes": c.get("peak_rss_bytes"),
                 **{k: m.get(k, {}).get("value") for k in KEYS},
                 "measurement_status": {k: m.get(k, {}).get("status") for k in KEYS},
                 "diagnostics": sorted({d["code"] for d in c.get("diagnostics", [])})}
        bs_times = (m.get("bs_edges", {}).get("crossings") or {})
        entry["bs_edge_times_s"] = bs_times.get("times")
        entry["bs_edge_kinds"] = bs_times.get("edges")
        entry["bs_edges_truncated"] = bs_times.get("truncated")
        corners[cid] = entry
        samples[cid] = per_clock(m, cid, c, rec_clocks)
    return corners, samples


def per_clock(m, cid, corner, rec_clocks):
    """The committed per-clock sample set for one anchor."""
    t, u, bs_v, o1, o2 = [], [], [], [], []
    for k in rec_clocks:
        sb = m.get(f"sb_{k:05d}", {}).get("value")
        s1 = m.get(f"s1_{k:05d}", {}).get("value")
        s2 = m.get(f"s2_{k:05d}", {}).get("value")
        if sb is None or s1 is None or s2 is None:
            continue
        t.append(mk.sample_time(k))
        u.append(mk.u_diff(mk.sample_time(k)))
        bs_v.append(sb)
        o1.append(s1)
        o2.append(s2)
    vdda = corner["supply_v"]["vdda"]
    return {
        "corner_id": cid,
        "process": corner["process"],
        "vdda_v": vdda,
        "temperature_c": corner["temperature_c"],
        "result_kind": "simulated (ngspice, transistor-level); never measured",
        "first_clock_index": rec_clocks[0],
        "n_clocks": len(t),
        "t_s": [round(x, 13) for x in t],
        "u_diff_v": [round(x, 9) for x in u],
        "bs_v": [round(x, 7) for x in bs_v],
        "y": [1 if x > 0.5 * vdda else -1 for x in bs_v],
        "o1d_v": [round(x, 7) for x in o1],
        "o2d_v": [round(x, 7) for x in o2],
    }


def input_sequence_block():
    """Everything a sibling needs to rebuild the discrete input u[n]."""
    return {
        "tone_hz": mk.FIN_HZ,
        "tone_cycles_in_record": mk.CYCLES,
        "amplitude_dbfs": mk.AMP_DBFS,
        "amplitude_peak_per_side_V": mk.AMP_SE_V,
        "amplitude_peak_differential_V": 2 * mk.AMP_SE_V,
        "full_scale_differential_V": mk.VREF_DIFF_V,
        "full_scale_note": (
            "Model B's full scale is the 1.2 V differential reference "
            "(sim/bmodel/model.py); -6 dBFS is 0.6 V peak differential, which "
            "is spec row 11's 0.5*VREF and the operating point spec sec 5.4 "
            "derives the swing from."),
        "phase_rad_at_t0": 0.0,
        "waveform": ("u(t) = 2*amplitude_peak_per_side_V * "
                     "sin(2*pi*tone_hz*t), differential, t in seconds from the "
                     "start of the transient; vinp = 0.9 + A*sin, "
                     "vinn = 0.9 - A*sin"),
        "fs_hz": mk.FS_HZ,
        "clock_source": (f"Vclk PULSE, first rising 50 % crossing at "
                         f"{mk.TRISE0:.12g} s, period {mk.TPER:.12g} s, 50 % "
                         f"duty, 0.2 ns edges, rescaled per corner to that "
                         f"corner's Vdda (corners.supply_waveforms)"),
        "input_sampling_edge": (
            "The input is sampled by the integrator cell during phi1, bottom "
            "plate first: phi1e falls before phi1 (design/modulator/README.md). "
            "phi1 is high while clk is low, so clock k samples the input "
            "around t = TRISE0 + (k + 0.5 .. 1.0)*Tclk; the exact instant is "
            "clkgen's phi1e falling edge and is corner dependent. u[n] in the "
            "samples files is the continuous-time differential input evaluated "
            "at the sample instant below, not at phi1e's fall: it is the "
            "analytic tone, so a sibling that wants another instant computes "
            "it from `waveform` directly."),
        "sample_instant": (
            "Each committed per-clock value is a .meas FIND of the held node "
            "at t = TRISE0 + (k + 0.5)*Tclk, clock k's falling 50 % crossing "
            "of the clk source. That is the end of the phi2 integrate phase "
            "and a few hundred ps before clkgen lowers phi2, so both "
            "integrator outputs carry the charge that clock transferred and "
            "are still driven."),
        "bitstream_polarity": (
            "bs high = the comparator decided y = +1 (bs and dp are both "
            "buffered from the latch node q; design/modulator/README.md). "
            "`y` in the samples files is +1 where bs_v > Vdda/2."),
    }


def staged_request_hashes():
    """klt's own sha256 of the request document it staged, per batch job.

    The record names these because they are what binds it to the bytes the
    fleet actually ran. `environment.netlist_sha256` does not: klt computes it
    client-side when it assembles the report, so a netlist edited between
    submission and collection is hashed there as though it had been
    simulated (2AMLogic/klayout-tools#5569). A job receipt, by contrast, is
    written at launch and records what was uploaded.

    The shard map's `fingerprint` would do the same job, but klt removes the
    map once every shard is collected -- there is nothing left to resume --
    so it is gone by the time a record is written. The receipts persist.

    Returns the distinct values in first-seen order: one submission stages
    once, and a `--resume` of an unchanged request stages the same bytes, so
    a single value is the expected result and more than one is a signal.
    """
    out = []
    for f in sorted((SCRATCH / "out-anchors").glob("batch-receipt-*.json")):
        try:
            h = json.loads(f.read_text()).get("request_sha256")
        except (OSError, ValueError):
            continue
        if h and h not in out:
            out.append(h)
    return out


def batch_job_ids(rep_env):
    """The fleet job id(s) behind this report.

    A one-unit-per-job split reports `environment.remote` as a `fleet[]` array
    with a `job_ids` roll-up instead of a single `job_id`, so both shapes are
    read here; the record names whichever the run produced.
    """
    remote = rep_env.get("remote") or {}
    ids = remote.get("job_ids")
    if ids:
        return list(ids)
    if remote.get("fleet"):
        return [f.get("job_id") for f in remote["fleet"]]
    return [remote["job_id"]] if remote.get("job_id") else []


def build_record(results, stamp, pin, rep_env, window_s, provenance=None):
    corners = results["corners"]
    worst_p = max((c["p_ana"], cid) for cid, c in corners.items())
    worst_o1 = max((c["o1_swing_pp"], cid) for cid, c in corners.items())
    worst_o2 = max((c["o2_swing_pp"], cid) for cid, c in corners.items())
    return {
        "fixture": (
            "Short full-modulator transistor-level transient (issue #125, "
            "DR-001 item 2): design/modulator/modulator.spice with "
            "design/ota/ota_fd.spice and "
            "design/modulator/comparator/comparator.spice, ideal DR-005 "
            "boundary sources, a coherent single tone at -6 dBFS and the "
            "5.12 MHz clock."),
        "result_kind": (
            "simulated (ngspice, transistor-level netlists of the assembled "
            "modulator; not the behavioural model, not measured silicon)"),
        "evidence_source": "T (DR-001 item 2)",
        "record_length": {
            "modulator_clocks": mk.N_REC,
            "settling_clocks_discarded": mk.N_SETTLE,
            "output_samples_at_osr_128": mk.N_REC / 128,
            "window_s": window_s,
            "transient_end_s": mk.T_END,
            "max_timestep_s": mk.T_MAX_STEP,
            "chosen_because": (
                "Cost. Measured on the dispatch host before any corner ran: "
                "about 3.1 s of ngspice per microsecond of transient at "
                "tt/27 C/1.80 V with a 1 ns maximum timestep, i.e. about "
                "0.61 s per modulator clock. 1088 clocks is ~11 min at tt and "
                "~22 min at a corner twice as slow, inside the batch fleet's "
                "3600 s whole-job ceiling with margin. DR-001 item 2 requires "
                "the length to be stated; this is that statement, written "
                "into make_request.py before the first result."),
        },
        "sndr": {
            "computed": False,
            "why_not": (
                "No SNDR is claimed from this record. An in-band figure needs "
                f"bins inside the 20 kHz band of spec row 1; {mk.N_REC} "
                f"modulator clocks give a bin bandwidth of "
                f"{mk.FS_HZ / mk.N_REC:.0f} Hz on the bitstream and only "
                f"{mk.N_REC / 128:g} output samples after decimation by the "
                "OSR, so neither route resolves the band. Spec sec 1.2's row 2 "
                "claim is a B-model result with the DR-001 cross-check; this "
                "bench supplies the cross-check's transistor-level side as "
                "bitstreams and integrator waveforms, not as an SNDR."),
        },
        "corner_set": {
            "name": "DR-002 anchor set",
            "points": len(mk.ANCHOR_POINTS),
            "subset_statement": (
                "A declared subset of the DR-002 full 45-point grid: DR-002 "
                "names the anchor set for the expensive runs and lists the "
                "short full-modulator transient as one of them. This record "
                "is an anchor-subset result and is not a full-grid result."),
            "anchors": [{"process": p, "vdda_v": v, "temperature_c": t}
                        for p, v, t in mk.ANCHOR_POINTS],
        },
        "limits": {
            "p_ana_max_W": mk.P_ANA_MAX_W,
            "p_ana_source": "spec/modulator-adc.md row 13 (P_ana <= 1 mW)",
            "p_ana_definition": (
                "Time-weighted mean over the recorded clocks of the power "
                "delivered by the VDDA source plus the two reference sources. "
                "The 5 uA bias current is drawn from vdda, so it is inside the "
                "VDDA term. The vcm source is reported as p_vcm and is NOT in "
                "this sum."),
            "swing_max_Vpp": mk.SWING_MAX_VPP,
            "swing_source": (
                "spec/modulator-adc.md sec 5.4: the integrator outputs 'stay "
                "well inside the ~1.39 Vpp output swing sky130-opamp reports "
                "at its worst corner'. That sentence is the only swing figure "
                "the ratified spec gives and no new number is introduced "
                "here. It is applied to the DIFFERENTIAL integrator output, "
                "which is how design/ota/SIZING.md 'Swing vs spec 5.4' reads "
                "it (it compares ~2.3 Vpp differential of static headroom "
                "against it). The single-ended extremes are reported beside "
                "it, ungraded, so the other reading of the sentence stays "
                "visible. It is the CONTINUOUS-TIME extreme over the window, "
                "which is what the amplifier has to deliver; the per-clock "
                "samples in samples/ are the held states and have a smaller "
                "peak-to-peak, because they skip the switching transients "
                "between sample instants. The two are not in conflict and "
                "neither replaces the other."),
            "row_12_coverage": (
                "Row 12 (supply 1.62-1.98 V) is covered by the anchor set "
                "spanning 1.620, 1.800 and 1.980 V, not by a limit of its "
                "own."),
        },
        "boundary": {
            "vcm_V": 0.9, "vrefp_V": 1.5, "vrefn_V": 0.3,
            "vref_differential_V": mk.VREF_DIFF_V, "ibias_uA": 5,
            "note": ("DR-005: the reference, vcm and bias are ideal inputs at "
                     "the boundary. vcm is held at 0.9 V on every corner and "
                     "does not track Vdda, as in the other transistor-level "
                     "benches here."),
        },
        "input_sequence": input_sequence_block(),
        "pdk_sources_stamp": stamp,
        "pdk_pin": {"file": "sim/pdk.json",
                    "open_pdks_revision": pin["open_pdks_revision"]},
        # The klt that RAN the corners, from the report's own provenance --
        # not `klt --version` at record time. This is a shared host whose tool
        # is re-provisioned under running work, so the two can differ, and the
        # record has to name the one that produced the numbers.
        "klt": (provenance or {}).get("klt_version") or subprocess.run(
            ["klt", "--version"], capture_output=True, text=True).stdout.strip(),
        "klt_git_commit": (provenance or {}).get("klt_git_commit"),
        "batch_staged_request_sha256": results.get("staged_request_sha256"),
        "ngspice": rep_env.get("engine_version", "unknown"),
        "engine_host": rep_env.get("engine_host"),
        "remote": rep_env.get("remote"),
        "batch_job_ids": batch_job_ids(rep_env),
        **{k: sha256(REPO / v) for k, v in NETLISTS.items()},
        **shas(),
        "samples": results["samples_index"],
        "corners": corners,
        "summary": {
            "corner_count": len(corners),
            "pass": sum(1 for c in corners.values() if c["status"] == "pass"),
            "fail": sum(1 for c in corners.values() if c["status"] != "pass"),
            "worst_p_ana_W": {"value": worst_p[0], "corner": worst_p[1]},
            "worst_o1_swing_pp_V": {"value": worst_o1[0], "corner": worst_o1[1]},
            "worst_o2_swing_pp_V": {"value": worst_o2[0], "corner": worst_o2[1]},
            "slowest_corner_runtime_s": max(
                ((c.get("runtime_s") or 0.0), cid) for cid, c in corners.items()),
        },
        "pass": all(c["status"] == "pass" for c in corners.values()),
    }


# ------------------------------------------------------------------- main --
def dump_samples(s):
    """JSON with the per-clock arrays on one line each.

    `indent` would put one number per line and multiply the file size by
    about five, for a file nothing reads by eye.
    """
    arrays = {k: v for k, v in s.items() if isinstance(v, list)}
    stub = {k: (f"@@{k}@@" if k in arrays else v) for k, v in s.items()}
    text = json.dumps(stub, indent=1)
    for k, v in arrays.items():
        text = text.replace(f'"@@{k}@@"', json.dumps(v, separators=(",", ":")))
    return text + "\n"


def write_samples(samples, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    index = {}
    for cid, s in sorted(samples.items()):
        name = f"{corner_slug(s_corner(s))}.json"
        path = outdir / name
        path.write_text(dump_samples(s))
        index[cid] = {"file": f"samples/{name}", "sha256": sha256(path),
                      "n_clocks": s["n_clocks"]}
    return index


def s_corner(s):
    return {"process": s["process"], "supply_v": {"vdda": s["vdda_v"]},
            "temperature_c": s["temperature_c"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--probe", action="store_true",
                    help="one tt/27C/1.8V corner, run locally, no record")
    ap.add_argument("--resume", action="store_true",
                    help="re-launch only the anchors a previous run left "
                         "unfinished (a shard the fleet refused for capacity "
                         "comes back `lost_shard`), instead of re-simulating "
                         "the whole anchor set")
    ap.add_argument("--record", action="store_true",
                    help="write record.json (refuses to overwrite: records are append-only)")
    ap.add_argument("--record-name", default="record.json",
                    help="record file name, for a re-run after a netlist change (new file)")
    a = ap.parse_args()

    pin = json.load(open(REPO / "sim/pdk.json"))
    root, stamp = pdk_stamp(pin["variant"], a.pdk_root)
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'",
              file=sys.stderr)
        return 2
    out = HERE / a.record_name
    if a.record and out.exists():
        print(f"REFUSE: {out.name} exists; records are append-only "
              "(use --record-name)", file=sys.stderr)
        return 2

    partial = PARTIALS / "anchors.json"
    saved = None
    if a.record and partial.exists():
        try:
            d = json.loads(partial.read_text())
        except ValueError:
            d = None
        if d and {k: d.get(k) for k in shas()} == shas():
            saved = d
        elif d:
            print("NOTE: ignoring stale .partials/anchors.json (request or deck "
                  "changed since it ran)", file=sys.stderr)

    if saved is None:
        if a.probe:
            tmp = pathlib.Path(tempfile.mkdtemp(prefix="modulator-tran-probe-"))
        else:
            tmp = SCRATCH
            tmp.mkdir(parents=True, exist_ok=True)
        res = run_klt(HERE / "request.json", a.probe, tmp, "anchors",
                      HERE / "probe_request.json", keys=KEYS,
                      artifacts_dir=None if a.probe else ARTIFACTS,
                      resume=a.resume and not a.probe)
        if res is None:
            print("REFUSE: no usable report (see .artifacts/klt-anchors.stderr.txt); "
                  "not falling back to a local grid or to .partials/",
                  file=sys.stderr)
            return 1
        rep, _ = res
        corners, samples = extract(rep)
        if a.probe:
            cid = next(iter(corners))
            print(json.dumps({"corner": corners[cid],
                              "first_8_clocks": {
                                  "bs_v": samples[cid]["bs_v"][:8],
                                  "y": samples[cid]["y"][:8],
                                  "o1d_v": samples[cid]["o1d_v"][:8],
                                  "o2d_v": samples[cid]["o2d_v"][:8]}},
                             indent=2))
            return 0
        saved = {"corners": corners, "samples": samples,
                 "environment": rep.get("environment", {}),
                 "provenance": rep.get("provenance", {}),
                 "staged_request_sha256": staged_request_hashes(),
                 "measurement_rollup": [m for m in rep.get("measurements", [])
                                        if m["name"] in KEYS],
                 **shas()}
        PARTIALS.mkdir(exist_ok=True)
        partial.write_text(json.dumps(saved, indent=2) + "\n")

    corners, samples = saved["corners"], saved["samples"]
    window_s = mk.N_REC * mk.TPER
    gates = (anchors_complete(corners) and scalars_present(corners)
             and samples_present(samples) and clock_ran_at_fs(corners)
             and power_routes_agree(corners, window_s))
    if not gates:
        return 1
    print(json.dumps({cid: {"status": c["status"], "p_ana_W": c["p_ana"],
                            "o1_swing_pp_V": c["o1_swing_pp"],
                            "o2_swing_pp_V": c["o2_swing_pp"],
                            "phi1_edges": c["phi1_edges"],
                            "bs_edges": c["bs_edges"]}
                      for cid, c in sorted(corners.items())}, indent=2))
    if not a.record:
        print("all 7 anchors complete; re-run with --record to write the record")
        return 0

    index = write_samples(samples, SAMPLES)
    rec = build_record({"corners": corners, "samples_index": index,
                        "staged_request_sha256":
                            saved.get("staged_request_sha256")
                            or staged_request_hashes()},
                       stamp, pin, saved["environment"], window_s,
                       saved.get("provenance"))
    rec["measurement_rollup"] = saved.get("measurement_rollup", [])
    out.write_text(json.dumps(rec, indent=2) + "\n")
    print(f"wrote {out.name}: pass={rec['pass']} "
          f"({rec['summary']['pass']}/{rec['summary']['corner_count']} anchors)")
    return 0 if rec["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

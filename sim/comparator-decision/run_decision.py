#!/usr/bin/env python3
"""Comparator decision-time / offset / hysteresis runner. See README.md.

Simulated, transistor-level: `klt sim` on the DR-002 full grid (45 points) for
each of the two variants, which `klt sim` sends to the batch fleet. Never
falls back to a local grid.

  --variant V  run only this variant (repeatable); the other is taken from
               .partials/ if a previous run left a matching one there
  --probe V    one tt/27C/1.8V corner of one variant, run locally, no record
  --record     write record.json (refuses to overwrite: records are
               append-only; use --record-name for a re-run)
  --work DIR   keep each variant's `klt sim` scratch under DIR instead of a
               fresh temporary directory, so --resume can finish it
  --resume     launch only the units a previous run into the same --work left
               unrun (lost shards, Spot reclaims), instead of the whole grid

Everything the record states beyond the raw per-corner measurements is
derived by the pure functions below, so the fixture tests in
test_run_decision.py cover the derivations without any EDA tool.
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
from settling_common import (CAPACITY_WAIT_S, grid_complete,  # noqa: E402
                             measurements_present, pdk_stamp, run_klt, sha256)
sys.path.insert(0, str(HERE))
import make_request as MR  # noqa: E402

VARIANTS = ("loop", "trip")
PARTIALS = HERE / ".partials"      # per-variant results, gitignored
ARTIFACTS = HERE / ".artifacts"    # raw klt report / batch receipt, gitignored

# The measurement whose presence separates "simulated and failing" from
# "never simulated" for each variant (settling_common.measurements_present).
ADMIT_KEY = {"loop": "tdec_frac", "trip": "v_trip_up"}

PROCESS = ("tt", "ss", "ff", "sf", "fs")


# --------------------------------------------------------------- derivations

def parse_corner(cid):
    """`tt/1.620V/-40C` -> {'process','vdda_V','temperature_C'} (klt's corner_id)."""
    parts = cid.split("/")
    if len(parts) != 3 or parts[0] not in PROCESS:
        raise ValueError(f"unrecognised corner id: {cid!r}")
    p, v, t = parts
    if not v.endswith("V") or not t.endswith("C"):
        raise ValueError(f"unrecognised corner id: {cid!r}")
    return {"process": p, "vdda_V": float(v[:-1]), "temperature_C": float(t[:-1])}


def fs(volts):
    """Volts of differential at the integrator-2 output -> model B x2 units.

    One x2 unit is MR.FS_VOLTS = 1.2 V of differential output; the derivation
    is in make_request.py and in README.md "Model-B units".
    """
    return None if volts is None else volts / MR.FS_VOLTS


def offset_hysteresis(v_trip_up, v_trip_dn):
    """Model-B `comparator_offset` / `comparator_hysteresis`, in volts.

    Model B holds y = +1 until x2 + off <= -h/2 and y = -1 until x2 + off >
    +h/2, so a rising sweep trips at x2 = +h/2 - off and a falling one at
    x2 = -h/2 - off. Inverting:

        off = -(x2_up + x2_dn)/2      h = x2_up - x2_dn

    A negative h means the falling trip sat ABOVE the rising one, which no
    hysteresis can produce; it is returned as measured (the caller reports it)
    rather than clamped to zero.
    """
    if v_trip_up is None or v_trip_dn is None:
        return None, None
    return -0.5 * (v_trip_up + v_trip_dn), v_trip_up - v_trip_dn


def quantization(v_trip_up, v_trip_dn, step_V):
    """What a staircase of step `step_V` can and cannot say about off and h.

    The sweep only ever shows the comparator grid points `step_V` apart, so
    with a true threshold `t` and a true hysteresis width `h`:

        the up sweep flips at the first grid point above t + h/2,
          so   v_up in (t + h/2,      t + h/2 + step]
        the down sweep flips at the first grid point below t - h/2,
          so   v_dn in [t - h/2 - step,  t - h/2)

    Subtracting and averaging those two:

        h in (v_up - v_dn - 2*step,  v_up - v_dn)
        t in ((v_up + v_dn)/2 - step/2,  (v_up + v_dn)/2 + step/2)

    So the offset is resolved to +/- step/2, and the measured difference
    `v_up - v_dn` is an UPPER bound on the hysteresis, not a measurement of
    it: a comparator with no hysteresis at all reads one whole step here.
    h is clamped at 0 from below -- it cannot be negative -- but the raw
    difference is reported unclamped by the caller so a reading that needs
    the clamp is visible rather than hidden.
    """
    if v_trip_up is None or v_trip_dn is None or not step_V:
        return None
    step = abs(step_V)
    raw = v_trip_up - v_trip_dn
    return {"offset_half_width_V": step / 2.0,
            "hysteresis_upper_bound_V": raw,
            "hysteresis_lower_bound_V": max(0.0, raw - 2.0 * step),
            "step_V": step}


def decision_limit(phi1_width_s):
    """The limit the worst decision time is held to, and where it comes from.

    DR-003 owes decision time "against this clock's half-period". The
    half-period (97.65625 ns) is not what the comparator is given: clkgen
    spends part of each half on the non-overlap gaps, so the limit is the
    phi1 high time the bench actually delivers at that corner -- measured,
    not assumed. No reservation is subtracted for the reference node to
    settle after dp/dn change: no committed record in this repo bounds that
    time, so per the issue's own instruction the limit is stated as the bare
    delivered phi1 width and labelled as such.
    """
    return phi1_width_s


def worst(corners, key, sign=1):
    """(corner_id, value) of the corner with the largest sign*value.

    Corners with no value for `key` are skipped; returns (None, None) if none
    has one.
    """
    have = [(k, v[key]) for k, v in sorted(corners.items()) if v.get(key) is not None]
    if not have:
        return None, None
    return max(have, key=lambda kv: sign * kv[1])


def worst_abs(corners, key):
    have = [(k, v[key]) for k, v in sorted(corners.items()) if v.get(key) is not None]
    if not have:
        return None, None
    return max(have, key=lambda kv: abs(kv[1]))


def per_clock_rows(corner, first, last):
    """The per-decision table for one corner of the `loop` variant."""
    rows = []
    for k in range(first, last + 1):
        rows.append({"clock": k,
                     "vod_V": corner.get(f"vod_{k}"),
                     "flipped": corner.get(f"flip_{k}"),
                     "t_dp_dn_s": corner.get(f"tdec_{k}"),
                     "t_outp_outn_s": corner.get(f"tcmp_{k}"),
                     "t_q_qb_s": corner.get(f"tq_{k}")})
    return rows


def binding_decision(corners):
    """Worst decision time over the grid, with the overdrive that produced it.

    The worst clock is the one whose own `tdec_k` equals the corner's
    `tdec_worst`, among the clocks where dp/dn actually changed -- the only
    clocks where the delay to dp/dn is observable at all.
    """
    cid, frac = worst(corners, "tdec_frac")
    if cid is None:
        return None
    c = corners[cid]
    rows = [r for r in per_clock_rows(c, MR.LOOP_FIRST, MR.LOOP_LAST) if r["flipped"]]
    hit = max(rows, key=lambda r: r["t_dp_dn_s"]) if rows else None
    return {"corner": cid, **parse_corner(cid),
            "t_decision_to_dp_dn_s": c.get("tdec_worst"),
            "phi1_width_s": c.get("phi1_width"),
            "limit_s": decision_limit(c.get("phi1_width")),
            "fraction_of_limit": frac,
            "flips_counted": c.get("n_flip"),
            # the smallest differential this corner was actually asked to
            # decide on, over the graded clocks: the bench does not command
            # the overdrive, the closed loop presents it
            "smallest_differential_decided_V": min(
                (abs(r["vod_V"]) for r in per_clock_rows(c, MR.LOOP_FIRST, MR.LOOP_LAST)
                 if r["vod_V"] is not None), default=None),
            # The intermediate crossings are reported from the SAME clock as
            # the worst delay. The corner-wide worsts below are each taken
            # over a different clock, so they do not line up with it and must
            # not be read as a breakdown of it.
            "at_the_worst_clock": None if hit is None else {
                "clock": hit["clock"],
                "differential_V": hit["vod_V"],
                "t_to_comparator_outputs_s": hit["t_outp_outn_s"],
                "t_to_sr_latch_s": hit["t_q_qb_s"],
                "t_to_dp_dn_s": hit["t_dp_dn_s"]},
            "worst_over_all_graded_clocks": {
                "t_to_comparator_outputs_s": c.get("tcmp_worst"),
                "t_to_sr_latch_s": c.get("tq_worst")}}


def job_ids(result):
    """Every fleet job id behind one variant's grid, in submission order.

    A request small enough for one job reports `{"job_id": ...}`; one the
    whole-job ceiling split reports `{"fleet": [...]}`, one entry per shard.
    The record names them either way -- that is the thread back from a number
    to the machine that produced it.
    """
    r = (result or {}).get("remote") or {}
    if r.get("fleet"):
        return [f.get("job_id") for f in r["fleet"]]
    return [r["job_id"]] if r.get("job_id") else []


def kickback_at(corner, clocks=MR.LOOP_KICK_CLKS):
    """Peak disturbance per node at each sampled clock, plus that clock's overdrive.

    Every sampled clock is kept, not just the worst: the common-mode part of
    the disturbance is the integrator's own phase transition and barely moves
    between clocks, while the differential part is the comparator's kickback
    and tracks the differential its input pair sees. Keeping both clocks is
    what lets a reader check that separation instead of taking it on trust.
    """
    out = {"by_clock": {}}
    for k in clocks:
        row = {"differential_at_this_clock_V": corner.get(f"vod_{k}"),
               "decision_changed": corner.get(f"flip_{k}")}
        for tag, _sig in MR.KICK_NODES:
            row[tag] = {"peak_deviation_V": corner.get(f"kb_{tag}_{k}"),
                        "held_value_V": corner.get(f"kbref_{tag}_{k}")}
        out["by_clock"][str(k)] = row
    for tag, _sig in MR.KICK_NODES:
        vals = [(k, corner.get(f"kb_{tag}_{k}")) for k in clocks
                if corner.get(f"kb_{tag}_{k}") is not None]
        out[f"worst_{tag}_V"] = max(v for _k, v in vals) if vals else None
    return out


def bracket_margin(corner):
    """Clocks between each trip and the nearer end of its own sweep.

    A trip found on the first or last swept clock is bracketed only by the
    edge of the sweep; one found in the middle is bracketed on both sides by
    several steps. Same number, both directions, so a reader can see which
    corners the staircase only just reached.
    """
    out = {}
    for tag, first, last in (("up", MR.TRIP_UP_FIRST, MR.TRIP_UP_LAST),
                             ("dn", MR.TRIP_DN_FIRST, MR.TRIP_DN_LAST)):
        k = corner.get(f"k_{tag}")
        out[tag] = None if k is None else min(int(k) - first, last - int(k))
    return out


def trip_summary(corners):
    """Offset and hysteresis per corner plus the binding corner of each."""
    per = {}
    for cid, c in sorted(corners.items()):
        off_V, hyst_V = offset_hysteresis(c.get("v_trip_up"), c.get("v_trip_dn"))
        step = [s for s in (c.get("step_up"), c.get("step_dn")) if s is not None]
        step_V = max((abs(s) for s in step), default=None)
        q = quantization(c.get("v_trip_up"), c.get("v_trip_dn"), step_V)
        per[cid] = {**parse_corner(cid),
                    "v_trip_up_V": c.get("v_trip_up"),
                    "v_trip_dn_V": c.get("v_trip_dn"),
                    "comparator_offset_V": off_V,
                    "comparator_offset_FS": fs(off_V),
                    "comparator_hysteresis_V": hyst_V,
                    "comparator_hysteresis_FS": fs(hyst_V),
                    "staircase_step_V": step_V,
                    "quantization": q,
                    # how far from the ends of the sweep the trip was found;
                    # 0 means it was bracketed only by the sweep's own edge
                    "bracket_margin_clocks": bracket_margin(c),
                    "t_decision_at_trip_up_s": c.get("tdec_up"),
                    "t_decision_at_trip_dn_s": c.get("tdec_dn")}
    off_cid, off_v = worst_abs({k: {"x": v["comparator_offset_V"]} for k, v in per.items()
                                if v["comparator_offset_V"] is not None}, "x")
    hy_cid, hy_v = worst_abs({k: {"x": v["comparator_hysteresis_V"]} for k, v in per.items()
                              if v["comparator_hysteresis_V"] is not None}, "x")
    steps = [v["staircase_step_V"] for v in per.values() if v["staircase_step_V"] is not None]
    return {
        "per_corner": per,
        # Each headline number carries the binding corner's own quantization,
        # so the bound travels with the value instead of living only in the
        # note above it.
        "comparator_offset": None if off_cid is None else {
            "binding_corner": off_cid, **parse_corner(off_cid),
            "V": off_v, "FS": fs(off_v),
            "half_width_V": (per[off_cid]["quantization"] or {}).get("offset_half_width_V"),
            "half_width_FS": fs((per[off_cid]["quantization"] or {}).get("offset_half_width_V")),
            "bracket_margin_clocks": per[off_cid]["bracket_margin_clocks"]},
        "comparator_hysteresis": None if hy_cid is None else {
            "binding_corner": hy_cid, **parse_corner(hy_cid),
            "is": "an upper bound; see what_these_numbers_are",
            "V": hy_v, "FS": fs(hy_v),
            "lower_bound_V": (per[hy_cid]["quantization"] or {}).get("hysteresis_lower_bound_V"),
            "lower_bound_FS": fs((per[hy_cid]["quantization"] or {}).get("hysteresis_lower_bound_V")),
            "staircase_step_V": per[hy_cid]["staircase_step_V"],
            "bracket_margin_clocks": per[hy_cid]["bracket_margin_clocks"]},
        # The staircase step is the resolution of both trip points, and it is
        # NOT the same at every corner: it is (Cs/Ci) * o1d, so where the
        # switched-capacitor transfer collapses (low supply, slow, cold) the
        # sweep narrows and its resolution sharpens. Both ends are reported,
        # each with the corner it came from, because a single number here
        # would be a claim about corners it was not measured at.
        "what_these_numbers_are": (
            "A staircase shows the comparator only grid points one step apart, "
            "so the offset is resolved to +/- step/2 and the measured "
            "v_trip_up - v_trip_dn is an UPPER BOUND on the hysteresis width, "
            "not a measurement of it -- a comparator with no hysteresis at all "
            "reads one whole step here. Each corner carries its own "
            "`quantization` block with that step and both hysteresis bounds; "
            "`comparator_hysteresis` below is the raw difference, i.e. the "
            "upper bound, and is the conservative value to give model B."),
        "resolution_V": max(steps) if steps else None,
        "resolution_FS": fs(max(steps)) if steps else None,
        "resolution_range_V": None if not steps else {
            "coarsest": max(steps),
            "coarsest_corner": max(per.items(), key=lambda kv: kv[1]["staircase_step_V"]
                                   if kv[1]["staircase_step_V"] is not None else -1.0)[0],
            "finest": min(steps),
            "finest_corner": min((kv for kv in per.items()
                                  if kv[1]["staircase_step_V"] is not None),
                                 key=lambda kv: kv[1]["staircase_step_V"])[0]},
    }


def netlist_hashes():
    return {
        "design/modulator/modulator.spice": sha256(REPO / "design/modulator/modulator.spice"),
        "design/modulator/comparator/comparator.spice":
            sha256(REPO / "design/modulator/comparator/comparator.spice"),
        "design/modulator/comparator/comparator_core.spice":
            sha256(REPO / "design/modulator/comparator/comparator_core.spice"),
        "design/ota/ota_fd.spice": sha256(REPO / "design/ota/ota_fd.spice"),
    }


# ------------------------------------------------------------------- plumbing

def keys_for(variant):
    """Every measurement name the variant declares, in request order."""
    return tuple(m["name"] for m in MR.VARIANTS[variant]["measurements"]())


def shas(v):
    return {"request_sha256": sha256(HERE / f"request_{v}.json"),
            "deck_sha256": sha256(HERE / f"comparator_decision_{v}.cir")}


def load_partial(v):
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


def usable(v, corners):
    """True if this variant's corners could stand in a record on their own.

    A fleet run can come back with every grid point present but some of them
    `error` -- a shard that never got Spot capacity returns one valueless
    entry per corner (`lost_shard`). Such a result is a legitimate thing to
    report and a legitimate thing to re-run, but it is NOT a thing to cache:
    a partial saved from it would be silently reused by a later invocation
    that did not ask for this variant.
    """
    return grid_complete([corners]) and measurements_present([corners], key=ADMIT_KEY[v])


def save_partial(v, result):
    PARTIALS.mkdir(exist_ok=True)
    (PARTIALS / f"{v}.json").write_text(json.dumps(result, indent=2) + "\n")


def summarize(variant, corners):
    ok = [k for k, v in corners.items() if v["status"] == "pass"]
    key = "tdec_frac" if variant == "loop" else "hyst_V"
    cid, val = worst_abs(corners, key)
    return {"corner_count": len(corners), "pass": len(ok), "fail": len(corners) - len(ok),
            f"worst_{key}": None if cid is None else [abs(val), cid]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--variant", choices=VARIANTS, action="append",
                    help="run only this variant (repeatable); default: both")
    ap.add_argument("--probe", choices=VARIANTS,
                    help="one tt/27C/1.8V corner of a variant, local, no record")
    ap.add_argument("--record", action="store_true",
                    help="write record.json (refuses to overwrite: records are append-only)")
    ap.add_argument("--record-name", default="record.json")
    ap.add_argument("--work", type=pathlib.Path,
                    help="keep klt sim's scratch (shard map, checkpoint) here so "
                         "--resume can finish a grid the fleet left incomplete")
    ap.add_argument("--resume", action="store_true",
                    help="with --work, launch only the units a previous run left "
                         "unrun; requires an unchanged request")
    ap.add_argument("--capacity-wait-s", type=int, default=CAPACITY_WAIT_S,
                    help="seconds a refused batch launch waits for fleet capacity "
                         f"before the shard is lost (default {CAPACITY_WAIT_S}, the "
                         "host rule's floor; raise it when the fleet is saturated)")
    a = ap.parse_args()

    pin = json.load(open(REPO / "sim/pdk.json"))
    root, stamp = pdk_stamp(pin["variant"], a.pdk_root)
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'", file=sys.stderr)
        return 2
    out = HERE / a.record_name
    if a.record and out.exists():
        print(f"REFUSE: {out.name} exists; records are append-only (use --record-name)",
              file=sys.stderr)
        return 2
    if a.resume and not a.work:
        print("REFUSE: --resume needs the --work directory the earlier run used",
              file=sys.stderr)
        return 2
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="comparator-decision-"))
    run = (a.probe,) if a.probe else tuple(dict.fromkeys(a.variant)) if a.variant else VARIANTS

    results = {}
    for v in (run if a.probe else VARIANTS):
        if v not in run:
            saved = load_partial(v)
            if saved:
                print(f"{v}: reusing .partials/{v}.json ({saved['summary']})")
                results[v] = saved
            continue
        res = run_klt(HERE / f"request_{v}.json", bool(a.probe), tmp, v,
                      HERE / f"probe_request_{v}.json",
                      artifacts_dir=None if a.probe else ARTIFACTS,
                      keys=keys_for(v), capacity_wait_s=a.capacity_wait_s,
                      outdir=(a.work / f"out-{v}") if a.work else None,
                      resume=a.resume)
        if res is None:
            print(f"{v}: no usable report (see .artifacts/klt-{v}.stderr.txt); "
                  "not falling back to a local grid or to .partials/", file=sys.stderr)
            continue
        rep, corners = res
        summary = summarize(v, corners)
        print(v, json.dumps({"status": rep.get("status"), **summary}, indent=2))
        e = rep.get("environment", {})
        results[v] = {"summary": summary, "corners": corners,
                      "pass": rep.get("status") == "pass",
                      "ngspice": e.get("engine_version", "unknown"),
                      "engine_host": e.get("engine_host"), "remote": e.get("remote"),
                      **shas(v)}
        if not a.probe:
            if usable(v, corners):
                save_partial(v, results[v])
            else:
                print(f"{v}: not cached in .partials/ -- this result cannot stand "
                      "in a record on its own; re-run this variant", file=sys.stderr)

    if a.probe:
        if a.probe not in results:
            print(f"REFUSE: no result for the {a.probe} probe; nothing printed.", file=sys.stderr)
            return 1
        print(json.dumps(results[a.probe]["corners"], indent=2))
        return 0
    missing = [v for v in VARIANTS if v not in results]
    if missing:
        print(f"REFUSE: no result for {', '.join(missing)}; no record written. "
              f"Re-run with --variant {missing[0]} when the fleet has capacity.", file=sys.stderr)
        return 1
    if not all(usable(v, results[v]["corners"]) for v in VARIANTS):
        return 1
    if not a.record:
        print("both variants complete; re-run with --record to write the record")
        return 0

    rec = build_record(results, pin, stamp)
    out.write_text(json.dumps(rec, indent=2) + "\n")
    print(f"wrote {out.name}: pass={rec['pass']}")
    print(json.dumps(rec["derived"]["decision_time"], indent=2))
    print(json.dumps({k: rec["derived"][k] for k in
                      ("comparator_offset", "comparator_hysteresis")}, indent=2))
    return 0 if rec["pass"] else 1


def build_record(results, pin, stamp):
    loop, trip = results["loop"]["corners"], results["trip"]["corners"]
    dec = binding_decision(loop)
    tsum = trip_summary(trip)
    kb_corner = dec["corner"] if dec else None
    reuse = json.load(open(REPO / "reuse.lock.json"))
    cmp_pin = next(i for i in reuse["imports"] if i["block"] == "comparator")
    return {
        "fixture": ("Comparator decision bench (issue #127): the whole modulator "
                    "(clkgen + both integrator cells + the vendored comparator + the "
                    "NAND SR latch and dp/dn/bs buffers), two variants on the DR-002 "
                    "full grid -- `loop` with the spec reference pair and a 0.06 V DC "
                    "input, `trip` with the reference pair nulled and a staircase "
                    "input that walks integrator 2's output across the trip point"),
        "result_kind": ("simulated (ngspice, transistor-level netlists of "
                        "design/modulator + design/ota/ota_fd + the vendored "
                        "comparator; not the behavioural model). Not measured."),
        "conditions": {
            "ibias_uA": 5, "vcm_V": 0.9,
            "vrefp_V": {"loop": 1.5, "trip": 0.9}, "vrefn_V": {"loop": 0.3, "trip": 0.9},
            "vin_diff_V": {"loop": MR.LOOP_VIN_DIFF, "trip": "staircase, see README"},
            "fs_Hz": MR.FS_HZ, "half_period_ns": MR.T_HALF * 1e9,
            "staircase_step_design_V": MR.STEP_V,
            "graded_clocks": {"loop": [MR.LOOP_FIRST, MR.LOOP_LAST],
                              "trip_up": [MR.TRIP_UP_FIRST, MR.TRIP_UP_LAST],
                              "trip_dn": [MR.TRIP_DN_FIRST, MR.TRIP_DN_LAST]},
            "corner_set": "DR-002 full grid, 5 process x 3 T x 3 Vdda",
            "substitutions": [
                "trip variant only: VREFP = VREFN = VCM = 0.9 V, which opens the "
                "feedback loop without disconnecting anything -- every reference "
                "switch still operates, it just transfers no charge",
                "the differential input is an ideal source pair at the block "
                "boundary (DR-005), as in every other bench here",
                "nothing in the comparator's own surroundings is substituted: real "
                "phi1, real integrator-2 OTA outputs, real NAND SR latch, real "
                "dp/dn/bs buffers loaded by both integrators' reference muxes",
            ],
        },
        "pass_criterion": (
            "loop: tdec_frac <= 1 at every corner, i.e. the worst delay from the "
            "phi1 rise to dp/dn carrying the new decision fits inside the phi1 high "
            "time that corner actually delivers; plus n_flip >= 2 so a corner that "
            "never changed dp/dn cannot pass with no evidence. trip: flip_up and "
            "flip_dn found, k_up/k_dn strictly inside the staircase, and the sweep "
            "spans at least +/-3.5 mV, so the trip points are bracketed. Kickback "
            "is reported, never graded: this repo has no kickback limit of its own "
            "and none is invented here."),
        "pdk_sources_stamp": stamp,
        "pdk_pin": {"file": "sim/pdk.json", "open_pdks_revision": pin["open_pdks_revision"]},
        "klt": subprocess.run(["klt", "--version"], capture_output=True, text=True).stdout.strip(),
        "netlist_sha256": netlist_hashes(),
        "comparator_pin": cmp_pin,
        "batch_job_ids": {v: job_ids(results[v]) for v in VARIANTS},
        "derived": {
            "decision_time": dec,
            "limit_derivation": (
                "The limit is the phi1 high time measured at the same corner, not "
                "the 97.65625 ns bare half-period: clkgen spends part of each half "
                "on the non-overlap gaps, so the comparator is given slightly less "
                "(and, because the phi1 buffer chain is not symmetric, sometimes "
                "slightly more) than half a period. No reservation is subtracted "
                "for the reference node to settle inside phi1 after dp/dn change -- "
                "no committed record in this repo bounds that time -- so the limit "
                "is the bare delivered phi1 width and is labelled as such."),
            "comparator_offset": tsum["comparator_offset"],
            "comparator_hysteresis": tsum["comparator_hysteresis"],
            "model_b_units": {
                "fs_volts": MR.FS_VOLTS,
                "derivation": ("one model-B x2 unit is 1.2 V of differential output at "
                               "integrator 2: the cell moves that output by "
                               "0.5*(v_o1_diff + vdac_diff) per clock with vdac_diff = "
                               "-y*(VREFP - VREFN) = -y*1.2 V, model B moves x2 by "
                               "0.5*(x1 - y), and the two agree for 1 unit = 1.2 V. "
                               "Same factor sim/integrator-ci/README.md derives for x1."),
                "resolution_V": tsum["resolution_V"], "resolution_FS": tsum["resolution_FS"],
                "resolution_range_V": tsum["resolution_range_V"],
                "what_these_numbers_are": tsum["what_these_numbers_are"],
            },
            "per_corner": tsum["per_corner"],
            "kickback": {
                "corner": kb_corner,
                "note": ("Peak deviation of each node from the value it holds through "
                         "the same phi1, at the binding decision-time corner. This is "
                         "the whole disturbance across the phi1 edge: the integrator's "
                         "own phi2 -> phi1 switch transition (symmetric, so it shows up "
                         "in the single-ended numbers and cancels in the differential "
                         "ones) superposed on the comparator's kickback (driven by its "
                         "input pair, so it scales with the differential). The two "
                         "sampled clocks have different differentials, so the record "
                         "carries the evidence for that split rather than asserting it. "
                         "Reported as a number; NO pass limit is invented for it. The "
                         "sibling's own ratified 5 mV row is against its bench -- ideal "
                         "sources through 1 kOhm, a different open_pdks pin -- not this "
                         "loading, so it is context and not a limit here."),
                "nodes": None if kb_corner is None else kickback_at(loop[kb_corner]),
            },
        },
        "variants": results,
        "pass": all(r["pass"] for r in results.values()),
    }


if __name__ == "__main__":
    sys.exit(main())

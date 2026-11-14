#!/usr/bin/env python3
"""Input-sampling completeness runner (issue #106). Simulated, transistor-level.

Issue #102's bench reads the integrator's *output* in the phi1 hold. This one
reuses the same decks, clocks and corner grid to read the *input* side: how much
of the differential input the `Sin` pass gate actually delivered onto Csi by the
instant `phi1e` falls and the sampled charge is frozen. See README.md ->
"Input sampling completeness (issue #106)".

Default: submit both amplitude requests (DR-002 full 45-point grid each) through
`klt sim`, which sends them to the batch fleet with --wait-for-capacity; never
falls back to a local grid.

    python3 -I sim/integrator-ci/run_sampling.py --probe post_v0p2  # 1 local corner
    python3 -I sim/integrator-ci/run_sampling.py                    # both grids
    python3 -I sim/integrator-ci/run_sampling.py --record           # record-i106.json

This runner writes NO pass/fail verdict. It reports the per-corner sampling
error `1 - sampled/ideal` against a labelled REFERENCE LINE
(`make_request.SAMP_REFERENCE_LINE` = 1e-4, the starting level
sim/integrator-settling grades against) because a number needs a scale to be
read on. No spec row bounds sampling completeness and this bench does not
invent one -- no measurement in the request carries `limits`.

It is kept separate from run_ci.py on purpose: run_ci.py's record, admission
sentinel and derivations are issue #102's charge-injection extraction, and
folding a second campaign with a different sentinel into them would change what
the committed record.json means.
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from settling_common import (CAPACITY_WAIT_S, GRID_POINTS, grid_complete,  # noqa: E402
                             measurements_present, pdk_stamp, run_klt, sha256)

sys.path.insert(0, str(HERE))
import make_request as mk  # noqa: E402

PARTIALS = HERE / ".partials"      # per-variant results, gitignored
ARTIFACTS = HERE / ".artifacts"    # raw klt report / batch receipt, gitignored
VARIANTS = mk.I106_VARIANTS
SENTINEL = mk.I106_SENTINEL
# The boundary common mode (DR-005), the same value make_request.render()
# centres vinp/vinn on and the deck drives onto `vcm`.
VCM = 0.9


# ------------------------------------------------------------- plumbing -----
def shas(v):
    return {"request_sha256": sha256(HERE / f"request_i106_{v}.json"),
            "deck_sha256": sha256(HERE / mk.deck_name(v))}


def partial_path(v):
    return PARTIALS / f"i106-{v}.json"


def load_partial(v):
    """A previously-run variant, if it matches the current request and deck."""
    p = partial_path(v)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except ValueError:
        return None
    cur = shas(v)
    if {k: d.get(k) for k in cur} != cur:
        print(f"NOTE: ignoring stale .partials/{p.name} (request or deck changed "
              "since it ran)", file=sys.stderr)
        return None
    return d


def save_partial(v, result):
    PARTIALS.mkdir(exist_ok=True)
    partial_path(v).write_text(json.dumps(result, indent=2) + "\n")


def summarize(corners):
    """Corner counts plus the worst sampling error -- never a pass/fail."""
    ok = [k for k, c in corners.items() if c["status"] == "pass"]
    return {"corner_count": len(corners), "pass": len(ok),
            "fail": len(corners) - len(ok)}


def submit(v, tmp, probe=False, hosts=None, capacity_wait_s=CAPACITY_WAIT_S):
    req = HERE / f"request_i106_{v}.json"
    tag = f"i106-{v}"
    res = run_klt(req, probe, tmp, tag, HERE / f"probe_request_{tag}.json",
                  artifacts_dir=None if probe else ARTIFACTS, keys=mk.I106_KEYS,
                  hosts=None if probe else hosts, capacity_wait_s=capacity_wait_s)
    if res is None:
        print(f"{tag}: no usable report (see .artifacts/klt-{tag}.stderr.txt); not "
              "falling back to a local grid or to .partials/", file=sys.stderr)
        return None
    rep, corners = res
    e = rep.get("environment", {})
    return {"summary": summarize(corners), "corners": corners,
            "pass": rep.get("status") == "pass",
            "ngspice": e.get("engine_version", "unknown"),
            "engine_host": e.get("engine_host"), "remote": e.get("remote"),
            **shas(v)}


# ---------------------------------------------------------- derivations -----
def windows_nonempty(corners_list):
    """True if every window divisor is a positive fraction of stored points.

    `bpip_s4` and friends are `mean(v*mask)/w_s4`: a `w_` of zero is a window
    with no stored timepoint in it, which makes the plate readings 0/0 rather
    than a measurement. The sentinel gate cannot catch that on its own, because
    an arithmetic combination of NaNs can still come back as a number.
    """
    bad = []
    for i, c in enumerate(corners_list):
        for cid, row in sorted(c.items()):
            for k in mk.I106_WINDOW_KEYS:
                w = row.get(k)
                if w is None or not (0.0 < float(w) <= 1.0):
                    bad.append((i, cid, k, w))
    if bad:
        i, cid, k, w = bad[0]
        print(f"REFUSE: {len(bad)} empty or impossible measurement window(s); first "
              f"is {k} = {w} at {cid} (set {i}). A window with no stored timepoint "
              "is not a measurement, so no record is written.", file=sys.stderr)
        return False
    return True


def corner_rows(variant_result, vin_diff):
    """Per-corner sampling numbers for one amplitude.

    `error_rel` is issue #106's `1 - sampled/ideal`, signed: positive is
    INCOMPLETE sampling. `ideal` is the applied differential input, because the
    bottom plates start the phase at vcm (the previous phi2 reset them) and
    phi1 drives them to vinp/vinn, so a complete sample puts exactly vin_diff
    across Csi differentially.
    """
    out = {}
    half = vin_diff / 2.0
    for cid, c in variant_result["corners"].items():
        sampled = c.get(SENTINEL)
        by_cycle = {}
        for k in mk.SAMP_CYCLES:
            s = c.get(f"samp_s{k}")
            by_cycle[f"c{k}"] = None if s is None else 1.0 - s / vin_diff
        row = {
            "ideal_V": vin_diff,
            "sampled_V": sampled,
            "error_rel": None if sampled is None else 1.0 - sampled / vin_diff,
            "error_rel_by_cycle": by_cycle,
            # The two sides see different switch resistances because the NMOS
            # and PMOS halves are each strong on one side of vcm and weak on
            # the other, so the deficit is not shared equally. Signed, with the
            # sign of "short of its target".
            "bpi_p_V": c.get(f"bpip_s{mk.SAMP_REPORT}"),
            "bpi_n_V": c.get(f"bpin_s{mk.SAMP_REPORT}"),
            "bpi_p_shortfall_V": (None if c.get(f"bpip_s{mk.SAMP_REPORT}") is None
                                  else (VCM + half) - c[f"bpip_s{mk.SAMP_REPORT}"]),
            "bpi_n_shortfall_V": (None if c.get(f"bpin_s{mk.SAMP_REPORT}") is None
                                  else c[f"bpin_s{mk.SAMP_REPORT}"] - (VCM - half)),
            # These sit at 0.9 V only while Sci still pins both top plates to
            # vcm at the phi1e fall. That is NOT a given: at the slow/cold
            # corners it departs (78.9 mV on the p side at fs/1.620V/-40C,
            # 0.6 V), which is what makes the across-Csi reading do real work.
            "tpi_p_V": c.get(f"tpip_s{mk.SAMP_REPORT}"),
            "tpi_n_V": c.get(f"tpin_s{mk.SAMP_REPORT}"),
            # Same charge, read in the following non-overlap gap where both
            # plates float. Their difference is the phi1/Sin turn-off injection
            # onto the bottom plate, which is issue #102's mechanism, not this
            # one -- recorded so the two cannot be confused.
            "frozen_V": c.get(f"samp_f{mk.SAMP_REPORT}"),
            "frozen_minus_sampled_V": (
                None if c.get(f"samp_f{mk.SAMP_REPORT}") is None or sampled is None
                else c[f"samp_f{mk.SAMP_REPORT}"] - sampled),
            # The same instant read on the bottom plates ALONE, which is the
            # literal form issue #106 reported. It is not the same number: Sci
            # is resistive too at a slow/cold corner, so the top plates are not
            # exactly at vcm when phi1e opens, and the difference between the
            # two forms is precisely that top-plate differential. What phi2
            # transfers onto Ci is the charge on Csi, i.e. the ACROSS-plate
            # reading -- so `sampled_V` is the headline and this one is carried
            # for comparison with the filing, never instead of it.
            "sampled_bpi_only_V": c.get(f"samp_bpi_s{mk.SAMP_REPORT}"),
            "top_plate_differential_V": (
                None if c.get(f"tpip_s{mk.SAMP_REPORT}") is None
                or c.get(f"tpin_s{mk.SAMP_REPORT}") is None
                else c[f"tpip_s{mk.SAMP_REPORT}"] - c[f"tpin_s{mk.SAMP_REPORT}"]),
            "error_rel_bpi_only": (
                None if c.get(f"samp_bpi_s{mk.SAMP_REPORT}") is None
                else 1.0 - c[f"samp_bpi_s{mk.SAMP_REPORT}"] / vin_diff),
            "window_occupancy": c.get(f"w_s{mk.SAMP_REPORT}"),
            "status": c["status"],
            "diagnostics": c.get("diagnostics", []),
        }
        row["error_vs_reference_line"] = (
            None if row["error_rel"] is None
            else abs(row["error_rel"]) / mk.SAMP_REFERENCE_LINE)
        out[cid] = row
    return out


def derive(results):
    """Per-corner rows, the binding corner, and the reference-line comparison."""
    per_amp, binding = {}, None
    for v in VARIANTS:
        vin_diff = mk.i106_variant(v)["vin_diff"]
        half = vin_diff / 2.0
        rows = corner_rows(results[v], vin_diff)
        vals = [(abs(r["error_rel"]), cid) for cid, r in rows.items()
                if r["error_rel"] is not None]
        worst = max(vals) if vals else None
        over = sorted(cid for cid, r in rows.items()
                      if r["error_rel"] is not None
                      and abs(r["error_rel"]) > mk.SAMP_REFERENCE_LINE)
        per_amp[v] = {
            "vinp_V": VCM + half, "vinn_V": VCM - half, "ideal_V": vin_diff,
            "per_side_offset_from_vcm_V": half,
            "worst_corner": None if worst is None else worst[1],
            "worst_error_rel": None if worst is None else rows[worst[1]]["error_rel"],
            "corners_over_reference_line": over,
            "corners_over_reference_line_count": len(over),
            "per_corner": rows,
        }
        if worst is not None and (binding is None or worst[0] > binding[0]):
            binding = (worst[0], v, worst[1])
    out = {
        "reference_line_rel": mk.SAMP_REFERENCE_LINE,
        "reference_line_label": (
            "REFERENCE LINE, NOT A LIMIT. 1e-4 relative is the starting level "
            "sim/integrator-settling grades its DR-005 settling against; it is "
            "reused here only so the sampling error has a scale this repo already "
            "uses. No ratified spec row bounds input-sampling completeness, this "
            "bench does not add one, and no measurement in the request carries "
            "`limits`. A corner listed in corners_over_reference_line has NOT "
            "failed anything."),
        "amplitudes": per_amp,
    }
    if binding is not None:
        _, v, cid = binding
        out["binding"] = {
            "amplitude": v, "corner": cid,
            "error_rel": per_amp[v]["per_corner"][cid]["error_rel"],
            "sampled_V": per_amp[v]["per_corner"][cid]["sampled_V"],
            "ideal_V": per_amp[v]["ideal_V"],
        }
    # Input-level dependence: the whole reason two amplitudes are recorded. A
    # sampling error that is the same fraction at both amplitudes is a gain
    # error; one that is not is distortion.
    if all(per_amp[v]["worst_error_rel"] is not None for v in VARIANTS):
        a, b = VARIANTS
        rows_a = per_amp[a]["per_corner"]
        rows_b = per_amp[b]["per_corner"]
        shared = sorted(set(rows_a) & set(rows_b))
        spread = [(abs(rows_a[cid]["error_rel"] - rows_b[cid]["error_rel"]), cid)
                  for cid in shared
                  if rows_a[cid]["error_rel"] is not None
                  and rows_b[cid]["error_rel"] is not None]
        worst_cid = max(spread)[1] if spread else None
        out["input_level_dependence"] = {
            "note": ("error_rel at the two amplitudes, corner by corner. Equal "
                     "fractions would be a pure gain error; a difference is a "
                     "level-dependent error, i.e. distortion. This bench measures "
                     "the difference, it does not convert it into a distortion or "
                     "SNDR figure -- nothing here has been through model B."),
            "worst_difference_corner": worst_cid,
            "worst_difference_rel": max(spread)[0] if spread else None,
            f"error_rel_{a}_at_worst": (None if worst_cid is None
                                        else rows_a[worst_cid]["error_rel"]),
            f"error_rel_{b}_at_worst": (None if worst_cid is None
                                        else rows_b[worst_cid]["error_rel"]),
        }
    return out


def conditions():
    return {
        "ibias_uA": 5, "vcm_V": VCM,
        "clock_mhz": mk.FS_HZ / 1e6, "clock_period_ns": mk.T_CLK * 1e9,
        "cycles_simulated": mk.N_CYC,
        "sampling_cycles_read": list(mk.SAMP_CYCLES),
        "reported_cycle": mk.SAMP_REPORT,
        "phi1_sampling_time_ns": mk.SAMP_PHI1_NS,
        "phi1_high_ns": mk.SAMP_PHI1_HIGH_NS,
        "phi1e_high_ns": round(mk.SAMP_PHI1_NS - 0.1, 6),
        "phi1_duration_note": (
            f"the input path has {mk.SAMP_PHI1_NS} ns: phi1 closes Sin at 0.1 ns "
            f"into the cycle and phi1e opens Sci at {mk.SAMP_PHI1_NS + 0.1} ns, "
            "which is when the charge on Csi is frozen. phi1 itself stays closed "
            "to 92.5 ns, but that moves both plates of Csi together and cannot "
            "change the sampled charge."),
        "sample_window_ns": [mk.W_SAMP[0] * 1e9, mk.W_SAMP[1] * 1e9],
        "frozen_window_ns": [mk.W_FROZEN[0] * 1e9, mk.W_FROZEN[1] * 1e9],
        "which_reading_is_the_headline": (
            "sampled_V (across Csi). What phi2 transfers onto Ci is the charge "
            "stored on Csi, which is Cs times the ACROSS-plate voltage at the "
            "phi1e fall. At a slow/cold corner Sci is resistive too, so the top "
            "plates are not exactly at vcm then and the bottom-plate-only "
            "reading (sampled_bpi_only_V) is larger by exactly the top-plate "
            "differential -- at ss/1.620V/-40C and the 0.2 V amplitude, 0.0991 V "
            "against 0.0914 V. The across-plate reading is the one that matches "
            "the per-clock output step issue #106 reported, so error_rel is "
            "computed from it; error_rel_bpi_only is carried alongside."),
        "measured_quantity": (
            "samp_s<k> = the differential voltage across Csi, (bpi_p - tpi_p) - "
            "(bpi_n - tpi_n), as a mean over the last 0.8 ns of phi1e in cycle k. "
            "Do NOT read this as equal to v(xint.bpi_p) - v(xint.bpi_n): that "
            "equality holds only while Sci still pins both top plates to vcm at "
            "the phi1e fall, which is true to the reported precision over most of "
            "the grid but false at the slow/cold corners -- at fs/1.620V/-40C and "
            "the 0.6 V amplitude the two forms differ by 78.9 mV. The "
            "bottom-plate-only form is carried alongside as sampled_bpi_only_V "
            "and their difference as top_plate_differential_V; "
            "which_reading_is_the_headline says which one error_rel uses."),
        "reset": "bench-only ideal 1 ohm switches across Ci until 40 ns (cell has none)",
        "clocks": ("behavioural rail-to-rail on Vdda from PULSE shape sources, "
                   "200 ps edges, >= 4.7 ns non-overlap, no non-overlap generator"),
        "load_per_side": mk.LOADNOTE,
        "spice_options": "reltol=1e-5 vntol=1e-7 abstol=1e-13 chgtol=1e-16 (in the deck)",
        "dac": mk.DACS["nulled"]["note"],
        "amplitudes": {v: {"vin_diff_V": mk.i106_variant(v)["vin_diff"],
                           "note": mk.i106_variant(v)["note"]} for v in VARIANTS},
        "switch_under_test": (
            "XSin_<p,n>_n = sky130_fd_pr__nfet_01v8 W 4 / L 0.15 in parallel with "
            "XSin_<p,n>_p = sky130_fd_pr__pfet_01v8 W 8 / L 0.15, gated by "
            "phi1/phi1b -- a complementary pass gate with no low-Vth half. Its DC "
            "Ron versus the voltage it passes is sim/switch-probe/probe-i106.json."),
    }


# ----------------------------------------------------------------- main -----
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdk-root")
    ap.add_argument("--variant", action="append", choices=VARIANTS,
                    help="run only this amplitude (repeatable); default: all")
    ap.add_argument("--probe", choices=VARIANTS,
                    help="one tt/27C/1.8V corner of an amplitude, local, no record")
    ap.add_argument("--from-partials", action="store_true",
                    help="assemble the record from the cached .partials/ only, "
                         "submitting nothing. Every amplitude must already have a "
                         "non-stale partial or the run refuses. A partial exists "
                         "only where a submit SUCCEEDED, so it cannot backfill a "
                         "failed submit (the issue #94 rule).")
    ap.add_argument("--record", action="store_true",
                    help="write the record (refuses to overwrite: records are append-only)")
    ap.add_argument("--record-name", help="record file name (default: record-i106.json)")
    ap.add_argument("--capacity-wait", type=int, default=CAPACITY_WAIT_S, metavar="S",
                    help=f"seconds to wait for fleet capacity before giving up "
                         f"(default {CAPACITY_WAIT_S}, the host-rule floor)")
    ap.add_argument("--hosts", type=int, metavar="N",
                    help="shard each submission across N fleet instances; does not "
                         "change the request file")
    a = ap.parse_args()

    pin = json.load(open(REPO / "sim/pdk.json"))
    root, stamp = pdk_stamp(pin["variant"], a.pdk_root)
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'",
              file=sys.stderr)
        return 2
    out = HERE / (a.record_name or "record-i106.json")
    if a.record and out.exists():
        print(f"REFUSE: {out.name} exists; records are append-only (use --record-name)",
              file=sys.stderr)
        return 2
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="integrator-sampling-"))
    try:
        if a.probe:
            res = submit(a.probe, tmp, probe=True)
            if res is None:
                print(f"REFUSE: no result for the {a.probe} probe; nothing printed.",
                      file=sys.stderr)
                return 1
            print(json.dumps(res["corners"], indent=2))
            return 0

        if a.from_partials:
            if a.variant:
                print("REFUSE: --from-partials submits nothing, so --variant has "
                      "no meaning with it", file=sys.stderr)
                return 2
            run = ()
        else:
            run = tuple(dict.fromkeys(a.variant)) if a.variant else VARIANTS

        results = {}
        for v in VARIANTS:
            if v not in run:
                saved = load_partial(v)
                if saved:
                    print(f"{v}: reusing {partial_path(v).name} ({saved['summary']})")
                    results[v] = saved
                continue
            res = submit(v, tmp, hosts=a.hosts, capacity_wait_s=a.capacity_wait)
            if res is None:
                continue
            print(v, json.dumps(res["summary"], indent=2))
            results[v] = res
            save_partial(v, res)

        missing = [v for v in VARIANTS if v not in results]
        if missing:
            how = ("no cached partial for" if a.from_partials else "no result for")
            print(f"REFUSE: {how} {', '.join(missing)}; no record written. "
                  f"Re-run with --variant {missing[0]} when the fleet has capacity.",
                  file=sys.stderr)
            return 1

        corner_sets = [results[v]["corners"] for v in VARIANTS]
        if not grid_complete(corner_sets, GRID_POINTS):
            return 1
        if not measurements_present(corner_sets, SENTINEL):
            return 1
        if not windows_nonempty(corner_sets):
            return 1
        if not a.record:
            print("all amplitudes complete; re-run with --record to write the record")
            return 0

        rec = {
            "fixture": ("Integrator input-sampling bench (issue #106): the full "
                        "integrator cell + ota_fd clocked for "
                        f"{mk.N_CYC} complete phi1/phi2 cycles; the differential "
                        "charge the input pass gate `Sin` delivered onto Csi, read "
                        "at the instant phi1e falls and the sample is frozen"),
            "result_kind": ("simulated (ngspice, transistor-level netlists of "
                            "design/integrator + design/ota/ota_fd; not the "
                            "behavioural model). SIMULATED, NEVER MEASURED."),
            "run_kind": "nominal_corner_grid",
            "assembled_from": ("cached .partials/ (fleet results from an earlier "
                               "invocation; nothing was submitted for this record)"
                               if a.from_partials else "this invocation's submissions"),
            "conditions": conditions(),
            "corner_set": "DR-002 full grid, 5 process x 3 T x 3 Vdda, per amplitude",
            "pass_criterion": (
                "NONE. This is an extraction, not a spec check. No measurement in "
                "either request carries a limit, and no ratified spec row bounds "
                "input-sampling completeness -- so this record states none, relaxes "
                "none, and adds none. The `pass` field below means only that every "
                "corner simulated without erroring; it is not a verdict on the "
                "circuit. The error is reported against a labelled reference line "
                "(derived.reference_line_label), which is a scale and not a "
                "threshold. No SNDR, ENOB or resolution consequence is claimed or "
                "implied: nothing here has been through model B."),
            "pdk_sources_stamp": stamp,
            "pdk_pin": {"file": "sim/pdk.json",
                        "open_pdks_revision": pin["open_pdks_revision"]},
            "klt": subprocess.run(["klt", "--version"], capture_output=True,
                                  text=True).stdout.strip(),
            "integrator_netlist_sha256": sha256(REPO / "design/integrator/integrator.spice"),
            "ota_netlist_sha256": sha256(REPO / "design/ota/ota_fd.spice"),
            "related_evidence": {
                "switch_ron_vs_input": "sim/switch-probe/probe-i106.json",
                "charge_injection_extraction": "sim/integrator-ci/record.json (issue #102)",
            },
            "amplitudes": results,
            "pass": all(r["pass"] for r in results.values()),
        }
        rec["derived"] = derive(results)
        out.write_text(json.dumps(rec, indent=2) + "\n")
        print(f"wrote {out.name}: pass={rec['pass']}, "
              f"binding={rec['derived'].get('binding')}")
        return 0 if rec["pass"] else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

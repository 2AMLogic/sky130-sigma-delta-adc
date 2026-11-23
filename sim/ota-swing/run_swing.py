#!/usr/bin/env python3
"""OTA output-swing / gain-compression runner (simulated, transistor-level).

See README.md. Submits request.json (DR-002 anchor set, 7 points; both load
cells in the one deck) through `klt sim` to the batch fleet; never falls back
to a local grid.

    python3 -I sim/ota-swing/run_swing.py --probe    # 1 local corner, no record
    python3 -I sim/ota-swing/run_swing.py            # the 7 anchors
    python3 -I sim/ota-swing/run_swing.py --record   # write record.json

A completed run is saved under .partials/, so --record can be run later
without re-simulating. A run requested in this invocation is NEVER served
from .partials/: a failed submit must not be reported as a result (issue
#94's rule, as in run_settling.py / run_tran.py).

Per anchor and cell the record carries the settled closed-loop transfer over
the amplitude grid, the extracted effective open-loop DC gain versus output
swing, the 1 dB and 3 dB compression points, the single-ended output range
and the output common-mode shift at those points, and the interpolated gain
at the integrator swings PR #257's c0p3 modulator record actually visited --
the figure the operator ruling on #148 conditions the section 5.4
clarification on.
"""
import argparse
import json
import math
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
import settling_common as sc  # noqa: E402
from settling_common import pdk_stamp, run_klt, sha256  # noqa: E402

sys.path.insert(0, str(HERE))
import make_request as mk  # noqa: E402

PARTIALS = HERE / ".partials"     # gitignored
ARTIFACTS = HERE / ".artifacts"   # gitignored
SCRATCH = PARTIALS / "klt-run"    # klt's shard map / receipts, gitignored

KEYS = ("vdda_v",)                # scalar per-corner measurements

# The committed reference table: the integrator output swings PR #257's c0p3
# modulator transient actually recorded, per DR-002 anchor. Read from that
# PR's sim/modulator-tran/record-c0p3.json (not merged; #257 is on an
# operator ratification hold), at PR head 80167c7. The file's sha256 and the
# commit are cited in every record this bench writes; if #257 re-records
# before merging, re-derive this table from the merged record and re-run.
C0P3_RECORD_SHA256 = "0da6c2070e3b3db444d4f5781f9751fd10698b042a2a3976128a49e625257b9b"
C0P3_RECORD_FROM = ("sim/modulator-tran/record-c0p3.json at PR #257 head "
                    "80167c7d1f8cf7e195cf66ed5652207528e0a6d1")
# per anchor (process, vdda, temp_c): o1/o2 differential swing Vpp, and the
# worst single-ended pp (o1p/o2p node range width)
C0P3_SWINGS = {
    ("tt", 1.80, 27):   {"o1_swing_pp": 2.475258, "o2_swing_pp": 1.566816},
    ("ss", 1.62, 125):  {"o1_swing_pp": 2.296592, "o2_swing_pp": 1.544747},
    ("ss", 1.62, -40):  {"o1_swing_pp": 2.274651, "o2_swing_pp": 1.384408},
    ("ff", 1.98, -40):  {"o1_swing_pp": 2.529588, "o2_swing_pp": 1.604727},
    ("ff", 1.98, 125):  {"o1_swing_pp": 2.521563, "o2_swing_pp": 1.608825},
    ("sf", 1.80, 27):   {"o1_swing_pp": 2.475657, "o2_swing_pp": 1.558681},
    ("fs", 1.80, 27):   {"o1_swing_pp": 2.401449, "o2_swing_pp": 1.589446},
}
C0P3_WORST_SE_VPP = {"o1": 1.279, "o2": 0.812}   # single-ended, worst anchor

# The comparison column: sim/ota-gain's 45-corner open-loop DC-gain record
# (issue #126). Its small-signal value (the ac gain at vod = 0) is what this
# bench's 0.2 Vpp reference point must reproduce; a disagreement larger than
# the tolerance below means the extraction is not measuring the same gain.
GAIN_RECORD = REPO / "sim/ota-gain/record.json"
GAIN_XCHECK_TOL_DB = 0.5

ERR_MIN_REL = 1e-5     # below this the (target - vod) difference is not resolvable


def db(a):
    return None if a is None or a <= 0 else 20.0 * math.log10(a)


def corner_key(c):
    """(process, vdda, temp) -- the anchor identity, independent of corner_id text."""
    return (c["process"], round(float(c["supply_v"]["vdda"]), 3), int(c["temperature_c"]))


def anchor_key(anchor):
    return (anchor[0], round(float(anchor[1]), 3), int(anchor[2]))


# ------------------------------------------------------------ extraction --
def extract(rep):
    """{corner_id: entry} from a klt sim report, segments keyed per cell."""
    corners = {}
    for c in rep["corners"]:
        m = {x["name"]: x for x in c["measurements"]}
        segs = {}
        for i, seg in enumerate(mk.SEGMENTS):
            pol = "u" if seg["direction"] > 0 else "d"
            for cell in sorted(mk.CELLS):
                name = mk.seg_name(cell, i, pol, "")
                vals = {k: m.get(f"{name}{k}", {}).get("value") for k in ("vod", "outp", "outn", "rip")}
                segs.setdefault(cell, {})[f"{i:02d}{pol}"] = {
                    "amp_vpp": seg["amp_vpp"], "direction": seg["direction"], **vals}
        corners[c["corner_id"]] = {
            "status": c["status"], "corner_key": corner_key(c),
            "runtime_s": c.get("runtime_s"),
            "vdda_v": m.get("vdda_v", {}).get("value"),
            "segments": segs,
            "diagnostics": sorted({d["code"] for d in c.get("diagnostics", [])}),
        }
    return corners


# ------------------------------------------------------------ derivation --
def seg_gain(seg, beta):
    """(A_eff V/V, settled vod) for one segment, or (None, vod).

    Exact inversion of the settled closed-loop relation
    vod = target * beta*A / (1 + beta*A), target = amp/2:
    A_eff = |vod| / (beta * (|target| - |vod|)).
    """
    vod = seg["vod"]
    target = seg["amp_vpp"] / 2.0
    if vod is None:
        return None, None
    err = target - abs(vod)
    if err <= 0 or err / target < ERR_MIN_REL:
        return None, vod        # railed past the target, or unresolvable
    return abs(vod) / (beta * err), vod


def interp(x, xs, ys):
    """Linear interpolation of ys over xs at x; None outside [xs[0], xs[-1]]."""
    if x < xs[0] or x > xs[-1]:
        return None
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


def compression_point(amps, comp_db, level_db):
    """First amplitude where comp <= -level_db, linearly interpolated; else None."""
    for i in range(1, len(amps)):
        if comp_db[i] <= -level_db:
            a0, a1, c0, c1 = amps[i - 1], amps[i], comp_db[i - 1], comp_db[i]
            if c1 == c0:
                return a1
            return a0 + (a1 - a0) * (-level_db - c0) / (c1 - c0)
    return None


def gain_at(amps, gains, swing_vpp):
    """Interpolated gain (dB) at a differential swing, or None beyond the grid."""
    return interp(swing_vpp, amps, gains)


def derive_cell(segments, cell):
    """The per-(anchor, cell) table the record carries."""
    beta_c = mk.beta(mk.CELLS[cell]["ci_pf"])
    rows = []
    for i, seg in enumerate(mk.SEGMENTS):
        pol = "u" if seg["direction"] > 0 else "d"
        s = segments[cell][f"{i:02d}{pol}"]
        a_eff, vod = seg_gain(s, beta_c)
        ocm = None if (s["outp"] is None or s["outn"] is None) \
            else 0.5 * (s["outp"] + s["outn"])
        rows.append({"amp_vpp": s["amp_vpp"], "pol": pol, "vod_settled_v": vod,
                     "gain_v_per_v": a_eff, "gain_db": db(a_eff),
                     "outp_v": s["outp"], "outn_v": s["outn"],
                     "ocm_v": ocm, "drift_v": None if (vod is None or s["rip"] is None)
                     else abs(vod - s["rip"])})
    # per amplitude: the worse polarity (compression is symmetric in sign;
    # device mismatch does not exist in this nominal grid, but the worst
    # polarity is what the modulator would experience)
    per_amp = {}
    for r in rows:
        a = r["amp_vpp"]
        cur = per_amp.get(a)
        if cur is None or (r["gain_db"] is not None
                           and (cur["gain_db"] is None or r["gain_db"] < cur["gain_db"])):
            per_amp[a] = r
    amps_sorted = sorted(per_amp)
    gains = [per_amp[a]["gain_db"] for a in amps_sorted]
    ref = gains[0]     # amp index 0 is the small-signal reference (mk.SMALL_REF_VPP)
    comp = [None if (g is None or ref is None) else g - ref for g in gains]
    usable = all(g is not None for g in gains)
    cp1 = compression_point(amps_sorted, comp, 1.0) if usable else None
    cp3 = compression_point(amps_sorted, comp, 3.0) if usable else None
    se_at = {}
    for cp in filter(None, (cp1, cp3)):
        near = _nearest(amps_sorted, cp)
        pes = [r for r in rows if r["amp_vpp"] == near
               and r["outp_v"] is not None and r["outn_v"] is not None]
        ses = [v for r in pes for v in (r["outp_v"], r["outn_v"])] if pes else None
        ocm_r = per_amp[near]
        se_at[f"{cp:.4g}"] = {
            "single_ended_range_v": None if ses is None else [min(ses), max(ses)],
            "ocm_shift_v": None if (ocm_r["ocm_v"] is None or rows[0]["ocm_v"] is None)
            else ocm_r["ocm_v"] - rows[0]["ocm_v"],
        }
    return {
        "cell": cell, "label": mk.CELLS[cell]["label"],
        "ci_pf": mk.CELLS[cell]["ci_pf"], "beta": beta_c,
        "small_signal_gain_db": ref,
        "gain_vs_swing": [{"amp_vpp": a, "gain_db": per_amp[a]["gain_db"],
                           "comp_db": c, "vod_settled_v": per_amp[a]["vod_settled_v"],
                           "ocm_v": per_amp[a]["ocm_v"]}
                          for a, c in zip(amps_sorted, comp)],
        "compression": {
            "cp1_vpp": cp1, "cp3_vpp": cp3,
            "not_reached_note": None if (cp3 is not None or not usable)
            else f"gain has not fallen 3 dB by {amps_sorted[-1]:g} Vpp",
            "worst_drift_v": max((r["drift_v"] or 0.0) for r in rows),
        },
        "at_compression_points": se_at,
        "segments": rows,
    }


def _nearest(amps, x):
    return min(amps, key=lambda a: abs(a - x))


def gain_xcheck(corners, derived):
    """Comparison against sim/ota-gain's 45-corner record, per anchor.

    One row per expected (cell, corner): a swing corner the reference record
    does not carry gets an explicit missing-reference row (no record value,
    delta None) that gain_reference_matches refuses -- a missing comparison
    must never pass as a verified one (issue #338). An empty return means
    the reference record itself could not be read.
    """
    try:
        rec = json.loads(GAIN_RECORD.read_text())
    except (OSError, ValueError):
        return {}
    out = {}
    for cid, d in derived.items():
        key = corners[cid]["corner_key"]
        gid = f"{key[0]}/{key[1]:.3f}V/{key[2]:g}C"
        row = rec.get("corners", {}).get(gid)
        for cell in ("a", "b"):
            small = d[cell]["small_signal_gain_db"]
            if row is None:
                out.setdefault(cell, {})[cid] = {
                    "ota_gain_record_db": None,
                    "this_bench_small_signal_db": small,
                    "delta_db": None,
                    "missing_reference": gid,
                }
                continue
            out.setdefault(cell, {})[cid] = {
                "ota_gain_record_db": row["dc_gain_db"],
                "this_bench_small_signal_db": small,
                "delta_db": None if small is None else small - row["dc_gain_db"],
            }
    return out


# ------------------------------------------------------------ record gates --
def anchors_complete(corners, expected=len(sc.ANCHOR_POINTS)):
    want = {anchor_key(a) for a in sc.ANCHOR_POINTS}
    got = {c["corner_key"] for c in corners.values()}
    if len(corners) != expected or got != want:
        print(f"REFUSE: {len(corners)} of {expected} DR-002 anchor points returned "
              f"(missing: {sorted(want - got)}, unexpected: {sorted(got - want)}); "
              "no record written", file=sys.stderr)
        return False
    return True


def segments_present(corners):
    bad = []
    for cid, c in sorted(corners.items()):
        for cell in sorted(mk.CELLS):
            want = len(mk.SEGMENTS)
            got = c["segments"].get(cell, {})
            if len(got) != want:
                bad.append(f"{cid}:cell{cell} {len(got)}/{want} segments")
                continue
            for name, s in sorted(got.items()):
                if any(s[k] is None for k in ("vod", "outp", "outn", "rip")):
                    bad.append(f"{cid}:cell{cell}:{name} missing a measurement")
    if bad:
        print(f"REFUSE: {len(bad)} segment(s) missing or unmeasured ({bad[:6]}"
              f"{', ...' if len(bad) > 6 else ''}); nothing was simulated there, "
              "so no record is written", file=sys.stderr)
        return False
    return True


def segments_settled(corners, limit_v=mk.RIPPLE_MAX_V):
    bad = []
    for cid, c in sorted(corners.items()):
        for cell in sorted(mk.CELLS):
            for name, s in sorted(c["segments"][cell].items()):
                d = abs(s["vod"] - s["rip"])
                if d > limit_v:
                    bad.append((cid, cell, name, d))
    if bad:
        worst = max(bad, key=lambda b: b[3])
        print(f"REFUSE: {len(bad)} segment(s) still moving at the measurement "
              f"instant (worst {worst[3]*1e3:.3f} mV on {worst[0]}:{worst[1]}:"
              f"{worst[2]}, limit {limit_v*1e3:g} mV); an unsettled reading is "
              "not a settled gain, so no record is written", file=sys.stderr)
        return False
    return True


def gain_reference_matches(xcheck, tol=GAIN_XCHECK_TOL_DB):
    """The 0.2 Vpp reference must reproduce sim/ota-gain at every anchor.

    This is the bench's own validity gate: the whole compression curve is
    normalized to the small-signal value, so if that value disagrees with the
    independent 45-corner record by more than `tol`, the curve is not the
    OTA's gain and the record refuses. A comparison row whose reference
    corner is missing from that record refuses too. An empty comparison
    means the record could not be read: nothing was verified, which refuses
    too.
    """
    if not xcheck:
        print("REFUSE: no anchor could be compared against sim/ota-gain's "
              "record (unreadable record, or no corner mapped onto it); the "
              "small-signal reference is unverified, so no record is written",
              file=sys.stderr)
        return False
    missing = sorted({(row["missing_reference"], cell, cid)
                      for cell, per in xcheck.items()
                      for cid, row in per.items()
                      if "missing_reference" in row})
    if missing:
        print(f"REFUSE: sim/ota-gain's record has no entry for {missing[:4]}"
              f"{', ...' if len(missing) > 4 else ''}; the small-signal "
              "reference is unverified there, so no record is written",
              file=sys.stderr)
        return False
    bad = []
    for cell, per in xcheck.items():
        for cid, row in sorted(per.items()):
            d = row["delta_db"]
            if d is None or abs(d) > tol:
                bad.append((cell, cid, d))
    if bad:
        print(f"REFUSE: the small-signal reference disagrees with sim/ota-gain "
              f"by more than {tol:g} dB at {bad[:4]}{', ...' if len(bad) > 4 else ''}; "
              "the compression curve would not be the OTA's gain, so no record "
              "is written", file=sys.stderr)
        return False
    return True


# ------------------------------------------------------------ the record --
def swing_reference_block():
    return {
        "from": C0P3_RECORD_FROM,
        "file_sha256": C0P3_RECORD_SHA256,
        "note": ("The integrator swings this bench interpolates its gain at. "
                 "Not merged: PR #257 is on an operator ratification hold, and "
                 "this bench does not depend on it merging -- the c0p3 cell "
                 "values are parameterised from that PR's design/integrator/"
                 "SIZING.md, and the swing points are read from its c0p3 "
                 "modulator record. If that PR re-records before merging, "
                 "re-derive C0P3_SWINGS in run_swing.py from the merged record "
                 "and re-run this bench."),
        "per_anchor_vpp": {
            f"{p}/{v:.2f}/{t:g}": s for (p, v, t), s in sorted(C0P3_SWINGS.items())},
        "worst_single_ended_vpp": C0P3_WORST_SE_VPP,
    }


def build_record(results, derived, xcheck, stamp, pin, rep_env,
                 provenance=None):
    """`derived` and `xcheck` are the very ones the admission gate ran on
    (issue #338): the record serialises the comparison that passed, not a
    second one computed again at write time."""
    corners = results["corners"]

    summary_cells = {}
    for cell in sorted(mk.CELLS):
        per_anchor = {}
        for cid in sorted(derived):
            key = corners[cid]["corner_key"]
            d = derived[cid][cell]
            ref_swings = C0P3_SWINGS.get(key, {})
            per_anchor[cid] = {
                "small_signal_gain_db": d["small_signal_gain_db"],
                "cp1_vpp": d["compression"]["cp1_vpp"],
                "cp3_vpp": d["compression"]["cp3_vpp"],
                "gain_at_o1_swing_db": gain_at(
                    [g["amp_vpp"] for g in d["gain_vs_swing"]],
                    [g["gain_db"] for g in d["gain_vs_swing"]],
                    ref_swings.get("o1_swing_pp", 0.0)),
                "gain_at_o2_swing_db": gain_at(
                    [g["amp_vpp"] for g in d["gain_vs_swing"]],
                    [g["gain_db"] for g in d["gain_vs_swing"]],
                    ref_swings.get("o2_swing_pp", 0.0)),
                "o1_ref_swing_vpp": ref_swings.get("o1_swing_pp"),
                "o2_ref_swing_vpp": ref_swings.get("o2_swing_pp"),
            }
        worst_cp1 = min((v["cp1_vpp"], k) for k, v in per_anchor.items()
                        if v["cp1_vpp"] is not None) if any(
                            v["cp1_vpp"] is not None for v in per_anchor.values()) else None
        summary_cells[mk.CELLS[cell]["label"]] = {
            "per_anchor": per_anchor,
            "worst_cp1_vpp": None if worst_cp1 is None
            else {"value": worst_cp1[0], "corner": worst_cp1[1]},
        }

    # the plain statement the operator ruling asks for: at the swings the c0p3
    # modulator actually visited, has the OTA lost more than 3 dB of gain?
    verdicts = {}
    for label, cell in summary_cells.items():
        gains = [v["gain_at_o1_swing_db"] for v in cell["per_anchor"].values()]
        smalls = [v["small_signal_gain_db"] for v in cell["per_anchor"].values()]
        if any(g is None or s is None for g, s in zip(gains, smalls)):
            verdicts[label] = "inconclusive: a recorded swing lies outside the sweep grid"
        else:
            worst = min(g - s for g, s in zip(gains, smalls))
            verdicts[label] = {
                "worst_gain_drop_at_o1_swings_db": worst,
                "linear_within_3db": worst > -3.0,
                "statement": (
                    "the OTA stays within 3 dB of its small-signal gain at every "
                    "recorded integrator-1 swing (2.27-2.53 Vpp differential) at "
                    "all 7 anchors" if worst > -3.0 else
                    "the OTA compresses by more than 3 dB somewhere inside the "
                    "recorded integrator-1 swing range"),
            }
    return {
        "fixture": ("OTA output-swing / gain-compression bench (issue #331): "
                    "design/ota/ota_fd.spice as committed on main, one instance "
                    "per load, in the closed-loop integrate-phase configuration "
                    "the integrator presents (driven Cs + parked Cs + Cp on the "
                    "summing node, Ci feedback, beta = Ci/(Ci+2Cs+Cp), 1.1 pF "
                    "external load per side), swept over the DR-002 anchor set"),
        "result_kind": ("simulated (ngspice, transistor-level netlist of "
                        "design/ota/ota_fd; not the behavioural model). A "
                        "simulated number is never called measured."),
        "evidence_source": ("T (step 1 of the operator ruling on #148, "
                            "2026-11-17)"),
        "cells": {c: mk.CELLS[c] for c in sorted(mk.CELLS)},
        "corner_set": {
            "name": "DR-002 anchor set",
            "points": len(sc.ANCHOR_POINTS),
            "subset_statement": sc.ANCHOR_SUBSET_NOTE.replace("Monte Carlo",
                                                              "expensive sweeps"),
            "anchors": [{"process": p, "vdda_v": v, "temperature_c": t}
                        for p, v, t in sc.ANCHOR_POINTS],
        },
        "method": {
            "analysis": json.load(open(HERE / mk.REQUEST))["analysis"],
            "sequence": (f"per amplitude ({mk.AMPS_VPP[0]:g} Vpp small-signal "
                         f"reference, then {mk.SWEEP_VPP[0]:g}-{mk.SWEEP_VPP[-1]:g} Vpp) "
                         f"and polarity: {mk.T_RESET*1e9:g} ns reset (ideal switches "
                         "short out<->summing node, unity feedback, vod -> 0), "
                         f"{mk.NSTEP} accumulated plate steps of one clock's charge "
                         f"transfer each ({mk.T_STEP*1e9:g} ns apart, the phase is "
                         "97.66 ns), then a hold past the phase; the step edges "
                         "are bench drives on ideal capacitor plates, not switch "
                         "edges, and the driven-plate excursion is Ci/Cs x the "
                         "output swing by charge conservation -- bench-only, on "
                         "linear capacitors, and it does not touch the settled "
                         "operating point the gain is extracted from"),
            "extraction": ("A_eff = |vod| / (beta * (|target| - |vod|)), the "
                           "exact inversion of the settled closed-loop relation "
                           "vod = target*beta*A/(1+beta*A); beta is computed "
                           "from the bench capacitor values (Cp = 35 fF per side, "
                           "the hand-calc value the settling benches also keep; "
                           "the OTA's own input capacitance is not in it, which "
                           "is why the 0.2 Vpp reference point is gated against "
                           "the ota-gain record rather than assumed exact)"),
            "compression_points": ("first amplitude where the extracted gain has "
                                   "fallen 1 dB / 3 dB below its small-signal "
                                   "value (the 0.2 Vpp reference point), linearly "
                                   "interpolated on the gain-vs-swing curve; the "
                                   "worse of the two polarities"),
            "settledness_gate": (f"every segment is read twice, {mk.T_RIPPLE_BEFORE*1e9:g} ns "
                                 f"apart, and the record refuses if the output "
                                 f"moved more than {mk.RIPPLE_MAX_V*1e3:g} mV"),
            "leaves_out": ("slew and settling dynamics inside the phase "
                           "(sim/ota-settling owns those), noise, mismatch "
                           "(nominal grid), layout parasitics, and the "
                           "switch-charge-injection effects sim/integrator-ci "
                           "owns"),
        },
        "no_spec_budget": ("there is no ratified swing row this record grades "
                           "against: spec 5.4's ~1.39 Vpp figure is the number "
                           "the #148 ruling wants clarified, and this record is "
                           "the simulated evidence that clarification waits on. "
                           "`pass` below is the validity verdict (all anchors "
                           "measured, all segments settled, the small-signal "
                           "reference matching sim/ota-gain), not a spec verdict."),
        "conditions": {"vcm_V": 0.9, "ibias_uA": 5, "cs_pf": mk.CS_PF,
                       "cp_pf": mk.CP_PF, "cl_pf_per_side": mk.CL_PF,
                       "step_hold_ns": [mk.T_STEP * 1e9, mk.T_HOLD * 1e9],
                       "max_timestep_s": mk.T_MAX_STEP},
        "swing_reference": swing_reference_block(),
        "comparison_column": {
            "from": "sim/ota-gain/record.json (issue #126, 45-corner grid)",
            "why": ("its open-loop ac gain at vod = 0 is the small-signal value "
                    "this bench's 0.2 Vpp reference must reproduce; the gate "
                    f"tolerance is {GAIN_XCHECK_TOL_DB:g} dB (the reference is a "
                    "secant over 0.2 Vpp, not the vod = 0 tangent, and beta "
                    "omits the OTA's input capacitance)"),
            "per_anchor": xcheck,
        },
        "pdk_sources_stamp": stamp,
        "pdk_pin": {"file": "sim/pdk.json",
                    "open_pdks_revision": pin["open_pdks_revision"]},
        "klt": (provenance or {}).get("klt_version") or subprocess.run(
            ["klt", "--version"], capture_output=True, text=True).stdout.strip(),
        "ngspice": rep_env.get("engine_version", "unknown"),
        "engine_host": rep_env.get("engine_host"),
        "remote": rep_env.get("remote"),
        "batch_receipt": results.get("batch_receipt"),
        **sc.shas(HERE / mk.REQUEST, HERE / mk.DECK),
        "ota_netlist_sha256": sha256(REPO / "design/ota/ota_fd.spice"),
        "summary": {
            "corner_count": len(corners),
            "pass": sum(1 for c in corners.values() if c["status"] == "pass"),
            "fail": sum(1 for c in corners.values() if c["status"] != "pass"),
            "per_cell": summary_cells,
            "verdict": verdicts,
            "slowest_corner_runtime_s": max(
                ((c.get("runtime_s") or 0.0), cid) for cid, c in corners.items()),
        },
        "corners": {
            cid: {"status": c["status"], "corner_key": list(c["corner_key"]),
                  "vdda_v": c["vdda_v"], "runtime_s": c["runtime_s"],
                  "diagnostics": c["diagnostics"],
                  **derived[cid]}
            for cid, c in sorted(corners.items())},
        "pass": (all(c["status"] == "pass" for c in corners.values())),
    }


# ------------------------------------------------------------------- main --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--probe", action="store_true",
                    help="one tt/27C/1.8V corner, run locally, no record")
    ap.add_argument("--resume", action="store_true",
                    help="re-launch only the anchors a previous run left unfinished")
    ap.add_argument("--record", action="store_true",
                    help="write record.json (refuses to overwrite: records are append-only)")
    ap.add_argument("--record-name", default="record.json")
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

    saved = None
    if a.record:
        saved = sc.load_partial(PARTIALS / "swing.json",
                                sc.shas(HERE / mk.REQUEST, HERE / mk.DECK))

    if saved is None:
        if a.probe:
            tmp = pathlib.Path(tempfile.mkdtemp(prefix="ota-swing-probe-"))
        else:
            tmp = SCRATCH
            tmp.mkdir(parents=True, exist_ok=True)
        res = run_klt(HERE / mk.REQUEST, a.probe, tmp, "swing",
                      HERE / "probe_request_swing.json", keys=KEYS,
                      artifacts_dir=None if a.probe else ARTIFACTS,
                      resume=a.resume and not a.probe)
        if res is None:
            print("REFUSE: no usable report (see .artifacts/klt-swing.stderr.txt); "
                  "not falling back to a local grid or to .partials/", file=sys.stderr)
            return 1
        rep, _ = res
        corners = extract(rep)
        if a.probe:
            probe_key = ("tt", 1.8, 27)
            cid = next((k for k, c in corners.items() if c["corner_key"] == probe_key),
                       next(iter(corners)))
            c = corners[cid]
            d = {cell: derive_cell(c["segments"], cell) for cell in sorted(mk.CELLS)}
            print(json.dumps({cid: {cell: {
                "small_signal_gain_db": d[cell]["small_signal_gain_db"],
                "cp1_vpp": d[cell]["compression"]["cp1_vpp"],
                "cp3_vpp": d[cell]["compression"]["cp3_vpp"],
                "gain_vs_swing": d[cell]["gain_vs_swing"]}
                for cell in d}}, indent=2))
            return 0
        saved = {"corners": corners,
                 "environment": rep.get("environment", {}),
                 "provenance": rep.get("provenance", {}),
                 "batch_receipt": rep.get("batch_receipt"),
                 **sc.shas(HERE / mk.REQUEST, HERE / mk.DECK)}
        sc.save_partial(PARTIALS / "swing.json", saved)

    corners = saved["corners"]
    gates = (anchors_complete(corners)
             and segments_present(corners)
             and segments_settled(corners))
    if not gates:
        return 1
    derived = {cid: {cell: derive_cell(c["segments"], cell)
                     for cell in sorted(mk.CELLS)}
               for cid, c in corners.items()}
    xcheck = gain_xcheck(corners, derived)
    if not gain_reference_matches(xcheck):
        return 1
    print(json.dumps({cid: {mk.CELLS[cell]["label"]: {
        "small_signal_gain_db": derived[cid][cell]["small_signal_gain_db"],
        "cp1_vpp": derived[cid][cell]["compression"]["cp1_vpp"],
        "cp3_vpp": derived[cid][cell]["compression"]["cp3_vpp"]}
        for cell in sorted(mk.CELLS)} for cid in sorted(corners)}, indent=2))
    if not a.record:
        print(f"all {len(sc.ANCHOR_POINTS)} anchors complete; "
              "re-run with --record to write the record")
        return 0

    rec = build_record({"corners": corners,
                        "batch_receipt": saved.get("batch_receipt")},
                       derived, xcheck, stamp, pin,
                       saved["environment"], saved.get("provenance"))
    out.write_text(json.dumps(rec, indent=2) + "\n")
    print(f"wrote {out.name}: pass={rec['pass']} "
          f"({rec['summary']['pass']}/{rec['summary']['corner_count']} anchors)")
    return 0 if rec["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

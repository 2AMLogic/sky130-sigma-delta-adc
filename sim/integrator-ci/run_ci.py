#!/usr/bin/env python3
"""Integrator charge-injection runner (simulated, transistor-level). See README.md.

Default: submit every nominal-grid request (DR-002 full 45-point grid per
variant) through `klt sim`, which sends them to the batch fleet; never falls
back to a local grid. `--mc` submits the two Monte Carlo requests instead (DR-002
anchor set, PDK `_mm` mismatch sections, N stated in the record).

    python3 -I sim/integrator-ci/run_ci.py --probe post_v0     # 1 local corner
    python3 -I sim/integrator-ci/run_ci.py --self-test         # sensitivity check
    python3 -I sim/integrator-ci/run_ci.py --probe-step post_v0  # step independence
    python3 -I sim/integrator-ci/run_ci.py                     # nominal grids
    python3 -I sim/integrator-ci/run_ci.py --mc                # Monte Carlo
    python3 -I sim/integrator-ci/run_ci.py --record            # write record.json

Each completed variant is saved under .partials/, so a fleet capacity refusal on
one variant does not discard another's corners: re-run the missing variant later
and --record assembles the record from all of them. A variant requested in this
invocation is NEVER served from .partials/ -- a failed submit must not be
reported as a result (issue #94's rule, same as run_settling.py).
"""
import argparse
import json
import math
import pathlib
import re
import shutil
import statistics
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from settling_common import (ANCHOR_SUBSET_NOTE, grid_complete,  # noqa: E402
                             measurements_present, pdk_stamp, run_klt, sha256,
                             summarize)

sys.path.insert(0, str(HERE))
import make_request as mk  # noqa: E402

PARTIALS = HERE / ".partials"      # per-variant results, gitignored
ARTIFACTS = HERE / ".artifacts"    # raw klt report / batch receipt, gitignored
SENTINEL = mk.SENTINEL
GRID_VARIANTS = tuple(mk.VARIANTS)
MC_VARIANTS = mk.MC_VARIANTS

# The switch halves whose turn-off charge reaches the summing node, and so the
# output: Sti/Str gate sump directly. Sbi/Sbr gate the *bottom* plate, which the
# next phi1 re-drives from vinp/rsel, so their turn-off charge is discarded
# before it can be transferred -- see README.md "Which switches actually land
# on Ci". design/integrator/SIZING.md frames the sqrt(W L) growth over all four,
# which is why the record carries both predictions.
SUMMING_SWITCHES = ("Sti", "Str")
VCM_SWITCHES = ("Sbi", "Sbr", "Sti", "Str")


# --------------------------------------------------- netlist device areas ---
def _join_continuations(text):
    out = []
    for line in text.splitlines():
        if line.startswith("+") and out:
            out[-1] += " " + line[1:].strip()
        else:
            out.append(line)
    return out


def switch_areas(netlist):
    """{switch_base: {"nmos": [(W, L)...], "pmos": [...]}} from a cell netlist.

    Reads W/L off the instance lines rather than taking them from a comment, so
    the sqrt(W L) prediction in the record is derived from the netlist that was
    simulated and cannot drift from it.
    """
    areas = {}
    for line in _join_continuations(pathlib.Path(netlist).read_text()):
        m = re.match(r"^X(S[a-z]{2})_([pn])(_p)?\s", line)
        if not m:
            continue
        base, half = m.group(1), ("pmos" if m.group(3) else "nmos")
        w = re.search(r"\bW=([0-9.eE+-]+)", line)
        ln = re.search(r"\bL=([0-9.eE+-]+)", line)
        if not (w and ln):
            continue
        # A `_p`-suffixed instance is only the PMOS half if it really is a pfet;
        # the pre-#92 cell has no such halves at all.
        if half == "pmos" and "pfet" not in line:
            half = "nmos"
        areas.setdefault(base, {"nmos": [], "pmos": []})[half].append(
            (float(w.group(1)), float(ln.group(1))))
    return areas


def area_prediction(pre_netlist, post_netlist):
    """Channel area per switch, pre vs post, and the sqrt(W L) growth factors."""
    pre, post = switch_areas(pre_netlist), switch_areas(post_netlist)

    def per_side(areas, names):
        # One side (the `_p` side) of each named switch: its halves' total
        # channel area. Both sides are drawn identically, so one is enough.
        tot = 0.0
        for n in names:
            halves = areas.get(n, {"nmos": [], "pmos": []})
            # Halves are listed per side; take the mean over sides so a cell
            # with p and n sides does not double-count.
            for kind in ("nmos", "pmos"):
                if halves[kind]:
                    tot += sum(w * ln for w, ln in halves[kind]) / 2.0
        return tot

    out = {}
    for tag, names in (("summing_node_switches", SUMMING_SWITCHES),
                       ("all_phi2_vcm_switches", VCM_SWITCHES)):
        a_pre, a_post = per_side(pre, names), per_side(post, names)
        out[tag] = {
            "switches": list(names),
            "channel_area_um2_per_side_pre": round(a_pre, 4),
            "channel_area_um2_per_side_post": round(a_post, 4),
            "area_ratio": round(a_post / a_pre, 4) if a_pre else None,
            "sqrt_area_ratio": round(math.sqrt(a_post / a_pre), 4) if a_pre else None,
        }
    out["note"] = (
        "The sqrt(W L) argument in design/integrator/SIZING.md predicts the "
        "differential residual grows as sqrt of the channel-area ratio. "
        "`summing_node_switches` is the prediction that applies to the output: "
        "only Sti/Str inject into the summing node, and Sbi/Sbr turn-off charge "
        "lands on the bottom plate, which the next phi1 re-drives from "
        "vinp/rsel before any transfer. `all_phi2_vcm_switches` is SIZING.md's "
        "own framing, kept for comparison. Areas are read from the simulated "
        "netlists; `nfet_01v8` -> `nfet_01v8_lvt` is part of the #92 delta and "
        "changes the charge at equal area, so neither factor is a complete "
        "prediction.")
    return out


# ------------------------------------------------------------- plumbing -----
def shas(v):
    return {"request_sha256": sha256(HERE / f"request_{v}.json"),
            "deck_sha256": sha256(HERE / mk.deck_name(v))}


def mc_shas(v):
    return {"request_sha256": sha256(HERE / f"request_mc_{v}.json"),
            "deck_sha256": sha256(HERE / mk.deck_name(v))}


def partial_path(v, mc):
    return PARTIALS / (f"mc-{v}.json" if mc else f"{v}.json")


def load_partial(v, mc):
    """A previously-run variant, if it matches the current request and deck."""
    p = partial_path(v, mc)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except ValueError:
        return None
    cur = mc_shas(v) if mc else shas(v)
    if {k: d.get(k) for k in cur} != cur:
        print(f"NOTE: ignoring stale .partials/{p.name} (request or deck changed "
              "since it ran)", file=sys.stderr)
        return None
    return d


def save_partial(v, mc, result):
    PARTIALS.mkdir(exist_ok=True)
    partial_path(v, mc).write_text(json.dumps(result, indent=2) + "\n")


def submit(v, mc, tmp, probe=False, probe_path=None, hosts=None):
    req = HERE / (f"request_mc_{v}.json" if mc else f"request_{v}.json")
    tag = f"mc-{v}" if mc else v
    res = run_klt(req, probe, tmp, tag, probe_path or (HERE / f"probe_request_{tag}.json"),
                  artifacts_dir=None if probe else ARTIFACTS, keys=mk.KEYS,
                  hosts=None if probe else hosts)
    if res is None:
        print(f"{tag}: no usable report (see .artifacts/klt-{tag}.stderr.txt); not "
              "falling back to a local grid or to .partials/", file=sys.stderr)
        return None
    rep, corners = res
    e = rep.get("environment", {})
    result = {"summary": summarize(corners, SENTINEL), "corners": corners,
              "pass": rep.get("status") == "pass",
              "ngspice": e.get("engine_version", "unknown"),
              "engine_host": e.get("engine_host"), "remote": e.get("remote"),
              "monte_carlo_env": e.get("monte_carlo"),
              **(mc_shas(v) if mc else shas(v))}
    return result


# ---------------------------------------------------------- derivations -----
def fs(volts):
    """Differential output volts -> model-B FS units (see make_request.py)."""
    return None if volts is None else volts / mk.VFS_DIFF_V


def nominal_derivation(results):
    """ci_offset / ci_gain_error over the nominal grid, per corner and worst-case."""
    base = results["post_v0"]["corners"]
    per_corner = {}
    for cid, c in base.items():
        row = {"dvod_mean_V": c[SENTINEL], "dvoc_mean_V": c.get("dvoc_mean"),
               "ci_offset_fs": fs(c[SENTINEL]),
               "dvod_leak_V": c.get("dvod_leak"), "voc_swing_V": c.get("voc_swing"),
               "vod_rst_V": c.get("vod_rst")}
        # Signal dependence: fit dvod_mean against vin_diff over the three
        # nulled-DAC amplitudes. slope = (Cs/Ci)*(1+gain error) = 0.5*(1+g).
        pts = []
        for v in ("post_v0", "post_v0p1", "post_v0p2"):
            cc = results.get(v, {}).get("corners", {}).get(cid)
            if cc and cc.get(SENTINEL) is not None:
                pts.append((mk.VARIANTS[v]["vin_diff"], cc[SENTINEL]))
        if len(pts) >= 2:
            n = len(pts)
            mx = sum(x for x, _ in pts) / n
            my = sum(y for _, y in pts) / n
            den = sum((x - mx) ** 2 for x, _ in pts)
            slope = sum((x - mx) * (y - my) for x, y in pts) / den
            row["step_slope_v_per_v"] = slope
            row["ci_gain_error_bound"] = slope / mk.C1 - 1.0
            # Departure from the straight line: a gain error cannot represent
            # it, so it is the distortion indicator.
            row["fit_max_residual_V"] = max(
                abs(y - (my + slope * (x - mx))) for x, y in pts)
            row["fit_points_vin_diff_V"] = [x for x, _ in pts]
        per_corner[cid] = row

    def worst(key):
        vals = [(abs(r[key]), cid) for cid, r in per_corner.items() if r.get(key) is not None]
        if not vals:
            return None
        _, cid = max(vals)
        return {"corner": cid, "value": per_corner[cid][key]}

    return {
        "per_corner": per_corner,
        "dac_crosscheck": dac_crosscheck(results),
        "worst_ci_offset_fs": worst("ci_offset_fs"),
        "worst_dvod_mean_V": worst("dvod_mean_V"),
        "worst_ci_gain_error_bound": worst("ci_gain_error_bound"),
        "worst_fit_max_residual_V": worst("fit_max_residual_V"),
        "ci_gain_error_caveat": (
            "step_slope_v_per_v is the whole input-to-output gain of one charge "
            "transfer, so ci_gain_error_bound lumps charge-injection gain error "
            "together with incomplete settling and finite DC gain, which "
            "sim/integrator-settling and the DC-gain extraction own separately. "
            "It is an UPPER BOUND on the charge-injection part, never an "
            "attribution of all of it to charge injection."),
    }


def dac_crosscheck(results):
    """What the real-DAC variant says about nulling the reference branch.

    With `dn` toggled every clock the DAC's +/-1.2 V transfer cancels over two
    clocks *in a linear circuit*, so `dvod_2clk` was intended to show the
    injection residual with the references live. It does not: the integrator's
    finite DC gain leaks the large intermediate state, and that leak dominates.
    Reading it the other way round makes the variant useful -- the residual
    divided by the state it leaked from is 1/A, an independent estimate of the
    OTA's DC gain, which design/ota/SIZING.md records as ~55 dB from a
    different measurement entirely.
    """
    out = {}
    for cid, c in results.get("post_dac", {}).get("corners", {}).items():
        res2, big = c.get("dvod_2clk"), c.get(f"vod_c{mk.STEADY_TO - 1}")
        row = {"dvod_2clk_V": res2, "leaking_state_V": big}
        if res2 and big and abs(big) > 1e-3:
            # dvod_2clk is the 2-clock change halved; the leak over the pair is
            # 2*dvod_2clk out of the state `big` it leaked from.
            inv_a = abs(2 * res2) / abs(big)
            row["implied_inv_dc_gain"] = inv_a
            row["implied_dc_gain"] = 1.0 / inv_a
            row["implied_dc_gain_db"] = 20.0 * math.log10(1.0 / inv_a)
        out[cid] = row
    gains = [r["implied_dc_gain_db"] for r in out.values() if "implied_dc_gain_db" in r]
    return {
        "per_corner": out,
        "implied_dc_gain_db_range": [min(gains), max(gains)] if gains else None,
        "interpretation": (
            "dvod_2clk on the `alternating` variant is NOT an injection residual: "
            "it is the finite-gain leak of the +/-0.6 V intermediate state, and it "
            "is orders of magnitude above the nulled-DAC bench's noise floor. That "
            "is the measured justification for nulling the reference branch -- with "
            "the spec references live, injection is unobservable here. Read as a "
            "gain measurement instead, it is an independent check of the OTA DC "
            "gain against the ~55 dB in design/ota/SIZING.md."),
    }


# A Monte Carlo campaign returns anchors x N samples; carrying all of
# make_request.KEYS for each would make the record megabytes of JSON for no
# gain. These are the per-sample values the record actually reasons about: the
# step itself, the confounders named in README.md "What else is in the step",
# and enough provenance to find the sample again.
MC_SAMPLE_KEYS = ("status", "dvod_mean", "dvoc_mean", "vod_rst", "dvod_leak",
                  "voc_swing", "w_c3", "diagnostics", "monte_carlo")


def trim_mc_samples(corners):
    return {cid: {k: v for k, v in c.items() if k in MC_SAMPLE_KEYS}
            for cid, c in corners.items()}


def mc_stats(corners):
    """Per base corner: mean/sigma/extremes of the differential step, over samples.

    Monte Carlo sample `corner_id`s are the base point plus a `/mc<i>` suffix,
    so the base point is the id with that suffix stripped.
    """
    groups = {}
    for cid, c in corners.items():
        base = cid.rsplit("/mc", 1)[0] if "/mc" in cid else cid
        if c.get(SENTINEL) is not None:
            groups.setdefault(base, []).append(c[SENTINEL])
    out = {}
    for base, vals in sorted(groups.items()):
        n = len(vals)
        sd = statistics.stdev(vals) if n > 1 else 0.0
        out[base] = {
            "n": n,
            "mean_dvod_V": statistics.fmean(vals),
            "sigma_dvod_V": sd,
            "max_abs_dvod_V": max(abs(v) for v in vals),
            "mean_ci_offset_fs": fs(statistics.fmean(vals)),
            "sigma_ci_offset_fs": fs(sd),
            # 1-sigma relative standard error of a Gaussian sigma estimate.
            "sigma_rel_standard_error": (1.0 / math.sqrt(2 * (n - 1))) if n > 1 else None,
        }
    return out


def mc_derivation(results, areas):
    # `results` is keyed by variant name in both modes; --mc only changes which
    # request each variant submits.
    post = mc_stats(results["post_v0"]["corners"])
    pre = mc_stats(results["pre_v0"]["corners"])
    # The two runs name different .lib sections per point (tt_mm etc.) but the
    # same anchors, so the base ids match; pair them by id.
    ratios = {}
    for cid in sorted(set(post) & set(pre)):
        s_pre, s_post = pre[cid]["sigma_dvod_V"], post[cid]["sigma_dvod_V"]
        r = (s_post / s_pre) if s_pre else None
        se = None
        if r is not None and post[cid]["n"] > 1 and pre[cid]["n"] > 1:
            se = r * math.hypot(post[cid]["sigma_rel_standard_error"],
                                pre[cid]["sigma_rel_standard_error"])
        ratios[cid] = {"sigma_pre_V": s_pre, "sigma_post_V": s_post,
                       "sigma_ratio_post_over_pre": r,
                       "sigma_ratio_standard_error": se}
    worst = max(((v["max_abs_dvod_V"], c) for c, v in post.items()), default=(None, None))
    return {
        "post_i92": post, "pre_i92": pre, "sigma_ratio": ratios,
        "worst_abs_dvod_V": {"corner": worst[1], "value": worst[0]},
        "worst_abs_ci_offset_fs": fs(worst[0]),
        "sqrt_wl_prediction": areas,
        "verdict_inputs": (
            "Compare sigma_ratio_post_over_pre (with its standard error) against "
            "sqrt_area_ratio for `summing_node_switches` (the pair that injects "
            "into the summing node) and for `all_phi2_vcm_switches` "
            "(design/integrator/SIZING.md's framing). The #92 delta also swaps "
            "nfet_01v8 for nfet_01v8_lvt on those switches, which neither "
            "sqrt(W L) factor accounts for."),
        "estimator": ("sigma is the sample standard deviation (statistics.stdev, "
                      "n-1) of dvod_mean over the Monte Carlo samples at each "
                      "anchor point; no distribution is assumed beyond quoting "
                      "the usual 1/sqrt(2(n-1)) relative standard error."),
    }


# ------------------------------------------------------------ local modes ---
SKEW_RE = re.compile(r"^(XSti_p_p\s+tpi_p\s+phi2b\s+sump\s+vdda\s+\S+\s+L=\S+\s+W=)([0-9.]+)")
SKEW_FACTOR = 1.10


def write_skewed_cell(dst):
    """The shipped cell with Sti_p's PMOS half 10% wider: a known asymmetry.

    Used only by --self-test, to show a zero differential residual on the
    symmetric cell is a measurement and not a dead bench. Generated from the
    shipped netlist on every run, so there is no committed copy to drift.
    """
    src = (REPO / "design/integrator/integrator.spice").read_text()
    out, hits = [], 0
    for line in src.splitlines():
        m = SKEW_RE.match(line)
        if m:
            w = float(m.group(2)) * SKEW_FACTOR
            line = SKEW_RE.sub(lambda _: f"{m.group(1)}{w:g}", line, count=1)
            hits += 1
        out.append(line)
    if hits != 1:
        raise SystemExit(f"REFUSE: expected exactly 1 XSti_p_p line to skew, found {hits}; "
                         "the netlist changed and --self-test needs updating")
    pathlib.Path(dst).write_text("\n".join(out) + "\n")
    return SKEW_FACTOR


def self_test(tmp):
    """One local corner of the shipped cell and of a 10%-skewed copy.

    Asserts the bench resolves an asymmetry it was built to find: the skewed
    cell's differential step must be orders of magnitude above the symmetric
    cell's, which is the bench's own noise floor.
    """
    cell = HERE / ".selftest_cell.spice"
    deck = HERE / ".selftest.cir"
    req = HERE / ".selftest_request.json"
    try:
        factor = write_skewed_cell(cell)
        body = (HERE / mk.deck_name("post_v0")).read_text().replace(
            '.include "../../design/integrator/integrator.spice"',
            f'.include "{cell.name}"')
        deck.write_text(body)
        r = json.loads((HERE / "request_post_v0.json").read_text())
        r["netlist"] = deck.name
        req.write_text(json.dumps(r, indent=2))
        res = run_klt(req, True, tmp, "selftest", HERE / ".selftest_probe.json", keys=mk.KEYS)
    finally:
        for f in (cell, deck, req):
            f.unlink(missing_ok=True)
    if res is None:
        print("REFUSE: the self-test probe returned no report", file=sys.stderr)
        return 1
    skewed = next(iter(res[1].values()))[SENTINEL]
    base = submit("post_v0", False, tmp, probe=True,
                  probe_path=HERE / ".selftest_probe_base.json")
    if base is None:
        return 1
    floor = next(iter(base["corners"].values()))[SENTINEL]
    if skewed is None or floor is None:
        print("REFUSE: self-test produced no dvod_mean", file=sys.stderr)
        return 1
    ratio = abs(skewed) / abs(floor) if floor else float("inf")
    print(json.dumps({
        "symmetric_dvod_mean_V": floor,
        f"skewed_dvod_mean_V (Sti_p PMOS half W x{factor})": skewed,
        "skewed_over_symmetric": ratio,
        "skewed_ci_offset_fs": fs(skewed),
        "corner": "tt/1.800V/27C, local",
    }, indent=2))
    if ratio < 100:
        print(f"REFUSE: a {factor}x width skew on one switch half moved the "
              f"differential step by only {ratio:.3g}x the symmetric cell's "
              "residual; the bench is not resolving the asymmetry it exists to "
              "measure, so a zero result from it would mean nothing", file=sys.stderr)
        return 1
    print(f"OK: the skew is {ratio:.3g}x the symmetric cell's residual "
          "(>= 100x required)")
    return 0


def probe_step(variant, tmp):
    """The same local corner at two internal step sizes, for step independence."""
    rows = {}
    for step in ("50p", "20p"):
        r = json.loads((HERE / f"request_{variant}.json").read_text())
        r["analysis"]["args"] = f"50p {mk.T_END:.6g} 0 {step}"
        p = HERE / f".probe_step_{step}.json"
        p.write_text(json.dumps(r, indent=2))
        try:
            res = run_klt(p, True, tmp, f"step-{step}", HERE / f".probe_step_pr_{step}.json",
                          keys=mk.KEYS)
        finally:
            p.unlink(missing_ok=True)
        if res is None:
            print(f"REFUSE: no report at max step {step}", file=sys.stderr)
            return 1
        c = next(iter(res[1].values()))
        rows[step] = {k: c.get(k) for k in (SENTINEL, "dvoc_mean", "voc_swing", "w_c3")}
    a, b = rows["50p"][SENTINEL], rows["20p"][SENTINEL]
    rows["abs_change_V"] = None if None in (a, b) else abs(b - a)
    print(json.dumps(rows, indent=2))
    return 0


# ----------------------------------------------------------------- main -----
def conditions():
    return {
        "ibias_uA": 5, "vcm_V": 0.9,
        "clock_mhz": mk.FS_HZ / 1e6, "clock_period_ns": mk.T_CLK * 1e9,
        "cycles_simulated": mk.N_CYC,
        "read_window_ns": [mk.W_READ[0] * 1e9, mk.W_READ[1] * 1e9],
        "drift_window_ns": [mk.W_DRIFT[0] * 1e9, mk.W_DRIFT[1] * 1e9],
        "reset_window_ns": [mk.W_RESET[0] * 1e9, mk.W_RESET[1] * 1e9],
        "step_cycles_averaged": [mk.STEADY_FROM, mk.STEADY_TO],
        "reset": "bench-only ideal 1 ohm switches across Ci until 40 ns (cell has none)",
        "clocks": ("behavioural rail-to-rail on Vdda from PULSE shape sources, "
                   "200 ps edges, >= 4.7 ns non-overlap, no non-overlap generator"),
        "load_per_side": mk.LOADNOTE,
        "spice_options": "reltol=1e-5 vntol=1e-7 abstol=1e-13 chgtol=1e-16 (in the deck)",
        "dac": {k: v["note"] for k, v in mk.DACS.items()},
        "variants": {k: {"cell": v["cell"], "vin_diff_V": v["vin_diff"],
                         "dac": v["dac"], "note": v["note"]}
                     for k, v in mk.VARIANTS.items()},
        "fs_unit_mapping": (
            f"model-B ci_offset [FS] = differential output step [V] / "
            f"{mk.VFS_DIFF_V} V, because one x1 unit is (VREFP-VREFN) = "
            f"{mk.VFS_DIFF_V} V of differential output at Cs/Ci = {mk.C1}"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--variant", action="append", choices=GRID_VARIANTS,
                    help="run only this variant (repeatable); default: all")
    ap.add_argument("--mc", action="store_true",
                    help="submit the Monte Carlo requests instead of the nominal grids")
    ap.add_argument("--probe", choices=GRID_VARIANTS,
                    help="one tt/27C/1.8V corner of a variant, local, no record")
    ap.add_argument("--probe-step", choices=GRID_VARIANTS,
                    help="one local corner at two internal step sizes, no record")
    ap.add_argument("--self-test", action="store_true",
                    help="local sensitivity check against a deliberately skewed cell")
    ap.add_argument("--record", action="store_true",
                    help="write the record (refuses to overwrite: records are append-only)")
    ap.add_argument("--record-name", help="record file name (default: record.json / record-mc.json)")
    ap.add_argument("--hosts", type=int, metavar="N",
                    help="shard each submission across N fleet instances. A Monte "
                         "Carlo campaign is anchors x N units in ONE job, and the "
                         "fleet kills a job still running at its whole-job ceiling "
                         "(reporting every unit batch_job_timeout), so split it if "
                         "the receipt's job_ceiling warns. Sharding does not change "
                         "the request file, so a partial from an unsharded run of "
                         "the same request stays valid.")
    a = ap.parse_args()

    pin = json.load(open(REPO / "sim/pdk.json"))
    root, stamp = pdk_stamp(pin["variant"], a.pdk_root)
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'",
              file=sys.stderr)
        return 2
    out = HERE / (a.record_name or ("record-mc.json" if a.mc else "record.json"))
    if a.record and out.exists():
        print(f"REFUSE: {out.name} exists; records are append-only (use --record-name)",
              file=sys.stderr)
        return 2
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="integrator-ci-"))
    try:
        if a.self_test:
            return self_test(tmp)
        if a.probe_step:
            return probe_step(a.probe_step, tmp)
        if a.probe:
            res = submit(a.probe, False, tmp, probe=True)
            if res is None:
                print(f"REFUSE: no result for the {a.probe} probe; nothing printed.",
                      file=sys.stderr)
                return 1
            print(json.dumps(res["corners"], indent=2))
            return 0

        want = MC_VARIANTS if a.mc else GRID_VARIANTS
        run = tuple(dict.fromkeys(a.variant)) if a.variant else want
        run = tuple(v for v in run if v in want)
        if a.variant and not run:
            print(f"REFUSE: --variant names nothing in this mode ({', '.join(want)})",
                  file=sys.stderr)
            return 2

        results = {}
        for v in want:
            if v not in run:
                saved = load_partial(v, a.mc)
                if saved:
                    print(f"{v}: reusing {partial_path(v, a.mc).name} ({saved['summary']})")
                    results[v] = saved
                continue
            res = submit(v, a.mc, tmp, hosts=a.hosts)
            if res is None:
                continue
            print(v, json.dumps(res["summary"], indent=2))
            results[v] = res
            save_partial(v, a.mc, res)

        missing = [v for v in want if v not in results]
        if missing:
            print(f"REFUSE: no result for {', '.join(missing)}; no record written. "
                  f"Re-run with --variant {missing[0]} when the fleet has capacity.",
                  file=sys.stderr)
            return 1

        corner_sets = [results[v]["corners"] for v in want]
        expected = (len(mk.ANCHOR_POINTS) * mk.MC_N) if a.mc else 45
        if not grid_complete(corner_sets, expected):
            return 1
        if not measurements_present(corner_sets, SENTINEL):
            return 1
        if not a.record:
            print("all variants complete; re-run with --record to write the record")
            return 0

        areas = area_prediction(HERE / mk.PRE_CELL, REPO / "design/integrator/integrator.spice")
        rec = {
            "fixture": ("Integrator charge-injection bench (issue #102): the full "
                        "integrator cell + ota_fd clocked for "
                        f"{mk.N_CYC} complete phi1/phi2 cycles; the differential and "
                        "common-mode output step per clock, read in the phi1 hold"),
            "result_kind": ("simulated (ngspice, transistor-level netlists of "
                            "design/integrator + design/ota/ota_fd; not the "
                            "behavioural model). SIMULATED, NEVER MEASURED."),
            "run_kind": "monte_carlo_mismatch" if a.mc else "nominal_corner_grid",
            "conditions": conditions(),
            "corner_set": (f"{ANCHOR_SUBSET_NOTE}; N = {mk.MC_N} per point, "
                           f"base seed {mk.MC_SEED}, vary=mismatch, seed_scope=point, "
                           "sky130 `_mm` .lib sections"
                           if a.mc else "DR-002 full grid, 5 process x 3 T x 3 Vdda"),
            "pdk_sources_stamp": stamp,
            "pdk_pin": {"file": "sim/pdk.json", "open_pdks_revision": pin["open_pdks_revision"]},
            "klt": subprocess.run(["klt", "--version"], capture_output=True,
                                  text=True).stdout.strip(),
            "integrator_netlist_sha256": sha256(REPO / "design/integrator/integrator.spice"),
            "pre_i92_fixture_sha256": sha256(HERE / mk.PRE_CELL),
            "pre_i92_fixture_commit": "e310b5f (first parent of the #92 merge 31c2da9)",
            "ota_netlist_sha256": sha256(REPO / "design/ota/ota_fd.spice"),
            "variants": results,
            "pass": all(r["pass"] for r in results.values()),
        }
        rec["derived"] = (mc_derivation(results, areas) if a.mc
                          else {**nominal_derivation(results), "sqrt_wl_prediction": areas})
        if a.mc:
            # Derivations above read the full corner sets; the record keeps the
            # trimmed per-sample rows (.partials/ still holds everything).
            for v in want:
                rec["variants"][v] = {**results[v],
                                      "corners": trim_mc_samples(results[v]["corners"]),
                                      "corner_keys_kept": list(MC_SAMPLE_KEYS)}
        out.write_text(json.dumps(rec, indent=2) + "\n")
        print(f"wrote {out.name}: pass={rec['pass']}")
        return 0 if rec["pass"] else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

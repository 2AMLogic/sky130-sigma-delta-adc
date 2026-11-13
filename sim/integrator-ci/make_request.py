#!/usr/bin/env python3
"""Regenerate the integrator charge-injection decks and `klt sim` requests.

    python3 -I sim/integrator-ci/make_request.py

Writes one deck per variant plus a nominal-grid request (DR-002 full 45-point
grid) for every variant, and a Monte Carlo request (DR-002 anchor set, PDK
mismatch models) for the two zero-input variants. See README.md.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from settling_common import ANCHOR_POINTS, anchor_units, request  # noqa: E402

# ---------------------------------------------------------------- timing ----
FS_HZ = 5.12e6              # spec row 5
T_CLK = 1.0 / FS_HZ         # 195.3125 ns
N_CYC = 6                   # complete clock cycles simulated (windows c0..c5)

# The output is read as the MEAN of v(vod)/v(voc) over a fixed 10 ns window
# late in each cycle's phi1 hold -- not as a point interpolated between two
# stored timepoints. ngspice emits duplicate timepoints at breakpoints, so the
# `v[k-1] + (t-time[k-1])/(time[k]-time[k-1])*...` idiom the settling bench
# uses can divide by a zero-width bracket; a windowed mean cannot, and it
# averages the solver's own numerical noise down as well.
#   per cycle: phi1e high [0.18, 90.52] ns, phi1 high [0.18, 92.53] ns,
#              phi2 high [97.64, 189.98] ns
# so [78, 88] ns sits in the hold with every switch into the summing node open,
# 2 ns clear of the phi1e fall and 35 ns clear of the phi2 fall before it.
W_READ = (78e-9, 88e-9)
# A second window earlier in the SAME hold: the differential change across it
# is leakage/drift with no clock edge in between, which separates drift from
# the per-clock injection step.
W_DRIFT = (50e-9, 60e-9)
# Bench reset is closed until 40 ns, so this window reads the OTA in unity
# feedback: its differential output there is the OTA offset, the confounder
# that shares the per-clock differential step with switch injection.
W_RESET = (30e-9, 38e-9)
T_END = 1.18e-6             # cycle 5's read window ends at 5*T + 88 ns
STEADY_FROM, STEADY_TO = 2, 5   # cycles the reported mean step is taken over

# -------------------------------------------------- model-B unit mapping ----
# Model B advances integrator 1 by `k*(u - y) + ci_offset` with k = C1 = 0.5,
# u and y in FS units (y = +/-1 is full scale). In the cell one clock moves the
# differential output by (Cs/Ci)*(vin_diff + vdac_diff) = 0.5*(vin_diff +
# vdac_diff), and y = +/-1 is the DAC's +/-(VREFP - VREFN) = +/-1.2 V. Equating
# the two gives 1 x1-unit == 1.2 V of differential output, so an injection
# residual of `dv` volts at the output is `dv / 1.2` in `ci_offset` FS units.
# The nulled-DAC variants hold VREFP = VREFN = VCM, but this normalisation is
# the *spec* DAC swing (spec/modulator-adc.md rows 11/14), not the bench's.
VFS_DIFF_V = 1.2
C1 = 0.5                    # Cs/Ci, the Boser-Wooley coefficient of model B

# ------------------------------------------------------------- variants -----
POST_CELL = "../../design/integrator/integrator.spice"
PRE_CELL = "integrator_pre_i92.spice"
# The pre-#92 .subckt predates klt-netlist's port-type regrouping: voutp/voutn
# sit at positions 5-6 instead of last. Each cell therefore carries its own
# instantiation line (see sim/integrator-settling/README.md "Port-order drift").
POST_XINT = ("Xint vdda 0 vinp vinn vrefp vrefn vcm ibias phi1 phi1b phi1e phi2 dp dn"
             " voutp voutn integrator")
PRE_XINT = ("Xint vdda 0 vinp vinn voutp voutn vrefp vrefn vcm ibias phi1 phi1b phi1e"
            " phi2 dp dn integrator")

DN_STATIC = "Vdns dns 0 DC 1"
# Toggle `dn` once per clock, in the non-overlap gap 2.5 ns before a cycle
# boundary, so the DAC charge alternates sign and two consecutive clocks'
# ideal transfer cancels exactly (README.md "Cross-check with the real DAC").
DN_TOGGLE = (f"Vdns dns 0 PULSE(1 0 {T_CLK - 2.5e-9:.7g} 0.2n 0.2n "
             f"{T_CLK - 0.2e-9:.7g} {2 * T_CLK:.7g})")

# Load: the first integrator's case-B load (0.1 pF output parasitics only), the
# same choice sim/integrator-settling calls `int1`. `ci_offset` is a model-B
# integrator-1 parameter, so integrator 1 is the stage to extract it from.
LOAD = "0.1p"
LOADNOTE = "0.1 pF output parasitics only (integrator 1, case B of design/integrator/SIZING.md)"

VARIANTS = {
    "post_v0": {
        "cell": "post", "vin_diff": 0.0, "dac": "nulled",
        "note": "shipped cell, zero differential input, DAC nulled: the step IS the injection residual",
    },
    "post_v0p1": {
        "cell": "post", "vin_diff": 0.1, "dac": "nulled",
        "note": "shipped cell, +0.1 V differential input, DAC nulled: signal dependence",
    },
    "post_v0p2": {
        "cell": "post", "vin_diff": 0.2, "dac": "nulled",
        "note": "shipped cell, +0.2 V differential input, DAC nulled: signal dependence",
    },
    "post_dac": {
        "cell": "post", "vin_diff": 0.0, "dac": "alternating",
        "note": "shipped cell, zero input, real +/-1.2 V DAC alternating every clock: "
                "cross-check that nulling the DAC did not hide an injection term",
    },
    "pre_v0": {
        "cell": "pre", "vin_diff": 0.0, "dac": "nulled",
        "note": "pre-#92 cell (e310b5f), zero differential input, DAC nulled: the #92 baseline",
    },
}
MC_VARIANTS = ("post_v0", "pre_v0")     # criteria 4 and 5: the mismatch pair

CELLS = {
    "post": {"file": POST_CELL, "inc": f'.include "{POST_CELL}"', "xint": POST_XINT},
    "pre": {"file": PRE_CELL, "inc": f'.include "{PRE_CELL}"', "xint": PRE_XINT},
}
DACS = {
    "nulled": {"vrefp": "0.9", "vrefn": "0.9", "dns": DN_STATIC,
               "note": "held at VCM, dn static: the reference branch transfers zero charge "
                       "while all of its switches still operate and inject"},
    "alternating": {"vrefp": "1.5", "vrefn": "0.3", "dns": DN_TOGGLE,
                    "note": "spec DR-005 references, dn toggled every clock so the ideal "
                            "transfer cancels over two consecutive clocks"},
}

# Monte Carlo: sky130 per-instance mismatch lives in the `_mm`-suffixed .lib
# sections, so the MC request's process axis names those, not the plain ones
# (klt sim docs, "Known-good mismatch mechanisms"). DR-002 requires the PDK's
# own mismatch models and an `N` stated per run.
MC_SECTION = {"tt": "tt_mm", "ss": "ss_mm", "ff": "ff_mm", "sf": "sf_mm", "fs": "fs_mm"}
# N = 100 per anchor point: the sigma of a sample of 100 carries a 1/sqrt(2*99)
# = 7.1% relative standard error, so a post/pre sigma *ratio* lands with ~10%,
# enough to separate the two competing sqrt(W L) predictions (1.33x and 2.38x,
# see run_ci.py area_prediction). 7 anchors x 100 x 2 cells = 1400 units.
# A re-run at larger N is a new append-only record, never an edit of this one.
MC_N = 100
MC_SEED = 20261113


# --------------------------------------------------------- measurements -----
def e(name, expr, unit=None, limits=None):
    m = {"name": name, "expr": expr}
    if unit:
        m["unit"] = unit
    if limits:
        m["limits"] = limits
    return m


def _window(tag, a, b, cyc=0):
    """Measurements reading vod and voc as a mean over [a, b] within cycle `cyc`.

    `mean(mask)` is the fraction of stored timepoints inside the window; it is
    recorded as `w_<tag>` so a record cannot hide an empty window, and it is
    the divisor that turns the masked sum into a mean. `ge`/`le` rather than
    `>=`/`<=`: bare angle brackets are shell redirections in ngspice's control
    language.
    """
    t0, t1 = cyc * T_CLK + a, cyc * T_CLK + b
    mask = f"(time ge {t0:.9g})*(time le {t1:.9g})"
    out = [e(f"w_{tag}", f"mean({mask})")]
    for sig in ("vod", "voc"):
        out.append(e(f"{sig}_{tag}", f"mean(v({sig})*{mask})/w_{tag}", "V"))
    return out


def measurements():
    m = []
    # OTA differential offset, read while the bench reset still holds the OTA
    # in unity feedback (README.md "What else is in the step").
    m += _window("rst", *W_RESET)
    # Earlier window in cycle STEADY_FROM+1's hold: the leakage/drift control.
    m += _window("d3", *W_DRIFT, cyc=STEADY_FROM + 1)
    for k in range(N_CYC):
        m += _window(f"c{k}", *W_READ, cyc=k)
    # Per-clock steps: the net charge one complete cycle delivered to Ci.
    for k in range(1, N_CYC):
        m.append(e(f"dvod_c{k}", f"vod_c{k} - vod_c{k - 1}", "V"))
        m.append(e(f"dvoc_c{k}", f"voc_c{k} - voc_c{k - 1}", "V"))
    n = STEADY_TO - STEADY_FROM
    # The headline numbers: a slope over n clocks, so the solver's numerical
    # noise and any one-off reset-release disturbance are divided by n.
    m.append(e("dvod_mean", f"(vod_c{STEADY_TO} - vod_c{STEADY_FROM})/{n}", "V"))
    m.append(e("dvoc_mean", f"(voc_c{STEADY_TO} - voc_c{STEADY_FROM})/{n}", "V"))
    # Two-clock step: the `alternating` DAC's ideal transfer cancels over it.
    m.append(e("dvod_2clk", f"(vod_c{STEADY_TO} - vod_c{STEADY_TO - 2})/2", "V"))
    # Differential drift across 28 ns of hold with no clock edge, and the same
    # rate scaled to a whole clock for comparison against dvod_mean.
    dt = W_READ[0] - W_DRIFT[0]
    m.append(e("drift_hold", f"vod_c{STEADY_FROM + 1} - vod_d3", "V"))
    m.append(e("dvod_leak", f"(vod_c{STEADY_FROM + 1} - vod_d3)*{T_CLK / dt:.9g}", "V"))
    m.append(e("dvoc_leak", f"(voc_c{STEADY_FROM + 1} - voc_d3)*{T_CLK / dt:.9g}", "V"))
    # The common-mode excursion the switching drives within a cycle: the
    # per-cycle `voc` numbers above are one phase of a swing this wide.
    lo, hi = STEADY_FROM * T_CLK, (STEADY_TO + 1) * T_CLK
    inwin = f"(time ge {lo:.9g})*(time le {hi:.9g})"
    m.append(e("voc_swing", f"vecmax(v(voc)*{inwin} - 10*(1-{inwin}))"
                            f" - vecmin(v(voc)*{inwin} + 10*(1-{inwin}))", "V"))
    return m


MEASUREMENTS = measurements()
# The keys run_ci.py carries into the record, in report order.
KEYS = tuple(m["name"] for m in MEASUREMENTS if not m["name"].startswith("k_"))
# The admission sentinel: a corner with no `dvod_mean` simulated nothing.
SENTINEL = "dvod_mean"


# ------------------------------------------------------------- requests -----
def deck_name(v):
    return f"integrator_ci_{v}.cir"


def render(v, d):
    cell, dac = CELLS[d["cell"]], DACS[d["dac"]]
    half = d["vin_diff"] / 2.0
    subs = {
        "@VARIANT@": v, "@NOTE@": d["note"],
        "@CELLFILE@": cell["file"], "@CELLTAG@": d["cell"],
        "@CELLINC@": cell["inc"], "@XINT@": cell["xint"],
        "@VREFP@": dac["vrefp"], "@VREFN@": dac["vrefn"],
        "@DNS@": dac["dns"], "@DNNOTE@": dac["note"],
        "@VINP@": f"{0.9 + half:.6g}", "@VINN@": f"{0.9 - half:.6g}",
        "@VINDIFF@": f"{d['vin_diff']:.6g}",
        "@LOAD@": LOAD, "@LOADNOTE@": LOADNOTE, "@NCYC@": str(N_CYC),
    }
    text = (HERE / "integrator_ci.cir.tmpl").read_text()
    for k, val in subs.items():
        text = text.replace(k, val)
    left = sorted({w for w in text.split() if w.startswith("@") and w.endswith("@")})
    if left:
        raise SystemExit(f"REFUSE: unsubstituted placeholder(s) in {v}: {left}")
    return text


def nominal_request(v):
    # Output step 50p and max internal step 50p: the clock edges are 200 ps,
    # and the read windows are means over stored points, so the stored density
    # is part of the measurement. run_ci.py --probe-step reruns one corner at
    # 20 ps to show the answer does not depend on it (README.md "Step
    # independence"). Tolerances are set in the deck, not here.
    r = request(deck_name(v), MEASUREMENTS, T_END, timeout_s=3600, poll_timeout_s=21600)
    r["analysis"]["args"] = f"50p {T_END:.6g} 0 50p"
    return r


def mc_request(v):
    r = nominal_request(v)
    # An explicit `corners.units` point list, so the 7 DR-002 anchors stay 7
    # points rather than a 45-point cross product with 38 exclusions.
    r["corners"] = {"units": anchor_units(MC_SECTION)}
    r["monte_carlo"] = {
        "n": MC_N, "seed": MC_SEED, "vary": "mismatch",
        # `point` keys each sample's seeds on the point's own identity plus
        # sample_index, so the pre-#92 and post-#92 requests -- separate
        # submissions over the same anchor points -- draw the same sample
        # sequence, which is what criterion 5's "same seeds" asks for.
        "seed_scope": "point",
        "quantiles": [1, 5, 50, 95, 99],
    }
    return r


if __name__ == "__main__":
    for v, d in VARIANTS.items():
        (HERE / deck_name(v)).write_text(render(v, d))
        (HERE / f"request_{v}.json").write_text(
            json.dumps(nominal_request(v), indent=2) + "\n")
        if v in MC_VARIANTS:
            (HERE / f"request_mc_{v}.json").write_text(
                json.dumps(mc_request(v), indent=2) + "\n")
    print(f"wrote {len(VARIANTS)} decks, {len(VARIANTS)} nominal and "
          f"{len(MC_VARIANTS)} Monte Carlo requests; {len(KEYS)} measurement keys")

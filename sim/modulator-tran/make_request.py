#!/usr/bin/env python3
"""Regenerate modulator_tran.cir and request.json for the short transient bench.

    python3 -I sim/modulator-tran/make_request.py

Everything the bench claims is derived here and written into the deck and the
request, so the committed request is the bench: the record names its sha256 and
nothing about the run is implicit. See README.md for what the numbers mean.
"""
import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from settling_common import ANCHOR_POINTS, CAPACITY_WAIT_S, request  # noqa: E402

# ----------------------------------------------------------------- timing ---
FS_HZ = 5.12e6                 # spec row 5, modulator clock
TPER = 1.0 / FS_HZ             # 195.3125 ns
TEDGE = 0.2e-9                 # clock rise/fall time
TCLK0 = 10.0e-9                # PULSE delay: the clock starts after 10 ns of DC
PW = TPER / 2.0 - TEDGE        # flat top, so the 50 % crossings are TPER/2 apart
TRISE0 = TCLK0 + TEDGE / 2.0   # first rising 50 % crossing

# Record length. DR-001 item 2 asks for a *short* full-modulator transient and
# requires the length to be stated before the first result; this is that
# statement. The choice is set by cost, measured on this host before any corner
# ran (sim/modulator-tran/README.md "Why 1024 clocks"): about 3.1 s of ngspice
# per microsecond of transient at tt/27 C/1.80 V with a 1 ns maximum timestep,
# i.e. about 0.61 s per modulator clock. 1088 clocks is ~11 min at tt and ~22
# min at a corner twice as slow, inside the batch fleet's 3600 s whole-job
# ceiling with margin. The settling clocks are discarded: the loop starts from
# the operating point with both integrators near VCM, not from a reset state.
N_SETTLE = 64                  # discarded start-up clocks
N_REC = 1024                   # recorded clocks = 8 output samples at OSR 128

# Coherent tone: CYCLES whole periods over the N_REC recorded clocks. 3 is odd
# and coprime with 1024, and puts the tone at 15 kHz, inside the 20 kHz band of
# spec row 1.
CYCLES = 3
FIN_HZ = CYCLES * FS_HZ / N_REC

# Amplitude. Model B's full scale is the 1.2 V differential reference
# (sim/bmodel/model.py: "+/-1 is full scale ... spec row 11 (0.5*VREF peak) is
# -6 dBFS"), so -6 dBFS is 0.6 V peak differential = 0.3 V peak per side about
# VCM -- the same operating point spec sec 5.4 derives the swing from and the
# amplitude the behavioural record was taken at.
VREF_DIFF_V = 1.2
AMP_DBFS = -6.0
AMP_SE_V = 0.5 * VREF_DIFF_V * 10.0 ** (AMP_DBFS / 20.0)   # 0.30069 V per side

# Window actually measured: clocks N_SETTLE .. N_SETTLE+N_REC-1.
T_REC_FROM = TCLK0 + N_SETTLE * TPER        # before that clock's rising edge
T_REC0 = TRISE0 + N_SETTLE * TPER           # the rising 50 % crossing itself
T_REC1 = T_REC0 + N_REC * TPER
T_END = TRISE0 + (N_SETTLE + N_REC + 1) * TPER   # one spare clock after the window
T_MAX_STEP = 1.0e-9

# Per-clock sampling instant: the clock's own falling 50 % crossing, which is
# the end of the phi2 integrate phase and a few hundred ps *before* clkgen
# lowers phi2, so both integrator outputs carry the charge this clock
# transferred and are still driven. Stated in the record; a sibling that
# rebuilds u[n] uses the same grid.
def sample_time(k):
    return TRISE0 + (k + 0.5) * TPER


def u_diff(t):
    """The differential input the modulator sees at time `t`, in volts.

    The deck drives vinp/vinn from two SIN sources with zero delay and zero
    damping, so the differential input is exactly this from t = 0. A sibling
    that rebuilds u[n] for model B divides by VREF_DIFF_V to get FS units.
    """
    return 2.0 * AMP_SE_V * math.sin(2.0 * math.pi * FIN_HZ * t)


REC_CLOCKS = tuple(range(N_SETTLE, N_SETTLE + N_REC))

# ----------------------------------------------------------------- limits ---
# Spec sec 5.4 is the only swing figure the ratified spec gives: the integrator
# outputs "stay well inside the ~1.39 Vpp output swing sky130-opamp reports at
# its worst corner". It is applied here to the *differential* integrator output,
# the stricter of the two readings the sentence allows; the single-ended
# extremes are reported beside it without a limit so the other reading is
# visible too. design/ota/SIZING.md's ~2.3 Vpp is a one-bias-point hand
# calculation and is not used as a limit.
SWING_MAX_VPP = 1.39
P_ANA_MAX_W = 1.0e-3           # spec row 13


def e(name, expr, unit=None, limits=None, spec_row=None):
    m = {"name": name, "expr": expr}
    if unit:
        m["unit"] = unit
    if limits:
        m["limits"] = limits
    if spec_row:
        m["spec_row"] = spec_row
    return m


def win_mask(lo, hi):
    """ngspice control-language mask, 1 inside [lo, hi] and 0 outside.

    `lt`/`gt`: bare < > are shell redirections in ngspice's control language.
    """
    return f"(time ge {lo:.12g})*(time le {hi:.12g})"


MASK = win_mask(T_REC0, T_REC1)


def wmax(vec):
    return f"vecmax({vec}*{MASK} - 10*(1-{MASK}))"


def wmin(vec):
    return f"vecmin({vec}*{MASK} + 10*(1-{MASK}))"


def cycle_mean(signal, unit, limits=None, spec_row=None, name=None):
    """Time-weighted mean of `signal` over the N_REC recorded clock periods.

    Aligned on the clock's own mid-rail crossing, so the window is a whole
    number of switching periods: a literal window biases a switched-capacitor
    average by up to ripple/cycles. The threshold is written as an expression
    against v(vdda) rather than a literal, so it follows the supply sweep
    without needing the runner's supply-relative `level` form.
    """
    m = {"name": name, "unit": unit,
         "cycle_mean": {"signal": signal, "align": "v(clk)-0.5*v(vdda)",
                        "level": 0.0, "edge": "rise",
                        "from": T_REC_FROM, "cycles": N_REC}}
    if limits:
        m["limits"] = limits
    if spec_row:
        m["spec_row"] = spec_row
    return m


def energy(name, source, voltage):
    return {"name": name, "unit": "J",
            "energy": {"source": source, "voltage": voltage,
                       "from": T_REC0, "to": T_REC1}}


def crossings(name, signal, edge, limits=None, spec_row=None, unit=None):
    m = {"name": name,
         "crossings": {"signal": signal, "level": 0.0, "edge": edge,
                       "from": T_REC_FROM, "to": T_REC1, "max": 100000}}
    if unit:
        m["unit"] = unit
    if limits:
        m["limits"] = limits
    if spec_row:
        m["spec_row"] = spec_row
    return m


def measurements():
    ms = [
        # --- what was actually simulated (reference validity, not a spec row)
        e("vdda_v", "v(vdda)[0]", "V"),

        # --- row 13: analog power -------------------------------------------
        cycle_mean("v(pana)", "W", {"max": P_ANA_MAX_W}, "13", name="p_ana"),
        cycle_mean("v(pvdda)", "W", name="p_vdda"),
        cycle_mean("v(pref)", "W", name="p_ref"),
        cycle_mean("v(pvcm)", "W", name="p_vcm"),
        # Independent second route to the same quantity: klt integrates each
        # source's own v*i over the window. run_tran.py cross-checks the two
        # and refuses a record whose routes disagree.
        energy("e_vdda", "vdda", "v(vdda)"),
        energy("e_vrefp", "vrefp", "v(vrefp)"),
        energy("e_vrefn", "vrefn", "v(vrefn)"),
        energy("e_vvcm", "vvcm", "v(vcm)"),

        # --- row 11: integrator output swing --------------------------------
        e("o1_max", wmax("v(o1d)"), "V"),
        e("o1_min", wmin("v(o1d)"), "V"),
        e("o1_swing_pp", "o1_max - o1_min", "V", {"max": SWING_MAX_VPP}, "11"),
        e("o2_max", wmax("v(o2d)"), "V"),
        e("o2_min", wmin("v(o2d)"), "V"),
        e("o2_swing_pp", "o2_max - o2_min", "V", {"max": SWING_MAX_VPP}, "11"),
        # Single-ended extremes: headroom to the rails, and the other reading
        # of spec sec 5.4's figure. Reported, never graded.
        e("o1p_max", wmax("v(xmod.o1p)"), "V"),
        e("o1p_min", wmin("v(xmod.o1p)"), "V"),
        e("o2p_max", wmax("v(xmod.o2p)"), "V"),
        e("o2p_min", wmin("v(xmod.o2p)"), "V"),

        # --- row 5: the loop is clocked at fs and the bitstream is alive -----
        # phi1 rises exactly once per modulator clock, so its count over the
        # window is N_REC if and only if the clock generator ran at fs for the
        # whole record.
        crossings("phi1_edges", "v(xmod.phi1)-0.5*v(vdda)", "rise",
                  {"min": N_REC, "max": N_REC}, "5"),
        # The bitstream must toggle (a stuck loop fails min) and must not
        # toggle more than once per clock (a glitching latch or a metastable
        # comparator fails max). The returned crossing times are the bitstream.
        crossings("bs_edges", "v(bs)-0.5*v(vdda)", "either",
                  {"min": 1, "max": N_REC}, "5"),
        cycle_mean("v(bs)", "V", name="bs_mean"),
    ]
    # --- per-clock held samples: the bitstream and both integrator outputs,
    # one value per recorded clock at the stated instant. These are .meas
    # cards rather than a waveform artifact so they come back inline in the
    # report from the batch fleet, with no artifact retrieval (#128 needs
    # them, DR-001 item 3 grades the model on them).
    for k in REC_CLOCKS:
        t = sample_time(k)
        for tag, vec in (("sb", "v(bs)"), ("s1", "v(o1d)"), ("s2", "v(o2d)")):
            name = f"{tag}_{k:05d}"
            ms.append({"name": name, "unit": "V",
                       "spice": f".meas tran {name} FIND {vec} AT={t:.12e}"})
    return ms


SAVE_VECTORS = [
    "v(vdda)", "v(clk)", "v(bs)", "v(o1d)", "v(o2d)",
    "v(pana)", "v(pvdda)", "v(pref)", "v(pvcm)",
    "v(vrefp)", "v(vrefn)", "v(vcm)", "v(vinp)", "v(vinn)",
    "v(xmod.phi1)", "v(xmod.phi2)", "v(xmod.phi1e)",
    "v(xmod.o1p)", "v(xmod.o1n)", "v(xmod.o2p)", "v(xmod.o2n)",
    "i(vdda)", "i(vrefp)", "i(vrefn)", "i(vvcm)",
]

# Fleet scheduling. The first run of this bench measured 270-324 s per corner
# on the fleet (and 680 s on the dispatch host), so a 1100 s per-corner budget
# is over 3x the observed worst. The fleet's whole-job ceiling is 3600 s and
# klt's pre-submit check uses the fully-serial bound timeout_s*units + 120, so
# 3 units per job gives 3420 s -- inside the ceiling, in three jobs rather
# than seven. The first run used one unit per job, chosen before any runtime
# was known, and the fleet refused those launches with `batch_no_capacity`
# until a shard was lost; three instances is a much smaller ask for the same
# work. See README.md "Fleet sharding".
PER_CORNER_TIMEOUT_S = 1100
POLL_TIMEOUT_S = 14400
MAX_UNITS_PER_JOB = 3
MAX_CONCURRENT_JOBS = 3

DECK = "modulator_tran.cir"


def anchor_units():
    """DR-002 anchor set, with `vclk` swept alongside `vdda`.

    settling_common.anchor_units() gives the shared 7-point list, but this
    bench needs the clock source's PULSE levels rescaled per corner too
    (corners.supply_waveforms), and that requires `vclk` to be a supply_v key
    of every unit. The anchor set itself still comes from the shared constant.
    """
    return [{"process": p, "supply_v": {"vdda": v, "vclk": v}, "temperature_c": t}
            for p, v, t in ANCHOR_POINTS]


def build_request():
    # settling_common.request() carries the shared engine/models/backend block;
    # its full 45-point grid and 0.1 ns step are replaced here (DR-002 keeps the
    # full grid for the cheap single-mechanism runs; this one is an anchor run).
    r = request(DECK, measurements(), T_END, timeout_s=PER_CORNER_TIMEOUT_S,
                poll_timeout_s=POLL_TIMEOUT_S)
    r["corners"] = {"units": anchor_units(), "supply_waveforms": ["vclk"]}
    r["analysis"] = {"kind": "tran",
                     "args": f"{T_MAX_STEP:.6g} {T_END:.9g} 0 {T_MAX_STEP:.6g}"}
    # Keep only the vectors the measurements and the reduction need resident:
    # the assembled modulator has of the order of a thousand nodes and the
    # record is ~300 k timepoints, which `save all` would make expensive.
    r["options"] = {"timeout_s": PER_CORNER_TIMEOUT_S, "keep_artifacts": False,
                    "save_vectors": SAVE_VECTORS}
    # Sharding is sized from the measured per-corner runtime (see
    # MAX_UNITS_PER_JOB). The fleet kills a job at its whole-job ceiling and
    # reports every unit `batch_job_timeout`, so each job's conservative
    # serial bound (timeout_s * units + 120) has to fit under it; too many
    # jobs is the other failure, because each one is an instance the shared
    # Spot quota has to find.
    r["batch"] = {"poll_timeout_s": POLL_TIMEOUT_S,
                  "capacity_wait_s": CAPACITY_WAIT_S,
                  "max_units_per_job": MAX_UNITS_PER_JOB,
                  "max_concurrent_jobs": MAX_CONCURRENT_JOBS}
    return r


def build_deck():
    tmpl = (HERE / "modulator_tran.cir.tmpl").read_text()
    subs = {
        "@TCLK0@": f"{TCLK0:.12g}",
        "@PW@": f"{PW:.12g}",
        "@TPER@": f"{TPER:.12g}",
        "@AMP@": f"{AMP_SE_V:.12g}",
        "@FIN@": f"{FIN_HZ:.12g}",
        "@FS@": f"{FS_HZ:.12g}",
        "@CYCLES@": str(CYCLES),
        "@NREC@": str(N_REC),
        "@DBFS@": f"{AMP_DBFS:g}",
        "@TRISE0@": f"{TRISE0:.12g}",
    }
    for k, v in subs.items():
        tmpl = tmpl.replace(k, v)
    return tmpl


if __name__ == "__main__":
    (HERE / DECK).write_text(build_deck())
    (HERE / "request.json").write_text(
        json.dumps(build_request(), indent=2) + "\n")
    print(f"wrote {DECK} and request.json: "
          f"{N_REC} recorded clocks after {N_SETTLE} settling clocks, "
          f"tone {FIN_HZ:.6g} Hz ({CYCLES} cycles), "
          f"{AMP_SE_V:.6g} V peak per side, t_end {T_END:.6g} s")

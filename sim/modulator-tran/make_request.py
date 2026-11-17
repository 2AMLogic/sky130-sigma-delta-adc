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
from types import SimpleNamespace

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

# Long-record bench (DR-001 corrigendum 01, issue #290). DR-001 item 3's
# in-band SNDR leg needs in-band noise bins beside the tone lobe; at 1024
# clocks the 4-term Blackman-Harris lobe covers the whole 20 kHz band
# (sim/bmodel/xcheck-record.json, sndr_inband_db.reason). The corrigendum
# lengthens the cross-check record to 4096 recorded clocks: 1250 Hz bins, 16
# band bins, the tone at bin 12, and 7 in-band noise bins -- thin, but
# computable, which is what the operator ruling requires ("lengthen the T
# record until in-band SNDR is computable"; the 3 dB gate is unchanged). The
# length is the longest band-resolving power of two that fits the fleet's
# 3600 s whole-job ceiling: the probe run measured 1104.6 s of unit runtime for
# one corner (tt/27 C/1.80 V, 4160 clocks, klt-sim-56a43a043984, ~0.265
# s/clock) against 441-606 s per 1088 clocks for the committed run, which puts
# 8192 recorded clocks past the ceiling at every measured per-clock rate, and
# one unit's runtime is not reducible by sharding (sharding divides units per
# job, never one unit's transient). Each long corner therefore gets its own
# batch job with the whole budget: one unit per job, timeout_s 3300, so the
# pre-submit serial bound 3300*1 + 120 = 3420 s stays inside the ceiling.
N_REC_LONG = 4096              # recorded clocks = 32 output samples at OSR 128
CYCLES_LONG = 12               # 12 cycles over 4096 clocks = 15 kHz, bin 12 exactly
DECK_LONG = "modulator_tran_long.cir"
REQUEST_LONG = "request_long.json"
PER_CORNER_TIMEOUT_S_LONG = 3300
MAX_UNITS_PER_JOB_LONG = 1
MAX_CONCURRENT_JOBS_LONG = 7   # one job per corner; capacity_wait_s absorbs refusals

# Coherent tone: CYCLES whole periods over the N_REC recorded clocks. 3 is odd
# and coprime with 1024, and puts the tone at 15 kHz, inside the 20 kHz band of
# spec row 1. The long bench (CYCLES_LONG over N_REC_LONG) lands the tone on
# the same 15 kHz: 12 cycles over 4096 clocks is exactly bin 12 at 1250 Hz
# bin bandwidth. On the bitstream route the tone bin only has to be an
# integer (coherence is by construction over the whole window), which 12 is.
CYCLES = 3
FIN_HZ = CYCLES * FS_HZ / N_REC

# Window actually measured: clocks N_SETTLE .. N_SETTLE+n_rec-1. The 1024
# constants below are this function applied to the committed bench length; the
# long bench calls it with N_REC_LONG (identical formulas, so identical
# floats where the lengths coincide).
def window(n_rec):
    """(T_REC_FROM, T_REC0, T_REC1, T_END) for an n_rec-clock record."""
    t_rec_from = TCLK0 + N_SETTLE * TPER
    t_rec0 = TRISE0 + N_SETTLE * TPER
    t_rec1 = t_rec0 + n_rec * TPER
    t_end = TRISE0 + (N_SETTLE + n_rec + 1) * TPER   # one spare clock after
    return t_rec_from, t_rec0, t_rec1, t_end


T_REC_FROM, T_REC0, T_REC1, T_END = window(N_REC)
T_MAX_STEP = 1.0e-9

# Amplitude. Model B's full scale is the 1.2 V differential reference
# (sim/bmodel/model.py: "+/-1 is full scale ... spec row 11 (0.5*VREF peak) is
# -6 dBFS"), so -6 dBFS is 0.6 V peak differential = 0.3 V peak per side about
# VCM -- the same operating point spec sec 5.4 derives the swing from and the
# amplitude the behavioural record was taken at.
VREF_DIFF_V = 1.2
AMP_DBFS = -6.0
AMP_SE_V = 0.5 * VREF_DIFF_V * 10.0 ** (AMP_DBFS / 20.0)   # 0.30069 V per side

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


def wmax(vec, mask):
    return f"vecmax({vec}*{mask} - 10*(1-{mask}))"


def wmin(vec, mask):
    return f"vecmin({vec}*{mask} + 10*(1-{mask}))"


def cycle_mean(signal, unit, limits=None, spec_row=None, name=None,
               t_rec_from=None, n_rec=None):
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
                        "from": t_rec_from, "cycles": n_rec}}
    if limits:
        m["limits"] = limits
    if spec_row:
        m["spec_row"] = spec_row
    return m


def energy(name, source, voltage, t_rec0, t_rec1):
    return {"name": name, "unit": "J",
            "energy": {"source": source, "voltage": voltage,
                       "from": t_rec0, "to": t_rec1}}


def crossings(name, signal, edge, limits=None, spec_row=None, unit=None,
              t_rec_from=None, t_rec1=None):
    m = {"name": name,
         "crossings": {"signal": signal, "level": 0.0, "edge": edge,
                       "from": t_rec_from, "to": t_rec1, "max": 100000}}
    if unit:
        m["unit"] = unit
    if limits:
        m["limits"] = limits
    if spec_row:
        m["spec_row"] = spec_row
    return m


def measurements(n_rec=N_REC):
    """The request's measurement list for an n_rec-clock record.

    With the default n_rec the output is byte-identical to the committed
    request's measurements (same formulas, same module constants); the long
    bench passes N_REC_LONG. Per-clock limits and window arguments follow the
    record length; nothing else moves.
    """
    t_rec_from, t_rec0, t_rec1, _ = window(n_rec)
    rec_clocks = tuple(range(N_SETTLE, N_SETTLE + n_rec))
    mask = win_mask(t_rec0, t_rec1)
    ms = [
        # --- what was actually simulated (reference validity, not a spec row)
        e("vdda_v", "v(vdda)[0]", "V"),

        # --- row 13: analog power -------------------------------------------
        cycle_mean("v(pana)", "W", {"max": P_ANA_MAX_W}, "13", name="p_ana",
                   t_rec_from=t_rec_from, n_rec=n_rec),
        cycle_mean("v(pvdda)", "W", name="p_vdda",
                   t_rec_from=t_rec_from, n_rec=n_rec),
        cycle_mean("v(pref)", "W", name="p_ref",
                   t_rec_from=t_rec_from, n_rec=n_rec),
        cycle_mean("v(pvcm)", "W", name="p_vcm",
                   t_rec_from=t_rec_from, n_rec=n_rec),
        # Independent second route to the same quantity: klt integrates each
        # source's own v*i over the window. run_tran.py cross-checks the two
        # and refuses a record whose routes disagree.
        energy("e_vdda", "vdda", "v(vdda)", t_rec0, t_rec1),
        energy("e_vrefp", "vrefp", "v(vrefp)", t_rec0, t_rec1),
        energy("e_vrefn", "vrefn", "v(vrefn)", t_rec0, t_rec1),
        energy("e_vvcm", "vvcm", "v(vcm)", t_rec0, t_rec1),

        # --- row 11: integrator output swing --------------------------------
        e("o1_max", wmax("v(o1d)", mask), "V"),
        e("o1_min", wmin("v(o1d)", mask), "V"),
        e("o1_swing_pp", "o1_max - o1_min", "V", {"max": SWING_MAX_VPP}, "11"),
        e("o2_max", wmax("v(o2d)", mask), "V"),
        e("o2_min", wmin("v(o2d)", mask), "V"),
        e("o2_swing_pp", "o2_max - o2_min", "V", {"max": SWING_MAX_VPP}, "11"),
        # Single-ended extremes: headroom to the rails, and the other reading
        # of spec sec 5.4's figure. Reported, never graded.
        e("o1p_max", wmax("v(xmod.o1p)", mask), "V"),
        e("o1p_min", wmin("v(xmod.o1p)", mask), "V"),
        e("o2p_max", wmax("v(xmod.o2p)", mask), "V"),
        e("o2p_min", wmin("v(xmod.o2p)", mask), "V"),

        # --- row 5: the loop is clocked at fs and the bitstream is alive -----
        # phi1 rises exactly once per modulator clock, so its count over the
        # window is n_rec if and only if the clock generator ran at fs for the
        # whole record.
        crossings("phi1_edges", "v(xmod.phi1)-0.5*v(vdda)", "rise",
                  {"min": n_rec, "max": n_rec}, "5",
                  t_rec_from=t_rec_from, t_rec1=t_rec1),
        # The bitstream must toggle (a stuck loop fails min) and must not
        # toggle more than once per clock (a glitching latch or a metastable
        # comparator fails max). The returned crossing times are the bitstream.
        crossings("bs_edges", "v(bs)-0.5*v(vdda)", "either",
                  {"min": 1, "max": n_rec}, "5",
                  t_rec_from=t_rec_from, t_rec1=t_rec1),
        cycle_mean("v(bs)", "V", name="bs_mean",
                   t_rec_from=t_rec_from, n_rec=n_rec),
    ]
    # --- per-clock held samples: the bitstream and both integrator outputs,
    # one value per recorded clock at the stated instant. These are .meas
    # cards rather than a waveform artifact so they come back inline in the
    # report from the batch fleet, with no artifact retrieval (#128 needs
    # them, DR-001 item 3 grades the model on them).
    for k in rec_clocks:
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
REQUEST = "request.json"
SAMPLES_DIR = "samples"
RECORD_NAME = "record.json"
TAG = "anchors"


def anchor_units():
    """DR-002 anchor set, with `vclk` swept alongside `vdda`.

    settling_common.anchor_units() gives the shared 7-point list, but this
    bench needs the clock source's PULSE levels rescaled per corner too
    (corners.supply_waveforms), and that requires `vclk` to be a supply_v key
    of every unit. The anchor set itself still comes from the shared constant.
    """
    return [{"process": p, "supply_v": {"vdda": v, "vclk": v}, "temperature_c": t}
            for p, v, t in ANCHOR_POINTS]


def build_request(long=False):
    # settling_common.request() carries the shared engine/models/backend block;
    # its full 45-point grid and 0.1 ns step are replaced here (DR-002 keeps the
    # full grid for the cheap single-mechanism runs; this one is an anchor run).
    n_rec = N_REC_LONG if long else N_REC
    deck = DECK_LONG if long else DECK
    timeout = PER_CORNER_TIMEOUT_S_LONG if long else PER_CORNER_TIMEOUT_S
    units = MAX_UNITS_PER_JOB_LONG if long else MAX_UNITS_PER_JOB
    conc = MAX_CONCURRENT_JOBS_LONG if long else MAX_CONCURRENT_JOBS
    _, _, _, t_end = window(n_rec)
    r = request(deck, measurements(n_rec), t_end, timeout_s=timeout,
                poll_timeout_s=POLL_TIMEOUT_S)
    r["corners"] = {"units": anchor_units(), "supply_waveforms": ["vclk"]}
    r["analysis"] = {"kind": "tran",
                     "args": f"{T_MAX_STEP:.6g} {t_end:.9g} 0 {T_MAX_STEP:.6g}"}
    # Keep only the vectors the measurements and the reduction need resident:
    # the assembled modulator has of the order of a thousand nodes and the
    # record is ~300 k timepoints, which `save all` would make expensive.
    r["options"] = {"timeout_s": timeout, "keep_artifacts": False,
                    "save_vectors": SAVE_VECTORS}
    # Sharding is sized from the measured per-corner runtime (see
    # MAX_UNITS_PER_JOB). The fleet kills a job at its whole-job ceiling and
    # reports every unit `batch_job_timeout`, so each job's conservative
    # serial bound (timeout_s * units + 120) has to fit under it; too many
    # jobs is the other failure, because each one is an instance the shared
    # Spot quota has to find.
    r["batch"] = {"poll_timeout_s": POLL_TIMEOUT_S,
                  "capacity_wait_s": CAPACITY_WAIT_S,
                  "max_units_per_job": units,
                  "max_concurrent_jobs": conc}
    return r


def build_deck(long=False):
    tmpl = (HERE / "modulator_tran.cir.tmpl").read_text()
    cycles = CYCLES_LONG if long else CYCLES
    n_rec = N_REC_LONG if long else N_REC
    fin_hz = cycles * FS_HZ / n_rec
    subs = {
        "@TCLK0@": f"{TCLK0:.12g}",
        "@PW@": f"{PW:.12g}",
        "@TPER@": f"{TPER:.12g}",
        "@AMP@": f"{AMP_SE_V:.12g}",
        "@FIN@": f"{fin_hz:.12g}",
        "@FS@": f"{FS_HZ:.12g}",
        "@CYCLES@": str(cycles),
        "@NREC@": str(n_rec),
        "@DBFS@": f"{AMP_DBFS:g}",
        "@TRISE0@": f"{TRISE0:.12g}",
    }
    for k, v in subs.items():
        tmpl = tmpl.replace(k, v)
    return tmpl


# -------------------------------------------------- record-facing identity ---
# run_tran.build_record stamps these verbatim; they are the per-length bench
# descriptions the committed record.json carries (kept byte-equal to it for
# the default bench) and their long-record counterparts.
RECORD_FIXTURE = (
    "Short full-modulator transistor-level transient (issue #125, "
    "DR-001 item 2): design/modulator/modulator.spice with "
    "design/ota/ota_fd.spice and "
    "design/modulator/comparator/comparator.spice, ideal DR-005 "
    "boundary sources, a coherent single tone at -6 dBFS and the "
    "5.12 MHz clock.")
RECORD_EVIDENCE_SOURCE = "T (DR-001 item 2)"
RECORD_LENGTH_NOTE = (
    "Cost. Measured on the dispatch host before any corner ran: "
    "about 3.1 s of ngspice per microsecond of transient at "
    "tt/27 C/1.80 V with a 1 ns maximum timestep, i.e. about "
    "0.61 s per modulator clock. 1088 clocks is ~11 min at tt and "
    "~22 min at a corner twice as slow, inside the batch fleet's "
    "3600 s whole-job ceiling with margin. DR-001 item 2 requires "
    "the length to be stated; this is that statement, written "
    "into make_request.py before the first result.")
RECORD_SONDR_NOTE = (
    "No SNDR is claimed from this record. An in-band figure needs "
    "bins inside the 20 kHz band of spec row 1; {n_rec} "
    "modulator clocks give a bin bandwidth of "
    "{bin_bw:.0f} Hz on the bitstream and only "
    "{n_out:g} output samples after decimation by the "
    "OSR, so neither route resolves the band. Spec sec 1.2's row 2 "
    "claim is a B-model result with the DR-001 cross-check; this "
    "bench supplies the cross-check's transistor-level side as "
    "bitstreams and integrator waveforms, not as an SNDR.")

LONG_RECORD_FIXTURE = (
    "Long-record full-modulator transistor-level transient (DR-001 item 2 "
    "as amended by DR-001 corrigendum 01, issue #290): the same fixture as "
    "the committed short bench (design/modulator/modulator.spice with "
    "design/ota/ota_fd.spice and "
    "design/modulator/comparator/comparator.spice, ideal DR-005 "
    "boundary sources, a coherent single tone at -6 dBFS and the "
    "5.12 MHz clock), run for "
    f"{N_REC_LONG} recorded clocks so DR-001 item 3's in-band SNDR leg is "
    "computable (1250 Hz bins: 16 band bins, tone bin 12, 7 in-band noise "
    "bins beside the 9-bin Blackman-Harris lobe).")
LONG_RECORD_EVIDENCE_SOURCE = ("T (DR-001 item 2, as amended by DR-001 "
                               "corrigendum 01)")
LONG_RECORD_LENGTH_NOTE = (
    "Cost, measured before the set ran (operator ruling note, issue #290): "
    "the probe run measured 1104.6 s of fleet unit runtime for one corner "
    "(tt/27 C/1.80 V, 4160 clocks including settling, klt-sim-56a43a043984, "
    "~0.86 GB peak RSS, ~0.265 s/clock), against 441-606 s per 1088 clocks "
    "for the committed short run. 8192 recorded clocks extrapolate past the "
    "fleet's 3600 s whole-job ceiling at every measured per-clock rate, and "
    "one unit's runtime is not reducible by sharding (sharding divides units "
    "per job, never one unit's transient), so 4096 is the longest "
    "band-resolving power of two that fits; each corner gets its own job "
    "(1 unit, timeout_s 3300, serial bound 3420 s <= 3600 s). "
    "spec/decisions/DR-001-corrigendum-01.md states this as the length's "
    "evidence.")
LONG_RECORD_SONDR_NOTE = (
    "No standalone SNDR is claimed from this record even though "
    "{n_rec} clocks now resolve the 20 kHz band ({bin_bw:.0f} Hz bins, "
    "{n_out:g} output samples at OSR 128): the bench supplies the "
    "cross-check's transistor-level side as bitstreams and integrator "
    "waveforms, and DR-001 item 3's in-band SNDR figures are computed on "
    "BOTH sides, identically, by the cross-check itself "
    "(sim/bmodel/xcheck.py, sim/bmodel/xcheck-record-long.json), never by "
    "one side alone. Spec sec 1.2's row 2 claim remains a B-model result "
    "with the DR-001 cross-check.")


def _identity(long):
    return {
        "RECORD_FIXTURE": LONG_RECORD_FIXTURE if long else RECORD_FIXTURE,
        "RECORD_EVIDENCE_SOURCE": (LONG_RECORD_EVIDENCE_SOURCE if long
                                   else RECORD_EVIDENCE_SOURCE),
        "RECORD_LENGTH_NOTE": LONG_RECORD_LENGTH_NOTE if long
        else RECORD_LENGTH_NOTE,
        "RECORD_SONDR_NOTE": LONG_RECORD_SONDR_NOTE if long
        else RECORD_SONDR_NOTE,
    }


# The long bench under the attribute names run_tran.py reads off this module
# for the default bench, so `B = mk` and `B = mk.LONG` are interchangeable
# there. Window()/measurements()/build_request()/build_deck() stay functions
# taking `long=`.
LONG = SimpleNamespace(
    DECK=DECK_LONG, REQUEST=REQUEST_LONG, N_REC=N_REC_LONG, CYCLES=CYCLES_LONG,
    FIN_HZ=CYCLES_LONG * FS_HZ / N_REC_LONG,
    REC_CLOCKS=tuple(range(N_SETTLE, N_SETTLE + N_REC_LONG)),
    PER_CORNER_TIMEOUT_S=PER_CORNER_TIMEOUT_S_LONG,
    MAX_UNITS_PER_JOB=MAX_UNITS_PER_JOB_LONG,
    MAX_CONCURRENT_JOBS=MAX_CONCURRENT_JOBS_LONG,
    SAMPLES_DIR="samples-long", RECORD_NAME="record-long.json",
    TAG="anchors-long",
    sample_time=sample_time, u_diff=u_diff,
    **_identity(True))
# Every remaining bench-independent name run_tran.py reads, spelled out so a
# missing one fails here rather than deep inside a record build.
for _name in ("N_SETTLE", "TPER", "T_MAX_STEP", "FS_HZ", "TRISE0",
              "AMP_DBFS", "AMP_SE_V", "VREF_DIFF_V", "ANCHOR_POINTS",
              "P_ANA_MAX_W", "SWING_MAX_VPP"):
    setattr(LONG, _name, globals()[_name])


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--long", action="store_true",
                    help="write the long-record bench (DR-001 corrigendum 01, "
                         "issue #290): modulator_tran_long.cir + "
                         "request_long.json, %d recorded clocks" % N_REC_LONG)
    a = ap.parse_args()
    if a.long:
        deck, req = DECK_LONG, REQUEST_LONG
        n_rec, cycles = N_REC_LONG, CYCLES_LONG
        body, request_doc = build_deck(long=True), build_request(long=True)
    else:
        deck, req = DECK, "request.json"
        n_rec, cycles = N_REC, CYCLES
        body, request_doc = build_deck(), build_request()
    (HERE / deck).write_text(body)
    (HERE / req).write_text(json.dumps(request_doc, indent=2) + "\n")
    fin_hz = cycles * FS_HZ / n_rec
    print(f"wrote {deck} and {req}: "
          f"{n_rec} recorded clocks after {N_SETTLE} settling clocks, "
          f"tone {fin_hz:.6g} Hz ({cycles} cycles), "
          f"{AMP_SE_V:.6g} V peak per side, "
          f"t_end {window(n_rec)[3]:.6g} s")

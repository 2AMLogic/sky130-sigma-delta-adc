#!/usr/bin/env python3
"""Regenerate ota_swing.cir and request.json for the OTA swing bench.

    python3 -I sim/ota-swing/make_request.py

Everything the bench claims is derived here and written into the deck and the
request (the committed deck/request are the bench; the record binds both by
sha256), the way sim/modulator-tran/make_request.py does it. See README.md
for what the numbers mean.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from settling_common import CAPACITY_WAIT_S, anchor_units, request  # noqa: E402

# ------------------------------------------------------------------ cells ---
# Two loads, both present in the same deck (two OTA instances, each in its own
# closed loop; one transient per corner covers both). The OTA is the committed
# design/ota/ota_fd.spice on main in both -- only the capacitors around it
# differ, because PR #257 rescales the integrating caps and nothing else.
CS_PF = 1.0        # sampling cap, driven by the staircase (spec 5.3 planning value)
CP_PF = 0.035      # summing-node parasitic per side, as in sim/ota-settling
CL_PF = 1.1        # per-side output load: next stage's Cs (1 pF) + 0.1 pF parasitics
CELLS = {
    # main cell as committed on main: Ci = Cs/0.5, C1 = C2 = 0.5 (model B until #148)
    "a": {"label": "main", "ci_pf": 2.0,
          "source": "design/integrator as on main: Ci = Cs/0.5 = 2 pF (C1 = C2 = 0.5)"},
    # the #257 rescale (DR-007): C1 = C2 = 0.3, Ci = Cs/0.3 = 3.334 pF drawn
    # (design/integrator/SIZING.md at PR #257 head 80167c7; not merged -- the
    # bench parameterises the cell values and does not depend on the merge)
    "b": {"label": "c0p3", "ci_pf": 3.334,
          "source": ("PR #257 rescale (DR-007): Ci = Cs/0.3 = 3.334 pF drawn "
                     "(40.64 x 40.64 um cap_mim_m3_1), design/integrator/SIZING.md "
                     "at PR #257 head 80167c7d1f8cf7e195cf66ed5652207528e0a6d1")},
}


def beta(ci_pf):
    """Feedback factor: Ci / (Ci + 2 Cs + Cp), the integrate-phase load.

    Both the input and the DAC sampling cap sit on the summing node in phi2
    (design/ota/SIZING.md's corrected trace), so the summing-node total is
    Ci + 2 Cs + Cp. sim/ota-settling models one Cs (beta ~ 0.66); this bench
    carries the second one as a cap parked at vcm, which is what the cell
    presents.
    """
    return ci_pf / (ci_pf + 2.0 * CS_PF + CP_PF)


# ------------------------------------------------------------- amplitudes ---
# Differential output swing, V peak-to-peak, from small signal to beyond the
# 2.6 Vpp the ruling cares about (the recorded integrator-1 swings reach
# 2.53 Vpp). SMALL_REF is the small-signal reference point: 0.2 Vpp is 50 mV
# per side about the common mode, far inside the ~0.57 V cascode margins, and
# its extracted gain is cross-checked against sim/ota-gain's 45-corner record
# at every anchor.
SMALL_REF_VPP = 0.2
SWEEP_VPP = tuple(round(0.2 * k, 4) for k in range(2, 15))   # 0.4 .. 2.8 Vpp
AMPS_VPP = (SMALL_REF_VPP,) + SWEEP_VPP                      # 14 amplitudes

# Each amplitude is reached by NSTEP accumulated transfer steps of the driven
# Cs plates, each step one clock's worth of charge transfer in the same
# direction, the way a run of same-decision clocks builds integrator-1 swing
# in the modulator. One single huge step would swing the driving plates
# Ci/Ci times the output (charge conservation), far outside anything the cell
# sees; five bounded steps keep every plate excursion at the per-clock scale
# (worst: 0.28 V per side for the main cell, 0.47 V for the c0p3 cell, against
# the real per-clock feedback step of 0.3 / 0.23 V per side).
NSTEP = 5

# ----------------------------------------------------------------- timing ---
# All times in seconds. Per amplitude and polarity: the loop is reset (ideal
# switches short out<->summing node: unity feedback, vod -> 0, Ci re-centered),
# the plates re-park at vcm, then NSTEP steps with T_STEP spacing, then a hold
# that ends well past the 97.66 ns phase (spec row 5): the settling record
# shows the worst corner settles to 6.8e-5 within ~100 ns of a full-scale step.
T_PRE = 500e-9        # initial reset: bias and CMFB start-up
T_RESET = 250e-9      # reset window per segment (absorbs the plate re-park kick)
T_QUIET = 50e-9       # after the reset switches open, before the first step
T_STEP = 120e-9       # between step edges (~one clock: the phase is 97.66 ns)
T_HOLD = 300e-9       # hold after the last step edge
T_MEAS_EXTRA = 50e-9  # slack between the measurement instant and segment end
T_RIPPLE_BEFORE = 150e-9   # settled-ness probe this far before the measurement
T_EDGE = 0.2e-9       # plate step ramp (bench drive, not a switch edge)
T_SW_EDGE = 1e-9      # reset switch control edge (well inside the quiet gap)
SEGMENT_S = T_RESET + T_QUIET + NSTEP * T_STEP + T_HOLD + T_MEAS_EXTRA
T_END = T_PRE + len(AMPS_VPP) * 2 * SEGMENT_S
T_MAX_STEP = 1e-9

RIPPLE_MAX_V = 5e-3   # settled-ness admission gate (run_swing.py), per segment

# ------------------------------------------------------- staircase layout --
def segment_times():
    """(reset_start, step_edges, measure_t, ripple_t, end_t) per segment.

    Segments are in amplitude order, up polarity then down polarity for each
    amplitude, all cells sharing the same clocking (the two loops are
    independent but time-aligned, so one measurement grid serves both).
    """
    out = []
    t = T_PRE
    for a in AMPS_VPP:
        for direction in (+1, -1):
            r0 = t
            steps = [r0 + T_RESET + T_QUIET + j * T_STEP for j in range(NSTEP)]
            meas = r0 + T_RESET + T_QUIET + (NSTEP - 1) * T_STEP + T_HOLD
            out.append({"amp_vpp": a, "direction": direction, "reset_start": r0,
                        "steps": steps, "measure_t": meas,
                        "ripple_t": meas - T_RIPPLE_BEFORE, "end_t": r0 + SEGMENT_S})
            t += SEGMENT_S
    return out


SEGMENTS = segment_times()


def plate_step_side(cell, amp_vpp):
    """Per-side driven-plate step that moves vod by amp_vpp/(2*NSTEP).

    A differential output step dVod takes dQ = Ci*dVod of feedback charge, so
    the driven plates must move dVside = dVod*Ci/(2*Cs) per side.
    """
    return (amp_vpp / (2.0 * NSTEP)) * CELLS[cell]["ci_pf"] / (2.0 * CS_PF)


# ------------------------------------------------------------ deck builder --
def _fmt(t):
    return f"{t:.9g}"


def _pwl(points):
    """ngspice PWL continuation lines from [(t, v), ...], folded, closed."""
    txt = " ".join(f"{_fmt(t)} {_fmt(v)}" for t, v in points) + " )"
    # every content line is a `+` continuation of the card line that opened
    # the PWL( ; keep them under ~190 chars
    out, line = [], "+ "
    for tok in txt.split(" "):
        if len(line) + len(tok) + 1 > 190:
            out.append(line.strip())
            line = "+ "
        line += " " + tok
    out.append(line.strip())
    return "\n".join(out)


def plate_pwl(cell, side):
    """PWL points for one driven plate (side 'p' or 'n') of one cell.

    Plates park at VCM inside every reset window (the re-park kick lands while
    the reset switches still short the loop, so it is absorbed before the
    switches open), then take NSTEP accumulated steps of one polarity.
    """
    v = 0.9
    pts = [(0.0, v)]
    for seg in SEGMENTS:
        r0 = seg["reset_start"]
        d = seg["direction"] * (1 if side == "p" else -1)
        step = d * plate_step_side(cell, seg["amp_vpp"])
        if abs(v - 0.9) > 0:                       # re-park inside reset
            pts.append((r0, v))
            pts.append((r0 + T_EDGE, 0.9))
            v = 0.9
        else:
            pts.append((r0, v))
        for j, ts in enumerate(seg["steps"]):
            pts.append((ts, v))
            v = round(0.9 + (j + 1) * step, 12)
            pts.append((ts + T_EDGE, v))
    return pts


def rst_pwl():
    """Reset switch control: 1 (closed) from t=0 and inside every reset window."""
    pts = [(0.0, 1.0)]
    closed = True
    for seg in SEGMENTS:
        r0 = seg["reset_start"]
        if not closed:                       # reopen the switch first
            pts.append((r0 - T_SW_EDGE, 0.0))
            pts.append((r0, 1.0))
        pts.append((r0 + T_RESET, 1.0))
        pts.append((r0 + T_RESET + T_SW_EDGE, 0.0))
        closed = False
    pts.append((T_END, 0.0))
    return pts


def build_deck():
    lines = [
        "* OTA output-swing / gain-compression bench (issue #331) -- circuit",
        "* body for `klt sim` (no .lib/.control/.end: klt sim owns those;",
        "* corner = process/temp/Vdda). Circuit under test:",
        "* design/ota/ota_fd.spice as committed on main, twice -- one instance",
        "* per load. Closed-loop integrate-phase configuration of",
        "* design/ota/SIZING.md with the summing-node load the integrator",
        "* presents in phi2 (driven Cs + parked Cs + Cp + Ci feedback,",
        "* beta = Ci/(Ci+2Cs+Cp)), 1.1 pF external load per side (next",
        "* stage's Cs + output parasitics, SIZING case A). Cell a: Ci = 2 pF",
        "* (main). Cell b: Ci = 3.334 pF (the #257 c0p3 rescale, DR-007,",
        "* parameterised here; it does not depend on that PR merging).",
        "* Boundary (DR-005): vcm = 0.9 V ideal, ibias = 5 uA ideal sink.",
        "* Sequence per amplitude and polarity: reset (ideal switches short",
        "* out<->sum, unity feedback, vod -> 0, plates re-park at vcm), then",
        f"* {NSTEP} accumulated plate steps (one clock's charge transfer each,",
        "* the way same-decision clocks build integrator swing), then a hold",
        "* past the 97.66 ns phase. vod and the output common mode are read",
        "* at the end of every hold; see make_request.py for the grid.",
        ".include \"../../design/ota/ota_fd.spice\"",
        "Vdda vdda 0 1.8",
        "Vvcm vcm 0 0.9",
        "Vrst rst 0 PWL(",
    ]
    lines.append(_pwl(rst_pwl()))
    for c in sorted(CELLS):
        ci = CELLS[c]["ci_pf"]
        lines += [
            f"* --- cell {c}: {CELLS[c]['label']} (Ci = {ci:g} pF) ---",
            "* one ibias source per cell: a shared node would halve every leg",
            "* (two diodes on one 5 uA source), and the OTA would run at half bias",
            f"Ibias{c} vdda ibias{c} 5u",
            f"Xota{c} vdda 0 sump{c} sumn{c} outp{c} outn{c} vcm ibias{c} ota_fd",
        ]
        for side in ("p", "n"):
            lines.append(f"Vs{side}{c} inp{c}{side} 0 PWL(")
            lines.append(_pwl(plate_pwl(c, side)))
        # driven Cs (input side) and parked Cs (DAC side, at vcm: phi2 position)
        lines += [
            f"Csp{c} inp{c}p sump{c} {CS_PF:g}p",
            f"Csn{c} inp{c}n sumn{c} {CS_PF:g}p",
            f"Cdp{c} sump{c} vcm {CS_PF:g}p",
            f"Cdn{c} sumn{c} vcm {CS_PF:g}p",
            f"Cip{c} sump{c} outn{c} {ci:g}p",
            f"Cin{c} sumn{c} outp{c} {ci:g}p",
            f"Cpp{c} sump{c} 0 {CP_PF * 1e3:g}f",
            f"Cpn{c} sumn{c} 0 {CP_PF * 1e3:g}f",
            f"Clp{c} outp{c} 0 {CL_PF:g}p",
            f"Cln{c} outn{c} 0 {CL_PF:g}p",
            f"Srp{c} outn{c} sump{c} rst 0 swr",
            f"Srn{c} outp{c} sumn{c} rst 0 swr",
            f"Bvod{c} vod{c} 0 V='v(outp{c})-v(outn{c})'",
            f"Bocm{c} ocm{c} 0 V='0.5*(v(outp{c})+v(outn{c}))'",
        ]
    lines += [
        ".model swr sw vt=0.5 vh=0.1 ron=1 roff=1e15",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------- measurements ---
def seg_name(cell, i, pol, kind):
    return f"s{cell}{i:02d}{pol}_{kind}"


def measurements():
    """The request's measurement list: one vdda probe + per-segment cards.

    Per cell, amplitude and polarity: the settled differential output, both
    single-ended outputs (their mean is the output common mode), and the
    differential output 150 ns earlier (the settled-ness pair run_swing.py
    gates on). The small-signal segments' vod cards carry a reference-validity
    limit: a loop that never closed reads ~0 there and fails the corner.
    """
    ms = [{"name": "vdda_v", "expr": "v(vdda)[0]", "unit": "V"}]
    small_target = SMALL_REF_VPP / 2.0
    for i, seg in enumerate(SEGMENTS):
        pol = "u" if seg["direction"] > 0 else "d"
        t, tr = seg["measure_t"], seg["ripple_t"]
        for c in sorted(CELLS):
            ms.append({"name": seg_name(c, i, pol, "vod"), "unit": "V",
                       "spice": f".meas tran {seg_name(c, i, pol, 'vod')} "
                                f"FIND v(vod{c}) AT={t:.9e}"})
            ms.append({"name": seg_name(c, i, pol, "outp"), "unit": "V",
                       "spice": f".meas tran {seg_name(c, i, pol, 'outp')} "
                                f"FIND v(outp{c}) AT={t:.9e}"})
            ms.append({"name": seg_name(c, i, pol, "outn"), "unit": "V",
                       "spice": f".meas tran {seg_name(c, i, pol, 'outn')} "
                                f"FIND v(outn{c}) AT={t:.9e}"})
            ms.append({"name": seg_name(c, i, pol, "rip"), "unit": "V",
                       "spice": f".meas tran {seg_name(c, i, pol, 'rip')} "
                                f"FIND v(vod{c}) AT={tr:.9e}"})
            if seg["amp_vpp"] == SMALL_REF_VPP:
                # small-signal reference: the loop must have closed
                lim = {"min": 0.9 * small_target} if pol == "u" \
                    else {"max": -0.9 * small_target}
                ms[-4]["limits"] = lim
    return ms


SAVE_VECTORS = ["v(vdda)", "v(rst)"]
for _c in sorted(CELLS):
    SAVE_VECTORS += [f"v(vod{_c})", f"v(ocm{_c})", f"v(outp{_c})", f"v(outn{_c})"]

# Fleet scheduling. Sized from the runs before the committed record: one unit
# (both cells, ~36 us transient at a 1 ns maximum timestep) measured 22.4 s
# worst on the fleet (tt/27C/1.80V) and ~45 s in a local single-corner probe,
# so the 900 s per-corner timeout carries an order of magnitude of margin.
# The fleet kills a job still running at its whole-job 3600 s ceiling and
# reports every unit batch_job_timeout, and klt's pre-submit bound is
# timeout_s*units + 120 s, so 3 units per job keeps the bound at 2820 s.
PER_CORNER_TIMEOUT_S = 900
POLL_TIMEOUT_S = 14400
MAX_UNITS_PER_JOB = 3
MAX_CONCURRENT_JOBS = 3

DECK = "ota_swing.cir"
REQUEST = "request.json"


def build_request():
    r = request(DECK, measurements(), t_end=T_END,
                timeout_s=PER_CORNER_TIMEOUT_S, poll_timeout_s=POLL_TIMEOUT_S)
    r["corners"] = {"units": anchor_units()}
    r["analysis"] = {"kind": "tran",
                     "args": f"{T_MAX_STEP:.6g} {T_END:.9g} 0 {T_MAX_STEP:.6g}"}
    r["options"] = {"timeout_s": PER_CORNER_TIMEOUT_S, "keep_artifacts": False,
                    "save_vectors": SAVE_VECTORS,
                    # the finite-gain extraction divides by (target - vod),
                    # ~3e-4 V wide at the small-signal reference, so the .meas
                    # values need far more than ngspice's default 6 digits
                    "ngspice_init": ["set numdgt=12", "set measureprec=12"]}
    r["batch"] = {"poll_timeout_s": POLL_TIMEOUT_S,
                  "capacity_wait_s": CAPACITY_WAIT_S,
                  "max_units_per_job": MAX_UNITS_PER_JOB,
                  "max_concurrent_jobs": MAX_CONCURRENT_JOBS}
    return r


if __name__ == "__main__":
    (HERE / DECK).write_text(build_deck())
    (HERE / REQUEST).write_text(json.dumps(build_request(), indent=2) + "\n")
    print(f"wrote {DECK} ({len(SEGMENTS)} segments, t_end {T_END*1e6:.1f} us) "
          f"and {REQUEST} ({len(measurements())} measurements)")

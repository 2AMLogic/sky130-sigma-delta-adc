#!/usr/bin/env python3
"""Regenerate the two deck/request pairs (loop, trip) for the comparator bench.

See README.md for what each variant measures and why the numbers mean what
they mean. Everything that is a derivation rather than a measurement lives
here or in run_decision.py, never in prose only.

The two variants share one template and differ in exactly two places: the
reference pair (live for `loop`, nulled for `trip`) and the differential
input waveform. Nothing in the comparator's own surroundings differs.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from settling_common import request  # noqa: E402

# ---------------------------------------------------------------- clock grid
FS_HZ = 5.12e6
TCLK = 1.0 / FS_HZ                 # 195.3125 ns, spec row 5
T_HALF = TCLK / 2.0                # 97.65625 ns, the bare half-period
T0 = 10.1e-9                       # 50 % point of the first clk rising edge
                                   # (`pulse(... 10n 0.2n ...)` in the deck)
# Measured on this hierarchy at tt / 27 C / 1.8 V (local probe, 2026-11-13):
# phi1 rises 0.86 ns after the clk edge, phi2 falls 0.28 ns after it, and the
# phi1 high time is ~97.8 ns. Nothing below assumes those numbers -- every
# edge is located inside its own window at the corner being measured -- but
# they are what sets the window widths.

# A decision is evaluated on the phi1 rise that follows the clk rise of its
# clock; the search window runs from just before the clk edge to the end of
# the phi1 high time it can possibly occupy.
W_LEAD = 2e-9                      # window opens this far before the clk edge
W_DEC = 110e-9                     # ... and closes this far after it

# The comparator's input is held by the integrator-2 OTA for the whole of
# phi1, so the value it decided on can be read anywhere inside phi1 once the
# kickback disturbance has settled. This window sits late in phi1 (phi1 is
# ~97 ns wide) and is deliberately wide enough that the solver always stores
# points inside it.
W_HOLD = (50e-9, 80e-9)            # relative to the clk edge
W_PREV = (-12e-9, -3e-9)           # dp/dn hold the PREVIOUS decision here
W_KICK = 40e-9                     # kickback search window after the clk edge

# ------------------------------------------------------------- model B units
# Model B advances integrator 2 by k2*(x1 - y) with k2 = C2 = 0.5 and y = +/-1
# at full scale; the cell moves its differential output by
# (Cs/Ci)*(v_o1_diff + vdac_diff) = 0.5*(v_o1_diff + vdac_diff) with
# vdac_diff = -y*(VREFP - VREFN) = -y*1.2 V. Substituting x1 = v_o1_diff/S
# makes the two agree for S = 1.2 V, i.e. one x2 unit is 1.2 V of differential
# output at integrator 2 -- the same factor sim/integrator-ci/README.md
# derives for x1 at integrator 1, which is expected since both stages are the
# same cell with the same Cs/Ci and the same DAC. comparator_offset and
# comparator_hysteresis are in those x2 units.
FS_VOLTS = 1.2

# ------------------------------------------------------------ `trip` variant
# Charge transfer per clock, nominal: Cs/Ci = 0.5 (sim/integrator-ci).
G = 0.5
STEP_V = 500e-6                    # staircase step at the comparator input,
                                   # i.e. the resolution of both trip points
O1D_FINE = STEP_V / G              # integrator-1 output held here during a ramp
# The staircase is deliberately offset by half a step so no decision is taken
# on an exactly-zero differential: a latch at its own trip point is
# metastable, and a metastable clock in the middle of the ramp would be a
# bench artefact, not a measurement.
O1D_COARSE = -2.25e-3              # two-clock approach to the foot of the ramp
RAMP_SPAN_V = 3.5e-3               # the sweep must cover at least this much

# Clock indices of the trip variant's phases (see README "Staircase").
TRIP_UP_FIRST, TRIP_UP_LAST = 4, 12      # decisions on a rising staircase
TRIP_DN_FIRST, TRIP_DN_LAST = 14, 23     # ... and on a falling one
TRIP_LAST_CLK = TRIP_DN_LAST

# ------------------------------------------------------------ `loop` variant
LOOP_VIN_DIFF = 0.06               # V differential = 0.05 FS, a small DC input
LOOP_FIRST, LOOP_LAST = 4, 13      # graded clocks (0..3 are loop start-up)
LOOP_KICK_CLKS = (6, 7)            # clocks the kickback numbers come from
LOOP_PHI1_REF = 8                  # clock the phi1 high time is measured on
LOOP_LAST_CLK = LOOP_LAST + 1

T_END = {"loop": T0 + (LOOP_LAST_CLK + 1) * TCLK + 130e-9,
         "trip": T0 + (TRIP_LAST_CLK + 1) * TCLK + 130e-9}

# Per-corner wall-clock budget. A 2.5 us transient of this hierarchy took
# 6 min on the development host; these transients are ~2.9 us (loop) and
# ~5.7 us (trip), and the slow corners (ss, 1.62 V, -40 C) are slower again.
TIMEOUT_S = 3600
POLL_TIMEOUT_S = 21600
# One job of 45 units at that budget would outrun the fleet's whole-job
# ceiling, so the request asks klt to split it into the fewest jobs that fit
# rather than being refused (or silently warned) at submit time.
JOB_CEILING_CHECK = "split"


def tedge(k):
    """50 % point of the clk rising edge of clock k."""
    return T0 + k * TCLK


def win(a, b):
    """ngspice mask vector, 1 inside [a, b] and 0 outside."""
    return f"(time ge {a:.9g})*(time le {b:.9g})"


def first_time(mask, sentinel):
    """First stored time where `mask` is 1, else `sentinel`.

    `vecmin(time*mask)` alone is always 0 (the masked-out samples are 0), so
    the masked-out samples have to be pushed above every real time instead.
    """
    return f"vecmin(time*({mask}) + {sentinel:.9g}*(1-({mask})))"


def last_time(mask):
    return f"vecmax(time*({mask}))"


def held(sig, a, b):
    """Mask-and-mean of `sig` over [a, b] -- the value it is holding there."""
    w = win(a, b)
    return f"mean(({sig})*({w}))/mean({w})"


def e(name, expr, unit=None, limits=None):
    m = {"name": name, "expr": expr}
    if unit:
        m["unit"] = unit
    if limits:
        m["limits"] = limits
    return m


def chain(fn, terms):
    """`fn(fn(fn(a, b), c), d)` -- ngspice's max/min take two arguments."""
    out = terms[0]
    for t in terms[1:]:
        out = f"{fn}({out}, {t})"
    return out


def phi1_high(window):
    return f"({window})*(v(xmod.phi1) ge 0.5*v(vdda))"


def phi1_width(k, name="phi1_width"):
    """Measured phi1 high time on clock k: the limit decision time is held to.

    DR-003 owes decision time against the half-period; the half-period is not
    what the comparator actually gets, because clkgen spends part of it on the
    non-overlap gaps. The limit is therefore the phi1 high time this bench
    delivers at the corner being measured, and it is measured, not assumed.
    No settling reservation is subtracted: no committed record in this repo
    bounds how long the reference node needs inside phi1 after dp/dn change
    (sim/integrator-settling grades the phi2 integrate phase), so the limit is
    stated as the bare delivered phi1 width and labelled as such.
    """
    te = tedge(k)
    m = phi1_high(win(te - W_LEAD, te + 150e-9))
    return e(name, f"{last_time(m)} - {first_time(m, te + 150e-9)}", "s")


def clock_measurements(k):
    """Per-decision measurements for the phi1 rise of clock k."""
    te = tedge(k)
    wdec = win(te - W_LEAD, te + W_DEC)
    sent = te + W_DEC
    out = [
        # when phi1 actually rose (clkgen delay is corner-dependent)
        e(f"tphi1_{k}", first_time(phi1_high(wdec), sent), "s"),
        # the differential the comparator decided on, held across phi1
        e(f"vod_{k}", held("v(o2d)", te + W_HOLD[0], te + W_HOLD[1]), "V"),
        # +1 if that differential calls for y = +1, else -1
        e(f"sgn_{k}", f"2*(vod_{k} ge 0) - 1"),
        # what dp/dn were holding from the previous decision
        e(f"ddpre_{k}", held("v(dd)", te + W_PREV[0], te + W_PREV[1]), "V"),
        # 1 when this decision actually changes dp/dn (only then is the
        # delay to dp/dn observable at all -- the SR latch holds otherwise)
        e(f"flip_{k}", f"(ddpre_{k}*sgn_{k} lt 0)"),
        # delay from the phi1 rise to dp/dn carrying the new decision. If the
        # comparator never resolves inside the window this saturates at the
        # window length, which is longer than any phi1 high time, so a
        # non-resolving corner FAILS the graded fraction below instead of
        # returning no measurement at all.
        e(f"tdec_{k}",
          f"{first_time(f'({wdec})*(v(dd)*sgn_{k} ge 0.5*v(vdda))', sent)} - tphi1_{k}", "s"),
        # intermediate: the comparator's own outputs (reset between clocks,
        # so this one is observable whether or not the decision changes)
        e(f"tcmp_{k}",
          f"{first_time(f'({wdec})*(v(cmpd)*sgn_{k} ge 0.5*v(vdda))', sent)} - tphi1_{k}", "s"),
        # intermediate: the SR latch outputs, before the dp/dn buffers
        e(f"tq_{k}",
          f"{first_time(f'({wdec})*(v(qd)*sgn_{k} ge 0.5*v(vdda))', sent)} - tphi1_{k}", "s"),
    ]
    return out


# Kickback is reported on both nodes DR-003 and the issue name: the
# comparator's own inputs o2p/o2n (where the disturbance lands) and the
# integrator-2 OTA summing nodes (how DR-003 words the owed check). Each is a
# peak deviation from the value that node holds through the same phi1, after
# the disturbance has settled -- which is the pre-edge held value, read late
# in phi1 because the non-overlap gap before the edge is ~0.6 ns wide and too
# narrow to sample reliably.
KICK_NODES = (("o2p", "v(xmod.o2p)"), ("o2n", "v(xmod.o2n)"),
              ("o2diff", "v(o2d)"), ("sump2", "v(xmod.xi2.sump)"),
              ("sumn2", "v(xmod.xi2.sumn)"), ("sumdiff2", "v(s2d)"))


def kickback_measurements(k):
    te = tedge(k)
    wk = win(te, te + W_KICK)
    out = []
    for tag, sig in KICK_NODES:
        ref = f"kbref_{tag}_{k}"
        out.append(e(ref, held(sig, te + W_HOLD[0], te + W_HOLD[1]), "V"))
        out.append(e(f"kb_{tag}_{k}", f"vecmax(abs(({sig}) - {ref})*({wk}))", "V"))
    return out


def loop_measurements():
    ks = list(range(LOOP_FIRST, LOOP_LAST + 1))
    ms = []
    for k in ks:
        ms += clock_measurements(k)
    for k in LOOP_KICK_CLKS:
        ms += kickback_measurements(k)
    ms.append(phi1_width(LOOP_PHI1_REF))
    # A corner in which dp/dn never change carries no decision-time evidence
    # at all, so it is a graded failure rather than a quiet pass.
    ms.append(e("n_flip", " + ".join(f"flip_{k}" for k in ks), None, {"min": 2}))
    ms.append(e("tdec_worst",
                chain("max", [f"(tdec_{k}*flip_{k})" for k in ks] + ["0"]), "s"))
    ms.append(e("tcmp_worst", chain("max", [f"tcmp_{k}" for k in ks]), "s"))
    ms.append(e("tq_worst",
                chain("max", [f"(tq_{k}*flip_{k})" for k in ks] + ["0"]), "s"))
    # THE graded row: the worst decision time, as a fraction of the phi1 high
    # time this corner actually delivers. <= 1 is "the decision fits".
    ms.append(e("tdec_frac", "tdec_worst/phi1_width", None, {"max": 1.0}))
    return ms


def trip_measurements():
    up_a, up_b = tedge(TRIP_UP_FIRST) - W_LEAD, tedge(TRIP_UP_LAST + 1) - W_LEAD
    dn_a, dn_b = up_b, tedge(TRIP_DN_LAST + 1) - W_LEAD
    uw, dw = win(up_a, up_b), win(dn_a, dn_b)
    # Sentinels are real clock edges inside each window, so a corner whose
    # decision never flips still evaluates every later expression on a valid
    # clock instead of producing NaN; `flip_up`/`flip_dn` are what fail it.
    up_sent, dn_sent = tedge(TRIP_UP_LAST), tedge(TRIP_DN_LAST)
    m_up = f"({uw})*(v(dd) ge 0.5*v(vdda))"
    m_dn = f"({dw})*(v(dd) le -0.5*v(vdda))"
    ms = [
        e("flip_up", f"vecmax({m_up})", None, {"min": 1}),
        e("flip_dn", f"vecmax({m_dn})", None, {"min": 1}),
        e("tflip_up", first_time(m_up, up_sent), "s"),
        e("tflip_dn", first_time(m_dn, dn_sent), "s"),
        # clock index of the flip, and that clock's own clk edge
        # Bench-validity gate, not a spec limit: the trip has to land strictly
        # inside the staircase. A flip on the first graded clock would mean the
        # sweep started above (or below) the trip point and never bracketed it.
        e("k_up", f"floor((tflip_up - {T0:.9g})/{TCLK:.9g})", None,
          {"min": TRIP_UP_FIRST + 1, "max": TRIP_UP_LAST}),
        e("k_dn", f"floor((tflip_dn - {T0:.9g})/{TCLK:.9g})", None,
          {"min": TRIP_DN_FIRST + 1, "max": TRIP_DN_LAST}),
        e("t_up", f"{T0:.9g} + k_up*{TCLK:.9g}", "s"),
        e("t_dn", f"{T0:.9g} + k_dn*{TCLK:.9g}", "s"),
    ]
    for tag in ("up", "dn"):
        # the differential that tripped it, and the one the clock before --
        # their difference is the staircase step actually delivered, i.e. the
        # resolution of the trip point and of everything derived from it
        hold = (f"(time ge (t_{tag}+{W_HOLD[0]:.9g}))*(time le (t_{tag}+{W_HOLD[1]:.9g}))")
        prev = (f"(time ge (t_{tag}-{TCLK - W_HOLD[0]:.9g}))"
                f"*(time le (t_{tag}-{TCLK - W_HOLD[1]:.9g}))")
        ms.append(e(f"v_trip_{tag}", f"mean(v(o2d)*({hold}))/mean({hold})", "V"))
        ms.append(e(f"v_prev_{tag}", f"mean(v(o2d)*({prev}))/mean({prev})", "V"))
        ms.append(e(f"step_{tag}", f"v_trip_{tag} - v_prev_{tag}", "V"))
        # decision time at the trip itself: the smallest overdrive this bench
        # presents. Reported, never graded -- every latch is slow at its own
        # trip point, and inventing a limit there would be inventing a spec.
        k = TRIP_UP_LAST if tag == "up" else TRIP_DN_LAST
        wd = (f"(time ge (t_{tag}-{W_LEAD:.9g}))*(time le (t_{tag}+{W_DEC:.9g}))")
        sent = tedge(k) + W_DEC
        ms.append(e(f"tphi1_{tag}", first_time(phi1_high(wd), sent), "s"))
        ms.append(e(f"tdec_{tag}", f"tflip_{tag} - tphi1_{tag}", "s"))
    # span checks: that the staircase really swept, and in which direction
    ms.append(e("span_up",
                f"{held('v(o2d)', tedge(TRIP_UP_LAST) + W_HOLD[0], tedge(TRIP_UP_LAST) + W_HOLD[1])}"
                f" - {held('v(o2d)', tedge(TRIP_UP_FIRST) + W_HOLD[0], tedge(TRIP_UP_FIRST) + W_HOLD[1])}",
                "V", {"min": RAMP_SPAN_V}))
    ms.append(e("span_dn",
                f"{held('v(o2d)', tedge(TRIP_DN_LAST) + W_HOLD[0], tedge(TRIP_DN_LAST) + W_HOLD[1])}"
                f" - {held('v(o2d)', tedge(TRIP_DN_FIRST) + W_HOLD[0], tedge(TRIP_DN_FIRST) + W_HOLD[1])}",
                "V", {"max": -RAMP_SPAN_V}))
    # the two quantities model B wants, in volts at the integrator-2 output.
    # Model B trips to +1 at x2 = +h/2 - off and back to -1 at x2 = -h/2 - off,
    # so off = -(up + dn)/2 and h = up - dn. run_decision.py converts to FS.
    ms.append(e("vos_V", "-0.5*(v_trip_up + v_trip_dn)", "V"))
    ms.append(e("hyst_V", "v_trip_up - v_trip_dn", "V"))
    ms.append(phi1_width(TRIP_UP_FIRST))
    return ms


def trip_input_pwl():
    """Differential input that walks integrator 2's output across its trip.

    With VREFP = VREFN = VCM the DAC transfers no charge whatever dp/dn do, so
    the loop is open and the two integrators are a plain cascade:

        o1d[n] = o1d[n-1] + G*u[n]          (u sampled during phi1 of clock n)
        o2d[n] = o2d[n-1] + G*o1d[n-1]      (delaying integrators)

    and the comparator decides on o2d[n-1] at the phi1 rise of clock n. Holding
    o1d at a constant +/-O1D_FINE therefore walks o2d by +/-STEP_V per clock.
    Only o1d's *targets* are designed here; the step the bench actually
    delivers is measured (`step_up`, `step_dn`), so a G that is not exactly
    0.5 changes the resolution, never the trip point.

    Returns (pwl_card, schedule) where schedule is the list of
    (clock, u_volts, o1d_after, o2d_after) rows the README table is built from.
    """
    targets = {}                      # clock -> o1d held from that clock on
    targets[0] = O1D_COARSE
    targets[TRIP_UP_FIRST - 2] = +O1D_FINE
    targets[TRIP_DN_FIRST - 2] = -O1D_FINE
    sched, pts, o1d, o2d, u_prev = [], [], 0.0, 0.0, None
    for n in range(TRIP_LAST_CLK + 1):
        o2d = o2d + G * o1d           # o2d[n] uses o1d[n-1]
        want = targets.get(n, o1d)
        u = (want - o1d) / G
        o1d = want
        if u_prev is None:
            pts.append((0.0, u))
        elif u != u_prev:
            t = tedge(n) - 60e-9      # inside phi2 of clock n-1: the input
            pts.append((t - 1e-9, u_prev))   # switch of clock n is open there
            pts.append((t + 1e-9, u))
        u_prev = u
        sched.append((n, u, o1d, o2d))
    pts.append((T_END["trip"], u_prev))
    card = "pwl(" + " ".join(f"{t:.9g} {v:.9g}" for t, v in pts) + ")"
    return card, sched


VARIANTS = {
    "loop": {
        "vrefp": "1.5", "vrefn": "0.3",
        "ind": f"dc {LOOP_VIN_DIFF:.9g}",
        "note": ("the modulator closed and running on the spec reference pair, "
                 f"with a steady {LOOP_VIN_DIFF:.9g} V differential input "
                 f"({LOOP_VIN_DIFF / FS_VOLTS:.3g} FS). The decision time and the "
                 "kickback are measured here, at the overdrives the loop itself "
                 "presents to the comparator."),
        "measurements": loop_measurements,
    },
    "trip": {
        "vrefp": "0.9", "vrefn": "0.9",
        "ind": None,     # filled in below
        "note": ("the reference pair is NULLED (VREFP = VREFN = VCM), so the "
                 "1-bit DAC transfers no charge whatever dp/dn do and the loop "
                 "is open; the input then walks integrator 2's output across "
                 f"the comparator's trip point in {STEP_V * 1e6:.0f} uV steps, up "
                 "and then down, which is what makes the systematic offset and "
                 "the hysteresis width observable. Every switch in the "
                 "reference branch still operates, as in sim/integrator-ci."),
        "measurements": trip_measurements,
    },
}
VARIANTS["trip"]["ind"] = trip_input_pwl()[0]


def build():
    tmpl = (HERE / "comparator_decision.cir.tmpl").read_text()
    for v, d in VARIANTS.items():
        deck = f"comparator_decision_{v}.cir"
        (HERE / deck).write_text(
            tmpl.replace("@VARIANT@", v).replace("@NOTE@", d["note"])
                .replace("@VREFP@", d["vrefp"]).replace("@VREFN@", d["vrefn"])
                .replace("@IND@", d["ind"]))
        req = request(deck, d["measurements"](), T_END[v],
                      timeout_s=TIMEOUT_S, poll_timeout_s=POLL_TIMEOUT_S)
        # settling_common.request() builds the shared DR-002 grid and batch
        # block; this bench needs a different analysis card and full printed
        # precision (the trip points are tens of microvolts apart).
        req["analysis"] = {"kind": "tran", "args": f"0.05n {T_END[v]:.9g} 0 5n"}
        req["options"]["ngspice_init"] = ["set numdgt=12", "set measureprec=12"]
        req["batch"]["job_ceiling_check"] = JOB_CEILING_CHECK
        (HERE / f"request_{v}.json").write_text(json.dumps(req, indent=2) + "\n")
        print(f"{v}: {deck}, {len(req['measurements'])} measurements, "
              f"t_end {T_END[v] * 1e6:.3f} us")


if __name__ == "__main__":
    build()

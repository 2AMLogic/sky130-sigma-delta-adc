#!/usr/bin/env python3
"""Regenerate the two deck/request pairs (int1, int2). See README.md."""
import json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from settling_common import request

T_STEP = 35.0e-9      # phi2 mid-edge (200 ps edge from 34.9 ns)
T_PHASE = 97.66e-9    # 1 / (2 * 5.12 MHz), spec row 5
T_SAMPLE = T_STEP + T_PHASE
T_END = 335e-9
IDEAL_DV = 0.9        # 0.5 * (0.6 V input + 1.2 V DAC): ideal charge transfer
ERR_MAX = 1e-4        # 0.01 %, the DR-005 settling level
RIPPLE_MAX = 1e-3     # reference-validity gate (not a spec row), see README.md
IDEAL_TOL = 0.05      # reference-validity gate (not a spec row), see README.md
T_SLEW0 = T_STEP + 0.3e-9

# Stage phasing: the integrators are delaying, so int1 integrates in phi2
# while int2 only samples in phi1 (int2's Sin is off in phi2): only parasitics
# load int1 (case B of design/integrator/SIZING.md). int2 drives the
# comparator and the feedback network; 1 pF per side extra is the case-A
# bound, pending the comparator input capacitance.
VARIANTS = {
    "int1": {"load": "0.1p", "note": "0.1 pF output parasitics only (case B: delaying integrators, the next Sin is off in phi2)"},
    "int2": {"load": "1.1p", "note": "0.1 pF parasitics + 1 pF (case A bound: next-stage Cs / comparator input)"},
}


def e(name, expr, unit=None, limits=None):
    m = {"name": name, "expr": expr}
    if unit:
        m["unit"] = unit
    if limits:
        m["limits"] = limits
    return m


# `lt`/`gt`: bare < > are shell redirections in ngspice's control language.
slewmask = f"(abs(deriv(v(vod))) ge 0.8*slope_pk)*(time gt {T_SLEW0:.6g})"
MEASUREMENTS = [
    e("vod_pre", "v(vod)[0]", "V"),
    e("vod_end", "v(vod)[length(v(vod))-1]", "V"),
    e("step_dv", "vod_end - vod_pre", "V"),
    e("k_phase", f"mean(time lt {T_SAMPLE:.6g})*length(time)"),
    e("vod_phase", f"v(vod)[k_phase-1] + ({T_SAMPLE:.6g}-time[k_phase-1])/(time[k_phase]-time[k_phase-1])"
                   "*(v(vod)[k_phase]-v(vod)[k_phase-1])", "V"),
    e("err_phase", "abs(vod_phase - vod_end)/abs(step_dv)", None, {"max": ERR_MAX}),
    e("t_1e4", f"vecmax((abs(v(vod)-vod_end) gt 1e-4*abs(step_dv))*time) - {T_STEP:.6g}", "s"),
    e("t_1e3", f"vecmax((abs(v(vod)-vod_end) gt 1e-3*abs(step_dv))*time) - {T_STEP:.6g}", "s"),
    e("t_1e2", f"vecmax((abs(v(vod)-vod_end) gt 1e-2*abs(step_dv))*time) - {T_STEP:.6g}", "s"),
    e("slope_pk", f"vecmax(abs(deriv(v(vod)))*(time gt {T_SLEW0:.6g}))", "V/s"),
    e("t_slew", f"vecmax({slewmask}*time) - vecmin({slewmask}*time + 1*(1-{slewmask}))", "s"),
    e("slew_frac", "t_slew/t_1e4"),
    e("end_ripple_rel", f"(vecmax(v(vod)*(time gt {T_END - 20e-9:.6g}) - 10*(time le {T_END - 20e-9:.6g}))"
                        f" - vecmin(v(vod)*(time gt {T_END - 20e-9:.6g}) + 10*(time le {T_END - 20e-9:.6g})))"
                        "/abs(step_dv)", None, {"max": RIPPLE_MAX}),
    e("step_err_vs_ideal", f"abs(abs(step_dv) - {IDEAL_DV})/{IDEAL_DV}", None, {"max": IDEAL_TOL}),
]


if __name__ == "__main__":
    tmpl = (HERE / "integrator_settling.cir.tmpl").read_text()
    for v, d in VARIANTS.items():
        deck = f"integrator_settling_{v}.cir"
        (HERE / deck).write_text(tmpl.replace("@VARIANT@", v).replace("@LOAD@", d["load"])
                                 .replace("@LOADNOTE@", d["note"]))
        (HERE / f"request_{v}.json").write_text(json.dumps(request(deck, MEASUREMENTS, T_END, timeout_s=60, poll_timeout_s=7200), indent=2) + "\n")

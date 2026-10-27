#!/usr/bin/env python3
"""Regenerate request.json (the 45-corner klt sim request). See README.md."""
import json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from settling_common import request

T_STEP = 3.0e-9       # step mid-edge (Vsp/Vsn PULSE: 2.99 ns delay, 20 ps edge)
T_PHASE = 97.66e-9    # 1 / (2 * 5.12 MHz), spec row 5
T_SAMPLE = T_STEP + T_PHASE
T_END = 300e-9
IDEAL_DV = 0.9        # |vod| after settling, ideal charge transfer: (Cs/Ci) * 1.8 V
ERR_MAX = 1e-4        # 0.01 %, the level design/ota/SIZING.md targets
RIPPLE_MAX = 1e-3     # reference-validity gate (not a spec row), see README.md
IDEAL_TOL = 0.05      # reference-validity gate (not a spec row), see README.md


def e(name, expr, unit=None, limits=None):
    m = {"name": name, "expr": expr}
    if unit:
        m["unit"] = unit
    if limits:
        m["limits"] = limits
    return m


# `lt`/`gt`: bare < > are shell redirections in ngspice's control language.
slewmask = "(abs(deriv(v(vod))) ge 0.8*slope_pk)*(time gt 3.3e-9)"
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
    e("slope_pk", "vecmax(abs(deriv(v(vod)))*(time gt 3.3e-9))", "V/s"),
    e("t_slew", f"vecmax({slewmask}*time) - vecmin({slewmask}*time + 1*(1-{slewmask}))", "s"),
    e("slew_frac", "t_slew/t_1e4"),
    e("end_ripple_rel", f"(vecmax(v(vod)*(time gt {T_END - 20e-9:.6g}) - 10*(time le {T_END - 20e-9:.6g}))"
                        f" - vecmin(v(vod)*(time gt {T_END - 20e-9:.6g}) + 10*(time le {T_END - 20e-9:.6g})))"
                        "/abs(step_dv)", None, {"max": RIPPLE_MAX}),
    e("step_err_vs_ideal", f"abs(abs(step_dv) - {IDEAL_DV})/{IDEAL_DV}", None, {"max": IDEAL_TOL}),
]

REQUEST = request("ota_fd_step.cir", MEASUREMENTS, T_END, timeout_s=900, poll_timeout_s=5400)

if __name__ == "__main__":
    (HERE / "request.json").write_text(json.dumps(REQUEST, indent=2) + "\n")

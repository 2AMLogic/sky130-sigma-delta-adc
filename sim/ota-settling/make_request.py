#!/usr/bin/env python3
"""Regenerate request.json (the 45-corner klt sim request). See README.md."""
import json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from settling_common import request, settling_measurements

T_STEP = 3.0e-9       # step mid-edge (Vsp/Vsn PULSE: 2.99 ns delay, 20 ps edge)
T_PHASE = 97.66e-9    # 1 / (2 * 5.12 MHz), spec row 5
T_SAMPLE = T_STEP + T_PHASE
T_END = 300e-9
IDEAL_DV = 0.9        # |vod| after settling, ideal charge transfer: (Cs/Ci) * 1.8 V
ERR_MAX = 1e-4        # 0.01 %, the level design/ota/SIZING.md targets
RIPPLE_MAX = 1e-3     # reference-validity gate (not a spec row), see README.md
IDEAL_TOL = 0.05      # reference-validity gate (not a spec row), see README.md
T_SLEW0 = T_STEP + 0.3e-9

MEASUREMENTS = settling_measurements(
    t_step=T_STEP, t_sample=T_SAMPLE, t_end=T_END, t_slew0=T_SLEW0,
    ideal_dv=IDEAL_DV, err_max=ERR_MAX, ripple_max=RIPPLE_MAX, ideal_tol=IDEAL_TOL)

REQUEST = request("ota_fd_step.cir", MEASUREMENTS, T_END, timeout_s=900, poll_timeout_s=5400)

if __name__ == "__main__":
    (HERE / "request.json").write_text(json.dumps(REQUEST, indent=2) + "\n")

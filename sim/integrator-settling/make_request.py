#!/usr/bin/env python3
"""Regenerate the two deck/request pairs (int1, int2). See README.md."""
import json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from settling_common import request, settling_measurements

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


MEASUREMENTS = settling_measurements(
    t_step=T_STEP, t_sample=T_SAMPLE, t_end=T_END, t_slew0=T_SLEW0,
    ideal_dv=IDEAL_DV, err_max=ERR_MAX, ripple_max=RIPPLE_MAX, ideal_tol=IDEAL_TOL)


if __name__ == "__main__":
    tmpl = (HERE / "integrator_settling.cir.tmpl").read_text()
    for v, d in VARIANTS.items():
        deck = f"integrator_settling_{v}.cir"
        (HERE / deck).write_text(tmpl.replace("@VARIANT@", v).replace("@LOAD@", d["load"])
                                 .replace("@LOADNOTE@", d["note"]))
        (HERE / f"request_{v}.json").write_text(json.dumps(request(deck, MEASUREMENTS, T_END, timeout_s=60, poll_timeout_s=7200), indent=2) + "\n")

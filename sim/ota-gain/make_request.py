#!/usr/bin/env python3
"""Regenerate request.json (the 45-corner klt sim request). See README.md."""
import json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from settling_common import request

# Swept band. The DC gain is the f -> 0 asymptote; it is read at F_LO, the
# bottom of the sweep. Both bench-only networks are negligible across this
# band (deck comment): the 1e12 H DC-feedback inductor shunts the ~1 Mohm
# output resistance by 7 orders at 1 Hz, and the lowest OTA pole is tens of
# kHz, so F_HI is still two decades below it. FLAT_MAX turns that reasoning
# into a per-corner gate instead of an assumption.
F_LO = 1.0
F_HI = 1e3
AC_ARGS = f"dec 10 {F_LO:g} {F_HI:g}"

FLAT_MAX = 1e-2    # reference-validity gate (not a spec row), see README.md
OPEN_MIN = 10.0    # reference-validity gate: a closed loop would read ~1 V/V
VID_TOL = 1e-9     # reference-validity gate: the drive really is 1 V differential
ACM_MAX = 1e-3     # reference-validity gate: the drive stays differential


def e(name, expr, unit=None, limits=None):
    m = {"name": name, "expr": expr}
    if unit:
        m["unit"] = unit
    if limits:
        m["limits"] = limits
    return m


# `mag()` makes each complex ac sample real so klt's scalar `expr` form can
# reduce it; `[0]` is the first swept point, F_LO. `lt`/`gt`: bare < > are
# shell redirections in ngspice's control language.
MEASUREMENTS = [
    # The differential drive, as actually solved. 1.0 by construction (two
    # ideal VCVSs off a 1 V AC source); a different value means the deck's
    # drive network changed and every gain below is scaled by it.
    e("vid_mag", "vecmin(mag(v(vid)))", "V", {"min": 1.0 - VID_TOL, "max": 1.0 + VID_TOL}),
    # The gain at the bottom of the sweep: the reported DC gain.
    e("a0_lo", "mag(v(vod))[0]", "V/V", {"min": OPEN_MIN}),
    e("a0_min", "vecmin(mag(v(vod)))", "V/V"),
    e("a0_max", "vecmax(mag(v(vod)))", "V/V"),
    # Band flatness. The reading is a DC gain only if the swept band is flat:
    # a rising edge would mean the DC feedback inductor is still shunting the
    # output, a falling edge that the dominant pole is inside the band.
    e("a0_flat_rel", "(vecmax(mag(v(vod))) - vecmin(mag(v(vod))))/vecmin(mag(v(vod)))",
      None, {"max": FLAT_MAX}),
    # Differential-to-common-mode conversion. A purely differential drive
    # should move the output common mode not at all; if it does, the CMFB loop
    # is not holding or the feedback pairing is wrong, and `a0_lo` is not a
    # differential gain. (An `ac` plot holds small-signal phasors, not the
    # bias, so the operating point itself is not readable here -- it is forced
    # by construction, see the deck comment, and recorded at tt/27 C/1.80 V in
    # sim/ota-op-smoke/record.json.)
    e("acm_max", "vecmax(mag(0.5*(v(outp) + v(outn))))", "V/V"),
    e("acm_rel", "acm_max/a0_lo", None, {"max": ACM_MAX}),
]

REQUEST = request("ota_gain.cir", MEASUREMENTS,
                  analysis={"kind": "ac", "args": AC_ARGS},
                  timeout_s=300, poll_timeout_s=5400,
                  options={"ngspice_init": ["set numdgt=12"]})

if __name__ == "__main__":
    (HERE / "request.json").write_text(json.dumps(REQUEST, indent=2) + "\n")

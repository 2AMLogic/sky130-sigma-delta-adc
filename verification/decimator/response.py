#!/usr/bin/env python3
"""Whole-chain frequency response of the decimator against spec rows 8-9.

Evaluated analytically at the input rate (5.12 MHz) as CIC x FIR, from the
quantized integer coefficients in rtl/decimator_coef.v (the file the RTL and
synthesis use), not from design floats.

  row 8  passband 0 - BW:   peak-to-peak gain variation <= 0.1 dB
  row 9  stopband:          >= 90 dB in the alias bands [k*fout - BW, k*fout + BW],
                            k = 1 .. fs/(2*fout), the last clipped to fs/2, and
                            >= 75 dB elsewhere from fout - BW to fs/2 (the gaps
                            between alias bands); see spec/decisions/DR-006

Gain is relative to DC (the chain has exactly unity DC gain: the coefficients
sum to 2**COEF_FRAC and the CIC gain is divided out by the offset/scale choice).
Exit 0 when all rows pass, 1 otherwise, 2 on a malformed coefficient file.

Frequency grid: 50 Hz spacing, endpoints included - 401 points in the passband,
and 801 points per alias band (32 bands, 25 232 points in total; the last band
is clipped at fs/2). The gap check uses the same grid over the points of
fout - BW .. fs/2 that lie outside every alias band.
"""
import argparse
import json
import math
import re
import sys

import model as m

STEP = 50.0
RIPPLE_LIMIT_DB = 0.1
STOP_LIMIT_DB = 90.0
GAP_LIMIT_DB = 75.0


def chain_mag(f, coefs=None):
    return m.chain_mag(f, coefs if coefs is not None else m.load_coefs())


def _grid(lo, hi):
    n = int(round((hi - lo) / STEP))
    return [lo + STEP * i for i in range(n + 1)]


def evaluate(coefs):
    db = lambda f: 20 * math.log10(max(m.chain_mag(f, coefs), 1e-300))
    pb = [db(f) for f in _grid(0.0, m.BW)]
    bands, worst_f, worst_att = [], None, 1e9
    for k in range(1, int(m.FS / 2 / m.FOUT) + 1):
        lo, hi = k * m.FOUT - m.BW, min(k * m.FOUT + m.BW, m.FS / 2)
        att = [(-db(f), f) for f in _grid(lo, hi)]
        a, f = min(att)
        bands.append({"k": k, "lo_hz": lo, "hi_hz": hi, "min_attenuation_db": round(a, 2), "at_hz": f})
        if a < worst_att:
            worst_att, worst_f = a, f
    in_band = lambda f: any(b["lo_hz"] <= f <= b["hi_hz"] for b in bands)
    gap_pts = [f for f in _grid(m.FOUT - m.BW, m.FS / 2) if not in_band(f)]
    gap = min((-db(f), f) for f in gap_pts)
    dc = m.chain_mag(0.0, coefs)
    return {
        "grid": {"step_hz": STEP, "passband_points": len(pb),
                 "alias_band_points": sum(len(_grid(b["lo_hz"], b["hi_hz"])) for b in bands)},
        "dc_gain": dc,
        "passband": {"band_hz": [0, m.BW], "peak_to_peak_db": round(max(pb) - min(pb), 4),
                     "max_db": round(max(pb), 4), "min_db": round(min(pb), 4),
                     "limit_db": RIPPLE_LIMIT_DB},
        "stopband_alias_bands": {"worst_attenuation_db": round(worst_att, 2), "worst_at_hz": worst_f,
                                 "limit_db": STOP_LIMIT_DB, "bands": bands},
        "stopband_gaps": {"range_hz": [m.FOUT - m.BW, m.FS / 2], "points": len(gap_pts),
                          "worst_attenuation_db": round(gap[0], 2), "worst_at_hz": gap[1],
                          "limit_db": GAP_LIMIT_DB},
    }


def rtl_param(name):
    return int(re.search(rf"parameter\s+{name}\s*=\s*(\d+)", m.DECIMATOR_V.read_text()).group(1))


def acc_width_check(coefs):
    """(bits needed, bits in the RTL); also refuses if the RTL defaults drifted from model.py."""
    for name in ("CIC_LOG2R", "FIR_LOG2D", "N_TAPS", "COEF_W", "COEF_FRAC"):
        if rtl_param(name) != getattr(m, name):
            raise SystemExit(f"ERROR: rtl/decimator.v {name}={rtl_param(name)} but model.py {name}={getattr(m, name)}")
    return m.acc_bits_needed(coefs), rtl_param("ACC_W")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--perturb", metavar="TAP:DELTA", action="append", default=[],
                    help="negative control: add DELTA LSB to coefficient TAP (and its mirror) before evaluating")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    a = ap.parse_args()
    try:
        coefs = m.load_coefs()
    except (ValueError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    for p in a.perturb:
        k, d = (int(x) for x in p.split(":"))
        coefs[k] += d
        coefs[m.N_TAPS - 1 - k] += d if k != m.N_TAPS - 1 - k else 0
    r = evaluate(coefs)
    need, have = acc_width_check(coefs)
    ok_rip = r["passband"]["peak_to_peak_db"] <= RIPPLE_LIMIT_DB
    ok_stop = r["stopband_alias_bands"]["worst_attenuation_db"] >= STOP_LIMIT_DB
    ok_gap = r["stopband_gaps"]["worst_attenuation_db"] >= GAP_LIMIT_DB
    ok_acc = have >= need
    ok_sum = sum(coefs) == 1 << m.COEF_FRAC
    if a.json:
        print(json.dumps(r, indent=1))
    pb, sb, gp = r["passband"], r["stopband_alias_bands"], r["stopband_gaps"]
    print(f"row 8 passband 0-{m.BW/1e3:.0f} kHz: peak-to-peak {pb['peak_to_peak_db']:.4f} dB "
          f"(limit {RIPPLE_LIMIT_DB}) {'PASS' if ok_rip else 'FAIL'}")
    print(f"row 9 alias bands k*{m.FOUT/1e3:.0f}k +/-{m.BW/1e3:.0f}k to fs/2: worst attenuation "
          f"{sb['worst_attenuation_db']:.2f} dB at {sb['worst_at_hz']/1e3:.2f} kHz (limit {STOP_LIMIT_DB}) "
          f"{'PASS' if ok_stop else 'FAIL'}")
    print(f"row 9 elsewhere, {gp['range_hz'][0]/1e3:.0f} kHz..fs/2 outside the alias bands: worst attenuation "
          f"{gp['worst_attenuation_db']:.2f} dB at {gp['worst_at_hz']/1e3:.2f} kHz (limit {GAP_LIMIT_DB}) "
          f"{'PASS' if ok_gap else 'FAIL'}")
    print(f"grid: {r['grid']['step_hz']:.0f} Hz spacing, {r['grid']['passband_points']} passband points, "
          f"{r['grid']['alias_band_points']} alias-band points, {gp['points']} gap points")
    print(f"coefficient sum {sum(coefs)} (need {1 << m.COEF_FRAC}) {'ok' if ok_sum else 'FAIL'}; "
          f"accumulator needs {need} bits, RTL ACC_W = {have} {'ok' if ok_acc else 'FAIL'}")
    return 0 if (ok_rip and ok_stop and ok_gap and ok_acc and ok_sum) else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""End-to-end check behind the "B" in spec row 9's evidence column.

Behavioural model B (sim/bmodel) measures SNDR through a float64 sinc^3 reference
decimator, not the RTL chain. This check feeds the *same* ideal-parameter
modulator bitstream through the bit-exact fixed-point model of rtl/decimator.v
(model.Decimator, cocotb-verified against the RTL) and compares the in-band SNDR
and noise of the two decimators, using sim/bmodel/sndr.py's window, tone
placement and bin bandwidth.

    python3 -I verification/decimator/bmodel_xcheck.py [--record-len N] [--record]
                                                       [--coef-perturb TAP]

Evidence kind: simulated, behavioural model B + bit-exact RTL model; not measured.
Default record: N = 2^16 output samples (4 194 304 modulator clocks), 4-term
Blackman-Harris window, bin bandwidth fout/N = 1.2207 Hz, band 0..20 kHz.

Tolerance: the RTL chain (CIC order 4 plus 41-tap FIR, 16-bit output) and the
sinc^3 reference differ by 16-bit output rounding (about 95 dB SNR in band at
-6 dBFS) and by their different passband/alias weighting. Measured at N = 2^13
the RTL SNDR sits 1.5-2.0 dB below the reference; the check allows the RTL chain
to be at most TOL_DB = 3.0 dB below the reference (in-band noise at most 3 dB
higher) and no more than 1.0 dB above it. A perturbed coefficient (--coef-perturb)
is the negative control: it must exceed the tolerance.
Exit 0 on pass, 1 on fail.
"""
import argparse, datetime, hashlib, importlib.util, json, pathlib, sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bm = _load("bmodel_model", REPO / "sim/bmodel/model.py")
sn = _load("bmodel_sndr", REPO / "sim/bmodel/sndr.py")
dm = _load("decimator_model", HERE / "model.py")

# The code whose contents determine this check's numbers. git state cannot name
# it: a record is written before the commit that contains it (issue #110). The
# B-model files are hashed here rather than via sim/bmodel/run.code_state()
# because this script loads the models by path and never imports run.py.
CODE_FILES = (REPO / "sim/bmodel/model.py", REPO / "sim/bmodel/sndr.py",
              HERE / "model.py", pathlib.Path(__file__).resolve())

AMPLITUDES_DBFS = (-6, -12)   # spec row 11 ceiling, and a mid-scale point
WARMUP_OUT = 8
TOL_BELOW_DB = 3.0            # RTL SNDR may be at most this far below the sinc^3 reference
TOL_ABOVE_DB = 1.0            # ... and at most this far above it
# Issue #107 fixed a 3.02 dB ENBW error in sndr.sndr_db, so the absolute SNDR
# figures move (the rtl-minus-sinc3 delta this check grades on does not: it is a
# difference of two sndr_db values). Results are append-only, so this writes a
# new file and leaves the superseded xcheck_record.json alone.
OUT_NAME = "xcheck_record-i107.json"


def one_point(params, amp_dbfs, n_out, cycles, coefs):
    rng = np.random.default_rng(params["seed"])
    u = bm.tone_input(10.0 ** (amp_dbfs / 20.0), cycles, n_out, sn.DECIM, WARMUP_OUT, params, rng=rng)
    y = bm.modulate(u, params, rng=rng)
    ref = sn.sinc3_decimate(y)[WARMUP_OUT:WARMUP_OUT + n_out]
    words = np.array(dm.Decimator(coefs).run((y > 0).astype(int).tolist()), dtype=float)
    rtl = words[WARMUP_OUT:WARMUP_OUT + n_out]
    s_ref, det = sn.sndr_db(ref, cycles)
    s_rtl, _ = sn.sndr_db(rtl, cycles)
    return {"amplitude_dbfs": amp_dbfs, "sndr_sinc3_db": s_ref, "sndr_rtl_model_db": s_rtl,
            "rtl_minus_sinc3_db": s_rtl - s_ref, "in_band_noise_rtl_minus_sinc3_db": s_ref - s_rtl}, det


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record-len", type=int, default=2**16)
    ap.add_argument("--record", action="store_true", help=f"write {OUT_NAME} (overwrites)")
    ap.add_argument("--coef-perturb", type=int, metavar="TAP",
                    help="negative control: add 2**14 to this coefficient before the RTL-model run")
    a = ap.parse_args(argv)
    if a.record_len & (a.record_len - 1):
        ap.error("--record-len must be a power of two")
    params = bm.load_params(REPO / "sim/bmodel/ideal.json")
    coefs = dm.load_coefs()
    if a.coef_perturb is not None:
        coefs[a.coef_perturb] += 1 << 14
    cycles = sn.odd_cycles(a.record_len)
    rows, det = [], None
    for amp in AMPLITUDES_DBFS:
        r, det = one_point(params, amp, a.record_len, cycles, coefs)
        r["pass"] = -TOL_BELOW_DB <= r["rtl_minus_sinc3_db"] <= TOL_ABOVE_DB
        rows.append(r)
        print(f"{amp:4d} dBFS: sinc3 {r['sndr_sinc3_db']:.2f} dB, RTL model {r['sndr_rtl_model_db']:.2f} dB, "
              f"delta {r['rtl_minus_sinc3_db']:+.2f} dB -> {'ok' if r['pass'] else 'FAIL'}")
    ok = all(r["pass"] for r in rows)
    print(f"N={a.record_len} ({a.record_len * sn.DECIM} clocks), bin {det['bin_bw_hz']:.4f} Hz, "
          f"window {det['window']}, band 0-{sn.BW_HZ:.0f} Hz: {'PASS' if ok else 'FAIL'}")
    if a.record and a.coef_perturb is None:
        rec = {
            "source": "B + bit-exact RTL model",
            "result_kind": "simulated (behavioural model B bitstream through bit-exact decimator model); not measured",
            "check": "in-band SNDR/noise of rtl/decimator chain vs float64 sinc^3 reference on the same bitstream",
            "record_len": a.record_len, "modulator_clocks": a.record_len * sn.DECIM,
            "window": det["window"], "bin_bw_hz": det["bin_bw_hz"], "band_hz": [0, sn.BW_HZ],
            "excluded_bins": det["excluded_bins"], "tone_cycles": cycles,
            "tone_hz": cycles * sn.FOUT_HZ / a.record_len,
            "params": "sim/bmodel/ideal.json (ideal parameters, no corner)", "params_sha256":
                hashlib.sha256(json.dumps(params, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "tolerance_db": {"rtl_below_sinc3": TOL_BELOW_DB, "rtl_above_sinc3": TOL_ABOVE_DB},
            "points": rows, "pass": ok,
            "rtl_sha256": {f: hashlib.sha256((REPO / "rtl" / f).read_bytes()).hexdigest()
                           for f in ("decimator.v", "decimator_coef.v")},
            "code_sha256": {str(f.relative_to(REPO)): hashlib.sha256(f.read_bytes()).hexdigest()
                            for f in CODE_FILES},
            "numpy": np.__version__,
            "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        }
        (HERE / OUT_NAME).write_text(json.dumps(rec, indent=2) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

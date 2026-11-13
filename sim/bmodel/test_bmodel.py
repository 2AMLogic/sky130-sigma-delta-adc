"""Tests for behavioural model B. Run:
python3 -I -m unittest discover -s sim/bmodel -p 'test_*.py'

Tests use a short record (N = 2^13 output samples = 524 288 clocks) for speed;
run.py's ideal run uses 2^16. SNDR is a power ratio over [0, BW], so the short
record changes the bin width, not the expected value.
"""
import json
import pathlib
import tempfile
import unittest

import numpy as np

import model
import run
import sndr

HERE = pathlib.Path(__file__).resolve().parent
N = 2**13
OSR = 128


def ideal():
    return model.load_params(HERE / "ideal.json")


def sndr_at(params, amp_dbfs):
    return run.run_point(params, amp_dbfs, N, sndr.odd_cycles(N))[0]


class KnownSnrEstimator(unittest.TestCase):
    """`sndr_db` on a synthetic tone + white noise of known in-band SNR.

    This is the check that would have caught issue #107: `sndr_db` multiplied
    the lobe-summed signal-to-noise ratio by the window's ENBW, adding
    10*log10(2.004) = 3.02 dB to every figure. No modulator and no decimator
    are involved -- the record is built analytically, so the expected answer is
    known in closed form.

    The noise is white over the full output band [0, fout/2] = [0, 40 kHz] and
    SNDR is measured over [0, 20 kHz], so half the noise power is in band:
    in-band SNR = (A^2/2) / (sigma^2/2).
    """

    TOL_DB = 0.3

    def _case(self, n, amp, sigma, seed=0):
        cycles = sndr.odd_cycles(n)
        rng = np.random.default_rng(seed)
        rec = amp * np.sin(2 * np.pi * cycles * np.arange(n) / n) + sigma * rng.standard_normal(n)
        true_db = 10 * np.log10((amp * amp / 2) / (sigma * sigma * 0.5))
        got_db, det = sndr.sndr_db(rec, cycles)
        return true_db, got_db, det

    def test_matches_known_snr_at_2_13(self):
        true_db, got_db, _ = self._case(2**13, 0.5, 1e-3)
        self.assertAlmostEqual(got_db, true_db, delta=self.TOL_DB,
                               msg=f"estimator {got_db:.3f} dB vs true in-band SNR {true_db:.3f} dB")

    def test_matches_known_snr_at_2_16(self):
        true_db, got_db, _ = self._case(2**16, 0.5, 1e-3)
        self.assertAlmostEqual(got_db, true_db, delta=self.TOL_DB,
                               msg=f"estimator {got_db:.3f} dB vs true in-band SNR {true_db:.3f} dB")

    def test_matches_known_snr_at_lower_amplitude(self):
        true_db, got_db, _ = self._case(2**16, 0.25, 1e-3)
        self.assertAlmostEqual(got_db, true_db, delta=self.TOL_DB,
                               msg=f"estimator {got_db:.3f} dB vs true in-band SNR {true_db:.3f} dB")

    def test_enbw_factor_is_not_applied(self):
        """Regression guard: re-introducing `* enbw` must break the tolerance.

        Asserts both halves of issue #107 -- that the reported value agrees with
        truth, and that the ENBW-multiplied value does not. Without the second
        half, widening TOL_DB to 3.1 dB would quietly re-admit the bug.
        """
        true_db, got_db, det = self._case(2**16, 0.5, 1e-3)
        enbw_db = 10 * np.log10(det["enbw_bins"])
        self.assertAlmostEqual(enbw_db, 3.02, delta=0.05, msg="4-term Blackman-Harris ENBW")
        self.assertLess(abs(got_db - true_db), self.TOL_DB)
        self.assertGreater(abs(got_db + enbw_db - true_db), self.TOL_DB,
                           "an ENBW-corrected lobe sum must NOT pass this test (issue #107)")


class IdealVsFormula(unittest.TestCase):
    """The ideal model reads ~8 dB BELOW the spec section 5.1 ceiling.

    Section 5.1 derives 94.2 dB at -6 dBFS for L = 2, N = 1, OSR = 128 assuming
    an unscaled (1-z^-1)^2 NTF and brick-wall decimation. The model runs
    Boser-Wooley 0.5/0.5 coefficients through a sinc^3 decimator with no droop
    compensation or FIR, and measures 86.26 dB (N = 2^13) -- a deficit of
    7.98 dB.

    That deficit is real, unexplained, and NOT closed here: issue #108 owns it.
    Until it is explained this test pins the measured relationship instead of
    asserting agreement, so a move in either direction fails. Before issue #107
    the same assertion read "within 6 dB" and passed only because the estimator
    was 3.02 dB optimistic; widening the tolerance again would hide #108 rather
    than resolve it.
    """

    DEFICIT_DB = 7.98   # measured, N = 2^13, -6 dBFS, fixed estimator (issue #107)
    TOL_DB = 0.5

    def test_section_5_1_bound_is_94_2_db(self):
        bound = 7.78 - 12.90 + 50 * np.log10(OSR) - 6  # spec 5.1, computed at -6 dBFS
        self.assertAlmostEqual(bound, 94.2, delta=0.1)

    def test_deficit_to_section_5_1_is_as_recorded(self):
        amp = -6
        bound = 7.78 - 12.90 + 50 * np.log10(OSR) + amp  # spec 5.1, computed
        measured = sndr_at(ideal(), amp)
        self.assertLess(measured, bound,
                        "the ideal model is not expected to beat the section 5.1 ceiling")
        self.assertAlmostEqual(
            bound - measured, self.DEFICIT_DB, delta=self.TOL_DB,
            msg=(f"ideal B reads {measured:.2f} dB against the section 5.1 bound of "
                 f"{bound:.2f} dB: deficit {bound - measured:.2f} dB, recorded as "
                 f"{self.DEFICIT_DB} dB. A change here is either progress on issue #108 "
                 f"(update DEFICIT_DB and #108) or a regression -- do not widen TOL_DB."))


class Monotone(unittest.TestCase):
    def test_lower_dc_gain_lowers_sndr(self):
        s = []
        for gain in (None, 1000.0, 100.0, 20.0, 5.0):
            p = ideal()
            p["dc_gain"] = gain
            s.append(sndr_at(p, -6))
        self.assertTrue(all(a > b for a, b in zip(s, s[1:])), s)

    def test_same_params_same_sndr(self):
        p = ideal()
        p["ktc_noise_var"] = 1e-8
        self.assertEqual(sndr_at(p, -6), sndr_at(p, -6))


class Params(unittest.TestCase):
    def test_unknown_key_rejected(self):
        p = ideal()
        p["bogus"] = 1
        with self.assertRaises(ValueError):
            model.validate_params(p)

    def test_missing_key_rejected(self):
        p = ideal()
        del p["seed"]
        with self.assertRaises(ValueError):
            model.validate_params(p)


class AppendOnly(unittest.TestCase):
    def test_second_write_fails_and_leaves_file_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "r.json"
            run.write_record(path, {"a": 1})
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                run.write_record(path, {"a": 2})
            self.assertEqual(path.read_bytes(), before)


class RecordFields(unittest.TestCase):
    def test_record_carries_required_fields(self):
        p = ideal()
        table, best, det, cycles = run.sweep(p, 2**12, amplitudes=[-6])
        rec = run.build_record(p, "x", 2**12, table, best, det, cycles)
        json.dumps(rec)
        for k in ("source", "record_len", "window", "bin_bw_hz", "amplitude_dbfs",
                  "peak_sndr_db", "cross_check"):
            self.assertIn(k, rec)
        self.assertEqual(rec["source"], "B")
        self.assertEqual(rec["cross_check"], "none (ideal parameters)")
        self.assertTrue(rec["peak_at_sweep_ceiling"])


if __name__ == "__main__":
    unittest.main()

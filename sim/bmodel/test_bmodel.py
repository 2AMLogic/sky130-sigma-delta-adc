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

import ceiling_gap
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
    """The ideal model's SNDR against the *corrected* section 5.1 ceiling.

    Issue #108 / DR-007. Section 5.1 used to write the quantizer term as
    `6.02*N + 1.76`, which assumes a full-scale sine half a step beyond the
    outermost quantizer level. For a single-bit quantizer whose feedback is
    +/-1 that is 6.02 dB too high, and the section reported 94.2 dB at
    -6 dBFS where the level-count form gives 88.2 dB. The remaining gap to
    ideal model B is measured and split by `ceiling_gap.py`:

        spec 5.1 as written       94.25 dB  (closed form, superseded)
        level-count corrected     88.23 dB  (closed form)
        brick-wall bitstream      85.02 dB  (measured)  -> single-bit loop
        committed sinc^3 path     86.17 dB  (measured)  -> decimator, +ve

    So the deficit is NOT the decimator and NOT the Boser-Wooley coefficients
    as such -- the sinc^3 path reads *higher* than a brick wall, because its
    passband droop attenuates more shaped noise than its finite stopband
    aliases back in. These tests assert that explained relationship. Widening
    a tolerance here hides a regression; the figures are pinned to the
    committed record, not chosen.
    """

    # Committed decomposition record, N = 2^16 (ceiling_gap.py). The tests
    # below run at N = 2^13 for speed.
    CORRECTED_BOUND_DB = 88.23
    BRICK_WALL_DB = 85.02
    SINC3_DB = 86.17
    TERMS_DB = {"formula_full_scale_convention": 6.02,
                "single_bit_loop": 3.21,
                "sinc3_decimator": -1.15}

    # Tolerance against those N = 2^16 figures. The spread of the measured
    # terms between N = 2^13 and N = 2^16 is 0.09 dB (decimator) and 0.01 dB
    # (single-bit loop); 0.2 dB covers it with margin and is the same figure
    # the record's own record-length check uses. Not chosen to pass.
    TOL_DB = 0.2

    def test_quantizer_term_convention_costs_6_02_db_at_one_bit(self):
        """The correction is exactly 20*log10(2^N/(2^N - 1)), and only bites at N = 1."""
        as_written = ceiling_gap.quantizer_term_db(1, level_count=False)
        corrected = ceiling_gap.quantizer_term_db(1, level_count=True)
        self.assertAlmostEqual(as_written, 7.78, delta=0.01)   # 6.02*1 + 1.76
        self.assertAlmostEqual(corrected, 1.76, delta=0.01)    # 10*log10(1.5)
        self.assertAlmostEqual(as_written - corrected, 6.02, delta=0.01)
        for n_bits in (13, 16):
            self.assertAlmostEqual(
                ceiling_gap.quantizer_term_db(n_bits, level_count=False),
                ceiling_gap.quantizer_term_db(n_bits, level_count=True), delta=0.002,
                msg=f"at N = {n_bits} the two conventions must agree: spec 5.5 is unaffected")

    def test_corrected_section_5_1_table(self):
        """Spec 5.1 as corrected: 79.2 / 94.2 / 109.3 dB full scale, 88.2 dB at -6 dBFS."""
        for osr, full_scale in ((64, 79.2), (128, 94.2), (256, 109.3)):
            self.assertAlmostEqual(ceiling_gap.bound_db(0, osr=osr), full_scale, delta=0.05)
        self.assertAlmostEqual(ceiling_gap.bound_db(-6, osr=OSR),
                               self.CORRECTED_BOUND_DB, delta=0.01)
        # The superseded form, kept only to pin the size of the correction:
        # 94.2 dB is now the FULL-SCALE ceiling, not the -6 dBFS one.
        self.assertAlmostEqual(ceiling_gap.bound_db(-6, osr=OSR, level_count=False),
                               94.25, delta=0.01)

    def test_closed_form_is_not_the_small_angle_approximation(self):
        """Rules out the formula's small-angle noise integral as a contributor."""
        self.assertAlmostEqual(ceiling_gap.exact_ntf_bound_db(-6, osr=OSR),
                               ceiling_gap.bound_db(-6, osr=OSR), delta=0.01)

    def test_ideal_b_sits_below_the_corrected_bound_by_the_explained_terms(self):
        """The model's own figure, against the corrected bound, is fully accounted for."""
        measured = sndr_at(ideal(), -6)
        bound = ceiling_gap.bound_db(-6, osr=OSR)
        self.assertLess(measured, bound,
                        "the ideal model is not expected to beat the corrected ceiling")
        explained = self.TERMS_DB["single_bit_loop"] + self.TERMS_DB["sinc3_decimator"]
        self.assertAlmostEqual(
            bound - measured, explained, delta=self.TOL_DB,
            msg=(f"ideal B reads {measured:.2f} dB against the corrected section 5.1 "
                 f"bound of {bound:.2f} dB: {bound - measured:.2f} dB, explained as "
                 f"{explained:.2f} dB (single-bit loop {self.TERMS_DB['single_bit_loop']} dB "
                 f"+ sinc^3 decimator {self.TERMS_DB['sinc3_decimator']} dB) by DR-007. "
                 f"A change here is either new work on the decomposition -- rerun "
                 f"ceiling_gap.py, commit the record, update these constants and "
                 f"DR-007 -- or a regression. Do not widen TOL_DB."))

    def test_decomposition_terms_reproduce(self):
        """Each of DR-007's three terms, re-measured, against the committed record."""
        d = ceiling_gap.decompose(ideal(), N)
        self.assertAlmostEqual(d["paths"]["brick_wall"]["sndr_db"],
                               self.BRICK_WALL_DB, delta=self.TOL_DB)
        self.assertAlmostEqual(d["paths"]["sinc3"]["sndr_db"],
                               self.SINC3_DB, delta=self.TOL_DB)
        for name, expect in self.TERMS_DB.items():
            self.assertAlmostEqual(d["terms_db"][name], expect, delta=self.TOL_DB, msg=name)
        self.assertAlmostEqual(d["closure_db"], 0.0, delta=1e-9,
                               msg="the three terms are successive differences; "
                                   "closure is algebraic and must be exact")
        self.assertGreater(d["terms_db"]["sinc3_decimator"] * -1, 0.0,
                           "the sinc^3 path must read HIGHER than a brick wall: its "
                           "droop beats its aliasing (DR-007). A sign change here "
                           "revives the hypothesis #108 refuted.")

    def test_sinc3_path_is_exactly_run_pys_committed_path(self):
        """The decomposition must explain the *committed* figure, not a variant.

        `ceiling_gap.sinc3_path` inlines `run.run_point` so it can reuse the one
        bitstream for both readings; if the two ever diverge, the decomposition
        stops being about the number `run.py` records.
        """
        cycles = sndr.odd_cycles(N)
        y, _u, _skip, _n_clk = ceiling_gap.bitstream(ideal(), -6, N, cycles)
        self.assertEqual(ceiling_gap.sinc3_path(y, N, cycles)[0],
                         run.run_point(ideal(), -6, N, cycles)[0])

    def test_sinc3_figure_is_predicted_by_folding_the_full_rate_spectrum(self):
        """Independent cross-check: the decimator's own response explains its figure."""
        d = ceiling_gap.decompose(ideal(), N)
        self.assertAlmostEqual(d["cross_checks"]["sinc3_prediction_error_db"], 0.0,
                               delta=self.TOL_DB,
                               msg="folding the full-rate spectrum through the sinc^3 "
                                   "response must reproduce the measured sinc^3 figure")

    def test_effective_quantizer_gain_is_not_the_unscaled_ntf_value(self):
        """Why the single-bit term exists at all (indicative, per DR-007)."""
        eq = ceiling_gap.decompose(ideal(), N)["cross_checks"]["effective_quantizer"]
        self.assertAlmostEqual(eq["gain"], 2.51, delta=0.05)
        self.assertAlmostEqual(eq["gain_for_unscaled_ntf"], 4.0, delta=1e-12)
        self.assertAlmostEqual(eq["err_var"], 0.306, delta=0.005)


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

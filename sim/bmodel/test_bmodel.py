"""Tests for behavioural model B. Run:
python3 -I -m unittest discover -s sim/bmodel -p 'test_*.py'

Tests use a short record (N = 2^13 output samples = 524 288 clocks) for speed;
run.py's ideal run uses 2^16. SNDR is a power ratio over [0, BW], so the short
record changes the bin width, not the expected value.
"""
import hashlib
import json
import pathlib
import tempfile
import unittest

import numpy as np

import ceiling_gap
import model
import make_item5_envelope
import run
import sndr
import xcheck

HERE = pathlib.Path(__file__).resolve().parent
REPO = run.REPO
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


class CornerParams(unittest.TestCase):
    """sim/bmodel/corners/<anchor>.json loading (run.load_corner).

    The corner file is the schema: every model-B parameter must be covered by
    a T source or listed under no_t_source, and every named T record must
    exist and hash to the sha256 the file names. A fixture corner declares
    all its parameters under no_t_source so no committed record is needed.
    """

    COVERED = ("dc_gain", "settling_error", "ci_offset", "ci_gain_error",
               "ktc_noise_var", "comparator_offset", "comparator_hysteresis",
               "jitter_rms_s")

    def fixture_corner(self, **over):
        doc = {
            "schema": "fixture",
            "corner_id": "tt/1.800V/27C",
            "sample_slug": "zz-fixture-no-such-samples",
            "params": dict(model.PARAM_DEFAULTS),
            "sources": {},
            "no_t_source": {k: {"why": "fixture"} for k in self.COVERED},
        }
        doc.update(over)
        return doc

    def write_and_load(self, doc, tmp):
        path = tmp / "corner.json"
        path.write_text(json.dumps(doc))
        return run.load_corner(path)

    def test_committed_corner_files_load(self):
        """Every committed corner file still validates against its named T
        records: a record edited after the corner file was written fails
        here instead of silently feeding stale parameters to a sweep."""
        corners = sorted((HERE / "corners").glob("*.json"))
        self.assertGreaterEqual(len(corners), 7)
        for c in corners:
            run.load_corner(c)

    def test_unknown_param_key_refused(self):
        with tempfile.TemporaryDirectory() as td:
            doc = self.fixture_corner()
            doc["params"]["bogus"] = 1
            with self.assertRaises(ValueError):
                self.write_and_load(doc, pathlib.Path(td))

    def test_missing_param_key_refused(self):
        with tempfile.TemporaryDirectory() as td:
            doc = self.fixture_corner()
            del doc["params"]["seed"]
            with self.assertRaises(ValueError):
                self.write_and_load(doc, pathlib.Path(td))

    def test_missing_wrapper_key_refused(self):
        with tempfile.TemporaryDirectory() as td:
            doc = self.fixture_corner()
            del doc["sources"]
            with self.assertRaises(ValueError):
                self.write_and_load(doc, pathlib.Path(td))

    def test_uncovered_parameter_refused(self):
        """A parameter with neither a T source nor a no_t_source entry is an
        error, never a silent default (issue #128 acceptance criteria)."""
        with tempfile.TemporaryDirectory() as td:
            doc = self.fixture_corner()
            del doc["no_t_source"]["ktc_noise_var"]
            with self.assertRaises(ValueError):
                self.write_and_load(doc, pathlib.Path(td))

    def test_missing_record_refused(self):
        with tempfile.TemporaryDirectory() as td:
            doc = self.fixture_corner()
            doc["sources"] = {"dc_gain": {
                "record": "sim/no-such-record.json",
                "record_sha256": "sha256:" + "0" * 64,
            }}
            with self.assertRaises(ValueError) as cm:
                self.write_and_load(doc, pathlib.Path(td))
            self.assertIn("does not exist", str(cm.exception))

    def test_stale_record_hash_refused(self):
        real = REPO / "sim/ota-gain/record.json"
        with tempfile.TemporaryDirectory() as td:
            doc = self.fixture_corner()
            doc["sources"] = {"dc_gain": {
                "record": "sim/ota-gain/record.json",
                "record_sha256": "sha256:" + "0" * 64,
            }}
            with self.assertRaises(ValueError) as cm:
                self.write_and_load(doc, pathlib.Path(td))
            self.assertIn("hashes to", str(cm.exception))
        self.assertTrue(real.is_file())  # the source the test pinned against


class CrossCheck(unittest.TestCase):
    """xcheck.compare_corner on fixture bitstream pairs.

    Both sides of every fixture come from model B itself -- these tests
    exercise the comparison arithmetic and its gates, not model quality: the
    real cross-check evidence is the committed xcheck-record.json built from
    the transistor-level samples (issue #125). The positive-control pair
    differs by a small comparator-offset perturbation; the negative control
    is a deliberately wrong parameter set and must fail.
    """

    N = 1024

    def side(self, params):
        u = model.tone_input(10 ** (-6 / 20), 3, self.N, 1, 0, params)
        y, x1, x2 = model.modulate_with_states(u, params)
        return {
            "n_clocks": self.N,
            "y": [int(v) for v in y],
            "o1d_v": [round(float(v) * 1.2, 7) for v in x1],
            "o2d_v": [round(float(v) * 1.2, 7) for v in x2],
        }

    def b_side(self, params):
        s = self.side(params)
        return {"y": s["y"],
                "x1_fs": [v / 1.2 for v in s["o1d_v"]],
                "x2_fs": [v / 1.2 for v in s["o2d_v"]]}

    def fixture_corner_path(self, tmp):
        doc = {
            "schema": "fixture",
            "corner_id": "tt/1.800V/27C",
            "sample_slug": "zz-fixture-no-such-samples",
            "params": dict(model.PARAM_DEFAULTS),
            "sources": {},
            "no_t_source": {k: {"why": "fixture"} for k in
                            ("dc_gain", "settling_error", "ci_offset",
                             "ci_gain_error", "ktc_noise_var",
                             "comparator_offset", "comparator_hysteresis",
                             "jitter_rms_s")},
        }
        p = tmp / "corner.json"
        p.write_text(json.dumps(doc))
        return p

    def compare(self, tmp, b_params, t_params):
        corner = self.fixture_corner_path(tmp)
        t_path = tmp / "t.json"
        t_path.write_text(json.dumps(self.side(t_params)))
        b_path = tmp / "b.json"
        b_path.write_text(json.dumps(self.b_side(b_params)))
        return xcheck.compare_corner(corner, b_path, t_path)

    def test_near_identical_pair_passes_all_legs(self):
        with tempfile.TemporaryDirectory() as td:
            p = dict(model.PARAM_DEFAULTS)
            q = dict(p, comparator_offset=p["comparator_offset"] + 1e-4)
            entry = self.compare(pathlib.Path(td), q, p)
            self.assertEqual(entry["legs_failed"], [], entry["legs"])
            self.assertTrue(all(v["pass"] for v in entry["legs"].values()))

    def test_wrong_parameter_set_fails(self):
        """Negative control: a deliberately wrong B parameter set must fail
        the cross-check, not slide through the gates."""
        with tempfile.TemporaryDirectory() as td:
            p = dict(model.PARAM_DEFAULTS)
            wrong = dict(p, dc_gain=2.0, ktc_noise_var=1e-3,
                         comparator_offset=0.2, comparator_hysteresis=0.2)
            entry = self.compare(pathlib.Path(td), wrong, p)
            self.assertNotEqual(entry["legs_failed"], [],
                                "the negative control must fail at least one leg")
            self.assertEqual(entry["legs_passed"], [], entry["legs"])

    def test_length_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            corner = self.fixture_corner_path(tmp)
            t_path = tmp / "t.json"
            t_path.write_text(json.dumps(self.side(dict(model.PARAM_DEFAULTS))))
            b = self.b_side(dict(model.PARAM_DEFAULTS))
            b["y"] = b["y"][:-1]
            b["x1_fs"] = b["x1_fs"][:-1]
            b["x2_fs"] = b["x2_fs"][:-1]
            b_path = tmp / "b.json"
            b_path.write_text(json.dumps(b))
            with self.assertRaises(ValueError):
                xcheck.compare_corner(corner, b_path, t_path)

    def test_passing_corner_is_still_incomplete(self):
        """A corner whose every computable leg passes is reported
        `incomplete`, never passed: DR-001's in-band SNDR leg is not
        computable at the committed T record length, so B numbers stay
        uncross-checked and out of row 2 (issue #128)."""
        with tempfile.TemporaryDirectory() as td:
            p = dict(model.PARAM_DEFAULTS)
            entry = xcheck.finalise_entry(
                self.compare(pathlib.Path(td), p, p))
            self.assertTrue(entry["cross_check_status"].startswith("incomplete"))
            self.assertIsNone(entry["sndr_inband_db"]["b"])
            self.assertFalse(entry["sndr_inband_db"]["computable"])

    def test_missing_t_bitstream_reported_uncrosschecked(self):
        """A corner with no committed T bitstream is reported
        uncross-checked, never skipped (issue #128 acceptance criteria)."""
        with tempfile.TemporaryDirectory() as td:
            entry = xcheck.finalise_entry(
                xcheck.no_t_samples_entry(self.fixture_corner_path(
                    pathlib.Path(td))))
            self.assertTrue(entry["cross_check_status"].startswith("uncross-checked"))
            self.assertIsNotNone(entry["error"])
            self.assertIsNone(entry["t_samples_file"])


class CodeIdentity(unittest.TestCase):
    """`code_sha256` names the code that produced the number.

    `git_commit` + `git_dirty` cannot: a record is written before the commit
    that contains it, so the tree is dirty on every run and the stamped commit
    is only the base the run started from (issue #110). Two records with the
    same `params_sha256` and different estimators are indistinguishable by
    their git fields alone.
    """

    def test_build_record_stamps_bmodel_code_hashes(self):
        p = ideal()
        table, best, det, cycles = run.sweep(p, 2**12, amplitudes=[-6])
        rec = run.build_record(p, "x", 2**12, table, best, det, cycles)
        self.assertEqual(set(rec["code_sha256"]),
                         {"sim/bmodel/model.py", "sim/bmodel/sndr.py", "sim/bmodel/run.py"})
        for rel, got in rec["code_sha256"].items():
            want = hashlib.sha256((run.REPO / rel).read_bytes()).hexdigest()
            self.assertEqual(got, want, rel)

    def test_code_state_adds_extra_paths(self):
        extra = HERE / "test_bmodel.py"
        m = run.code_state(extra=[extra])["code_sha256"]
        self.assertEqual(set(m), {"sim/bmodel/model.py", "sim/bmodel/sndr.py",
                                  "sim/bmodel/run.py", "sim/bmodel/test_bmodel.py"})
        self.assertEqual(m["sim/bmodel/test_bmodel.py"],
                         hashlib.sha256(extra.read_bytes()).hexdigest())

    def test_hash_tracks_file_contents(self):
        """A one-byte edit moves only that entry."""
        base = run.code_state()["code_sha256"]
        with tempfile.TemporaryDirectory() as td:
            fake = pathlib.Path(td) / "sndr.py"
            fake.write_bytes((HERE / "sndr.py").read_bytes() + b"\n# one byte\n")
            self.assertNotEqual(hashlib.sha256(fake.read_bytes()).hexdigest(),
                                base["sim/bmodel/sndr.py"])
        self.assertEqual(run.code_state()["code_sha256"], base)

    def test_decompose_record_stamps_ceiling_gap_code_hash(self):
        """The ceiling-gap record names its own estimator, not just run.py's.

        `ceiling_gap.decompose()` is a second B-record writer, so it has to
        stamp `code_sha256` the same way `run.build_record` does (issue #108),
        and the map has to include `ceiling_gap.py` itself -- without the
        `extra=[__file__]` the record would name the three shared B-model files
        and silently omit the code that actually produced the decomposition.
        """
        d = ceiling_gap.decompose(ideal(), 2**12)
        self.assertEqual(set(d["code_sha256"]),
                         {"sim/bmodel/model.py", "sim/bmodel/sndr.py",
                          "sim/bmodel/run.py", "sim/bmodel/ceiling_gap.py"})
        for rel, got in d["code_sha256"].items():
            want = hashlib.sha256((run.REPO / rel).read_bytes()).hexdigest()
            self.assertEqual(got, want, rel)


class Item5EnvelopeRecords(unittest.TestCase):
    """`make_item5_envelope` binds every records[] field to the record its
    entry names, and the committed envelope agrees with the records on disk.

    The first revision of the generator built `records[]` with a
    comprehension that referenced a leaked outer name -- always the last
    RECORDS entry (fs/1.800V/27C) -- so all seven committed entries carried
    fs's corner_params_file, corner_params_sha256, peak SNDR and
    cross_check. Six corners' peak SNDR was attributed to the wrong corner,
    and the two ss corners' span_10pct failures ("a corner that fails is
    reported as failed", item #128's acceptance criteria) were replaced by
    fs's all-computable-legs string. The content-hash gate cannot catch
    this: it proves the envelope has not been edited since the manifest was
    written, not that the generator put the right corner's values in it.
    """

    @staticmethod
    def _committed_recs():
        return {cid: json.loads((REPO / rel).read_text())
                for cid, rel in make_item5_envelope.RECORDS.items()}

    @staticmethod
    def _assert_entry_matches_record(test, entry):
        rec = json.loads((REPO / entry["file"]).read_text())
        test.assertEqual(entry["corner_params_file"], rec["corner_params_file"]["path"])
        test.assertEqual(entry["corner_params_sha256"], rec["corner_params_file"]["sha256"])
        test.assertEqual(entry["peak_sndr_db_uncross_checked"], rec["peak_sndr_db"])
        test.assertEqual(entry["cross_check"], rec["cross_check"])

    def test_entry_fields_come_from_the_named_record(self):
        entries = make_item5_envelope.build_records(self._committed_recs())
        self.assertEqual([e["corner_id"] for e in entries],
                         list(make_item5_envelope.RECORDS))
        for entry in entries:
            self.assertEqual(entry["file"], make_item5_envelope.RECORDS[entry["corner_id"]])
            self._assert_entry_matches_record(self, entry)

    def test_ss_corners_carry_their_span_failure(self):
        entries = {e["corner_id"]: e
                   for e in make_item5_envelope.build_records(self._committed_recs())}
        for cid in ("ss/1.620V/125C", "ss/1.620V/-40C"):
            self.assertIn("FAILED legs: span_10pct", entries[cid]["cross_check"])
            self.assertNotEqual(entries[cid]["peak_sndr_db_uncross_checked"],
                                entries["fs/1.800V/27C"]["peak_sndr_db_uncross_checked"])

    def test_check_records_refuses_leaked_values(self):
        """The defect shape itself: `file` bound per corner, values leaked
        from the last RECORDS entry. The re-derivation guard must refuse."""
        entries = make_item5_envelope.build_records(self._committed_recs())
        leaked = entries[-1]
        for key in ("corner_params_file", "corner_params_sha256",
                    "peak_sndr_db_uncross_checked", "cross_check"):
            entries[0][key] = leaked[key]
        with self.assertRaises(SystemExit):
            make_item5_envelope.check_records(entries)

    def test_committed_envelope_matches_its_records(self):
        envelope = json.loads((HERE / "item5-model-run.json").read_text())
        self.assertEqual([e["corner_id"] for e in envelope["records"]],
                         list(make_item5_envelope.RECORDS))
        for entry in envelope["records"]:
            self._assert_entry_matches_record(self, entry)


class CrossCheckLong(unittest.TestCase):
    """compare_corner(long=True) at the corrigendum's 4096-clock record
    (DR-001 corrigendum 01, issue #290): DR-001 item 3's in-band SNDR leg is
    computable and applied, and the first record's in-band-power proxy is
    demoted to a reported diagnostic. Both fixture sides still come from
    model B itself -- these tests exercise the comparison arithmetic and its
    gates, not model quality; the real evidence is the committed
    xcheck-record-long-dc-excluded.json built from the long transistor-level
    samples (the first derivation, xcheck-record-long.json, summed bins
    1..edge without sec 1.2's DC-leakage exclusion and is superseded).

    The tone bin (12) is read from the long bench's committed record
    (record-long.json, input_sequence.tone_cycles_in_record), exactly as the
    short path reads the short record."""

    N = 4096

    def side(self, params):
        u = model.tone_input(10 ** (-6 / 20), 12, self.N, 1, 0, params)
        y, x1, x2 = model.modulate_with_states(u, params)
        return {
            "n_clocks": self.N,
            "u_diff_v": [float(v) * 1.2 for v in u],
            "y": [int(v) for v in y],
            "o1d_v": [round(float(v) * 1.2, 7) for v in x1],
            "o2d_v": [round(float(v) * 1.2, 7) for v in x2],
        }

    def b_side(self, params):
        s = self.side(params)
        return {"y": s["y"],
                "x1_fs": [v / 1.2 for v in s["o1d_v"]],
                "x2_fs": [v / 1.2 for v in s["o2d_v"]]}

    def fixture_corner_path(self, tmp, params=None):
        doc = {
            "schema": "fixture",
            "corner_id": "tt/1.800V/27C",
            "sample_slug": "zz-fixture-no-such-samples",
            "params": dict(model.PARAM_DEFAULTS) if params is None
            else dict(params),
            "sources": {},
            "no_t_source": {k: {"why": "fixture"} for k in
                            ("dc_gain", "settling_error", "ci_offset",
                             "ci_gain_error", "ktc_noise_var",
                             "comparator_offset", "comparator_hysteresis",
                             "jitter_rms_s")},
        }
        p = tmp / "corner.json"
        p.write_text(json.dumps(doc))
        return p

    def compare(self, tmp, b_params, t_params):
        # The corner file carries the B side's parameters, as the real
        # pipeline does (run.py --xcheck loads them from the corner file),
        # so the seed ensemble re-derives the committed B side exactly.
        corner = self.fixture_corner_path(tmp, params=b_params)
        t_path = tmp / "t.json"
        t_path.write_text(json.dumps(self.side(t_params)))
        b_path = tmp / "b.json"
        b_path.write_text(json.dumps(self.b_side(b_params)))
        return xcheck.compare_corner(corner, b_path, t_path, long=True)

    def test_band_resolves_with_noise_bins_beside_the_lobe(self):
        """The BH-lobe-vs-band edge case at N_T: 1250 Hz bins put the 20 kHz
        band at bins 1..16, the coherent tone at exact bin 12, its lobe at
        8..16, and -- after sec 1.2's DC-leakage exclusion (bins 0..4,
        sndr.DC_EXCL_BINS) -- 3 in-band noise bins (5..7) beside it
        (issue #290)."""
        fs = run.model.FS_HZ
        _, edge = xcheck.band_bins(self.N, fs, sndr.BW_HZ)
        self.assertEqual(edge, 16)
        self.assertEqual(sndr.BW_HZ * self.N / fs, 16.0)
        lobe = xcheck.lobe_bins(12)
        self.assertEqual(int(lobe[0]), 8)
        self.assertEqual(int(lobe[-1]), 16)
        noise = xcheck.inband_noise_bin_indices(edge, 12)
        self.assertEqual([int(b) for b in noise], list(range(5, 8)))

    def test_band_does_not_resolve_at_1024(self):
        """The short record stays honestly incomputable: 5 kHz bins, band
        bins 1..4, tone lobe -1..7 covering all of them."""
        fs = run.model.FS_HZ
        _, edge = xcheck.band_bins(1024, fs, sndr.BW_HZ)
        self.assertEqual(edge, 4)
        self.assertEqual(len(xcheck.inband_noise_bin_indices(edge, 3)), 0)

    def test_near_identical_pair_passes_all_legs_including_sndr(self):
        with tempfile.TemporaryDirectory() as td:
            p = dict(model.PARAM_DEFAULTS)
            q = dict(p, comparator_offset=p["comparator_offset"] + 1e-4)
            entry = xcheck.finalise_entry(self.compare(pathlib.Path(td), q, p),
                                          long=True)
            self.assertEqual(entry["legs_failed"], [], entry["legs"])
            self.assertIn("sndr_inband_3db", entry["legs"])
            self.assertNotIn("inband_power_3db", entry["legs"],
                             "the proxy is demoted once the SNDR leg applies")
            self.assertTrue(entry["sndr_inband_db"]["computable"])
            self.assertLessEqual(entry["sndr_inband_db"]["delta_db"], 3.0)
            self.assertTrue(entry["cross_check_status"].startswith("passed"))
            self.assertIn("cross-checked", entry["cross_check_status"])

    def test_wrong_parameter_set_fails(self):
        """Negative control: a deliberately wrong B parameter set must fail
        the cross-check at the long length too, not slide through."""
        with tempfile.TemporaryDirectory() as td:
            p = dict(model.PARAM_DEFAULTS)
            wrong = dict(p, dc_gain=2.0, ktc_noise_var=1e-3,
                         comparator_offset=0.2, comparator_hysteresis=0.2)
            entry = xcheck.finalise_entry(self.compare(pathlib.Path(td), wrong, p),
                                          long=True)
            self.assertNotEqual(entry["legs_failed"], [],
                                "the negative control must fail at least one leg")
            self.assertTrue(entry["cross_check_status"].startswith("failed"))
            self.assertIn("model finding", entry["cross_check_status"])

    def test_length_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            corner = self.fixture_corner_path(tmp)
            t_path = tmp / "t.json"
            t_path.write_text(json.dumps(self.side(dict(model.PARAM_DEFAULTS))))
            b = self.b_side(dict(model.PARAM_DEFAULTS))
            b["y"] = b["y"][:-1]
            b_path = tmp / "b.json"
            b_path.write_text(json.dumps(b))
            with self.assertRaises(ValueError):
                xcheck.compare_corner(corner, b_path, t_path, long=True)

    def test_seed_ensemble_verdict_branches(self):
        """The ensemble rule itself (issue #290 review round 3): the gate
        returns a verdict only where its outcome is invariant across the
        model's noise seeds -- all-out is a robust fail, all-in a robust
        pass, a straddling ensemble is indeterminate."""
        self.assertEqual(xcheck.ensemble_verdict([-8.0, -6.1, -9.4], 3.0),
                         ("robust_fail", 0))
        self.assertEqual(xcheck.ensemble_verdict([0.5, -2.9, 1.0], 3.0),
                         ("robust_pass", 3))
        self.assertEqual(xcheck.ensemble_verdict([2.0, 5.0, -4.0], 3.0),
                         ("indeterminate", 1))
        self.assertEqual(xcheck.ensemble_verdict([3.0], 3.0),
                         ("robust_pass", 1))

    def test_noise_free_ensemble_is_degenerate(self):
        """Without seeded noise terms every seed reproduces the same
        bitstream: zero spread, the verdict is the committed draw's, and
        seed 1 re-derives the committed side exactly."""
        with tempfile.TemporaryDirectory() as td:
            p = dict(model.PARAM_DEFAULTS)
            q = dict(p, comparator_offset=p["comparator_offset"] + 1e-4)
            entry = xcheck.finalise_entry(self.compare(pathlib.Path(td), q, p),
                                          long=True)
            leg = entry["legs"]["sndr_inband_3db"]
            ens = leg["seed_ensemble"]
            self.assertEqual(ens["n_seeds"], xcheck.SEED_ENSEMBLE_N)
            self.assertEqual(ens["spread_db"], 0.0)
            self.assertEqual(leg["verdict"], "robust_pass")
            self.assertEqual(ens["seed1_delta_vs_committed_db"], 0.0)
            self.assertTrue(ens["seed1_matches_committed_side"])
            self.assertTrue(entry["cross_check_status"].startswith("passed"))

    def test_noisy_b_side_records_its_spread(self):
        """With seeded noise the ensemble spreads and is recorded beside the
        gate; the verdict is one of the three ensemble outcomes, never the
        committed draw alone."""
        with tempfile.TemporaryDirectory() as td:
            p = dict(model.PARAM_DEFAULTS, ktc_noise_var=1e-5)
            entry = xcheck.finalise_entry(self.compare(pathlib.Path(td), p, p),
                                          long=True)
            leg = entry["legs"]["sndr_inband_3db"]
            ens = leg["seed_ensemble"]
            self.assertEqual(ens["n_seeds"], xcheck.SEED_ENSEMBLE_N)
            self.assertGreater(ens["spread_db"], 0.0)
            self.assertIn(leg["verdict"],
                          ("robust_fail", "robust_pass", "indeterminate"))
            self.assertTrue(ens["seed1_matches_committed_side"])
            lo, hi = (ens["delta_signed_db"]["min"],
                      ens["delta_signed_db"]["max"])
            self.assertLessEqual(lo, hi)
            self.assertLessEqual(ens["spread_db"], hi - lo + 1e-9)

    def test_missing_t_bitstream_reported_uncrosschecked(self):
        with tempfile.TemporaryDirectory() as td:
            entry = xcheck.finalise_entry(
                xcheck.no_t_samples_entry(self.fixture_corner_path(
                    pathlib.Path(td)), long=True), long=True)
            self.assertTrue(entry["cross_check_status"].startswith("uncross-checked"))
            self.assertIn("samples-long", entry["error"])

    def test_long_record_header_names_the_corrigendum(self):
        rec = xcheck.build_record([], long=True)
        self.assertIn("DR-001-corrigendum-01", rec["method_basis"])
        self.assertIn("4096", rec["corrigendum_length_evidence"])
        self.assertIn("sndr_inband_3db", rec["acceptance_gates"])
        self.assertIn("seed", rec["acceptance_gates"]["sndr_inband_3db"])
        self.assertIn("indeterminate", rec["acceptance_gates"]["sndr_inband_3db"])
        self.assertIn("indeterminate", rec["dr001_acceptance"])
        self.assertIn("declined", rec["acceptance_gates"]["reported_not_gating"])


if __name__ == "__main__":
    unittest.main()

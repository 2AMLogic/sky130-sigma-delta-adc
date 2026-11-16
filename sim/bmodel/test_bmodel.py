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
    """The ideal model reads ~8 dB BELOW the spec section 5.1 ceiling.

    Section 5.1 derives 94.2 dB at -6 dBFS for L = 2, N = 1, OSR = 128 assuming
    an unscaled (1-z^-1)^2 NTF and brick-wall decimation. The model runs
    C1 = C2 = 0.3 coefficients (DR-007; they were 0.5/0.5, deficit 7.98 dB at
    86.26 dB, N = 2^13) through a sinc^3 decimator with no droop compensation
    or FIR, and measures 82.92 dB (N = 2^13) -- a deficit of 11.32 dB. The
    3.34 dB widening is the price DR-007 pays to keep integrator 1 off the
    rails; it is not new unexplained loss.

    That deficit is real, unexplained, and NOT closed here: issue #108 owns it.
    Until it is explained this test pins the measured relationship instead of
    asserting agreement, so a move in either direction fails. Before issue #107
    the same assertion read "within 6 dB" and passed only because the estimator
    was 3.02 dB optimistic; widening the tolerance again would hide #108 rather
    than resolve it.
    """

    DEFICIT_DB = 11.32  # measured, N = 2^13, -6 dBFS, C1 = C2 = 0.3 (DR-007); was 7.98 at 0.5/0.5
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
        for gain in (1000.0, 100.0, 20.0, 5.0):
            p = ideal()
            p["dc_gain"] = gain
            s.append(sndr_at(p, -6))
        self.assertTrue(all(a > b for a, b in zip(s, s[1:])), s)
        # A = 1000 leaks 0.1 % per clock: at this record length its SNDR is
        # indistinguishable from infinite gain (0.66 dB apart, in the
        # estimator's noise, at C1 = 0.3), so only a bounded gap is asserted.
        self.assertLess(abs(sndr_at(ideal(), -6) - s[0]), 1.0, s)

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


if __name__ == "__main__":
    unittest.main()

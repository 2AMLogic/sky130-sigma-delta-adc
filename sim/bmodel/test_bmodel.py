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


class IdealVsFormula(unittest.TestCase):
    def test_within_6db_of_section_5_1(self):
        amp = -6
        bound = 7.78 - 12.90 + 50 * np.log10(OSR) + amp  # spec 5.1, computed
        self.assertAlmostEqual(bound, 94.2, delta=0.1)
        self.assertAlmostEqual(sndr_at(ideal(), amp), bound, delta=6.0)


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

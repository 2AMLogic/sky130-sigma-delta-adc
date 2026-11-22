"""Tests for the span seed-spread characterisation (issue #311). Run:
python3 -I -m unittest discover -s sim/bmodel -p 'test_*.py'

Seeds [1, 2, 3] on the tt anchor only: 3 x 1024 clocks of model B per call,
sub-second, on the real committed inputs. Determinism, gate flagging, shape,
the mechanism statistics and the exclusive-create record contract are all
exercised there; the seed-1 row is additionally cross-checked against the
committed B-side samples it must reproduce (same corner file, same input,
same seed).
"""
import json
import pathlib
import tempfile
import unittest

import numpy as np

import run as brun
import span_seed_spread as sss

HERE = pathlib.Path(__file__).resolve().parent
TT = HERE / "corners" / "tt-1.800V-27C.json"
B_SIDE_DIR = HERE / "xcheck-sides"
SEEDS = [1, 2, 3]


def anchor(seeds=SEEDS):
    return sss.summarize_anchor(TT, B_SIDE_DIR, seeds)


def record(seeds=SEEDS):
    return sss.build_record([("committed-1024-clock", [anchor(seeds)])], seeds)


class Determinism(unittest.TestCase):
    """Same seeds and same inputs -> bit-identical numbers (issue #311 AC:
    'A test pins the sweep's determinism')."""

    def test_same_seeds_same_numbers(self):
        a = anchor()
        b = anchor()
        self.assertEqual(json.dumps(a, sort_keys=True),
                         json.dumps(b, sort_keys=True))

    def test_record_payload_is_deterministic(self):
        # everything but the wall-clock naming/git stamps is a pure function
        # of the inputs; the record build itself must not depend on call order
        r1 = record()
        r2 = record()
        for key in ("input_sets", "mechanism_check", "seeds", "statistics",
                    "long_record_leg", "gates_quoted_not_changed"):
            self.assertEqual(json.dumps(r1[key], sort_keys=True),
                             json.dumps(r2[key], sort_keys=True), key)

    def test_seed_changes_the_draw(self):
        a = anchor([1])
        b = anchor([2])
        self.assertNotEqual(
            json.dumps(a["seed_values"], sort_keys=True),
            json.dumps(b["seed_values"], sort_keys=True))


class SeedOneReproducesCommittedEvidence(unittest.TestCase):
    """Seed 1 is the corner file's committed seed, so the sweep's first row
    must reproduce the committed cross-check B-side statistics exactly --
    this sweep and sim/bmodel/xcheck.py read the same corner file, the same
    committed input sequence and the same loop."""

    def test_seed1_ptp_matches_committed_b_side(self):
        anch = anchor([1])
        row = anch["seed_values"][0]
        with open(B_SIDE_DIR / "bx-tt-1.800V-27C.json") as f:
            b = json.load(f)
        # the committed arrays are the JSON form of the same computation,
        # rounded to 9 decimals, so the full-precision sweep agrees to the
        # committed data's own precision (~3e-11 on tt's p2p), not to 1e-12
        self.assertAlmostEqual(row["ptp_x1_fs"],
                               float(np.ptp(np.asarray(b["x1_fs"], float))),
                               delta=1e-8)
        self.assertAlmostEqual(row["ptp_x2_fs"],
                               float(np.ptp(np.asarray(b["x2_fs"], float))),
                               delta=1e-8)
        self.assertAlmostEqual(row["duty"], float(np.mean(b["y"])), places=12)


class GateStatements(unittest.TestCase):
    """Per anchor and integrator the record must state whether the seed
    spread exceeds the 10 % span_10pct gate (issue #311 AC)."""

    def test_every_stat_has_spread_and_gate_statement(self):
        anch = anchor()
        for k in sss.STAT_KEYS:
            st = anch["spread"][k]
            for field in ("min", "max", "spread_abs", "spread_rel"):
                self.assertIn(field, st, f"{k}.{field}")

    def test_span_gate_flag_matches_data(self):
        anch = anchor()
        for key in ("ptp_x1_fs", "ptp_x2_fs"):
            st = anch["spread"][key]
            rel = (st["max"] - st["min"]) / (0.5 * (st["max"] + st["min"]))
            self.assertEqual(st["exceeds_span_10pct_gate"], rel > 0.10, key)
            self.assertEqual(st["gate_rel"], 0.10)

    def test_duty_gate_flag_matches_data(self):
        st = anchor()["spread"]["duty"]
        self.assertEqual(st["exceeds_duty_0p05_gate"], st["spread_abs"] > 0.05)
        self.assertEqual(st["gate_abs"], 0.05)

    def test_verdict_range_is_consistent_with_rows(self):
        anch = anchor()
        with open(B_SIDE_DIR / "bx-tt-1.800V-27C.json") as f:
            b = json.load(f)
        with open(brun.REPO / b["t_samples_file"]) as f:
            t = json.load(f)
        t_p2p = float(np.ptp(np.asarray(t["o2d_v"], float))) / b["fs_volts"]
        rels = sorted(abs(r["ptp_x2_fs"] - t_p2p) / t_p2p
                      for r in anch["seed_values"])
        vr = anch["span_verdict_range_against_committed_t"]["o2"]
        # min_rel / max_rel against the committed (9-decimal-rounded) T-side
        # p2p: agree to the rounding floor, not to 1e-12
        self.assertAlmostEqual(vr["min_rel"], rels[0], delta=1e-8)
        self.assertAlmostEqual(vr["max_rel"], rels[-1], delta=1e-8)
        self.assertEqual(vr["n_seeds"], len(anch["seed_values"]))
        self.assertEqual(vr["n_seeds_within_gate"],
                         sum(1 for v in rels if v <= 0.10))


class Shape(unittest.TestCase):
    def test_seed_values_shape(self):
        anch = anchor()
        self.assertEqual([r["seed"] for r in anch["seed_values"]], SEEDS)
        for r in anch["seed_values"]:
            for k in sss.STAT_KEYS:
                self.assertIsInstance(r[k], float, k)
        self.assertEqual(anch["n_clocks"], 1024)

    def test_all_seven_anchors_resolve(self):
        corners = sorted(HERE.glob("corners/*.json"))
        self.assertEqual(len(corners), 7)
        for c in corners:
            inp = sss.anchor_inputs(c, B_SIDE_DIR)
            self.assertEqual(inp["u"].size, inp["n_clocks"])
            self.assertGreater(inp["u"].size, 0)


class MechanismStatistics(unittest.TestCase):
    """The alternative statistics must be present so the
    extreme-order-statistic hypothesis is tested, not asserted (#311 AC)."""

    def test_percentile_and_rms_statistics_present(self):
        sp = anchor()["spread"]
        for k in ("p1p99_x1_fs", "p1p99_x2_fs", "rms_x1_fs", "rms_x2_fs"):
            self.assertIn(k, sp)
        mech = sss.mechanism_summary([anchor()])
        for integ, *_ in sss.INTEGRATORS:
            self.assertIn(integ, mech)
            self.assertIn("spread_of", mech[integ])
        self.assertIn("finding", mech)
        self.assertIn("hypothesis", mech)


class RecordContract(unittest.TestCase):
    def test_record_write_is_exclusive(self):
        rec = record()
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "r.json"
            brun.write_record(p, rec)
            with self.assertRaises(FileExistsError):
                brun.write_record(p, rec)

    def test_record_names_contract_fields(self):
        rec = record()
        self.assertTrue(rec["which_side"].startswith(
            "B-side behavioural model"), rec["which_side"])
        self.assertIn("window", rec)
        self.assertEqual(rec["seeds"], SEEDS)
        for st in rec["input_sets"]:
            self.assertTrue(st["n_clocks"])
            for a in st["anchors"]:
                self.assertEqual(a["n_clocks"], 1024)
                self.assertTrue(a["bin_bw_hz"] > 0)

    def test_long_record_leg_inputs_landed_306(self):
        # PR #306 landed sim/bmodel/xcheck-sides-long/, so #319's sweep
        # repeated the driver verbatim on the long set and landed the
        # append-only record naming it: the status this asserts is the
        # committed record's, not a synthetic in-process one.
        self.assertTrue(sss.LONG_INPUTS_DIR.is_dir(),
                        "long inputs removed again: restore this test")
        rec_path = (HERE / "records"
                    / "20261118T071215Z-f45c2c29.json")
        self.assertTrue(rec_path.is_file(),
                        f"swept record missing: {rec_path.name}")
        with open(rec_path) as f:
            rec = json.load(f)
        self.assertEqual(rec["long_record_leg"]["status"],
                         "swept (long-record inputs present on main)")
        self.assertIn("xcheck-sides-long", rec["long_record_leg"]["why"])
        # the swept record covers both input sets with the contract fields
        # (record length, bin bandwidth), the long set at 4096 clocks
        sets = {st["name"]: st for st in rec["input_sets"]}
        self.assertEqual(sorted(sets),
                         ["committed-1024-clock", "long-record"])
        self.assertEqual(sets["long-record"]["n_clocks"], [4096])
        self.assertEqual(sets["long-record"]["bin_bw_hz"], [1250.0])
        self.assertEqual(len(rec["seeds"]), 20)


if __name__ == "__main__":
    unittest.main()

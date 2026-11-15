"""Fixture tests for the gain runner's derivations. Run:
python3 -I -m unittest discover -s sim/ota-gain -p 'test_*.py'

No fleet, no ngspice, no klt: every corner set here is hand-built. What is
covered is the arithmetic the record depends on (V/V -> dB, the binding
corner, the integrator-ci comparison column) and that a partial or unmeasured
grid is refused as a record.
"""
import contextlib
import io
import math
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import run_gain as rg
import settling_common as sc

PROCESS = ("tt", "ss", "ff", "sf", "fs")
VDDA = ("1.620V", "1.800V", "1.980V")
TEMP = ("-40C", "27C", "125C")
CORNER_IDS = tuple(f"{p}/{v}/{t}" for p in PROCESS for v in VDDA for t in TEMP)


def measured(a0=687.29, status="pass", flat=1e-4, diagnostics=()):
    return {"status": status, "vid_mag": 1.0, "a0_lo": a0, "a0_min": a0 * (1 - flat),
            "a0_max": a0, "a0_flat_rel": flat, "acm_max": 1e-12, "acm_rel": 1e-15,
            "diagnostics": list(diagnostics)}


def unmeasured(status="fail", diagnostics=("batch_job_failed",)):
    c = {"status": status, "diagnostics": list(diagnostics)}
    c.update({k: None for k in rg.KEYS})
    return c


def corner_set(n=sc.GRID_POINTS, factory=measured, **kw):
    return {cid: factory(**kw) for cid in CORNER_IDS[:n]}


def call(fn, *args, **kw):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        verdict = fn(*args, **kw)
    return verdict, err.getvalue()


class Decibels(unittest.TestCase):
    def test_known_values(self):
        self.assertAlmostEqual(rg.db(1.0), 0.0)
        self.assertAlmostEqual(rg.db(10.0), 20.0)
        self.assertAlmostEqual(rg.db(687.2879124659), 56.74277411823585, places=10)

    def test_round_trip(self):
        for a in (1.5, 100.0, 687.29, 1234.5):
            self.assertAlmostEqual(10 ** (rg.db(a) / 20.0), a, places=8)

    def test_non_positive_and_none_are_none(self):
        self.assertIsNone(rg.db(None))
        self.assertIsNone(rg.db(0.0))
        self.assertIsNone(rg.db(-5.0))


class Derive(unittest.TestCase):
    def test_gain_is_carried_in_both_units(self):
        rows = rg.derive({"tt/1.800V/27C": measured(a0=687.2879124659)})
        row = rows["tt/1.800V/27C"]
        self.assertAlmostEqual(row["dc_gain_v_per_v"], 687.2879124659)
        self.assertAlmostEqual(row["dc_gain_db"], 56.74277411823585, places=10)

    def test_comparison_column_delta_is_signed(self):
        rows = rg.derive({"tt/1.800V/27C": measured(a0=1000.0)},
                         ci={"tt/1.800V/27C": 50.0})
        row = rows["tt/1.800V/27C"]
        self.assertEqual(row["integrator_ci_implied_db"], 50.0)
        self.assertAlmostEqual(row["integrator_ci_delta_db"], 60.0 - 50.0)

    def test_missing_comparison_corner_is_none_not_zero(self):
        rows = rg.derive({"tt/1.800V/27C": measured()}, ci={})
        self.assertIsNone(rows["tt/1.800V/27C"]["integrator_ci_implied_db"])
        self.assertIsNone(rows["tt/1.800V/27C"]["integrator_ci_delta_db"])

    def test_unmeasured_corner_survives_derivation_as_null(self):
        rows = rg.derive({"ss/1.620V/-40C": unmeasured()})
        self.assertIsNone(rows["ss/1.620V/-40C"]["dc_gain_v_per_v"])
        self.assertIsNone(rows["ss/1.620V/-40C"]["dc_gain_db"])


class Binding(unittest.TestCase):
    def test_binding_corner_is_the_lowest_gain_not_the_largest_magnitude(self):
        rows = rg.derive({"tt/1.800V/27C": measured(a0=687.0),
                          "fs/1.620V/-40C": measured(a0=110.0),
                          "ss/1.980V/-40C": measured(a0=940.0)})
        b = rg.binding(rows)
        self.assertEqual(b["corner_id"], "fs/1.620V/-40C")
        self.assertAlmostEqual(b["dc_gain_v_per_v"], 110.0)
        self.assertAlmostEqual(b["dc_gain_db"], 20 * math.log10(110.0))

    def test_binding_ignores_unmeasured_corners(self):
        rows = rg.derive({"tt/1.800V/27C": measured(a0=687.0),
                          "ss/1.620V/125C": unmeasured()})
        self.assertEqual(rg.binding(rows)["corner_id"], "tt/1.800V/27C")

    def test_binding_is_none_when_nothing_measured(self):
        self.assertIsNone(rg.binding(rg.derive(corner_set(factory=unmeasured))))

    def test_summary_range_spans_the_grid(self):
        rows = rg.derive({"a/1.800V/27C": measured(a0=110.0),
                          "b/1.800V/27C": measured(a0=940.0)})
        lo, hi = rg.summarize(rows)["dc_gain_db_range"]
        self.assertAlmostEqual(lo, 20 * math.log10(110.0))
        self.assertAlmostEqual(hi, 20 * math.log10(940.0))


class RecordGates(unittest.TestCase):
    """The gates that separate 'simulated and failing' from 'never simulated'."""

    def test_full_measured_grid_passes_both_gates(self):
        full = corner_set()
        self.assertEqual(len(full), sc.GRID_POINTS)
        self.assertTrue(sc.grid_complete([full]))
        self.assertTrue(sc.measurements_present([full], key="a0_lo"))

    def test_partial_grid_is_refused(self):
        short = corner_set(n=sc.GRID_POINTS - 1)
        verdict, err = call(sc.grid_complete, [short])
        self.assertFalse(verdict)
        self.assertIn("not all 45 grid points returned", err)

    def test_dead_fleet_job_is_refused_even_at_full_count(self):
        dead = corner_set(factory=unmeasured)
        self.assertTrue(sc.grid_complete([dead]), "the count gate alone accepts a dead job")
        verdict, err = call(sc.measurements_present, [dead], key="a0_lo")
        self.assertFalse(verdict)
        self.assertIn("returned no a0_lo", err)
        self.assertIn("batch_job_failed", err)

    def test_a_corner_that_missed_a_gate_but_measured_is_accepted(self):
        """A failing validity gate is not this gate's call: it still measured."""
        bad = corner_set(status="fail", flat=0.5)
        verdict, err = call(sc.measurements_present, [bad], key="a0_lo")
        self.assertTrue(verdict)
        self.assertEqual(err, "")


class RequestShape(unittest.TestCase):
    def test_request_is_the_dr_002_full_grid_on_an_ac_analysis(self):
        import make_request as mkq
        r = mkq.REQUEST
        self.assertEqual(r["analysis"]["kind"], "ac")
        self.assertEqual(r["backend"], "batch")
        c = r["corners"]
        self.assertEqual(len(c["process"]) * len(c["supply_v"]["vdda"])
                         * len(c["temperature_c"]), sc.GRID_POINTS)
        self.assertEqual(r["batch"]["capacity_wait_s"], sc.CAPACITY_WAIT_S)

    def test_committed_request_matches_the_builder(self):
        import json
        import make_request as mkq
        self.assertEqual(json.loads((HERE / "request.json").read_text()), mkq.REQUEST)

    def test_every_measurement_key_the_runner_reads_is_requested(self):
        import make_request as mkq
        names = {m["name"] for m in mkq.MEASUREMENTS}
        self.assertEqual(set(rg.KEYS) - names, set())

    def test_the_reported_gain_is_gated_open_loop(self):
        """a0_lo carries a min limit: a closed loop would read about 1 V/V."""
        import make_request as mkq
        a0 = next(m for m in mkq.MEASUREMENTS if m["name"] == "a0_lo")
        self.assertGreater(a0["limits"]["min"], 1.0)


if __name__ == "__main__":
    unittest.main()

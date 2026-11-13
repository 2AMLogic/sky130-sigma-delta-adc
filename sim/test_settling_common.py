"""Fixture tests for the two record-validity gates in settling_common. Run:
python3 -I -m unittest discover -s sim -p 'test_settling*.py'

No fleet, no ngspice, no klt: every corner set here is hand-built. The gates
are what separate "simulated and failing" from "never simulated", so they are
the last thing standing between a dead fleet job and a recorded result
(issue #94). `grid_complete` counts grid points; `measurements_present`
requires a non-null `err_phase` at every one of them.
"""
import contextlib
import io
import unittest

import settling_common as sc

PROCESS = ("tt", "ss", "ff", "sf", "fs")
VDDA = ("1p620", "1p800", "1p980")
TEMP = ("m40", "27", "125")

# DR-002 full grid: 5 process x 3 Vdda x 3 T, in the runner's corner_id shape.
CORNER_IDS = tuple(f"{p}_{v}_{t}" for p in PROCESS for v in VDDA for t in TEMP)


def measured(err_phase=1.2e-5, status="pass", diagnostics=()):
    """A corner that actually simulated: every measurement carries a value."""
    c = {"status": status}
    c.update({k: 1.0 for k in sc.KEYS})
    c["err_phase"] = err_phase
    c["diagnostics"] = list(diagnostics)
    return c


def unmeasured(status="fail", diagnostics=("batch_job_failed",)):
    """The shape a dead fleet job returns: an entry, but no measured values."""
    c = {"status": status}
    c.update({k: None for k in sc.KEYS})
    c["diagnostics"] = list(diagnostics)
    return c


def corner_set(n=sc.GRID_POINTS, factory=measured, **kwargs):
    assert n <= len(CORNER_IDS)
    return {cid: factory(**kwargs) for cid in CORNER_IDS[:n]}


def call(fn, *args):
    """Run a gate, returning (verdict, stderr) — the gates print on refusal."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        verdict = fn(*args)
    return verdict, err.getvalue()


class MeasurementsPresent(unittest.TestCase):
    def test_dead_fleet_job_is_refused(self):
        """45 entries, every err_phase null: the count gate alone would pass."""
        dead = corner_set(factory=unmeasured)
        self.assertEqual(len(dead), sc.GRID_POINTS)
        self.assertTrue(sc.grid_complete([dead, dead]), "count gate accepts a dead job")
        verdict, err = call(sc.measurements_present, [dead, dead])
        self.assertFalse(verdict)
        self.assertIn("REFUSE", err)
        self.assertIn("batch_job_failed", err)
        self.assertIn(f"{2 * sc.GRID_POINTS} corner(s) returned no err_phase", err)

    def test_failing_but_measured_grid_is_accepted(self):
        """A circuit that misses the limit still measured: that is not this gate's call."""
        failing = corner_set(status="fail", err_phase=4.1e-3)
        verdict, err = call(sc.measurements_present, [failing, failing])
        self.assertTrue(verdict)
        self.assertEqual(err, "")

    def test_one_null_err_phase_among_measured_corners_is_refused(self):
        partial = corner_set()
        partial[CORNER_IDS[7]] = unmeasured(diagnostics=("tran_convergence_failed",))
        self.assertEqual(len(partial), sc.GRID_POINTS)
        verdict, err = call(sc.measurements_present, [partial, corner_set()])
        self.assertFalse(verdict)
        self.assertIn("1 corner(s) returned no err_phase", err)
        self.assertIn("tran_convergence_failed", err)

    def test_missing_diagnostics_still_refuses(self):
        """No diagnostic code at all must not read as an all-clear."""
        blank = corner_set(factory=unmeasured, diagnostics=())
        verdict, err = call(sc.measurements_present, [blank])
        self.assertFalse(verdict)
        self.assertIn("<none>", err)

    def test_a_measured_grid_passes_both_gates(self):
        sets = [corner_set(), corner_set()]
        self.assertTrue(sc.grid_complete(sets))
        self.assertTrue(sc.measurements_present(sets))


class GridComplete(unittest.TestCase):
    def test_full_grid_is_accepted(self):
        verdict, err = call(sc.grid_complete, [corner_set(), corner_set()])
        self.assertTrue(verdict)
        self.assertEqual(err, "")

    def test_short_grid_is_refused(self):
        short = corner_set(n=sc.GRID_POINTS - 1)
        self.assertEqual(len(short), 44)
        verdict, err = call(sc.grid_complete, [short])
        self.assertFalse(verdict)
        self.assertIn(f"not all {sc.GRID_POINTS} grid points returned", err)

    def test_one_short_set_refuses_the_whole_record(self):
        verdict, _ = call(sc.grid_complete, [corner_set(), corner_set(n=1)])
        self.assertFalse(verdict)

    def test_grid_points_matches_the_dr_002_grid(self):
        self.assertEqual(sc.GRID_POINTS, len(PROCESS) * len(VDDA) * len(TEMP))


if __name__ == "__main__":
    unittest.main()

"""Fixture tests for settling_common's record-validity gates and `request()`.
Run: python3 -I -m unittest discover -s sim -p 'test_settling*.py'

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


class Request(unittest.TestCase):
    """`request()` builds the common DR-002 full-grid batch request.

    The `analysis` argument (issue #126) lets a bench that measures something
    a transient cannot reach -- an `ac` gain, a `.noise` spectrum -- reuse this
    builder. The historical transient form must stay byte-identical, because
    the settling benches' committed requests and the `request_sha256` in their
    records are both pinned to it.
    """

    MEAS = [{"name": "x", "expr": "v(out)"}]

    def req(self, **kw):
        return sc.request("d.cir", self.MEAS, timeout_s=60, poll_timeout_s=600, **kw)

    def test_transient_form_is_unchanged(self):
        r = self.req(t_end=300e-9)
        self.assertEqual(r["analysis"], {"kind": "tran", "args": "10p 3e-07 0 0.1n"})
        self.assertEqual(r["options"], {"timeout_s": 60, "keep_artifacts": False})

    def test_grid_is_the_dr_002_full_grid(self):
        c = self.req(t_end=1e-9)["corners"]
        self.assertEqual(len(c["process"]) * len(c["supply_v"]["vdda"])
                         * len(c["temperature_c"]), sc.GRID_POINTS)

    def test_every_request_waits_for_fleet_capacity(self):
        self.assertEqual(self.req(t_end=1e-9)["batch"]["capacity_wait_s"], sc.CAPACITY_WAIT_S)

    def test_analysis_replaces_the_transient(self):
        a = {"kind": "ac", "args": "dec 10 1 1000"}
        r = self.req(analysis=a)
        self.assertEqual(r["analysis"], a)

    def test_analysis_object_is_not_mutated_or_aliased_into_the_request(self):
        a = {"kind": "noise", "args": "v(out) V1 dec 20 1 1e11"}
        r = self.req(analysis=dict(a))
        self.assertEqual(r["analysis"], a)

    def test_an_analysis_request_is_otherwise_identical_to_a_transient_one(self):
        tran = self.req(t_end=1e-9)
        ac = self.req(analysis={"kind": "ac", "args": "dec 10 1 1000"})
        self.assertEqual({k: v for k, v in tran.items() if k != "analysis"},
                         {k: v for k, v in ac.items() if k != "analysis"})

    def test_options_are_merged_without_displacing_the_managed_keys(self):
        r = self.req(analysis={"kind": "op", "args": ""},
                     options={"ngspice_init": ["set numdgt=12"]})
        self.assertEqual(r["options"], {"ngspice_init": ["set numdgt=12"],
                                        "timeout_s": 60, "keep_artifacts": False})

    def test_options_cannot_override_timeout_or_keep_artifacts(self):
        r = self.req(analysis={"kind": "op", "args": ""},
                     options={"timeout_s": 1, "keep_artifacts": True})
        self.assertEqual(r["options"]["timeout_s"], 60)
        self.assertFalse(r["options"]["keep_artifacts"])

    def test_neither_t_end_nor_analysis_is_refused(self):
        with self.assertRaises(ValueError):
            self.req()

    def test_both_t_end_and_analysis_is_refused(self):
        with self.assertRaises(ValueError):
            self.req(t_end=1e-9, analysis={"kind": "ac", "args": "dec 10 1 1000"})

    def test_missing_timeouts_are_refused(self):
        with self.assertRaises(ValueError):
            sc.request("d.cir", self.MEAS, t_end=1e-9, poll_timeout_s=600)
        with self.assertRaises(ValueError):
            sc.request("d.cir", self.MEAS, t_end=1e-9, timeout_s=60)


class CommittedRequestsAreUnmoved(unittest.TestCase):
    """The pre-#126 benches' committed requests must still rebuild byte-exactly.

    Their records pin `request_sha256` to these files, so a change here would
    silently orphan a recorded result from the request that produced it.
    """

    def test_integrator_settling_requests_rebuild_identically(self):
        self.assertEqual(*self._rebuild("integrator-settling"))

    def test_integrator_ci_requests_rebuild_identically(self):
        self.assertEqual(*self._rebuild("integrator-ci"))

    def _rebuild(self, bench):
        import importlib.util
        import json
        import pathlib
        here = pathlib.Path(__file__).resolve().parent / bench
        spec = importlib.util.spec_from_file_location(f"{bench}_mk", here / "make_request.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        on_disk, rebuilt = {}, {}
        for p in sorted(here.glob("request*.json")):
            on_disk[p.name] = json.loads(p.read_text())
            name = p.stem.replace("request_", "", 1)
            if bench == "integrator-settling":
                rebuilt[p.name] = sc.request(f"integrator_settling_{name}.cir", mod.MEASUREMENTS,
                                             mod.T_END, timeout_s=60, poll_timeout_s=7200)
            else:
                v = name.replace("mc_", "", 1)
                rebuilt[p.name] = (mod.mc_request(v) if name.startswith("mc_")
                                   else mod.nominal_request(v))
        self.assertTrue(on_disk, f"no committed requests found for {bench}")
        return on_disk, rebuilt


if __name__ == "__main__":
    unittest.main()

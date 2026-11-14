"""Tests for the integrator-settling runner's result-admission paths. Run:
python3 -I -m unittest discover -s sim/integrator-settling -p 'test_*.py'

No fleet, no ngspice, no klt: `run_klt` and `pdk_stamp` are patched and the
runner's HERE / .partials are redirected into a temporary directory, so the
committed record.json is never read or written. `shas()` is NOT patched — the
real request and deck files are copied into the temporary HERE, so the
.partials hash gate is exercised as written.

The harness itself is `sim/runner_test_common.py`, shared with the
charge-injection bench; this module binds it to this bench and keeps the
bench-specific gates below.

What is pinned here (issue #94): a variant requested in this invocation whose
submit fails is never served from .partials/ — the run refuses with exit 1 and
writes no record — while reuse of a partial for a variant *not* requested this
invocation still works.
"""
import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
# `sim/` is not on sys.path under `python3 -I`: isolated mode drops CWD and
# PYTHONPATH, and `discover -s sim/integrator-settling` puts only the bench
# directory there. The runner inserts it in load_runner() below, which is too
# late for this import.
sys.path.insert(0, str(HERE.parent))

import runner_test_common as rtc                                    # noqa: E402
from runner_test_common import CORNER_IDS                           # noqa: E402

RUNNER = rtc.load_runner("run_settling_under_test", HERE / "run_settling.py")
SC = sys.modules["settling_common"]   # put on sys.path by run_settling.py above
KEYS, GRID_POINTS = SC.KEYS, SC.GRID_POINTS


def measured_corners(n=GRID_POINTS, status="pass", err_phase=1.2e-5):
    """A simulated grid: one entry per point, every measurement with a value."""
    out = {}
    for cid in CORNER_IDS[:n]:
        c = {"status": status}
        c.update({k: 1.0 for k in KEYS})
        c["err_phase"] = err_phase
        c["diagnostics"] = []
        out[cid] = c
    return out


def report(status="pass", job="job-0001"):
    return {"status": status,
            "environment": {"engine_version": "ngspice-44", "engine_host": "fleet-node-1",
                            "remote": {"job_id": job}}}


class RunnerCase(rtc.RunnerCase):
    """The shared harness, bound to this bench's runner and inputs."""

    RUNNER = RUNNER
    BENCH = HERE
    VARIANTS = RUNNER.VARIANTS
    TMP_PREFIX = "test-run-settling-"
    ARGV0 = "run_settling.py"
    NGSPICE = "ngspice-44"
    GRID_POINTS = GRID_POINTS

    def deck_name(self, v):
        return f"integrator_settling_{v}.cir"

    def default_corners(self):
        return measured_corners()

    def partial_summary(self):
        s = super().partial_summary()
        s["worst_err_phase"] = [1.2e-5, CORNER_IDS[0]]
        return s


class FailedSubmitIsNotServedFromPartials(rtc.FailedSubmitRefusalTests, RunnerCase):
    REQUESTED = "int1"
    OTHER = "int2"
    REUSE_FMT = "{v}: reusing .partials/{v}.json"

    def test_both_submits_failing_refuses_both_variants(self):
        self.write_partial("int1")
        self.write_partial("int2")

        rc, out, err = self.run_main(["--record"], {})

        self.assertEqual(rc, 1)
        self.assertNoRecord()
        self.assertIn("REFUSE: no result for int1, int2", err)
        self.assertEqual(self.calls, ["int1", "int2"])


class NonRequestedVariantReuseIsUnchanged(RunnerCase):
    def test_variant_int2_reuses_the_saved_int1_partial(self):
        saved = self.write_partial("int1")

        rc, out, err = self.run_main(
            ["--variant", "int2"], {"int2": (report(), measured_corners())})

        self.assertEqual(rc, 0, f"stdout={out!r} stderr={err!r}")
        self.assertIn("int1: reusing .partials/int1.json", out)
        self.assertIn("all variants complete; re-run with --record", out)
        self.assertEqual(self.calls, ["int2"], "int1 must not be re-submitted")
        # int2's fresh result is cached; int1's saved partial is untouched.
        fresh = json.loads((self.partials / "int2.json").read_text())
        self.assertEqual(fresh["remote"], {"job_id": "job-0001"})
        self.assertEqual(json.loads((self.partials / "int1.json").read_text()), saved)

    def test_non_requested_variant_with_a_stale_partial_is_not_reused(self):
        self.write_partial("int1", stale=True)

        rc, out, err = self.run_main(
            ["--variant", "int2"], {"int2": (report(), measured_corners())})

        self.assertEqual(rc, 1)
        self.assertIn("ignoring stale .partials/int1.json", err)
        self.assertIn("REFUSE: no result for int1", err)

    def test_a_dead_grid_from_a_partial_still_fails_the_measurement_gate(self):
        dead = measured_corners()
        for c in dead.values():
            c["err_phase"] = None
        self.write_partial("int1", corners=dead)

        rc, out, err = self.run_main(
            ["--variant", "int2", "--record"], {"int2": (report(), measured_corners())})

        self.assertEqual(rc, 1)
        self.assertIn("returned no err_phase", err)
        self.assertNoRecord()


class Probe(RunnerCase):
    def test_probe_with_no_report_exits_1_instead_of_raising(self):
        self.write_partial("int1")

        rc, out, err = self.run_main(["--probe", "int1"], {"int1": None})

        self.assertEqual(rc, 1)
        self.assertIn("REFUSE: no result for the int1 probe", err)
        self.assertEqual(out, "", "the saved partial's corners must not be printed")

    def test_probe_with_no_report_and_no_partial_exits_1(self):
        rc, out, err = self.run_main(["--probe", "int2"], {"int2": None})

        self.assertEqual(rc, 1)
        self.assertIn("REFUSE: no result for the int2 probe", err)

    def test_successful_probe_is_unaffected(self):
        one = measured_corners(n=1)

        rc, out, err = self.run_main(
            ["--probe", "int1"], {"int1": (report(), one)})

        self.assertEqual(rc, 0, f"stderr={err!r}")
        self.assertIn(json.dumps(one, indent=2), out, "the probe prints its own corners")
        self.assertEqual(self.calls, ["int1"], "a probe runs only its own variant")
        self.assertFalse((self.partials / "int1.json").exists(),
                         "a probe must not write a partial")


if __name__ == "__main__":
    unittest.main()

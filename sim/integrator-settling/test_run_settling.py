"""Tests for the integrator-settling runner's result-admission paths. Run:
python3 -I -m unittest discover -s sim/integrator-settling -p 'test_*.py'

No fleet, no ngspice, no klt: `run_klt` and `pdk_stamp` are patched and the
runner's HERE / .partials are redirected into a temporary directory, so the
committed record.json is never read or written. `shas()` is NOT patched — the
real request and deck files are copied into the temporary HERE, so the
.partials hash gate is exercised as written.

What is pinned here (issue #94): a variant requested in this invocation whose
submit fails is never served from .partials/ — the run refuses with exit 1 and
writes no record — while reuse of a partial for a variant *not* requested this
invocation still works.
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent


def load_runner():
    """Load run_settling.py by path: 'integrator-settling' is not importable."""
    spec = importlib.util.spec_from_file_location(
        "run_settling_under_test", HERE / "run_settling.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUNNER = load_runner()
PIN = json.loads((RUNNER.REPO / "sim/pdk.json").read_text())

PROCESS = ("tt", "ss", "ff", "sf", "fs")
VDDA = ("1p620", "1p800", "1p980")
TEMP = ("m40", "27", "125")
CORNER_IDS = tuple(f"{p}_{v}_{t}" for p in PROCESS for v in VDDA for t in TEMP)
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


class RunnerCase(unittest.TestCase):
    """Runs main() against a temporary HERE with run_klt / pdk_stamp patched."""

    maxDiff = None

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-run-settling-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.here = self.tmp / "bench"
        self.here.mkdir()
        for v in RUNNER.VARIANTS:                       # real inputs: real shas()
            for name in (f"request_{v}.json", f"integrator_settling_{v}.cir"):
                (self.here / name).write_bytes((HERE / name).read_bytes())
        self.partials = self.here / ".partials"
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.calls = []

    def shas(self, v):
        """The hashes load_partial() demands, computed with the real helper."""
        with mock.patch.object(RUNNER, "HERE", self.here):
            return RUNNER.shas(v)

    def write_partial(self, v, corners=None, passed=True, stale=False):
        self.partials.mkdir(exist_ok=True)
        d = {"summary": {"corner_count": GRID_POINTS, "pass": GRID_POINTS, "fail": 0,
                         "worst_err_phase": [1.2e-5, CORNER_IDS[0]]},
             "corners": measured_corners() if corners is None else corners,
             "pass": passed, "ngspice": "ngspice-44", "engine_host": "fleet-node-0",
             "remote": {"job_id": f"job-earlier-{v}"}, **self.shas(v)}
        if stale:
            d["deck_sha256"] = "0" * 64
        (self.partials / f"{v}.json").write_text(json.dumps(d, indent=2) + "\n")
        return d

    def run_main(self, argv, submits):
        """main() with argv; `submits` maps variant -> run_klt return value."""
        def fake_run_klt(request_path, probe, tmpdir, tag, probe_path, **kw):
            self.calls.append(tag)
            return submits.get(tag)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.object(RUNNER, "HERE", self.here))
            st.enter_context(mock.patch.object(RUNNER, "PARTIALS", self.partials))
            st.enter_context(mock.patch.object(RUNNER, "ARTIFACTS", self.here / ".artifacts"))
            st.enter_context(mock.patch.object(
                RUNNER, "pdk_stamp",
                lambda variant, root: (pathlib.Path("/fake/pdk"), PIN["sources_stamp"])))
            st.enter_context(mock.patch.object(RUNNER, "run_klt", fake_run_klt))
            st.enter_context(mock.patch.object(
                RUNNER.tempfile, "mkdtemp", lambda *a, **k: str(self.work)))
            st.enter_context(mock.patch.object(sys, "argv", ["run_settling.py", *argv]))
            st.enter_context(contextlib.redirect_stdout(out))
            st.enter_context(contextlib.redirect_stderr(err))
            rc = RUNNER.main()
        return rc, out.getvalue(), err.getvalue()

    def assertNoRecord(self, name="record.json"):
        self.assertFalse((self.here / name).exists(),
                         f"{name} was written from a run whose submit failed")


class FailedSubmitIsNotServedFromPartials(RunnerCase):
    def test_requested_variant_with_failed_submit_refuses_despite_matching_partial(self):
        self.write_partial("int1")
        self.write_partial("int2")
        before = (self.partials / "int1.json").read_text()

        rc, out, err = self.run_main(["--variant", "int1", "--record"], {"int1": None})

        self.assertEqual(rc, 1)
        self.assertNoRecord()
        self.assertIn("not falling back to a local grid or to .partials/", err)
        self.assertIn("REFUSE: no result for int1", err)
        self.assertNotIn("falling back to the saved", out + err)
        # int2 was not requested, so its partial is still reused ...
        self.assertIn("int2: reusing .partials/int2.json", out)
        # ... and int1's partial is left on disk for an operator to re-run into.
        self.assertEqual((self.partials / "int1.json").read_text(), before)

    def test_both_submits_failing_refuses_both_variants(self):
        self.write_partial("int1")
        self.write_partial("int2")

        rc, out, err = self.run_main(["--record"], {})

        self.assertEqual(rc, 1)
        self.assertNoRecord()
        self.assertIn("REFUSE: no result for int1, int2", err)
        self.assertEqual(self.calls, ["int1", "int2"])

    def test_stale_partial_with_failed_submit_also_refuses(self):
        self.write_partial("int1", stale=True)
        self.write_partial("int2")

        rc, out, err = self.run_main(["--variant", "int1", "--record"], {"int1": None})

        self.assertEqual(rc, 1)
        self.assertNoRecord()
        self.assertIn("REFUSE: no result for int1", err)

    def test_record_name_variant_is_not_written_either(self):
        self.write_partial("int1")
        self.write_partial("int2")

        rc, _, err = self.run_main(
            ["--variant", "int1", "--record", "--record-name", "record-retry.json"],
            {"int1": None})

        self.assertEqual(rc, 1)
        self.assertNoRecord("record-retry.json")


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

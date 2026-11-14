"""Shared test harness for the `klt sim` bench runners.

Imported by the per-bench test modules (`sim/integrator-ci/test_run_ci.py`,
`sim/integrator-settling/test_run_settling.py`). The module name is
deliberately NOT `test_`-prefixed: neither
`python3 -I -m unittest discover -s sim -p 'test_settling*.py'` nor a
per-bench `discover -s sim/<bench> -p 'test_*.py'` may collect it, because
the classes here have no runner bound until a bench subclasses them.

`sim/` is not importable at module scope under `python3 -I`: isolated mode
drops the CWD and PYTHONPATH, and `discover` puts only its *start* directory
on `sys.path`. The benches' runners do `sys.path.insert(0, str(HERE.parent))`
themselves, but that happens inside `load_runner()`, too late for a top-of-file
import. Each bench test module therefore inserts `HERE.parent` on `sys.path`
itself before importing this one.

What lives here is the scaffold, not the rule. The admission rule has one
implementation (`sim/settling_common.py`); this is the one implementation of
the harness that asserts it, so a change to the rule no longer needs two
hand-synchronized test edits. Both benches still assert the issue #94 rule
independently -- each binds `FailedSubmitRefusalTests` to its own variant pair
and its own refusal strings -- and every bench-specific gate, derivation and
fixture check stays in its own bench's test module.

This is the test-side half of the consolidation `sim/settling_common.py` made
on the runner side for exactly these benches (issue #57).
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SIM = pathlib.Path(__file__).resolve().parent

# The PDK pin the fake `pdk_stamp` hands back. Read from this module's own
# directory: `sim/pdk.json` is the same file the runners reach for as
# `RUNNER.REPO / "sim/pdk.json"`.
PIN = json.loads((SIM / "pdk.json").read_text())

# DR-002 full grid: 5 process x 3 Vdda x 3 T, in the runners' corner_id shape.
PROCESS = ("tt", "ss", "ff", "sf", "fs")
VDDA = ("1p620", "1p800", "1p980")
TEMP = ("m40", "27", "125")
CORNER_IDS = tuple(f"{p}_{v}_{t}" for p in PROCESS for v in VDDA for t in TEMP)


def load_runner(module_name, path):
    """Load a runner by path: a bench directory is not an importable name."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RunnerCase(unittest.TestCase):
    """Runs main() against a temporary HERE with run_klt / pdk_stamp patched.

    No fleet, no ngspice, no klt. `shas()` is NOT faked: the real request and
    deck files are copied into the temporary HERE, so the .partials hash gate
    is exercised as written.

    A bench binds the knobs. Class attributes: `RUNNER` (the module under
    test), `BENCH` (the directory the real inputs are copied from), `VARIANTS`,
    `TMP_PREFIX`, `ARGV0`, `NGSPICE`, `GRID_POINTS`. Hooks: `deck_name()`,
    `default_corners()`, and -- where a bench needs more -- `input_names()`,
    `partial_summary()`, `partial_name()`, `shas()`, `patch_here()` and
    `patch_extra()`.
    """

    maxDiff = None

    RUNNER = None          # the runner module under test
    BENCH = None           # the bench directory holding the committed inputs
    VARIANTS = ()          # the variants a bare `--record` run submits
    TMP_PREFIX = "test-runner-"
    ARGV0 = "runner.py"
    NGSPICE = "ngspice-47"
    GRID_POINTS = 45       # DR-002 full grid, as a cached partial reports it

    # ---- per-bench knobs -------------------------------------------------

    def deck_name(self, v):
        """The deck filename for variant `v`, relative to BENCH."""
        raise NotImplementedError

    def default_corners(self):
        """The corner dict `write_partial()` caches when it is given none."""
        raise NotImplementedError

    def input_names(self):
        """Filenames copied BENCH -> temporary HERE, so shas() stays real."""
        for v in self.VARIANTS:
            yield f"request_{v}.json"
            yield self.deck_name(v)

    def partial_summary(self):
        """The `summary` block of a cached partial."""
        n = self.GRID_POINTS
        return {"corner_count": n, "pass": n, "fail": 0}

    def partial_body(self, v, corners, passed):
        """A cached partial for variant `v`, minus the sha fields."""
        return {"summary": self.partial_summary(),
                "corners": corners,
                "pass": passed,
                "ngspice": self.NGSPICE,
                "engine_host": "fleet-node-0",
                "remote": {"job_id": f"job-earlier-{v}"}}

    def partial_name(self, v, **kw):
        """The filename variant `v`'s partial is cached under."""
        return f"{v}.json"

    @contextlib.contextmanager
    def patch_here(self):
        """Point the runner at the temporary bench directory, for shas()."""
        with mock.patch.object(self.RUNNER, "HERE", self.here):
            yield

    def shas(self, v, **kw):
        """The hashes load_partial() demands, computed with the real helper."""
        with self.patch_here():
            return self.RUNNER.shas(v)

    def patch_extra(self, stack):
        """Bench-specific context managers entered for every run_main()."""

    # ---- the harness -----------------------------------------------------

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix=self.TMP_PREFIX))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.here = self.tmp / "bench"
        self.here.mkdir()
        for name in self.input_names():                 # real inputs: real shas()
            (self.here / name).write_bytes((self.BENCH / name).read_bytes())
        self.partials = self.here / ".partials"
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.calls = []
        self.kwargs = []

    def write_partial(self, v, corners=None, passed=True, stale=False, **kw):
        """Cache a partial for `v`; `stale=True` breaks its deck hash."""
        self.partials.mkdir(exist_ok=True)
        d = {**self.partial_body(
                 v, self.default_corners() if corners is None else corners, passed),
             **self.shas(v, **kw)}
        if stale:
            d["deck_sha256"] = "0" * 64
        (self.partials / self.partial_name(v, **kw)).write_text(
            json.dumps(d, indent=2) + "\n")
        return d

    def run_main(self, argv, submits):
        """main() with argv; `submits` maps run_klt tag -> its return value."""
        def fake_run_klt(request_path, probe, tmpdir, tag, probe_path, **kw):
            self.calls.append(tag)
            self.kwargs.append(kw)
            return submits.get(tag)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.object(self.RUNNER, "HERE", self.here))
            st.enter_context(mock.patch.object(self.RUNNER, "PARTIALS", self.partials))
            st.enter_context(mock.patch.object(
                self.RUNNER, "ARTIFACTS", self.here / ".artifacts"))
            st.enter_context(mock.patch.object(
                self.RUNNER, "pdk_stamp",
                lambda variant, root: (pathlib.Path("/fake/pdk"), PIN["sources_stamp"])))
            st.enter_context(mock.patch.object(self.RUNNER, "run_klt", fake_run_klt))
            st.enter_context(mock.patch.object(
                self.RUNNER.tempfile, "mkdtemp", lambda *a, **k: str(self.work)))
            self.patch_extra(st)
            st.enter_context(mock.patch.object(sys, "argv", [self.ARGV0, *argv]))
            st.enter_context(contextlib.redirect_stdout(out))
            st.enter_context(contextlib.redirect_stderr(err))
            rc = self.RUNNER.main()
        return rc, out.getvalue(), err.getvalue()

    def assertNoRecord(self, name="record.json"):
        self.assertFalse((self.here / name).exists(),
                         f"{name} was written from a run that should have refused")


class FailedSubmitRefusalTests:
    """The issue #94 rule, as test methods a bench binds to its own variants.

    A plain mixin, NOT a TestCase: importing it into a bench's test module
    must not get it collected and run with no runner bound. Each bench mixes
    it into its own `RunnerCase` subclass.

    The rule: a variant requested in this invocation whose submit fails is
    never served from .partials/ -- the run refuses with exit 1 and writes no
    record -- while reuse of a partial for a variant *not* requested this
    invocation still works.

    Knobs: `REQUESTED` is the variant submitted and made to fail; `OTHER` is a
    variant not requested this invocation, whose partial must still be reused.
    `REUSE_FMT` and `REFUSE_FMT` are that runner's own two lines.
    """

    REQUESTED = None
    OTHER = None
    REUSE_FMT = "{v}: reusing {v}.json"
    REFUSE_FMT = "REFUSE: no result for {v}"

    def write_all_partials(self, stale=None):
        """Cache every variant, so only the failed submit can refuse the run."""
        for v in self.VARIANTS:
            self.write_partial(v, stale=(v == stale))

    def test_requested_variant_with_failed_submit_refuses_despite_matching_partial(self):
        self.write_all_partials()
        before = (self.partials / f"{self.REQUESTED}.json").read_text()

        rc, out, err = self.run_main(
            ["--variant", self.REQUESTED, "--record"], {self.REQUESTED: None})

        self.assertEqual(rc, 1)
        self.assertNoRecord()
        self.assertIn("not falling back to a local grid or to .partials/", err)
        self.assertIn(self.REFUSE_FMT.format(v=self.REQUESTED), err)
        self.assertNotIn("falling back to the saved", out + err)
        # A variant not requested this time still comes from its partial ...
        self.assertIn(self.REUSE_FMT.format(v=self.OTHER), out)
        # ... and the failed one's partial is left on disk to re-run into.
        self.assertEqual((self.partials / f"{self.REQUESTED}.json").read_text(), before)
        self.assertEqual(self.calls, [self.REQUESTED])

    def test_stale_partial_with_failed_submit_also_refuses(self):
        self.write_all_partials(stale=self.REQUESTED)

        rc, _, err = self.run_main(
            ["--variant", self.REQUESTED, "--record"], {self.REQUESTED: None})

        self.assertEqual(rc, 1)
        self.assertNoRecord()
        self.assertIn(self.REFUSE_FMT.format(v=self.REQUESTED), err)

    def test_record_name_variant_is_not_written_either(self):
        self.write_all_partials()

        rc, _, err = self.run_main(
            ["--variant", self.REQUESTED, "--record", "--record-name", "record-retry.json"],
            {self.REQUESTED: None})

        self.assertEqual(rc, 1)
        self.assertNoRecord("record-retry.json")

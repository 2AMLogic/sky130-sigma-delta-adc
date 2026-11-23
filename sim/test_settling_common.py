"""Fixture tests for settling_common's record-validity gates and `request()`.
Run: python3 -I -m unittest discover -s sim -p 'test_settling*.py'

No fleet, no ngspice, no klt: every corner set here is hand-built. The gates
are what separate "simulated and failing" from "never simulated", so they are
the last thing standing between a dead fleet job and a recorded result
(issue #94). `grid_complete` counts grid points; `measurements_present`
requires a non-null `err_phase` at every one of them.

`RunVariantSet` below pins the shared multi-variant loop the same way
(issue #354): reuse, the failed-submit refusal, the `usable_fn` cache gate,
and the two `--from-partials` refusals, all against a fake `run_klt` with no
bench bound -- the four `test_run_*.py` suites still assert the rule through
their own runners.
"""
import contextlib
import io
import json
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

import settling_common as sc
import runner_test_common as rtc

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
    return rtc.unmeasured(sc.KEYS, status=status, diagnostics=diagnostics)


def corner_set(n=sc.GRID_POINTS, factory=measured, **kwargs):
    return rtc.corner_set(CORNER_IDS, n, factory, **kwargs)


def call(fn, *args, **kw):
    return rtc.call(fn, *args, **kw)


def record_request_pins(node, path="$"):
    """Yield (path, digest) for every `request_sha256` pin in a parsed record.

    The pin is committed in several shapes: a plain string at the record root
    (`ota-settling`, `ota-gain`), a variant->digest map (`integrator-noise`),
    or per-variant strings under `variants` (`comparator-decision`,
    `integrator-ci`, `integrator-settling`). Subtrees under `batch_receipt`
    are skipped: klt echoes there the sha256 of the request payload the fleet
    received, which is a receipt of submission, not a pin on a committed
    request file.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "batch_receipt":
                continue
            if key == "request_sha256":
                if isinstance(value, str):
                    yield path, value
                elif isinstance(value, dict):
                    for variant, digest in value.items():
                        if isinstance(digest, str):
                            yield f"{path}[{variant}]", digest
                continue
            yield from record_request_pins(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from record_request_pins(item, f"{path}[{i}]")


def unresolved_request_pins(bench, record):
    """The record's pins that no committed `request*.json` in `bench` hashes to."""
    committed = {sc.sha256(p) for p in sorted(bench.glob("request*.json"))}
    return [(path, digest) for path, digest in record_request_pins(record)
            if digest not in committed]


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


class NgspiceVersion(unittest.TestCase):
    """`ngspice_version()`'s branches, with no ngspice on the path.

    `subprocess.run` raising is the assertion: a log hit must never shell out,
    and every miss must fall back to `ngspice -v` exactly as #145 shipped it.
    """

    def test_log_hit_answers_from_the_log_without_spawning_ngspice(self):
        boom = mock.Mock(side_effect=AssertionError("log hit must not run ngspice -v"))
        with mock.patch.object(sc.subprocess, "run", boom):
            self.assertEqual(sc.ngspice_version("banner\nngspice-46\nmore"), "ngspice-46")

    def test_empty_log_falls_back_to_ngspice_v(self):
        out = mock.Mock(stdout="warning\nngspice-44 compiled for ...")
        with mock.patch.object(sc.subprocess, "run", return_value=out) as run:
            self.assertEqual(sc.ngspice_version(""), "ngspice-44")
            self.assertEqual(run.call_args[0][0], ["ngspice", "-v"])

    def test_tokenless_log_falls_back_to_ngspice_v(self):
        out = mock.Mock(stdout="ngspice-44: circuit level 1.6.0")
        with mock.patch.object(sc.subprocess, "run", return_value=out):
            self.assertEqual(sc.ngspice_version("log without a version token"),
                             "ngspice-44")

    def test_no_version_anywhere_returns_unknown(self):
        out = mock.Mock(stdout="")
        with mock.patch.object(sc.subprocess, "run", return_value=out):
            self.assertEqual(sc.ngspice_version("no token here"), "unknown")

    def test_no_argument_still_shells_out(self):
        out = mock.Mock(stdout="warning\nngspice-44 compiled for ...")
        with mock.patch.object(sc.subprocess, "run", return_value=out) as run:
            self.assertEqual(sc.ngspice_version(), "ngspice-44")
            self.assertEqual(run.call_args[0][0], ["ngspice", "-v"])


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
        import json
        import pathlib
        here = pathlib.Path(__file__).resolve().parent / bench
        mod = rtc.load_runner(f"{bench}_mk", here / "make_request.py")
        on_disk, rebuilt = {}, {}
        for p in sorted(here.glob("request*.json")):
            on_disk[p.name] = json.loads(p.read_text())
            name = p.stem.replace("request_", "", 1)
            if bench == "integrator-settling":
                rebuilt[p.name] = sc.request(f"integrator_settling_{name}.cir", mod.MEASUREMENTS,
                                             mod.T_END, timeout_s=60, poll_timeout_s=7200)
            else:
                if name.startswith("mc_"):
                    rebuilt[p.name] = mod.mc_request(name.replace("mc_", "", 1))
                elif name.startswith("i106_"):
                    rebuilt[p.name] = mod.i106_request(name.replace("i106_", "", 1))
                else:
                    rebuilt[p.name] = mod.nominal_request(name)
        self.assertTrue(on_disk, f"no committed requests found for {bench}")
        return on_disk, rebuilt


class RecordRequestPinsResolve(unittest.TestCase):
    """Every committed record's request_sha256 pin resolves to a committed request.

    A record pins the sha256 of the request that produced it, so committing a
    regenerated `request*.json` — or editing one a record pins — silently
    orphans the recorded result from the request that produced it. This is the
    repo-wide form of the invariant `CommittedRequestsAreUnmoved` checks for
    the two rebuildable benches, and the only guard over
    `sim/ota-settling/request.json`, which by design cannot rebuild
    identically: it predates 6df6862's `capacity_wait_s` emission and both of
    its records pin it as committed (issue #192).

    Deliberately not pre-solved: the legitimate future path (regenerate the
    request, commit it, add a new record) fails this guard too, because the
    older records then pin a digest no committed file carries any more. That
    failure is correct — it forces the retention decision for the superseded
    request text; no archive convention exists yet.
    """

    def test_every_committed_record_pin_resolves(self):
        import json
        import pathlib
        here = pathlib.Path(__file__).resolve().parent
        orphaned = []
        covered = set()
        for rec in sorted(here.glob("*/record*.json")):
            record = json.loads(rec.read_text())
            pins = list(record_request_pins(record))
            if pins:
                covered.add(rec.parent.name)
            for path, digest in unresolved_request_pins(rec.parent, record):
                orphaned.append(f"{rec.relative_to(here)}: {path} pins {digest}")
        self.assertEqual(
            orphaned, [],
            "committed records pin request_sha256 digests that no committed"
            " request*.json in the same bench directory hashes to — each is"
            " orphaned from the request that produced it (issue #192):\n  "
            + "\n  ".join(orphaned))
        self.assertIn("ota-settling", covered,
                      "no ota-settling record was seen; the guard this issue"
                      " exists for covers nothing")

    def test_a_bench_without_request_files_does_not_pass_vacuously(self):
        import json
        import tempfile
        import pathlib
        with tempfile.TemporaryDirectory() as tmp:
            bench = pathlib.Path(tmp)
            record = {"request_sha256": "ab" * 32}
            (bench / "record.json").write_text(json.dumps(record))
            self.assertTrue(unresolved_request_pins(bench, record),
                            "a pin with no committed request*.json to resolve"
                            " against must be reported, not skipped")

    def test_a_record_without_a_pin_is_skipped(self):
        self.assertEqual(list(record_request_pins(
            {"summary": {}, "corners": [{"status": "pass"}]})), [])

    def test_batch_receipt_digests_are_not_treated_as_pins(self):
        record = {"batch_receipt": {"request_sha256": "cd" * 32,
                                    "job_id": "klt-sim-x"},
                  "request_sha256": "ab" * 32}
        self.assertEqual(list(record_request_pins(record)), [("$", "ab" * 32)])

    def test_the_map_form_is_walked_per_variant(self):
        record = {"request_sha256": {"amp": "ab" * 32, "ampq": "cd" * 32}}
        self.assertEqual(list(record_request_pins(record)),
                         [("$[amp]", "ab" * 32), ("$[ampq]", "cd" * 32)])


class RunVariantSet(unittest.TestCase):
    """The shared multi-variant loop (issue #354), pinned with no bench bound.

    `run_variant_set`/`run_probe`/`refuse_missing_variants`/
    `refuse_from_partials_conflicts` are what the four multi-variant runners
    call; these tests hold the loop's own rules (the issue #94 failed-submit
    refusal, reuse for unrequested variants, the `usable_fn` cache gate and
    the `--from-partials` refusals) so the per-bench suites only have to pin
    what their bench adds.
    """

    VARIANTS = ("a", "b")

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-variant-set-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.partials = self.tmp / ".partials"
        self.calls, self.kwargs = [], []

    # ---- the fake bench ------------------------------------------------

    def fake_run_klt(self, submits):
        def run_klt(request_path, probe, tmpdir, tag, probe_path, **kw):
            self.calls.append(tag)
            self.kwargs.append(kw)
            return submits.get(tag)
        return run_klt

    def hooks(self):
        return dict(
            request_fn=lambda v: self.tmp / f"request_{v}.json",
            probe_request_fn=lambda v: self.tmp / f"probe_request_{v}.json",
            tag_fn=lambda v: v,
            partial_fn=lambda v: self.partials / f"{v}.json",
            shas_fn=lambda v: {"request_sha256": v, "deck_sha256": v},
            summarize_fn=lambda v, c: {"corner_count": len(c)})

    @staticmethod
    def report(job="job-1"):
        return {"status": "pass",
                "environment": {"engine_version": "ngspice-47",
                                "engine_host": "fleet-node-1",
                                "remote": {"job_id": job}}}

    @staticmethod
    def corners(n=2):
        return {f"c{i}": {"status": "pass", "err_phase": 1e-5, "diagnostics": []}
                for i in range(n)}

    def run_set(self, run, submits, want=VARIANTS, err=None, out=None, **kw):
        """run_variant_set with stdout/stderr captured; returns (results, out, err)."""
        out, err = out or io.StringIO(), err or io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            results = sc.run_variant_set(
                want, run, self.tmp / "work",
                run_klt_fn=self.fake_run_klt(submits),
                artifacts_dir=None, **self.hooks(), **kw)
        return results, out.getvalue(), err.getvalue()

    def write_partial(self, v, **over):
        d = {"summary": {"corner_count": 2}, "corners": self.corners(),
             "pass": True, "ngspice": "ngspice-47", "engine_host": "fleet-node-0",
             "remote": {"job_id": f"job-earlier-{v}"},
             "request_sha256": v, "deck_sha256": v}
        d.update(over)
        sc.save_partial(self.partials / f"{v}.json", d)
        return d

    # ---- reuse and the issue #94 rule ----------------------------------

    def test_a_variant_not_requested_is_reused_from_its_partial(self):
        self.write_partial("a")

        results, out, _ = self.run_set(("b",), {"b": (self.report(), self.corners())})

        self.assertEqual(self.calls, ["b"], "a must not be re-submitted")
        self.assertIn("a: reusing a.json", out)
        self.assertEqual(results["a"]["remote"], {"job_id": "job-earlier-a"})
        self.assertEqual(results["b"]["remote"], {"job_id": "job-1"})
        self.assertTrue((self.partials / "b.json").exists(),
                        "a fresh submit is cached")

    def test_a_failed_submit_is_refused_never_backfilled_from_partials(self):
        before = json.dumps(self.write_partial("a"))

        results, _, err = self.run_set(("a",), {"a": None})

        self.assertNotIn("a", results)
        self.assertIn("a: no usable report", err)
        self.assertIn("not falling back to a local grid or to .partials/", err)
        self.assertEqual(json.loads((self.partials / "a.json").read_text()),
                         json.loads(before), "the old partial is left on disk")
        verdict, rerr = call(sc.refuse_missing_variants, self.VARIANTS, results)
        self.assertTrue(verdict)
        self.assertIn("REFUSE: no result for a", rerr)

    def test_a_stale_partial_is_not_reused_and_refuses_the_set(self):
        self.write_partial("a", deck_sha256="0" * 64)

        results, _, err = self.run_set(("b",), {"b": (self.report(), self.corners())})

        self.assertNotIn("a", results)
        self.assertIn("ignoring stale .partials/a.json", err)
        verdict, rerr = call(sc.refuse_missing_variants, self.VARIANTS, results)
        self.assertTrue(verdict)
        self.assertIn("REFUSE: no result for a", rerr)

    # ---- the usable_fn cache gate ---------------------------------------

    def test_usable_fn_skips_the_cache_but_keeps_the_result(self):
        results, _, err = self.run_set(
            ("b",), {"b": (self.report(), self.corners())},
            usable_fn=lambda v, c: False)

        self.assertIn("b", results, "an unusable result is still reported")
        self.assertFalse((self.partials / "b.json").exists(),
                         "an unusable result must not be cached")
        self.assertIn("not cached in .partials/", err)

    def test_usable_fn_does_not_shadow_a_good_partial(self):
        """The gate runs on the fresh submit only; a reused partial passes as-is."""
        self.write_partial("a")

        results, out, _ = self.run_set(
            ("b",), {"b": (self.report(), self.corners())},
            usable_fn=lambda v, c: v != "b")

        self.assertIn("a: reusing a.json", out)
        self.assertIn("a", results)

    # ---- the probe ------------------------------------------------------

    def test_run_probe_refuses_with_exit_one_wording_when_submit_fails(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            res = sc.run_probe(
                "a", self.tmp / "work", run_klt_fn=self.fake_run_klt({}),
                artifacts_dir=None, **self.hooks())

        self.assertIsNone(res)
        self.assertIn("a: no usable report", err.getvalue())
        self.assertIn("REFUSE: no result for the a probe; nothing printed.",
                      err.getvalue())
        self.assertFalse((self.partials / "a.json").exists(),
                         "a probe must not write a partial")

    def test_run_probe_assembles_the_result_and_prints_no_partial(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            res = sc.run_probe(
                "a", self.tmp / "work",
                run_klt_fn=self.fake_run_klt({"a": (self.report(), self.corners())}),
                artifacts_dir=None, status_line=True, **self.hooks())

        self.assertEqual(res["corners"], self.corners())
        self.assertIn('"status": "pass"', out.getvalue())
        self.assertFalse((self.partials / "a.json").exists())

    # ---- --from-partials -------------------------------------------------

    def test_from_partials_conflicts_refuse_with_the_tested_wording(self):
        verdict, err = call(sc.refuse_from_partials_conflicts,
                            probe=True, variant=False)
        self.assertTrue(verdict)
        self.assertIn("--from-partials", err)
        self.assertIn("--probe has no meaning", err)

        verdict, err = call(sc.refuse_from_partials_conflicts, variant=True)
        self.assertTrue(verdict)
        self.assertIn("--variant has no meaning", err,
                      "the wording test_run_ci.py asserts")

        verdict, err = call(sc.refuse_from_partials_conflicts,
                            probe=False, variant=False, resume=False)
        self.assertFalse(verdict)
        self.assertEqual(err, "")

    def test_from_partials_run_reuses_only_and_says_cached_partial(self):
        for v in self.VARIANTS:
            self.write_partial(v)

        results, out, err = self.run_set((), {})

        self.assertEqual(self.calls, [], "nothing is submitted")
        self.assertEqual(set(results), set(self.VARIANTS))
        self.assertFalse(sc.refuse_missing_variants(
            self.VARIANTS, results, from_partials=True))

    def test_from_partials_missing_variant_says_no_cached_partial(self):
        self.write_partial("a")

        results, _, err = self.run_set((), {})
        self.assertNotIn("b", results)

        verdict, err2 = call(sc.refuse_missing_variants, self.VARIANTS, results,
                             from_partials=True)
        self.assertTrue(verdict)
        self.assertIn("no cached partial for b", err2)
        self.assertNotIn("no result for b", err2)

    # ---- the assembled result --------------------------------------------

    def test_submit_variant_assembles_the_common_result_dict(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            res = sc.submit_variant(
                self.fake_run_klt({"t": (self.report(job="j"), self.corners())}),
                self.tmp / "request_t.json", self.tmp / "work", "t",
                self.tmp / "probe_t.json",
                summarize_fn=lambda v, c: {"corner_count": len(c)},
                shas={"request_sha256": "r", "deck_sha256": "d"},
                env_fields=lambda e: {"monte_carlo_env": e.get("monte_carlo")})

        self.assertEqual(res["summary"], {"corner_count": 2})
        self.assertEqual(res["pass"], True)
        self.assertEqual(res["ngspice"], "ngspice-47")
        self.assertEqual(res["engine_host"], "fleet-node-1")
        self.assertEqual(res["remote"], {"job_id": "j"})
        self.assertEqual(res["monte_carlo_env"], None)
        self.assertEqual(res["request_sha256"], "r")
        self.assertEqual(res["deck_sha256"], "d")
        self.assertEqual(self.kwargs, [{"artifacts_dir": None}])

    def test_status_line_merges_the_report_status_into_the_summary(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sc.submit_variant(
                self.fake_run_klt({"t": (self.report(), self.corners())}),
                self.tmp / "r.json", self.tmp / "work", "t", self.tmp / "p.json",
                summarize_fn=lambda v, c: {"corner_count": len(c)},
                shas={}, status_line=True)
        self.assertIn('"status": "pass"', out.getvalue())
        self.assertTrue(out.getvalue().startswith("t "))

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sc.submit_variant(
                self.fake_run_klt({"t": (self.report(), self.corners())}),
                self.tmp / "r.json", self.tmp / "work", "t", self.tmp / "p.json",
                summarize_fn=lambda v, c: {"corner_count": len(c)},
                shas={})
        self.assertNotIn('"status"', out.getvalue())


if __name__ == "__main__":
    unittest.main()

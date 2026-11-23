#!/usr/bin/env python3
"""Grammar tests for attestation/item8_envelope.py.

Fixtures only: these mutate a copy of the committed
`measurements/characterization.md` in memory and assert what the parser accepts
and rejects. No EDA tools, no network, no writes.

The cases that matter are the ones guarding the `declared-gap` status (#131): a
limit no further run can close is cited to the ratified record that declares it,
never to an issue that could never close it, and it may not read as evidence.

The verify_issues classes (#218) pin the three-way gh classification (open /
closed / could-not-run) and main()'s 0/1/3 exit mapping with a stubbed
`subprocess.run` -- offline and tool-free, so no gh is reachable or invoked,
and the suite passes with gh absent from PATH entirely.
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("item8_envelope", ROOT / "attestation" / "item8_envelope.py")
env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(env)

REPORT = (ROOT / "measurements" / "characterization.md").read_text()
GAP_ROW_PREFIX = "| Fmax at the other 35 DR-002 corners |"
RECORD = "spec/decisions/DR-008-digital-timing-corners.md"


def gap_row(text: str) -> str:
    """The committed declared-gap row, verbatim."""
    for line in text.splitlines():
        if line.startswith(GAP_ROW_PREFIX):
            return line
    raise AssertionError(f"no row starting {GAP_ROW_PREFIX!r} in the report")


def with_gap_row(replacement: str) -> str:
    return REPORT.replace(gap_row(REPORT), replacement)


def errors(text: str) -> list[str]:
    return env.parse(text)[4]


def only_gap_errors(text: str) -> list[str]:
    """Errors naming the declared-gap row, so an unrelated report edit cannot pass a test."""
    return [e for e in errors(text) if "other 35 DR-002 corners" in e]


class CommittedReport(unittest.TestCase):
    def test_report_parses_clean(self):
        self.assertEqual([], errors(REPORT))

    def test_declared_gap_row_is_a_gap_citing_the_record(self):
        _, dec, cited, issues, _ = env.parse(REPORT)
        gaps = [d for d in dec if d["declared_gap"]]
        self.assertEqual(1, len(gaps), "expected exactly one declared gap")
        gap = gaps[0]
        self.assertFalse(gap["evidenced"], "a declared gap is never evidenced")
        self.assertEqual([RECORD], gap["records"])
        self.assertEqual([], gap["issues"], "a declared gap names no closing issue")
        self.assertIn(RECORD, cited, "the record must be bound into the envelope by sha256")
        self.assertNotIn("131", issues, "the declared gap must not re-park on #131")


class PassRule(unittest.TestCase):
    """A declared gap must not hold the envelope at `fail`; a pending row must."""

    EVIDENCED_ROW = {"verdict": "evidenced"}
    PENDING_ROW = {"verdict": "pending"}
    EVIDENCED_QTY = {"evidenced": True, "declared_gap": False}
    GAP_QTY = {"evidenced": False, "declared_gap": True}
    PENDING_QTY = {"evidenced": False, "declared_gap": False}

    def test_all_evidenced_passes(self):
        self.assertTrue(env.is_met([self.EVIDENCED_ROW], [self.EVIDENCED_QTY]))

    def test_a_declared_gap_still_passes(self):
        self.assertTrue(env.is_met([self.EVIDENCED_ROW], [self.EVIDENCED_QTY, self.GAP_QTY]))

    def test_a_pending_quantity_fails(self):
        self.assertFalse(env.is_met([self.EVIDENCED_ROW], [self.EVIDENCED_QTY, self.PENDING_QTY]))

    def test_a_pending_spec_row_fails_even_with_every_quantity_settled(self):
        self.assertFalse(env.is_met([self.EVIDENCED_ROW, self.PENDING_ROW], [self.GAP_QTY]))

    def test_todays_fail_is_owed_work_not_the_gap(self):
        """The committed report fails because work is still owed, not because of the gap."""
        rows, dec, _, _, _ = env.parse(REPORT)
        self.assertFalse(env.is_met(rows, dec))
        owed = ([r["row"] for r in rows if r["verdict"] != "evidenced"]
                + [d["quantity"] for d in dec if not (d["evidenced"] or d["declared_gap"])])
        self.assertTrue(owed, "something must still be owed for the fail to be explained")
        settled = [dict(d, evidenced=True) if not d["declared_gap"] else d for d in dec]
        self.assertTrue(env.is_met([dict(r, verdict="evidenced") for r in rows], settled),
                        "with the owed work evidenced, the declared gap alone must not fail it")

    def test_envelope_is_committed_and_reproduces(self):
        envelope, errs, _ = env.build()
        self.assertEqual([], errs)
        committed = (ROOT / "attestation" / "item8-envelope.json").read_text()
        self.assertEqual(json.dumps(envelope, indent=2) + "\n", committed,
                         "regenerate with 'python3 -I attestation/item8_envelope.py'")
        self.assertEqual("fail", envelope["status"])


class DeclaredGapGrammar(unittest.TestCase):
    def test_rejects_declared_gap_with_no_record(self):
        bad = f"{GAP_ROW_PREFIX} none | the points | none | declared-gap: the library ships nothing |"
        self.assertTrue(any("must cite the ratified record" in e for e in only_gap_errors(with_gap_row(bad))))

    def test_rejects_declared_gap_citing_a_non_record_file(self):
        bad = f"{GAP_ROW_PREFIX} none | the points | none | declared-gap per `layout/README.md` |"
        self.assertTrue(any("must cite the ratified record" in e for e in only_gap_errors(with_gap_row(bad))))

    def test_rejects_declared_gap_citing_a_record_that_does_not_exist(self):
        bad = (f"{GAP_ROW_PREFIX} none | the points | none | declared-gap per "
               "`spec/decisions/DR-099-not-written.md` |")
        self.assertTrue(any("does not exist" in e for e in only_gap_errors(with_gap_row(bad))))

    def test_rejects_declared_gap_that_also_cites_evidence(self):
        bad = (f"{GAP_ROW_PREFIX} none | the points | "
               f"`layout/digital/sta-decimator.report.json` | declared-gap per `{RECORD}` |")
        self.assertTrue(any("cites no evidence" in e for e in only_gap_errors(with_gap_row(bad))))

    def test_rejects_declared_gap_that_also_names_an_issue(self):
        """Re-parking an unclosable gap on an issue is the failure DR-008 exists to end."""
        bad = (f"{GAP_ROW_PREFIX} none | the points | none | "
               f"declared-gap per `{RECORD}`, tracked at #131 |")
        self.assertTrue(any("names no issue" in e for e in only_gap_errors(with_gap_row(bad))),
                        "a declared gap citing an issue must be rejected, not silently accepted")

    def test_rejects_an_unknown_status_prefix(self):
        bad = f"{GAP_ROW_PREFIX} none | the points | none | gap, see DR-008 |"
        errs = only_gap_errors(with_gap_row(bad))
        self.assertTrue(any("status must start one of" in e for e in errs))
        self.assertFalse(any("names no issue" in e for e in errs),
                         "an unknown prefix is one complaint, not two")

    def test_still_rejects_a_pending_row_with_no_issue(self):
        bad = f"{GAP_ROW_PREFIX} none | the points | none | pending: nothing yet |"
        self.assertTrue(any("names no issue" in e for e in only_gap_errors(with_gap_row(bad))))

    def test_accepts_a_pending_row_that_names_an_issue(self):
        ok = f"{GAP_ROW_PREFIX} none | the points | none | pending (#33): not yet run |"
        self.assertEqual([], only_gap_errors(with_gap_row(ok)))


def gh_result(returncode=0, stdout="", stderr=""):
    """The CompletedProcess a stubbed `gh issue view` returns."""
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def stub_gh(outcomes):
    """A `subprocess.run` replacement mapping issue number -> gh_result.

    `verify_issues()` asks `gh issue view <n> -R <repo> --json state --jq
    .state`; the issue number is cmd[3]. Every call is recorded so tests can
    assert what was actually asked of gh. Offline: no gh is reachable or
    invoked, so the suite needs no token and no network.
    """
    calls = []

    def run(cmd, *args, **kwargs):
        calls.append(cmd)
        return outcomes[cmd[3]]

    run.calls = calls
    return run


class VerifyIssuesClassification(unittest.TestCase):
    """verify_issues()'s three-way gh classification (#218), pinned offline.

    The four rows -- (rc 0, OPEN) verified; (rc 0, CLOSED) genuinely closed;
    (rc != 0) could-not-run; (rc 0, anything else) could-not-run -- plus the
    mixed case and the edges. The exit codes those rows map to live in
    main() and are pinned by MainExitMapping below.
    """

    def verify(self, outcomes, issues):
        stub = stub_gh(outcomes)
        with mock.patch.object(env.subprocess, "run", stub):
            bad, could_not_run = env.verify_issues(issues)
        return bad, could_not_run, stub.calls

    def test_open_issue_lands_in_neither_list(self):
        bad, could_not_run, calls = self.verify({"33": gh_result(stdout="OPEN\n")}, {"33"})
        self.assertEqual([], bad)
        self.assertEqual([], could_not_run)
        self.assertEqual([["gh", "issue", "view", "33", "-R", env.GH_REPO,
                           "--json", "state", "--jq", ".state"]], calls,
                         "the lookup stays pinned to this repo (-R), never the cwd remote")

    def test_closed_issue_is_bad_only(self):
        bad, could_not_run, _ = self.verify({"33": gh_result(stdout="CLOSED\n")}, {"33"})
        self.assertEqual(["#33 is not an open issue (CLOSED)"], bad)
        self.assertEqual([], could_not_run)

    def test_gh_failure_is_could_not_run_only(self):
        bad, could_not_run, _ = self.verify(
            {"33": gh_result(returncode=1, stderr="gh: authentication failed")}, {"33"})
        self.assertEqual([], bad, "a gh failure is never a closure")
        self.assertEqual(["#33: gh issue view failed (gh: authentication failed)"],
                         could_not_run)

    def test_unexpected_stdout_is_could_not_run_only(self):
        bad, could_not_run, _ = self.verify({"33": gh_result(stdout="weird")}, {"33"})
        self.assertEqual([], bad)
        self.assertEqual(["#33: unexpected gh output 'weird'"], could_not_run)

    def test_mixed_closed_and_failure_lands_one_in_each_list(self):
        bad, could_not_run, _ = self.verify(
            {"33": gh_result(stdout="CLOSED\n"),
             "34": gh_result(returncode=4, stderr="gh: rate limit spent")},
            {"33", "34"})
        self.assertEqual(["#33 is not an open issue (CLOSED)"], bad)
        self.assertEqual(["#34: gh issue view failed (gh: rate limit spent)"],
                         could_not_run)

    def test_empty_issue_set_asks_gh_nothing(self):
        bad, could_not_run, calls = self.verify({}, set())
        self.assertEqual([], bad)
        self.assertEqual([], could_not_run)
        self.assertEqual([], calls)

    def test_failure_detail_is_the_last_stderr_line(self):
        _, could_not_run, _ = self.verify(
            {"33": gh_result(returncode=1, stderr="first\nsecond\n")}, {"33"})
        self.assertEqual(["#33: gh issue view failed (second)"], could_not_run)

    def test_failure_with_no_output_at_all_says_gh_failed(self):
        _, could_not_run, _ = self.verify({"33": gh_result(returncode=1)}, {"33"})
        self.assertEqual(["#33: gh issue view failed (gh failed)"], could_not_run)

    def test_lowercase_open_is_not_silently_accepted(self):
        bad, could_not_run, _ = self.verify({"33": gh_result(stdout="  open\n")}, {"33"})
        self.assertEqual([], bad)
        self.assertEqual(["#33: unexpected gh output 'open'"], could_not_run,
                         "only exact 'OPEN' is an open issue; anything else is could-not-run")


class NoFalseClosureInvariant(unittest.TestCase):
    """The regression this suite exists to bite on (#187, #218).

    A `gh` that cannot answer -- auth failure, rate limit, network, or output
    it does not recognize -- must never read as a closed citation: that is
    the false finding the three-way classification exists to remove. Fold
    `could_not_run` back into `bad`, as the pre-#213 code did, and these
    assertions fail loudly.
    """

    def test_every_could_not_run_mode_leaves_bad_empty(self):
        outcomes = {
            "33": gh_result(returncode=1, stderr="gh: authentication failed"),
            "34": gh_result(stdout="weird"),
            "35": gh_result(returncode=4),
        }
        stub = stub_gh(outcomes)
        with mock.patch.object(env.subprocess, "run", stub):
            bad, could_not_run = env.verify_issues({"33", "34", "35"})
        self.assertEqual([], bad, "no gh failure may be reported as a closure")
        self.assertEqual(["#33", "#34", "#35"],
                         [c.split(":")[0] for c in could_not_run])


class MainExitMapping(unittest.TestCase):
    """main()'s exit mapping: 0 verified, 1 a genuinely closed citation,
    3 could-not-run -- which wins the exit code even when a closure was also
    found, while the closure is still printed (#218).

    build() is pinned to a clean result and ROOT/ENVELOPE to a temp
    directory, so live repo state can contribute neither errors nor writes;
    verify_issues() is patched because its classification is pinned above.
    """

    def run_main(self, bad, could_not_run):
        out, err = io.StringIO(), io.StringIO()
        envelope = {"schema_version": 1, "status": "fail", "summary": "pinned by test"}
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(env, "build", return_value=(envelope, [], {"33", "34"})), \
                 mock.patch.object(env, "verify_issues", return_value=(bad, could_not_run)), \
                 mock.patch.object(env, "ROOT", Path(d)), \
                 mock.patch.object(env, "ENVELOPE", "envelope.json"), \
                 mock.patch.object(sys, "argv", ["item8_envelope.py", "--verify-issues"]), \
                 contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = env.main()
        return rc, out.getvalue(), err.getvalue()

    def test_all_open_exits_0(self):
        rc, _, err = self.run_main([], [])
        self.assertEqual(0, rc)
        self.assertEqual("", err)

    def test_a_genuine_closure_exits_1(self):
        rc, _, err = self.run_main(["#33 is not an open issue (CLOSED)"], [])
        self.assertEqual(1, rc)
        self.assertIn("error: #33 is not an open issue (CLOSED)", err)
        self.assertNotIn("could not verify", err)

    def test_could_not_run_alone_exits_3(self):
        rc, _, err = self.run_main([], ["#34: gh issue view failed (gh failed)"])
        self.assertEqual(3, rc)
        self.assertIn("could not verify cited issues", err)
        self.assertNotIn("is not an open issue", err,
                         "a gh failure names no closure")

    def test_could_not_run_beats_the_closure_for_the_exit_code(self):
        rc, _, err = self.run_main(
            ["#33 is not an open issue (CLOSED)"],
            ["#34: gh issue view failed (gh failed)"])
        self.assertEqual(3, rc, "could-not-run wins the exit code, not the closure")
        self.assertIn("error: #33 is not an open issue (CLOSED)", err,
                      "the closure is still printed, not swallowed")
        self.assertIn("could not verify cited issues", err)
        self.assertIn("  #34: gh issue view failed (gh failed)", err)


class GhLaunchFailure(unittest.TestCase):
    """A gh that cannot start is exit 3, never a traceback (#328).

    Runs the script itself with `sys.executable` under a PATH we control, so
    the coverage is offline: no gh is reachable and none is invoked.
    """

    def run_checker(self, path_dir: Path, *flags: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-I", str(ROOT / "attestation" / "item8_envelope.py"), *flags],
            capture_output=True, text=True, cwd=ROOT,
            env=dict(os.environ, PATH=str(path_dir)))

    def assert_could_not_start(self, proc: subprocess.CompletedProcess, why: str):
        self.assertEqual(3, proc.returncode, proc.stderr)
        self.assertIn("could not start gh", proc.stderr)
        self.assertIn(why, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertNotIn("is not an open issue", proc.stderr,
                         "a launch failure must never read as a closed citation")
        self.assertEqual(1, proc.stderr.count("could not start gh"),
                         "one launch failure stops further lookups for that invocation")

    def test_missing_gh_exits_3_with_a_plain_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            proc = self.run_checker(Path(d), "--check", "--verify-issues")
        self.assert_could_not_start(proc, "No such file or directory")

    def test_non_executable_gh_exits_3_with_a_plain_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            gh = Path(d) / "gh"
            gh.write_text("#!/bin/sh\nexit 4\n")
            gh.chmod(0o644)
            proc = self.run_checker(Path(d), "--check", "--verify-issues")
        self.assert_could_not_start(proc, "Permission denied")

    def test_plain_check_needs_no_gh(self):
        with tempfile.TemporaryDirectory() as d:
            proc = self.run_checker(Path(d), "--check")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("reproduces", proc.stdout)


if __name__ == "__main__":
    unittest.main()

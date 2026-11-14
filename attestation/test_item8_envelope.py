#!/usr/bin/env python3
"""Grammar tests for attestation/item8_envelope.py.

Fixtures only: these mutate a copy of the committed
`measurements/characterization.md` in memory and assert what the parser accepts
and rejects. No EDA tools, no network, no writes.

The cases that matter are the ones guarding the `declared-gap` status (#131): a
limit no further run can close is cited to the ratified record that declares it,
never to an issue that could never close it, and it may not read as evidence.
"""
import importlib.util
import json
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()

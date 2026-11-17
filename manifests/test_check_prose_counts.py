#!/usr/bin/env python3
"""Fixtures for the prose T1-count invariant (issue #221).

Covers the behaviours the CI step relies on:

  * a doc whose count sentence equals the record's arithmetic passes;
  * a stale sentence fails, naming the found sentence and the record's
    counts -- the defect this issue fixes in ROADMAP.md;
  * several sentences in one doc are each checked;
  * a doc with no count sentence asserts nothing -- README.md gains its
    first one with PR #180, and the guard must tolerate the tree before and
    after;
  * a sentence the Markdown wraps across lines is still found, both when it
    matches and when it disagrees;
  * the "and" separator README.md commits ("10 met, 1 not applicable and
    11 unmet") is asserted like the comma form -- rewording the separator
    cannot hide a stale count;
  * hyphenated ("not-applicable") and differently-cased spellings are still
    matched and still asserted;
  * a doc that cannot be read is a violation, not a traceback.

Plus the record edge cases: a malformed record (a top level that is not an
object, missing or non-integer `t1_*` fields, or met + not_applicable
exceeding the item count) is a check error, not a crash; `main()` reports
it as one `::error` annotation and exits 1; and the committed tree itself
satisfies the invariant.

Run directly:  python3 -I -m unittest discover -s manifests -p 'test_check_prose_counts.py'
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import check_prose_counts as cpc

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMITTED_RECORD = REPO_ROOT / "manifests" / "sky130-sigma-delta-adc.signoff.json"


def sentence(met: int, na: int, unmet: int) -> str:
    return f"{met} met, {na} not applicable, {unmet} unmet"


def and_sentence(met: int, na: int, unmet: int) -> str:
    """README.md's committed separator: "and" before the unmet count."""
    return f"{met} met, {na} not applicable and {unmet} unmet"


class FixtureTree(unittest.TestCase):
    """A temporary repo root mirroring the committed layout.

    The record sits at `<tmp>/manifests/record.json`, so the prose docs
    resolve against `<tmp>` exactly as README.md and ROADMAP.md resolve
    against the repository root.
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write_record(
        self, total: int = 22, met: int = 10, na: int = 1
    ) -> Path:
        """Write a well-formed record; unmet is the arithmetic remainder."""
        path = self.root / "manifests" / "record.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "block": "fixture-block",
            "kind": "mixed-signal",
            "t1_item_count": total,
            "t1_met_count": met,
            "t1_not_applicable_count": na,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def write_record_raw(self, payload: object) -> Path:
        """Write a record verbatim, for malformed-record cases."""
        path = self.root / "manifests" / "record.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def write_doc(self, name: str, text: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def violations(
        self, record: Path, doc_name: str, text: str | None = None
    ) -> list[str]:
        if text is not None:
            self.write_doc(doc_name, text)
        return cpc.violations_in(record.parent.parent / doc_name, cpc.expected_counts(record))


class CountArithmeticTests(FixtureTree):
    """The unmet count is the remainder, never a stored field."""

    def test_unmet_is_the_remainder(self) -> None:
        record = self.write_record(total=5, met=2, na=1)
        self.assertEqual(cpc.expected_counts(record), (2, 1, 2))

    def test_matching_sentence_passes(self) -> None:
        record = self.write_record()
        text = f"Grades 22 rows: **{sentence(10, 1, 11)}.**"
        self.assertEqual(self.violations(record, "ROADMAP.md", text), [])

    def test_stale_sentence_fails_naming_both_triples(self) -> None:
        record = self.write_record()
        text = f"**{sentence(9, 1, 12)}.**"
        violations = self.violations(record, "ROADMAP.md", text)
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("9 met, 1 not applicable, 12 unmet", violations[0])
        self.assertIn("10 met, 1 not applicable, 11 unmet", violations[0])

    def test_every_sentence_is_checked(self) -> None:
        record = self.write_record()
        text = (
            f"First: {sentence(10, 1, 11)}. Second: {sentence(9, 1, 12)}. "
            f"Third: {sentence(8, 2, 12)}."
        )
        violations = self.violations(record, "ROADMAP.md", text)
        self.assertEqual(len(violations), 2, violations)
        self.assertIn("9 met", violations[0])
        self.assertIn("8 met", violations[1])


class SeparatorTests(FixtureTree):
    """The "and" form README.md commits is asserted like the comma form."""

    def test_readme_and_form_matching_passes(self) -> None:
        record = self.write_record()
        text = (
            "The committed verdict grades 22 T1 rows as "
            f"**{and_sentence(10, 1, 11)}**; the per-item state is in the record."
        )
        self.assertEqual(self.violations(record, "README.md", text), [])

    def test_readme_and_form_stale_fails(self) -> None:
        # Rewording the separator must not hide a stale count (issue #221:
        # the sentence drifted once inside a single review cycle).
        record = self.write_record()
        text = f"Grades as **{and_sentence(9, 1, 12)}**."
        violations = self.violations(record, "README.md", text)
        self.assertEqual(len(violations), 1, violations)
        self.assertIn(
            "9 met, 1 not applicable and 12 unmet", violations[0]
        )
        self.assertIn("10 met, 1 not applicable, 11 unmet", violations[0])

    def test_both_forms_in_one_doc_are_each_checked(self) -> None:
        record = self.write_record()
        text = (
            f"Comma form: {sentence(10, 1, 11)}. And form: "
            f"{and_sentence(9, 1, 12)}."
        )
        violations = self.violations(record, "ROADMAP.md", text)
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("9 met, 1 not applicable and 12 unmet", violations[0])


class ToleranceTests(FixtureTree):
    """Absence of a count sentence asserts nothing."""

    def test_doc_without_a_sentence_passes(self) -> None:
        # README.md pre-#180: no count sentence anywhere in the file.
        record = self.write_record()
        text = "# Block\n\nA switched-capacitor delta-sigma ADC on sky130.\n"
        self.assertEqual(self.violations(record, "README.md", text), [])

    def test_wrapped_sentence_is_still_found_when_matching(self) -> None:
        record = self.write_record()
        text = "Grades 22 rows: **10 met, 1 not\napplicable, 11\nunmet.**\n"
        self.assertEqual(self.violations(record, "ROADMAP.md", text), [])

    def test_wrapped_sentence_is_still_found_when_stale(self) -> None:
        record = self.write_record()
        text = "Grades 22 rows: **9 met, 1 not\napplicable, 12\nunmet.**\n"
        violations = self.violations(record, "ROADMAP.md", text)
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("9 met, 1 not applicable, 12 unmet", violations[0])

    def test_hyphenated_and_cased_spellings_are_still_checked(self) -> None:
        record = self.write_record()
        text = "Verdict: 9 Met, 1 Not-Applicable, 12 Unmet."
        violations = self.violations(record, "ROADMAP.md", text)
        self.assertEqual(len(violations), 1, violations)
        text = "Verdict: 10 met, 1 not-applicable, 11 unmet."
        self.assertEqual(self.violations(record, "ROADMAP.md", text), [])

    def test_unreadable_doc_is_a_violation(self) -> None:
        record = self.write_record()
        violations = cpc.violations_in(
            self.root / "README.md", cpc.expected_counts(record)
        )
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("cannot read", violations[0])


class MalformedRecordTests(FixtureTree):
    """A record the counts cannot be derived from is a check error."""

    def test_non_object_record_raises(self) -> None:
        record = self.write_record_raw([1, 2, 3])
        with self.assertRaises(ValueError):
            cpc.expected_counts(record)

    def test_missing_field_raises(self) -> None:
        record = self.write_record_raw({"block": "fixture-block"})
        with self.assertRaises(ValueError):
            cpc.expected_counts(record)

    def test_non_integer_field_raises(self) -> None:
        record = self.write_record_raw(
            {"t1_item_count": 22, "t1_met_count": "ten", "t1_not_applicable_count": 1}
        )
        with self.assertRaises(ValueError):
            cpc.expected_counts(record)

    def test_boolean_field_raises(self) -> None:
        record = self.write_record_raw(
            {"t1_item_count": 22, "t1_met_count": True, "t1_not_applicable_count": 1}
        )
        with self.assertRaises(ValueError):
            cpc.expected_counts(record)

    def test_negative_field_raises(self) -> None:
        record = self.write_record_raw(
            {"t1_item_count": 22, "t1_met_count": -1, "t1_not_applicable_count": 1}
        )
        with self.assertRaises(ValueError):
            cpc.expected_counts(record)

    def test_inconsistent_counts_raise(self) -> None:
        record = self.write_record_raw(
            {"t1_item_count": 22, "t1_met_count": 20, "t1_not_applicable_count": 5}
        )
        with self.assertRaises(ValueError):
            cpc.expected_counts(record)


class MainTests(FixtureTree):
    """The CLI contract: ::error annotations, exit codes, never a traceback."""

    def test_stale_doc_exits_nonzero_with_annotation(self) -> None:
        record = self.write_record()
        doc = self.write_doc("ROADMAP.md", f"**{sentence(9, 1, 12)}.**")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cpc.main(["--record", str(record), "--docs", str(doc)])
        self.assertEqual(rc, 1)
        self.assertEqual(out.getvalue().count("::error"), 1, out.getvalue())
        self.assertIn(f"::error file={doc}::", out.getvalue())
        self.assertIn("9 met, 1 not applicable, 12 unmet", out.getvalue())
        self.assertNotIn("Traceback", out.getvalue())

    def test_matching_doc_exits_zero(self) -> None:
        record = self.write_record()
        doc = self.write_doc("ROADMAP.md", f"**{sentence(10, 1, 11)}.**")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cpc.main(["--record", str(record), "--docs", str(doc)])
        self.assertEqual(rc, 0)
        self.assertIn("every count sentence matches", out.getvalue())

    def test_malformed_record_is_one_annotation_not_a_traceback(self) -> None:
        record = self.write_record_raw([1, 2, 3])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cpc.main(["--record", str(record)])
        self.assertEqual(rc, 1)
        self.assertEqual(out.getvalue().count("::error"), 1, out.getvalue())
        self.assertIn(f"::error file={record}::", out.getvalue())
        self.assertIn("not a JSON object", out.getvalue())
        self.assertNotIn("Traceback", out.getvalue())


class CommittedTreeTests(unittest.TestCase):
    """The committed README.md and ROADMAP.md match the committed record."""

    def test_committed_prose_matches_committed_record(self) -> None:
        expected = cpc.expected_counts(COMMITTED_RECORD)
        for name in ("README.md", "ROADMAP.md"):
            self.assertEqual(
                cpc.violations_in(REPO_ROOT / name, expected),
                [],
                f"{name} disagrees with {COMMITTED_RECORD.name}",
            )

    def test_stale_roadmap_sentence_reproduces_issue_221(self) -> None:
        # The regression guard from the issue's test plan: the stale
        # "9 met, 1 not applicable, 12 unmet" sentence the record's
        # 10 / 1 / 11 outlived must fail the checker.
        expected = cpc.expected_counts(COMMITTED_RECORD)
        stale = tempfile.TemporaryDirectory()
        self.addCleanup(stale.cleanup)
        doc = Path(stale.name) / "ROADMAP.md"
        doc.write_text(f"Grades 22 rows: **{sentence(9, 1, 12)}.**\n", encoding="utf-8")
        violations = cpc.violations_in(doc, expected)
        self.assertEqual(len(violations), 1, violations)

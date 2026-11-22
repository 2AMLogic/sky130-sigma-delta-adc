#!/usr/bin/env python3
"""Check prose T1-count sentences against the verdict of record (issue #221).

`manifests/sky130-sigma-delta-adc.signoff.json` is the verdict of record:
`klt signoff` writes `t1_item_count`, `t1_met_count` and
`t1_not_applicable_count`, and unmet is their arithmetic remainder. Nothing
checked the prose against those numbers, which is how ROADMAP.md carried
"9 met, 1 not applicable, 12 unmet" beside a record reading 10 / 1 / 11
through two regrades (issue #221).

The repo invariant this asserts:

  every "N met, M not applicable, K unmet" sentence in README.md and
  ROADMAP.md equals the record's own counts;

  a file with no such sentence asserts nothing -- README.md gains its first
  count sentence with PR #180, and the guard must tolerate the tree both
  before and after that lands.

The last number may be joined by a comma or an "and" (README.md's committed
sentence is "10 met, 1 not applicable and 11 unmet"); both forms are
asserted, so a prose drift cannot hide by rewording the separator.
Sentences are matched after collapsing whitespace, so a count claim the
Markdown wraps across lines is still found. Deliberately tool-free (stdlib
only, no `klt`, no EDA tools) so it runs as a plain step in CI beside the
files it guards, in the style of `check_content_hashes.py`.

    python3 -I manifests/check_prose_counts.py                 # the committed tree
    python3 -I manifests/check_prose_counts.py --record P      # another record
    python3 -I manifests/check_prose_counts.py --docs A.md B.md

Exits 0 when every found sentence matches; exits 1 with one
`::error file=...::` line per stale sentence, naming the file, the found
sentence and the record's counts.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORD = REPO_ROOT / "manifests" / "sky130-sigma-delta-adc.signoff.json"
DEFAULT_DOCS = ("README.md", "ROADMAP.md")

# "N met, M not applicable, K unmet" -- the last separator may be a comma or
# "and"; group 3 captures it with its whitespace verbatim for the error
# message. Hyphenated "not-applicable" accepted and case-insensitive,
# matched on whitespace-collapsed text so a sentence the Markdown wraps
# across lines still matches.
SENTENCE = re.compile(
    r"(\d+)\s+met,\s*(\d+)\s+not[-\s]applicable((?:,\s*|\s+and\s+))(\d+)\s+unmet",
    re.IGNORECASE,
)


def expected_counts(record_path: Path) -> tuple[int, int, int]:
    """(met, not_applicable, unmet) from the record's `t1_*` fields.

    unmet is the remainder of the T1 items: `t1_item_count` minus met minus
    not_applicable. The record's T2/T3/T4 tier placeholders are not T1
    items and never enter the arithmetic.

    Raises ValueError (or a JSON/IO error) on a malformed record: a top
    level that is not an object, a missing or non-integer `t1_*` field, or
    counts where met + not_applicable exceeds the item count.
    """
    data = json.loads(record_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("record top level is not a JSON object")
    fields: dict[str, int] = {}
    for name in ("t1_item_count", "t1_met_count", "t1_not_applicable_count"):
        value = data.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"record field {name} is not a non-negative integer: {value!r}"
            )
        fields[name] = value
    total = fields["t1_item_count"]
    met = fields["t1_met_count"]
    na = fields["t1_not_applicable_count"]
    if met + na > total:
        raise ValueError(
            f"record counts are inconsistent: t1_met_count ({met}) + "
            f"t1_not_applicable_count ({na}) exceeds t1_item_count ({total})"
        )
    return met, na, total - met - na


def violations_in(doc_path: Path, expected: tuple[int, int, int]) -> list[str]:
    """Violations for one prose file: each count sentence that disagrees.

    An empty list means the file carries no count sentence or every sentence
    it carries matches; absence of a sentence asserts nothing (README.md
    pre-#180). A file that cannot be read is itself a violation.
    """
    try:
        text = doc_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"cannot read: {exc}"]
    expected_text = (
        f"{expected[0]} met, {expected[1]} not applicable, {expected[2]} unmet"
    )
    violations: list[str] = []
    collapsed = " ".join(text.split())
    for match in SENTENCE.finditer(collapsed):
        met_s, na_s, sep, unmet_s = match.groups()
        triple = (int(met_s), int(na_s), int(unmet_s))
        if triple != expected:
            found_text = f"{met_s} met, {na_s} not applicable{sep}{unmet_s} unmet"
            violations.append(f'says "{found_text}", but the record counts {expected_text}')
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--record",
        type=Path,
        default=DEFAULT_RECORD,
        help="verdict-of-record JSON to derive the counts from (default: %(default)s)",
    )
    parser.add_argument(
        "--docs",
        type=Path,
        nargs="*",
        default=[Path(name) for name in DEFAULT_DOCS],
        help="prose files to scan, repo-root-relative (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    root = args.record.resolve().parent.parent
    try:
        expected = expected_counts(args.record)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"::error file={args.record}::cannot derive counts from record: {exc}")
        return 1
    expected_text = (
        f"{expected[0]} met, {expected[1]} not applicable, {expected[2]} unmet"
    )
    stale = 0
    for doc in args.docs:
        path = doc if doc.is_absolute() else root / doc
        for violation in violations_in(path, expected):
            print(f"::error file={path}::{violation}")
            stale += 1
    if stale:
        print(f"prose-count check: {stale} stale sentence(s); record counts {expected_text}")
        return 1
    print(f"prose-count check: every count sentence matches the record ({expected_text})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

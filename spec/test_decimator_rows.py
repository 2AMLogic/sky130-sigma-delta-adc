#!/usr/bin/env python3
"""Bind the digital partition's `not_applicable` claim to the ratified spec.

T1 checklist item 6 ("statistical claims carry Monte Carlo evidence") is
discharged for the *digital* partition by a recorded `not_applicable`:
`manifests/sky130-sigma-delta-adc.json` cites, under `evidence."6.digital"`,
a JSON projection of the decimator's spec rows and a statement classing each
of them deterministic. `klt signoff` hash-binds both of those JSON files, so
a silent edit to either is caught by the committed verdict of record.

What `klt signoff` cannot see is the link back to the ratified Markdown: the
projection is a *copy* of `spec/modulator-adc.md` §1.1, and nothing in the
manifest notices when the Markdown moves out from under it. That is the hole
this module closes. It is deliberately tool-free (stdlib only, no `klt`, no
numpy) so it runs as a plain unittest in CI beside the files it guards.

Together the two halves are closed:

  * the Markdown changes      -> `test_recorded_source_hash_is_current` fails
  * the projection changes    -> the manifest's content hash goes stale and
                                 the signoff byte-compare step fails

Run directly:  python3 -I -m unittest discover -s spec -p 'test_*.py'
"""

from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

#: Repository root, derived from this file's location (`<root>/spec/`).
REPO_ROOT = Path(__file__).resolve().parent.parent

#: The ratified target specification. The projection is a copy of its §1.1
#: table; this module is what notices when the copy stops matching.
SPEC_MD = REPO_ROOT / "spec" / "modulator-adc.md"
#: JSON projection of the decimator rows, cited as the `spec` document.
ROWS_JSON = REPO_ROOT / "spec" / "decimator-rows.json"
#: The committed claim that each projected row is deterministic.
STATEMENT_JSON = REPO_ROOT / "spec" / "decimator-not-statistical.json"
#: The block manifest that cites both of the above under `6.digital`.
MANIFEST_JSON = REPO_ROOT / "manifests" / "sky130-sigma-delta-adc.json"

#: The spec rows the decimation filter (the digital partition) is graded on:
#: §1.1 rows 6-10 -- output word rate, output word, passband, stopband,
#: filter order. Rows 1-5 and 11-14 describe the modulator and the block as a
#: whole and are graded by the analog partition, which may not use this
#: outcome at all (see the statement's `scope` note and issue #34).
DIGITAL_ROW_IDS: tuple[str, ...] = ("6", "7", "8", "9", "10")

#: The §1.1 table's columns after the leading row number, in order.
ROW_FIELDS: tuple[str, ...] = (
    "parameter",
    "target",
    "fallback",
    "stretch",
    "evidence",
)

#: The pinned `klayout-tools`' own conservative scan for statistical wording
#: (`signoff.py` `_NA_STATISTICAL_TEXT_RE`, 0.8.0). Mirrored here so a row or
#: a reason that would make `klt signoff` refuse with
#: `not_applicable_statistical_row` fails in a fast, tool-free test instead
#: of only in the signoff step. The tool remains the authority; this is a
#: tripwire, not a reimplementation.
STATISTICAL_TEXT_RE = re.compile(
    r"σ|\bsigma\b|\bcpk\b|\bppk\b|\byield\b|\bmonte[ _-]?carlo\b"
    r"|\bmismatch\b|\bmatching\b|\boffset\b|\baccuracy\b",
    re.IGNORECASE,
)


def sha256_file(path: Path) -> str:
    """`sha256:`-prefixed digest of `path`, matching the manifest's form."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def parse_spec_table(markdown: str) -> dict[str, dict[str, str]]:
    """Read the §1.1 parameter table -> `{row id: {field: cell text}}`.

    The sole definition, in this repository, of what "copied verbatim from
    `spec/modulator-adc.md` §1.1" means. The projection is generated through
    this function and checked against it, so the two cannot drift apart.

    Scoped to the `### 1.1 Table` section so a table added elsewhere in the
    document cannot be mistaken for the parameter table. Cells are taken
    exactly as written, stripped of surrounding whitespace only.
    """
    lines = markdown.splitlines()
    try:
        start = next(
            index
            for index, line in enumerate(lines)
            if line.strip().startswith("### 1.1")
        )
    except StopIteration:  # pragma: no cover - guarded by a test
        raise AssertionError("spec/modulator-adc.md has no '### 1.1' section") from None
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("### ")
        ),
        len(lines),
    )

    rows: dict[str, dict[str, str]] = {}
    for line in lines[start:end]:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != len(ROW_FIELDS) + 1:
            continue
        if not cells[0].isdigit():  # the header and its `|---|` separator
            continue
        rows[cells[0]] = dict(zip(ROW_FIELDS, cells[1:], strict=True))
    return rows


def load_json(path: Path) -> dict:
    """Parse `path` as a JSON object."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class TestSpecProjection(unittest.TestCase):
    """The projection is a faithful, current copy of the ratified rows."""

    def setUp(self) -> None:
        self.projection = load_json(ROWS_JSON)
        self.table = parse_spec_table(SPEC_MD.read_text(encoding="utf-8"))

    def test_recorded_source_hash_is_current(self) -> None:
        """The spec the projection was taken from still hashes the same.

        This is the whole point of the module: editing the ratified spec
        invalidates the `not_applicable` claim built on top of it, and must
        fail CI rather than silently leave a stale projection cited.
        """
        source = self.projection["source"]
        self.assertEqual(source["file"], "spec/modulator-adc.md")
        self.assertEqual(
            source["content_hash"],
            sha256_file(SPEC_MD),
            "spec/modulator-adc.md has changed since spec/decimator-rows.json "
            "was projected from it. The recorded `not_applicable` claim for T1 "
            "item 6 (digital) no longer describes the ratified spec. Re-project "
            "the rows, refresh `source.content_hash` here and the manifest's "
            "content hashes, and regenerate "
            "manifests/sky130-sigma-delta-adc.signoff.json in the same change.",
        )

    def test_status_is_ratified(self) -> None:
        """`klt signoff` refuses an unratified spec; say so explicitly."""
        self.assertEqual(self.projection["status"], "ratified")

    def test_projects_exactly_the_digital_rows(self) -> None:
        """Rows 6-10, in order, with no extra and no duplicate ids."""
        ids = [row["id"] for row in self.projection["rows"]]
        self.assertEqual(ids, list(DIGITAL_ROW_IDS))

    def test_row_ids_are_strings(self) -> None:
        """The pinned tool requires a non-empty string `id` per row."""
        for row in self.projection["rows"]:
            self.assertIsInstance(row["id"], str)
            self.assertTrue(row["id"].strip())

    def test_row_text_is_verbatim_from_the_table(self) -> None:
        """Every projected cell matches §1.1 character for character."""
        for row in self.projection["rows"]:
            self.assertIn(
                row["id"], self.table, f"row {row['id']} is not in §1.1 at all"
            )
            for field in ROW_FIELDS:
                self.assertEqual(
                    row[field],
                    self.table[row["id"]][field],
                    f"row {row['id']} field '{field}' is not verbatim from §1.1",
                )

    def test_no_statistical_wording_in_the_projection(self) -> None:
        """A projected row that reads statistical would be refused."""
        for row in self.projection["rows"]:
            for field in ROW_FIELDS:
                hit = STATISTICAL_TEXT_RE.search(row[field])
                self.assertIsNone(
                    hit,
                    f"row {row['id']} field '{field}' contains statistical "
                    f"wording ({hit.group(0) if hit else ''!r}); klt signoff "
                    "would refuse this claim with "
                    "`not_applicable_statistical_row`",
                )


class TestStatement(unittest.TestCase):
    """The statement accounts for every projected row, deterministically."""

    def setUp(self) -> None:
        self.projection = load_json(ROWS_JSON)
        self.statement = load_json(STATEMENT_JSON)

    def test_one_entry_per_projected_row(self) -> None:
        """No missing, extra or duplicate row id (the tool's own rule)."""
        spec_ids = [row["id"] for row in self.projection["rows"]]
        statement_ids = [row["id"] for row in self.statement["rows"]]
        self.assertEqual(
            sorted(statement_ids, key=int),
            sorted(spec_ids, key=int),
            "the statement must have exactly one entry per projected spec row; "
            "klt signoff refuses otherwise with "
            "`not_applicable_statement_incomplete`",
        )
        self.assertEqual(len(set(statement_ids)), len(statement_ids))

    def test_every_entry_has_class_and_reason(self) -> None:
        """Each row carries a non-empty string `id`, `class` and `reason`."""
        for row in self.statement["rows"]:
            for key in ("id", "class", "reason"):
                self.assertIsInstance(row[key], str)
                self.assertTrue(row[key].strip(), f"row {row['id']}: empty {key}")

    def test_no_statistical_wording_in_class_or_reason(self) -> None:
        """A class or reason conceding a statistical row would be refused.

        The pinned tool scans `class` only; `reason` is held to the same bar
        here because a reason that needs one of those words is describing a
        row that cannot use this outcome.
        """
        for row in self.statement["rows"]:
            for key in ("class", "reason"):
                hit = STATISTICAL_TEXT_RE.search(row[key])
                self.assertIsNone(
                    hit,
                    f"statement row {row['id']} field '{key}' contains "
                    f"statistical wording ({hit.group(0) if hit else ''!r})",
                )

    def test_scope_note_is_present(self) -> None:
        """The statement says which rows it does *not* speak for.

        The projection covers the decimator rows only, so the statement must
        not read as a claim about the modulator's rows -- row 2 (peak SNDR)
        among them -- which the analog partition still owes Monte Carlo
        evidence for (issue #34).
        """
        scope = self.statement["scope"]
        self.assertTrue(scope.strip())
        self.assertIn("analog", scope.lower())


class TestManifestCitation(unittest.TestCase):
    """The manifest cites both documents, currently and unambiguously."""

    def setUp(self) -> None:
        self.manifest = load_json(MANIFEST_JSON)
        self.evidence = self.manifest["evidence"]

    def test_cites_both_documents_under_6_digital(self) -> None:
        """`evidence."6.digital".not_applicable` names spec and statement."""
        form = self.evidence["6.digital"]["not_applicable"]
        self.assertEqual(form["spec"]["file"], "spec/decimator-rows.json")
        self.assertEqual(
            form["statement"]["file"], "spec/decimator-not-statistical.json"
        )

    def test_cited_content_hashes_are_current(self) -> None:
        """Both hashes match the files on disk.

        `klt signoff` enforces this too (as `stale_evidence`); checking it
        here turns a stale hash into an immediate, tool-free failure that
        names the file.
        """
        form = self.evidence["6.digital"]["not_applicable"]
        for label, path in (
            ("spec", ROWS_JSON),
            ("statement", STATEMENT_JSON),
        ):
            self.assertEqual(
                form[label]["content_hash"],
                sha256_file(path),
                f"manifest's '{label}' content hash is stale for {path.name}",
            )

    def test_no_bare_spec_rows_declaration_for_item_6(self) -> None:
        """A bare `spec_rows."6"` would invalidate this claim.

        Per the pinned tool's `_resolve_spec_rows`, a bare key applies to
        *both* partitions, and a `not_applicable` entry graded against a
        declared row set renders `invalid_evidence`. The analog campaign
        (issue #34) declares the partition-qualified `spec_rows."6.analog"`
        instead.
        """
        spec_rows = self.manifest.get("spec_rows") or {}
        self.assertNotIn(
            "6",
            spec_rows,
            'a bare spec_rows."6" applies to both partitions and would grade '
            'the digital not_applicable entry as invalid_evidence; use '
            'spec_rows."6.analog" for the analog campaign',
        )

    def test_analog_half_is_not_claimed(self) -> None:
        """Item 6 analog is left to issue #34's Monte Carlo campaign.

        The outcome is available to a digital partition only; an analog
        partition always requires Monte Carlo evidence.
        """
        self.assertNotIn("6.analog", self.evidence)
        self.assertNotIn("6", self.evidence)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Fixtures for the manifest content-hash invariant (issue #155).

Covers the invariant's three failure modes and its two valid shapes:

  * a citation declaring a pin its cited file cannot verify (the file has no
    `provenance.input.content_hash`) fails -- the latent item-8 blocker;
  * a citation whose pin differs from the declared input hash fails;
  * a `not_applicable` binding whose pin is not the cited file's own sha256
    fails (and one that matches passes);
  * a citation omitting the pin on a file that carries
    `provenance.input.content_hash` fails -- the invariant's other half,
    enforced since issue #215;
  * a citation declaring no pin on a file with no provenance hash passes
    (`5.digital[1]` today);
  * two entries citing different files that attest the same declared input
    pass on one shared pin value (`2.digital`/`3.digital` today) -- pins are
    compared per entry, never for uniqueness across the manifest.

Plus the edge cases the CI step cannot show on its own: a missing cited file
fails with a clear message rather than a traceback, a citation list is
handled per element, the committed manifest itself satisfies the invariant,
and re-adding a pin to `8.analog` reproduces exactly the defect issue #155
fixes (the regression guard from its test plan).

Run directly:  python3 -I -m unittest discover -s manifests -p 'test_*.py'
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import check_content_hashes as cch

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMITTED_MANIFEST = REPO_ROOT / "manifests" / "sky130-sigma-delta-adc.json"

#: A well-formed-looking pin value, distinct from every real file hash.
GOOD = "sha256:" + "a1" * 32
#: A second, different pin value for mismatch cases.
OTHER = "sha256:" + "b2" * 32


class FixtureTree(unittest.TestCase):
    """A temporary manifests/ + evidence tree mirroring the repo layout.

    The manifest sits at `<tmp>/manifests/manifest.json`, so citations
    resolve against `<tmp>` exactly as the committed manifest resolves
    against the repository root.
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write_bytes(self, rel: str, payload: bytes) -> str:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return rel

    def write_json(self, rel: str, payload: object) -> str:
        return self.write_bytes(rel, json.dumps(payload).encode("utf-8"))

    def envelope(self, provenance_hash: str | None = None, rel: str = "attest/envelope.json") -> str:
        """Write a cited envelope file with (or without) a provenance block."""
        payload: dict = {"summary": "fixture envelope"}
        if provenance_hash is not None:
            payload["provenance"] = {"input": {"content_hash": provenance_hash}}
        return self.write_json(rel, payload)

    def manifest(self, evidence: dict) -> Path:
        manifest = {"block": "fixture-block", "kind": "mixed-signal", "evidence": evidence}
        path = self.root / "manifests" / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def violations_for(self, evidence: dict) -> list[str]:
        return cch.check_manifest(self.manifest(evidence))


class CitationTests(FixtureTree):
    """The citation branch: a pin is declared iff the file declares an input.

    Both directions are enforced (issue #215): a pin the file cannot verify
    fails, and a missing pin where the file declares one fails too.
    """

    def test_matching_pin_passes(self) -> None:
        cited = self.envelope(provenance_hash=GOOD)
        self.assertEqual(
            self.violations_for({"1.analog": {"file": cited, "content_hash": GOOD}}),
            [],
        )

    def test_mismatched_pin_fails_naming_both_hashes(self) -> None:
        cited = self.envelope(provenance_hash=GOOD)
        violations = self.violations_for(
            {"1.analog": {"file": cited, "content_hash": OTHER}}
        )
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("1.analog", violations[0])
        self.assertIn(GOOD, violations[0])
        self.assertIn(OTHER, violations[0])

    def test_unverifiable_pin_fails(self) -> None:
        # The item-8 shape: a pin on a provenance-less file. No value is
        # correct here -- klt can never verify the pin, so the check rejects
        # the shape itself rather than any particular hash.
        cited = self.envelope(provenance_hash=None)
        violations = self.violations_for(
            {"8.analog": {"file": cited, "content_hash": GOOD}}
        )
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("8.analog", violations[0])
        self.assertIn(GOOD, violations[0])
        self.assertIn("provenance", violations[0])

    def test_missing_pin_on_provenance_carrying_file_fails(self) -> None:
        # The iff's other half (issue #215): a file that carries
        # provenance.input.content_hash must be pinned by its citation.
        cited = self.envelope(provenance_hash=GOOD)
        violations = self.violations_for({"1.analog": {"file": cited}})
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("1.analog", violations[0])
        self.assertIn(GOOD, violations[0])

    def test_no_pin_on_file_without_provenance_passes(self) -> None:
        # Absence is valid only where the cited file itself carries no
        # provenance hash (5.digital[1] today): no pin, no claim for klt.
        cited = self.envelope(provenance_hash=None)
        self.assertEqual(self.violations_for({"5.digital": {"file": cited}}), [])

    def test_shared_pin_value_passes(self) -> None:
        # 2.digital/3.digital: different files attesting the same declared
        # input. The same pin value twice is legitimate; pins are compared
        # per entry, never for uniqueness.
        first = self.envelope(provenance_hash=GOOD, rel="attest/first.json")
        second = self.envelope(provenance_hash=GOOD, rel="attest/second.json")
        self.assertEqual(
            self.violations_for(
                {
                    "2.digital": {"file": first, "content_hash": GOOD},
                    "3.digital": {"file": second, "content_hash": GOOD},
                }
            ),
            [],
        )


class NotApplicableTests(FixtureTree):
    """The not_applicable branch: the pin binds the cited file's own bytes."""

    def test_binding_pinning_the_file_hash_passes(self) -> None:
        payload = b'{"rows": []}'
        cited = self.write_bytes("spec/rows.json", payload)
        pin = "sha256:" + hashlib.sha256(payload).hexdigest()
        self.assertEqual(
            self.violations_for(
                {"6.digital": {"not_applicable": {"spec": {"file": cited, "content_hash": pin}}}}
            ),
            [],
        )

    def test_binding_with_a_wrong_pin_fails_naming_both_hashes(self) -> None:
        payload = b'{"rows": []}'
        cited = self.write_bytes("spec/rows.json", payload)
        violations = self.violations_for(
            {
                "6.digital": {
                    "not_applicable": {
                        "spec": {"file": cited, "content_hash": GOOD},
                        "statement": {"file": cited, "content_hash": GOOD},
                    }
                }
            }
        )
        self.assertEqual(len(violations), 2, violations)
        for key, violation in zip(("6.digital.spec", "6.digital.statement"), violations):
            self.assertIn(key, violation)
            self.assertIn(GOOD, violation)
            self.assertIn(hashlib.sha256(payload).hexdigest(), violation)

    def test_binding_without_a_pin_fails(self) -> None:
        # The not_applicable branch has no "absence is valid" case: the pin
        # is what hash-binds the claim to the file it describes.
        cited = self.write_bytes("spec/rows.json", b'{"rows": []}')
        violations = self.violations_for(
            {"6.digital": {"not_applicable": {"spec": {"file": cited}}}}
        )
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("6.digital.spec", violations[0])


class EdgeCaseTests(FixtureTree):
    """Failure shapes beyond the hash comparisons themselves."""

    def test_missing_cited_file_fails_with_a_clear_message(self) -> None:
        violations = self.violations_for(
            {"9": {"file": "attest/gone.json", "content_hash": GOOD}}
        )
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("9", violations[0])
        self.assertIn("attest/gone.json", violations[0])
        self.assertIn("does not exist", violations[0])

    def test_citation_list_is_handled_per_element(self) -> None:
        verifiable = self.envelope(provenance_hash=GOOD, rel="attest/sta.json")
        unverifiable = self.envelope(provenance_hash=None, rel="attest/fv.json")
        violations = self.violations_for(
            {
                "5.digital": [
                    {"file": verifiable, "content_hash": GOOD},
                    {"file": unverifiable, "content_hash": OTHER},
                ]
            }
        )
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("5.digital[1]", violations[0])
        self.assertNotIn("5.digital[0]", violations[0])

    def test_unreadable_cited_file_with_no_pin_stays_valid(self) -> None:
        # Omitting a pin must not turn a non-JSON cited file into a new
        # read failure (issue #215): with nothing declared there is nothing
        # to compare, so the citation stays valid.
        cited = self.write_bytes("attest/blob.json", b"\xff\xfe not json")
        self.assertEqual(self.violations_for({"7": {"file": cited}}), [])

    def test_manifest_without_evidence_fails_cleanly(self) -> None:
        self.write_json("manifests/manifest.json", {"block": "x"})
        self.assertEqual(
            cch.check_manifest(self.root / "manifests" / "manifest.json"),
            ['manifest has no "evidence" object to check'],
        )

    def test_main_reports_violations_as_annotations_and_exits_nonzero(self) -> None:
        cited = self.envelope(provenance_hash=None)
        path = self.manifest({"8.analog": {"file": cited, "content_hash": GOOD}})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cch.main(["--manifest", str(path)])
        self.assertEqual(rc, 1)
        self.assertIn(f"::error file={path}::", out.getvalue())
        self.assertIn("8.analog", out.getvalue())

    def test_main_passes_a_clean_manifest(self) -> None:
        cited = self.envelope(provenance_hash=GOOD)
        path = self.manifest({"1.analog": {"file": cited, "content_hash": GOOD}})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cch.main(["--manifest", str(path)])
        self.assertEqual(rc, 0)
        self.assertIn("verifies", out.getvalue())


class CommittedManifestTests(unittest.TestCase):
    """The committed manifest itself satisfies the invariant."""

    def test_committed_manifest_has_no_violations(self) -> None:
        self.assertEqual(cch.check_manifest(COMMITTED_MANIFEST), [])

    def test_readding_the_item8_pin_reproduces_issue_155(self) -> None:
        # Regression guard (issue #155 test plan): re-add a content_hash to
        # 8.analog the way the defect had it and confirm the check bites.
        manifest = json.loads(COMMITTED_MANIFEST.read_text(encoding="utf-8"))
        entry = manifest["evidence"]["8.analog"]
        self.assertNotIn("content_hash", entry, "the issue's fix is no longer in place")
        entry["content_hash"] = "sha256:" + "0" * 64
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Mirror every repo directory the manifest cites so the only
            # violation is the re-added pin, not a forest of missing files.
            cited: list[str] = []
            for value in manifest["evidence"].values():
                if isinstance(value, list):
                    cited.extend(b["file"] for b in value)
                elif isinstance(value, dict) and isinstance(value.get("not_applicable"), dict):
                    cited.extend(b["file"] for b in value["not_applicable"].values())
                elif isinstance(value, dict):
                    cited.append(value["file"])
            for name in sorted({Path(f).parts[0] for f in cited}):
                (root / name).symlink_to(REPO_ROOT / name, target_is_directory=True)
            (root / "manifests").mkdir()
            path = root / "manifests" / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            violations = cch.check_manifest(path)
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("8.analog", violations[0])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Check the manifest's `content_hash` pins are verifiable (issue #155).

`manifests/sky130-sigma-delta-adc.json` pins a `content_hash` on each evidence
citation, and the pinned `klt signoff` verifies a citation's pin only against
the cited file's own `provenance.input.content_hash` -- never against the
cited file's raw bytes. Two consequences, measured against klt 0.8.0
(`.github/klt-version`) while diagnosing issue #155, make the pins worth a
repo-side gate:

  * A pin on a file with no `provenance` block (the generic item-8 envelope)
    can never grade `met`: klt refuses it as `unverifiable_provenance`
    whatever the value, and while the envelope also fails its own check
    (`check_failed`) that refusal is masked -- which is how item 8's stale pin
    sat unnoticed. The pin is a latent blocker; the fix is to omit the field,
    not to refresh it.
  * No other CI step compares the pins at all, so a value that drifts from
    the declared input it names, or a `not_applicable` binding that stops
    matching the file it binds, stays invisible until grading reaches it --
    which for a failing item may be never.

The repo invariant this asserts (issue #155, "Verified corrections"):

  a citation declares a `content_hash` if and only if the cited file carries
  `provenance.input.content_hash`, and then the pin equals it -- enforced
  in both directions (issue #215: a citation omitting the pin on a file
  that carries one fails too);

  a `not_applicable` `spec`/`statement` binding instead pins the cited
  file's own sha256.

Declared pins are not unique: two entries may cite different files that
attest the same declared input (2.digital and 3.digital share one value), so
pins are compared per entry, never for uniqueness across the manifest.

Deliberately tool-free (stdlib only, no `klt`, no EDA tools) so it runs as a
plain step in CI beside the files it guards, in the style of
`attestation/item8_envelope.py` and `spec/test_decimator_rows.py`.

    python3 -I manifests/check_content_hashes.py                # the committed manifest
    python3 -I manifests/check_content_hashes.py --manifest P   # another manifest

Exits 0 when every declared pin verifies; exits 1 with one
`::error file=...::` line per violation, naming the offending evidence key
and both hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "manifests" / "sky130-sigma-delta-adc.json"


def sha256_file(path: Path) -> str:
    """`sha256:`-prefixed digest of `path`, matching the manifest's form."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def provenance_input_hash(path: Path) -> str | None:
    """The file's `provenance.input.content_hash`, or None when absent."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        return None
    source = provenance.get("input")
    if not isinstance(source, dict):
        return None
    content_hash = source.get("content_hash")
    return content_hash if isinstance(content_hash, str) else None


def check_binding(key: str, binding: object, root: Path, pins_own_file: bool) -> list[str]:
    """Violations for one evidence binding.

    `pins_own_file=False` is a citation: the citation must declare a pin if
    and only if the cited file carries `provenance.input.content_hash`, and
    then the pin must equal it -- a missing pin where the file carries one
    is a violation naming the hash the pin should carry (issue #215), and
    absence stays valid only when the file carries none (5.digital[1]
    today). `pins_own_file=True` is a `not_applicable` `spec`/`statement`
    binding: the pin is required, and must equal the cited file's own
    sha256, which is what klt hash-binds.
    """
    if not isinstance(binding, dict):
        return [f"{key}: evidence entry is not a JSON object"]
    rel = binding.get("file")
    if not isinstance(rel, str) or not rel.strip():
        return [f'{key}: entry names no "file"']
    path = root / rel
    if not path.is_file():
        return [f"{key}: cited file {rel} does not exist"]
    declared = binding.get("content_hash")

    if pins_own_file:
        if not isinstance(declared, str) or not declared:
            return [
                f"{key}: not_applicable binding cites {rel} with no "
                "content_hash pin; a not_applicable spec/statement binding "
                "pins the cited file's own sha256"
            ]
        actual = sha256_file(path)
        if declared != actual:
            return [
                f"{key}: declares content_hash {declared}, but {rel}'s own "
                f"sha256 is {actual}"
            ]
        return []

    missing_pin = declared is None
    if not missing_pin and (not isinstance(declared, str) or not declared):
        return [f"{key}: content_hash must be a `sha256:...` string"]
    try:
        declared_input = provenance_input_hash(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        if missing_pin:
            return []
        return [f"{key}: cited file {rel} is not readable JSON: {exc}"]
    if missing_pin:
        if declared_input is not None:
            return [
                f"{key}: cites {rel}, which carries provenance.input."
                f"content_hash ({declared_input}), but declares no "
                "content_hash pin; the invariant is if-and-only-if -- add "
                "the pin (issue #215)"
            ]
        return []
    if declared_input is None:
        return [
            f"{key}: declares content_hash {declared}, but {rel} carries no "
            "provenance.input.content_hash; klt grades such a pin "
            "`unverifiable_provenance`, so the citation can never grade met "
            "-- omit the field or add the provenance block (issue #155)"
        ]
    if declared != declared_input:
        return [
            f"{key}: declares content_hash {declared}, but {rel}'s "
            f"provenance.input.content_hash is {declared_input}"
        ]
    return []


def check_manifest(manifest_path: Path) -> list[str]:
    """All violations in the manifest at `manifest_path`.

    Cited paths are repo-root-relative and the manifest lives under
    `<root>/manifests/`, so the root the citations resolve against is the
    manifest's grandparent directory.
    """
    root = manifest_path.resolve().parent.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evidence = manifest.get("evidence")
    if not isinstance(evidence, dict):
        return ['manifest has no "evidence" object to check']

    violations: list[str] = []
    for key, value in evidence.items():
        if isinstance(value, list):
            for index, element in enumerate(value):
                violations.extend(
                    check_binding(f"{key}[{index}]", element, root, pins_own_file=False)
                )
        elif isinstance(value, dict) and isinstance(value.get("not_applicable"), dict):
            for role, binding in value["not_applicable"].items():
                violations.extend(
                    check_binding(f"{key}.{role}", binding, root, pins_own_file=True)
                )
        elif isinstance(value, dict):
            violations.extend(check_binding(key, value, root, pins_own_file=False))
        else:
            violations.append(
                f"{key}: evidence entry is neither a citation, a list of "
                "citations, nor a not_applicable binding"
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="manifest to check (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    try:
        violations = check_manifest(args.manifest)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"::error file={args.manifest}::cannot check manifest: {exc}")
        return 1
    for violation in violations:
        print(f"::error file={args.manifest}::{violation}")
    if violations:
        print(f"content-hash check: {len(violations)} violation(s) in {args.manifest}")
        return 1
    print(f"content-hash check: every declared pin in {args.manifest} verifies")
    return 0


if __name__ == "__main__":
    sys.exit(main())

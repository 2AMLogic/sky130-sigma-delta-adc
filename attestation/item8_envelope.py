#!/usr/bin/env python3
"""Generate or check the T1 item-8 generic envelope from measurements/characterization.md.

`klt signoff --attest` accepts only items 1, 9 and 10 in the pinned klt, so this
script plays that role for item 8: it parses the hand-written report, enforces
its structure, and binds it and every file it cites by sha256 into a bare
generic envelope (the form item 8 is graded on).

Structure enforced:
  * the per-row table has exactly rows 1-14, each with a verdict of
    evidenced / partial / pending;
  * every cited evidence file exists; evidenced and partial rows cite at least
    one; a pending row cites none;
  * a partial or pending row names a blocking issue (#N) in "Remaining";
  * the decimator table's Fmax and power rows are evidenced or name an issue.

The envelope status is `pass` only if every row and every decimator quantity is
evidenced; otherwise `fail`, so item 8 grades `check_failed` until the pending
work lands. Hand-editing a verdict in the report, or changing any cited file,
changes the bytes this script produces, so `--check` fails until the envelope is
regenerated in the same change.

    python3 -I attestation/item8_envelope.py            # write the envelope
    python3 -I attestation/item8_envelope.py --check    # exit 1 if stale or malformed
    python3 -I attestation/item8_envelope.py --verify-issues   # also: pending issues are open (needs gh)
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = "measurements/characterization.md"
ENVELOPE = "attestation/item8-envelope.json"
VERDICTS = {"evidenced", "partial", "pending"}
PATH_RE = re.compile(r"`([^`]+)`")
ISSUE_RE = re.compile(r"#(\d+)")


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def table_after(text: str, heading: str) -> list[list[str]]:
    """Cells of the data rows of the first table after `heading`."""
    start = text.index(heading)
    rows = []
    for line in text[start:].splitlines()[1:]:
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not set(cells[0]) <= set("-: ") and cells[0] not in ("Row", "Quantity"):
                rows.append(cells)
        elif rows:
            break
    return rows


def parse(text: str):
    errors, cited, issues = [], set(), set()

    def check_paths(label: str, cell: str) -> list[str]:
        paths = PATH_RE.findall(cell)
        for p in paths:
            if not (ROOT / p).is_file():
                errors.append(f"{label}: cited file does not exist: {p}")
        cited.update(paths)
        return paths

    rows = []
    for c in table_after(text, "## Per-row characterization"):
        if len(c) != 6 or not c[0].isdigit():
            errors.append(f"per-row table: malformed row {c[:2]}")
            continue
        n, verdict = int(c[0]), c[2]
        label = f"row {n}"
        if verdict not in VERDICTS:
            errors.append(f"{label}: verdict {verdict!r} not in {sorted(VERDICTS)}")
        paths = check_paths(label, c[4])
        if verdict == "pending" and (paths or c[4].lower() != "none"):
            errors.append(f"{label}: a pending row cites no evidence (write 'none')")
        if verdict in ("evidenced", "partial") and not paths:
            errors.append(f"{label}: {verdict} but cites no evidence file")
        refs = ISSUE_RE.findall(c[5])
        if verdict in ("partial", "pending") and not refs:
            errors.append(f"{label}: {verdict} but 'Remaining' names no issue (#N)")
        issues.update(refs if verdict != "evidenced" else [])
        rows.append({"row": n, "verdict": verdict, "evidence": paths, "issues": sorted(set(refs), key=int)})
    if [r["row"] for r in rows] != list(range(1, 15)):
        errors.append(f"per-row table must hold exactly rows 1-14, found {[r['row'] for r in rows]}")

    dec = []
    for c in table_after(text, "## Decimator Fmax, area and power"):
        if len(c) != 5:
            errors.append(f"decimator table: malformed row {c[:1]}")
            continue
        status = c[4]
        paths = check_paths(f"decimator '{c[0]}'", c[3])
        refs = ISSUE_RE.findall(status)
        done = status.startswith("evidenced")
        if not done and not status.startswith("pending"):
            errors.append(f"decimator '{c[0]}': status must start 'evidenced' or 'pending'")
        if done and not paths:
            errors.append(f"decimator '{c[0]}': evidenced but cites no evidence file")
        if not done and not refs:
            errors.append(f"decimator '{c[0]}': pending but names no issue (#N)")
        if not done:
            issues.update(refs)
        dec.append({"quantity": c[0], "evidenced": done, "evidence": paths, "issues": sorted(set(refs), key=int)})
    names = " ".join(d["quantity"].lower() for d in dec)
    for need in ("area", "fmax", "power"):
        if need not in names:
            errors.append(f"decimator table has no {need} row")
    return rows, dec, cited, issues, errors


def build() -> tuple[dict, list[str], set[str]]:
    report = ROOT / REPORT
    rows, dec, cited, issues, errors = parse(report.read_text())
    met = all(r["verdict"] == "evidenced" for r in rows) and all(d["evidenced"] for d in dec)
    counts = {v: sum(r["verdict"] == v for r in rows) for v in sorted(VERDICTS)}
    envelope = {
        "schema_version": 1,
        "kind": "generic",
        "status": "pass" if met else "fail",
        "t1_item": 8,
        "summary": (
            "T1 item 8 (Characterization report): spec rows "
            + ", ".join(f"{n} {k}" for k, n in counts.items())
            + "; decimator Fmax/area/power "
            + f"{sum(d['evidenced'] for d in dec)}/{len(dec)} evidenced"
        ),
        "source": REPORT,
        "metrics": {
            "report_sha256": sha256(report),
            "spec_rows": rows,
            "decimator": dec,
            "evidence_sha256": {p: sha256(ROOT / p) for p in sorted(cited) if (ROOT / p).is_file()},
            "pending_issues": sorted(issues, key=int),
        },
    }
    return envelope, errors, issues


def verify_issues(issues: set[str]) -> list[str]:
    bad = []
    for n in sorted(issues, key=int):
        out = subprocess.run(["gh", "issue", "view", n, "--json", "state", "--jq", ".state"],
                             capture_output=True, text=True)
        if out.returncode != 0 or out.stdout.strip() != "OPEN":
            bad.append(f"#{n} is not an open issue ({out.stdout.strip() or out.stderr.strip()})")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--verify-issues", action="store_true")
    args = ap.parse_args()

    envelope, errors, issues = build()
    if args.verify_issues:
        errors += verify_issues(issues)
    if errors:
        print("\n".join(f"error: {e}" for e in errors), file=sys.stderr)
        return 1
    data = json.dumps(envelope, indent=2) + "\n"
    out = ROOT / ENVELOPE
    if args.check:
        if not out.is_file() or out.read_text() != data:
            print(f"error: {ENVELOPE} is stale: regenerate with "
                  "'python3 -I attestation/item8_envelope.py' and commit it", file=sys.stderr)
            return 1
        print(f"ok: {ENVELOPE} reproduces ({envelope['status']}): {envelope['summary']}")
        return 0
    if not out.is_file() or out.read_text() != data:
        out.write_text(data)
    print(f"{ENVELOPE}: {envelope['status']}: {envelope['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

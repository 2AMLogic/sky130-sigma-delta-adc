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
  * the decimator table's Fmax and power rows are evidenced, name an issue, or
    are a declared gap citing the ratified record that declares it.

A decimator row whose status starts `declared-gap` is a limit that no further
run can close (DR-008: the standard-cell library ships no liberty file for 35 of
the 45 DR-002 points). Such a row names no issue - there is none that could
close it - and instead cites a `spec/decisions/DR-NNN-*.md` record, which must
exist and is bound into the envelope by sha256 like any other cited file. A
declared gap is outside the graded set by that record, so it does not hold the
envelope at `fail`; what it must never do is read as evidence.

The envelope status is `pass` only if every spec row is evidenced and every
decimator quantity is evidenced or a declared gap; otherwise `fail`, so item 8
grades `check_failed` until the pending work lands. Hand-editing a verdict in
the report, or changing any cited file, changes the bytes this script produces,
so `--check` fails until the envelope is regenerated in the same change.

    python3 -I attestation/item8_envelope.py            # write the envelope
    python3 -I attestation/item8_envelope.py --check    # exit 1 if stale or malformed
    python3 -I attestation/item8_envelope.py --verify-issues   # also: pending issues are open (needs gh)

Exit codes: 0 = verified; 1 = malformed, stale, or a genuinely closed citation;
3 = `--verify-issues` could not run (gh failed). A gh failure (no auth, rate
limit, network, or gh could not start -- missing or non-executable) is reported
plainly as "could not verify" and never as a closed citation, so a red run
cannot be misread as a finding -- or as a pass.
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
DEC_STATUSES = ("evidenced", "pending", "declared-gap")
PATH_RE = re.compile(r"`([^`]+)`")
ISSUE_RE = re.compile(r"#(\d+)")
# The report cites this repo's issues; pin the slug so `gh` never resolves it
# from the cwd's git remote (a fork PR's checkout would resolve the fork,
# where these issue numbers do not exist).
GH_REPO = "2AMLogic/sky130-sigma-delta-adc"
RECORD_RE = re.compile(r"spec/decisions/DR-\d+-[^`]+\.md$")


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
        status, label = c[4], f"decimator '{c[0]}'"
        paths = check_paths(label, c[3])
        refs = ISSUE_RE.findall(status)
        done = status.startswith("evidenced")
        gap = status.startswith("declared-gap")
        if not done and not gap and not status.startswith("pending"):
            errors.append(f"{label}: status must start one of {list(DEC_STATUSES)}")
        if done and not paths:
            errors.append(f"{label}: evidenced but cites no evidence file")
        records = []
        if gap:
            records = [q for q in check_paths(label, status) if RECORD_RE.search(q)]
            if not records:
                errors.append(f"{label}: a declared gap must cite the ratified record "
                              "that declares it (`spec/decisions/DR-NNN-*.md`)")
            if paths:
                errors.append(f"{label}: a declared gap cites no evidence (write 'none')")
            if refs:
                errors.append(f"{label}: a declared gap names no issue (#N) - there is "
                              "none that could close it; cite the record instead")
        elif status.startswith("pending"):
            if not refs:
                errors.append(f"{label}: pending but names no issue (#N)")
            issues.update(refs)
        dec.append({"quantity": c[0], "evidenced": done, "declared_gap": gap,
                    "evidence": paths, "records": records,
                    "issues": sorted(set(refs), key=int)})
    names = " ".join(d["quantity"].lower() for d in dec)
    for need in ("area", "fmax", "power"):
        if need not in names:
            errors.append(f"decimator table has no {need} row")
    return rows, dec, cited, issues, errors


def is_met(rows: list[dict], dec: list[dict]) -> bool:
    """The envelope passes only when nothing is still owed.

    A declared gap is outside the graded set by the record that declares it, so
    it does not hold the envelope at `fail`; a pending row does.
    """
    return (all(r["verdict"] == "evidenced" for r in rows)
            and all(d["evidenced"] or d["declared_gap"] for d in dec))


def build() -> tuple[dict, list[str], set[str]]:
    report = ROOT / REPORT
    rows, dec, cited, issues, errors = parse(report.read_text())
    met = is_met(rows, dec)
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
            + f"{sum(d['evidenced'] for d in dec)}/{len(dec)} evidenced, "
            + f"{sum(d['declared_gap'] for d in dec)} declared gap"
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


def verify_issues(issues: set[str]) -> tuple[list[str], list[str]]:
    """Check every cited issue is still open, via `gh`.

    Returns (bad, could_not_run): genuinely closed citations, and issues `gh`
    could not answer (no auth, rate limit, network, or gh could not start).
    A gh failure is never reported as a closed citation -- the caller exits 3
    and says plainly that the check could not run.
    """
    bad, could_not_run = [], []
    for n in sorted(issues, key=int):
        # -R pins the repo: gh otherwise resolves owner/repo from the cwd's
        # git remote, which on a fork PR's checkout is the fork, where these
        # issue numbers do not exist. The report cites THIS repo's issues.
        try:
            out = subprocess.run(["gh", "issue", "view", n, "-R", GH_REPO,
                                  "--json", "state", "--jq", ".state"],
                                 capture_output=True, text=True)
        except OSError as e:
            # gh missing from PATH (FileNotFoundError) or not executable
            # (PermissionError): the CLI could not start, which is a failure
            # to run the check, not a finding. No later lookup can start
            # either, so stop here and let main() report it with exit 3.
            could_not_run.append(f"#{n}: could not start gh: {e}")
            break
        if out.returncode != 0:
            detail = (out.stderr.strip() or out.stdout.strip() or "gh failed").splitlines()[-1]
            could_not_run.append(f"#{n}: gh issue view failed ({detail})")
        elif out.stdout.strip() == "OPEN":
            continue
        elif out.stdout.strip() == "CLOSED":
            bad.append(f"#{n} is not an open issue (CLOSED)")
        else:
            could_not_run.append(f"#{n}: unexpected gh output {out.stdout.strip()!r}")
    return bad, could_not_run


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--verify-issues", action="store_true")
    args = ap.parse_args()

    envelope, errors, issues = build()
    could_not_run: list[str] = []
    if args.verify_issues:
        bad, could_not_run = verify_issues(issues)
        errors += bad
    if could_not_run:
        if errors:
            print("\n".join(f"error: {e}" for e in errors), file=sys.stderr)
        print("error: could not verify cited issues: gh failed, so the check "
              "did not run to completion (this is not a pass and names no "
              "closure)", file=sys.stderr)
        print("\n".join(f"  {e}" for e in could_not_run), file=sys.stderr)
        return 3
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

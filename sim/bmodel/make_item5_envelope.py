#!/usr/bin/env python3
"""Generate sim/bmodel/item5-model-run.json, the klt `model-run` envelope for
T1 item 5 (analog), rows 1 and 4.

Row 2's number is a model-B result, but DR-001 item 3's cross-check is
incomplete at every anchor (sim/bmodel/xcheck-record.json), so B numbers are
uncross-checked and are NOT entered here; the manifest declares row 2 a gap.
Rows 5, 11, 12, 13 belong to the transistor-level short-transient bench
(sim/modulator-tran), whose raw `klt sim` report was not retained
(`.artifacts/` is gitignored), so no envelope can cite it; the manifest
declares those rows gaps too. This envelope therefore covers exactly the rows
model B can honestly carry: 1 (bandwidth 20 kHz) and 4 (OSR 128).

Read-only over the committed sweep records and the cross-check record; writes
the envelope (refuses to overwrite; delete it first for a regeneration).

    python3 -I sim/bmodel/make_item5_envelope.py
"""
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
ENVELOPE = HERE / "item5-model-run.json"
XCHECK = HERE / "xcheck-record.json"

# corner_id -> committed long-record sweep (run.py --corner-file, N=2^16)
RECORDS = {
    "tt/1.800V/27C": "sim/bmodel/records/20261116T202526Z-155d8e27.json",
    "ss/1.620V/125C": "sim/bmodel/records/20261116T202548Z-9b6f3f72.json",
    "ss/1.620V/-40C": "sim/bmodel/records/20261116T202610Z-a11dab73.json",
    "ff/1.980V/-40C": "sim/bmodel/records/20261116T202631Z-99e68069.json",
    "ff/1.980V/125C": "sim/bmodel/records/20261116T202652Z-7b6364c6.json",
    "sf/1.800V/27C": "sim/bmodel/records/20261116T202713Z-4a489626.json",
    "fs/1.800V/27C": "sim/bmodel/records/20261116T202736Z-24b179e2.json",
}


def sha256_file(rel):
    return "sha256:" + hashlib.sha256((REPO / rel).read_bytes()).hexdigest()


def build_records(recs):
    """The per-record provenance block: one entry per committed record.

    Every derived field is read from the record the entry names; main()
    re-derives them from the file on disk and refuses the envelope if any
    entry disagrees.
    """
    records = []
    for cid, rel in RECORDS.items():
        rec = recs[cid]
        records.append({
            "corner_id": cid,
            "file": rel,
            "sha256": sha256_file(rel),
            "corner_params_file": rec.get("corner_params_file", {}).get("path"),
            "corner_params_sha256": rec.get("corner_params_file", {}).get("sha256"),
            "peak_sndr_db_uncross_checked": rec["peak_sndr_db"],
            "cross_check": rec["cross_check"],
        })
    return records


def check_records(records):
    """Re-derive every records[] entry from the file it names; exit on drift.

    The first revision of this block was a comprehension that referenced a
    leaked outer name, so every entry carried the last RECORDS entry's
    values while `corner_id`/`file` stayed correctly bound -- six corners'
    peak SNDR attributed to the wrong corner and two ss corners' span
    failures replaced by a passing string. Reading the fields back from the
    file each entry's own `file` names catches exactly that: the derived
    fields and the `file` are bound independently.
    """
    for entry in records:
        rec = json.loads((REPO / entry["file"]).read_text())
        for key, want in (
            ("corner_params_file", rec.get("corner_params_file", {}).get("path")),
            ("corner_params_sha256", rec.get("corner_params_file", {}).get("sha256")),
            ("peak_sndr_db_uncross_checked", rec["peak_sndr_db"]),
            ("cross_check", rec["cross_check"]),
        ):
            got = entry[key]
            if got != want:
                sys.exit(
                    f"refusing: records[] entry for {entry['corner_id']} carries "
                    f"{key} = {got!r}, but {entry['file']} says {want!r}"
                )
    return records


def main():
    recs = {cid: json.loads((REPO / rel).read_text()) for cid, rel in RECORDS.items()}

    # Every record must agree on the two covered rows and carry the corner
    # the envelope names; anything else is a stale-record error, not an
    # envelope with quietly wrong values.
    for cid, rec in recs.items():
        if rec["corner"] != cid:
            sys.exit(f"refusing: {RECORDS[cid]} records corner {rec['corner']!r}, expected {cid!r}")
        if rec["band_hz"] != [0, 20000.0]:
            sys.exit(f"refusing: {RECORDS[cid]} band {rec['band_hz']}, expected [0, 20000.0]")
        if rec["oversampling_ratio"] != 128:
            sys.exit(f"refusing: {RECORDS[cid]} OSR {rec['oversampling_ratio']}, expected 128")

    row1 = {"name": "band_bw_hz", "spec_row": "1", "status": "pass",
            "limits": {"min": 20000.0}, "value": 20000.0,
            "what": "analysed band of the committed records: 0-20 kHz, DC and "
                    "tone-lobe bins excluded; set by fout/4 at OSR 128"}
    row4 = {"name": "oversampling_ratio", "spec_row": "4", "status": "pass",
            "limits": {"min": 128, "max": 128}, "value": 128,
            "what": "modulator clock 5.12 MHz, decimation 128 -> fout 40 kSps "
                    "(fallback row in the spec table); the loop and decimator "
                    "configuration every committed record stamps"}

    corners = []
    for cid, rel in RECORDS.items():
        rec = recs[cid]
        corners.append({
            "corner_id": cid,
            "status": "pass",
            "measurements": [
                dict(row1, value=float(rec["band_hz"][1])),
                dict(row4, value=rec["oversampling_ratio"]),
            ],
        })

    doc = {
        "schema_version": 1,
        "kind": "model-run",
        "status": "pass",
        "method": (
            "behavioural model B (sim/bmodel/model.py: second-order single-bit "
            "delaying-integrator loop) loaded with the per-corner T-extracted "
            "parameters (sim/bmodel/corners/, one file per DR-002 anchor, "
            "every parameter's T record and hash named), swept over 12 "
            "amplitudes at N = 2^16 output samples, Blackman-Harris 4-term, "
            "coherent tone. klt does not execute this model "
            "(executed_by_klt: false on the citation). The rows covered here "
            "are configuration the records stamp directly; row 2 (peak SNDR) "
            "is deliberately NOT carried: every corner's DR-001 cross-check "
            "is incomplete (sim/bmodel/xcheck-record.json), so the B numbers "
            "are uncross-checked and the manifest declares row 2 a gap."),
        "measurements": [row1, row4],
        "corners": corners,
        "records": check_records(build_records(recs)),
        "provenance": {
            "input": {
                "path": {
                    "path": "sim/bmodel/xcheck-record.json",
                    "scope": "repo",
                },
                "content_hash": sha256_file("sim/bmodel/xcheck-record.json"),
            },
        },
    }

    if ENVELOPE.exists():
        sys.exit(f"refusing to overwrite {ENVELOPE}; delete it first for a regeneration")
    ENVELOPE.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {ENVELOPE}")


if __name__ == "__main__":
    main()

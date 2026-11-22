#!/usr/bin/env bash
# Reproduce layout/digital/erc-decimator.report.json (issue #333).
# Usage: layout/digital/run_erc.sh [--check | --rerun]   (run from anywhere)
# Default: regenerate the report (the routed decimator's supply evidence for
# T1 item 11 digital: one island per declared supply, the VDDD/VPWR and
# VSSD/VGND same_net_as joins, the unlabelled-strap remainder, and the
# n-well/substrate ties through the tapvpwrvgnd cells). Antenna ratios are
# not graded (no --pdk), so klt erc exits 4 with status "not_checked" by
# design -- gate on erc_status, which this script does: the report is kept
# only when erc_status is "clean". --check: klt erc's native re-hash check
# of the committed report's layout/spec hashes (exit 0 consistent, 3
# drifted, no re-analysis). --rerun: --check plus a full re-run whose
# erc_findings and erc_coverage are diffed against the committed report.
# klt is pinned by .github/klt-version; klt runs from layout/digital/
# because the committed report records the spec's request-relative path,
# which `klt erc --check` resolves against the current directory.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
KLT_VERSION="$(cat "$REPO_ROOT/.github/klt-version")"
klt() { uvx --from "klayout-tools==${KLT_VERSION}" klt "$@"; }
GDS=decimator.gds
SPEC=erc_request.json
REPORT=erc-decimator.report.json
cd "$HERE"
case "${1:-}" in
  "")
    rc=0
    klt erc "$GDS" "$SPEC" --top decimator --deck sky130 \
      --omit-antenna-tables --format json > "$REPORT.tmp" || rc=$?
    # exit 4 = antenna "not_checked" (no --pdk) with findings still reported.
    if [ "$rc" -eq 0 ]; then
      rm -f "$REPORT.tmp"
      echo "klt erc exited 0, expected 4 (antenna not_checked) -- the klt exit-code contract changed; the committed report was NOT regenerated" >&2
      exit 1
    fi
    if [ "$rc" -ne 4 ]; then
      echo "klt erc failed (exit $rc):" >&2
      cat "$REPORT.tmp" >&2 || true; rm -f "$REPORT.tmp"
      exit "$rc"
    fi
    python3 -I - "$REPORT" <<'PY' || { rm -f "$REPORT.tmp"; exit 1; }
import json, sys
rep = json.load(open(sys.argv[1] + ".tmp"))
status = rep.get("erc_status")
if status != "clean":
    sys.exit(f"erc_status is {status!r}, not 'clean' -- a finding is a real result (issue #333 step 3)")
print("erc_status:", status, "| findings:", rep.get("erc_finding_count"))
PY
    mv "$REPORT.tmp" "$REPORT"
    ;;
  --check) klt erc --check "$REPORT" ;;
  --rerun) klt erc --check "$REPORT" --rerun ;;
  *) echo "usage: $0 [--check | --rerun]" >&2; exit 2 ;;
esac

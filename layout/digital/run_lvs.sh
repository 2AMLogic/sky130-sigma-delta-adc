#!/usr/bin/env bash
# Reproduce layout/digital/lvs-decimator.report.json (issue #161).
# Usage: layout/digital/run_lvs.sh [--check | --rerun]   (run from anywhere)
# Default: regenerate the report (about 30 minutes; layout extraction of the
# 5331 abstracted cell instances dominates). --check: klt lvs's native
# re-hash check of the committed report's layout/reference/deck hashes
# (exit 0 consistent, 3 drifted, no compare re-run). --rerun: --check plus a
# full compare re-run whose verdict-bearing fields are diffed against the
# committed report. klt is pinned by .github/klt-version.
# klt runs from layout/digital/ because the committed report records the
# reference netlist's request-relative path, which `klt lvs --check` resolves
# against the current directory.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
KLT_VERSION="$(cat "$REPO_ROOT/.github/klt-version")"
klt() { uvx --from "klayout-tools==${KLT_VERSION}" klt "$@"; }
REQUEST=lvs_request.json
REPORT=lvs-decimator.report.json
cd "$HERE"
case "${1:-}" in
  "")      klt lvs "$REQUEST" --format json > "$REPORT" ;;
  --check) klt lvs --check "$REPORT" ;;
  --rerun) klt lvs --check "$REPORT" --rerun ;;
  *) echo "usage: $0 [--check | --rerun]" >&2; exit 2 ;;
esac

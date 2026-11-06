#!/usr/bin/env bash
# Reproduce layout/digital/drc-decimator.report.json (issue #82).
# Usage: layout/digital/run_drc.sh [--check]   (run from anywhere)
# Default: regenerate the report. --check: re-run and compare verdict and
# deck/input content hashes against the committed report.
# klt is pinned by .github/klt-version; the run takes about 3.5 minutes.
set -euo pipefail
cd "$(dirname "$0")/../.."
KLT_VERSION="$(cat .github/klt-version)"
klt() { uvx --from "klayout-tools==${KLT_VERSION}" klt "$@"; }
GDS=layout/digital/decimator.gds
REPORT=layout/digital/drc-decimator.report.json
if [ "${1:-}" = "--check" ]; then
  tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
  klt drc "$GDS" --deck sky130 --top decimator --format json > "$tmp"
  python3 -I - "$tmp" "$REPORT" <<'PY'
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
keys = lambda d: (d["status"], d["violation_count"],
                  d["provenance"]["deck"]["content_hash"],
                  d["provenance"]["input"]["content_hash"])
if keys(a) != keys(b):
    sys.exit(f"DRC report drift: fresh {keys(a)} != committed {keys(b)}")
print("DRC report reproduces:", keys(a))
PY
else
  klt drc "$GDS" --deck sky130 --top decimator --format json > "$REPORT"
fi

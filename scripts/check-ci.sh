#!/usr/bin/env bash
#
# Local gate: run the tool-free checks CI already runs (issue #104).
#
# This is what `npm run check:ci` / `npm test` resolve to, and it is the test
# command a Builder records locally. It mirrors the "no EDA tools" steps of
# .github/workflows/signoff.yml so that a green local gate means those tests
# actually ran.
#
# Deliberately NOT here: the klt steps (`klt signoff --attest 9/10`, the signoff
# re-run), the smoke runners and `run_synth.py`. They need the pinned klt,
# ngspice, iverilog, yosys or the PDK; CI is their gate.
#
# Adding a tool-free step to the workflow? Add it to CHECKS below too — the
# drift guard at the end of this file fails if the two lists diverge, which is
# the recurrence this script exists to prevent (the suites and response.py
# landed after the gate was written, and the gate was never revisited).
#
# Usage: scripts/check-ci.sh        (from anywhere; it cd's to the repo root)

set -uo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo_root" || exit 1

WORKFLOW=".github/workflows/signoff.yml"

# The tool-free checks, as "<cwd>|<command>", in workflow order.
# Each command is byte-identical to the workflow's so the two lists can be
# compared by eye (and by the drift guard). `python3` is rewritten to the
# interpreter chosen below at run time.
CHECKS=(
  ".|python3 -I attestation/item8_envelope.py --check"
  ".|python3 -I -m unittest discover -s sim/bmodel -p 'test_*.py'"
  ".|python3 -I -m unittest discover -s sim -p 'test_settling*.py'"
  ".|python3 -I -m unittest discover -s sim/integrator-settling -p 'test_*.py'"
  ".|python3 -I -m unittest discover -s sim/integrator-ci -p 'test_*.py'"
  "verification/decimator|python3 response.py"
)

# Workflow commands that look tool-free to the drift guard (they invoke
# `python3 -I` or `python3 response.py`) but are deliberately not run locally.
# Keep empty unless a real case appears; say why in a comment when adding one.
WORKFLOW_ONLY=()

# ---------------------------------------------------------------------------
# Interpreter: prefer the repo-local .venv the README's Reproduce step creates,
# fall back to the host python3 (some hosts carry numpy system-wide, the fleet
# workers may not). numpy is required by the bmodel suite and response.py, so
# probe for it and fail loudly rather than skipping checks.
# ---------------------------------------------------------------------------
if [ -x "$repo_root/.venv/bin/python" ]; then
  PY="$repo_root/.venv/bin/python"
  PY_LABEL=".venv/bin/python"
else
  PY="$(command -v python3 || true)"
  PY_LABEL="python3"
fi

if [ -z "$PY" ]; then
  echo "check:ci: FAIL - no python3 found on PATH and no $repo_root/.venv" >&2
  exit 1
fi

if ! "$PY" -I -c "import numpy" >/dev/null 2>&1; then
  cat >&2 <<EOF
check:ci: FAIL - numpy is not importable by $PY_LABEL.

The behavioural-model suite (sim/bmodel) and verification/decimator/response.py
need numpy ($(grep -v '^#' sim/bmodel/requirements.txt | tr -d '[:space:]')).
These checks are not skipped: the gate fails so a local pass cannot mean
"the tests did not run".

Create the repo-local venv the README's Reproduce section specifies, then
re-run (this script prefers .venv/bin/python when it exists):

  uv venv .venv && uv pip install --python .venv/bin/python numpy==1.26.4 cocotb==2.1.0

Host-wide installs are not an option on the shared fleet workers.
EOF
  exit 1
fi

echo "check:ci: $PY_LABEL ($("$PY" -V 2>&1), numpy $("$PY" -I -c 'import numpy;print(numpy.__version__)'))"

# ---------------------------------------------------------------------------
# The checks CI runs that need no EDA tools, in order, stopping at the first
# failure. Plus the committed-JSON parse the gate has always done.
# ---------------------------------------------------------------------------
total=$(( ${#CHECKS[@]} + 1 ))
step=0

run_step() {
  local label="$1" cwd="$2" cmd="$3" rc=0
  step=$(( step + 1 ))
  printf '\n[%d/%d] %s\n' "$step" "$total" "$label"
  if [ "$cwd" != "." ]; then
    printf '      (cd %s) %s\n' "$cwd" "$cmd"
  else
    printf '      %s\n' "$cmd"
  fi
  ( cd -- "$repo_root/$cwd" && eval "$cmd" ) || rc=$?
  if [ "$rc" -ne 0 ]; then
    printf '\ncheck:ci: FAIL - step %d/%d exited %d: %s\n' "$step" "$total" "$rc" "$cmd" >&2
    exit "$rc"
  fi
}

run_step "committed JSON parses" "." \
  "'$PY' -I -c \"import json,pathlib; fs=sorted(pathlib.Path('manifests').rglob('*.json')); assert fs, 'no manifests found'; [json.load(open(f)) for f in fs]; print('ok:', len(fs), 'manifest JSON files parse')\""

for entry in "${CHECKS[@]}"; do
  cwd="${entry%%|*}"
  cmd="${entry#*|}"
  run_step "workflow step: $cmd" "$cwd" "${cmd/#python3/$PY}"
done

# ---------------------------------------------------------------------------
# Drift guard: every `python3 -I ...` / `python3 response.py` command in the
# workflow must appear in CHECKS (or WORKFLOW_ONLY). This is the mechanism that
# keeps the local gate from silently falling behind CI again.
# ---------------------------------------------------------------------------
step=$(( step + 1 ))
printf '\n[drift] %s tool-free command list matches CHECKS\n' "$WORKFLOW"

if [ ! -f "$WORKFLOW" ]; then
  echo "check:ci: FAIL - $WORKFLOW not found; cannot verify the gate is in step with CI" >&2
  exit 1
fi

declared="$(
  { printf '%s\n' "${CHECKS[@]}" | sed 's/^[^|]*|//'
    if [ "${#WORKFLOW_ONLY[@]}" -gt 0 ]; then printf '%s\n' "${WORKFLOW_ONLY[@]}"; fi
  } | sort -u
)"

in_workflow="$(
  grep -ohE "python3 -I [^|&;]*|python3 response\.py" "$WORKFLOW" |
    sed 's/[[:space:]]*$//' | sort -u
)"

if [ -z "$in_workflow" ]; then
  echo "check:ci: FAIL - found no tool-free python3 commands in $WORKFLOW; the drift guard cannot have checked anything" >&2
  exit 1
fi

missing="$(comm -13 <(printf '%s\n' "$declared") <(printf '%s\n' "$in_workflow"))"
extra="$(comm -23 <(printf '%s\n' "$declared") <(printf '%s\n' "$in_workflow"))"

if [ -n "$missing" ] || [ -n "$extra" ]; then
  {
    echo
    echo "check:ci: FAIL - this gate has drifted from $WORKFLOW."
    if [ -n "$missing" ]; then
      echo
      echo "  In the workflow but not run locally -- add to CHECKS in $0"
      echo "  (or to WORKFLOW_ONLY, with a comment, if it needs EDA tools):"
      printf '%s\n' "$missing" | sed 's/^/    /'
    fi
    if [ -n "$extra" ]; then
      echo
      echo "  Declared here but no longer in the workflow -- remove from CHECKS in $0:"
      printf '%s\n' "$extra" | sed 's/^/    /'
    fi
    echo
    echo "  Note: the guard only sees workflow commands written as 'python3 -I ...'"
    echo "  or 'python3 response.py'. A tool-free step written another way needs"
    echo "  adding to CHECKS by hand."
  } >&2
  exit 1
fi

printf '      ok: %d tool-free workflow commands, all run above\n' "$(printf '%s\n' "$in_workflow" | wc -l | tr -d ' ')"

printf '\ncheck:ci: PASS - %d checks\n' "$total"

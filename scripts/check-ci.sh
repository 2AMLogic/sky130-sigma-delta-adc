#!/usr/bin/env bash
#
# The gate: the tool-free checks CI runs, plus the two attestation re-hash
# steps (issue #308). The commands are written once — in this script — and
# .github/workflows/signoff.yml calls this script for its no-EDA steps, so
# a green local gate and a green `signoff` job are the same checks (see the
# "One source for a gate" ruling: the workflow never holds a second copy of
# the list, and nothing compares the two).
#
# This is what `npm run check:ci` / `npm test` resolve to, and it is the test
# command a Builder records locally.
#
# Also here: `klt signoff --attest 9/10 ... --check ...` (#308). --check skips
# the local_only cold_start bench and only re-hashes, so these steps need no
# EDA tools — just the pin in .github/klt-version, taken from PATH when klt
# already reports that exact version (CI pip-installs the pin) and through
# `uvx --from` otherwise, exactly how attestation/README.md regenerates.
# These are the steps that caught the twice-failed item-9 envelope drift on
# PR #306, and the ones authors never ran before pushing.
#
# Still NOT here: the full signoff re-run (it executes the bench), the
# workflow-only steps signoff.yml keeps (checkout/setup-python/pip installs,
# the pyflakes + compile gate, the wider committed-JSON walk, the signoff
# byte-compare), the smoke runners and `run_synth.py`. They need ngspice,
# iverilog, yosys or the PDK; CI is their gate.
#
# Adding a tool-free check to CI? Add a `python3 -I ...` command to CHECKS or
# a `klt signoff ... --check ...` command to KLT_CHECKS below — the workflow
# then runs it here and on the forge, and nowhere else needs editing.
#
# Usage: scripts/check-ci.sh        (from anywhere; it cd's to the repo root)

set -uo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo_root" || exit 1

# The tool-free checks, as "<cwd>|<command>". `python3` is rewritten to the
# interpreter chosen below at run time.
CHECKS=(
  # Item 8 (characterization report): the pinned klt's --attest takes only
  # items 1, 9 and 10, so attestation/item8_envelope.py regenerates the
  # generic envelope from measurements/characterization.md in memory and
  # fails if the committed one differs (a hand-edited verdict, a cited
  # record that changed, a missing file, a pending row with no issue).
  ".|python3 -I attestation/item8_envelope.py --check"
  # The grammar the check above enforces, in particular that a
  # `declared-gap` row cites the ratified record that declares it and never
  # reads as evidence (issue #131). Fixtures only: no EDA tools.
  ".|python3 -I -m unittest discover -s attestation -p 'test_*.py'"
  ".|python3 -I -m unittest discover -s manifests -p 'test_check_content_hashes.py'"
  # The manifest's content_hash pins are the claim that a citation names
  # a particular declared input, and klt signoff verifies a citation's
  # pin only against the cited file's provenance.input.content_hash --
  # a pin on a file with no provenance block is a latent blocker it
  # grades unverifiable_provenance (masked while the item also fails its
  # own check; issue #155). This asserts the repo invariant directly, in
  # both directions: a citation declares a pin iff the cited file carries
  # provenance.input.content_hash and equals it -- a missing pin where the
  # file carries one fails too (issue #215); a not_applicable spec/statement
  # binding pins the cited file's own sha256. Runs before the workflow's
  # byte-compare step so a violation names the offending key.
  ".|python3 -I manifests/check_content_hashes.py"
  ".|python3 -I -m unittest discover -s manifests -p 'test_check_prose_counts.py'"
  # The status documents hand-state the record's headline counts
  # ("N met, M not applicable, K unmet"), which is how ROADMAP.md said
  # 9 / 1 / 12 beside a record reading 10 / 1 / 11 through two regrades
  # (issue #221). This derives the counts from the record's t1_*
  # fields and fails on any sentence in README.md or ROADMAP.md that
  # disagrees; a file with no count sentence asserts nothing. Same
  # fixtures-only shape as the content-hash gate above.
  ".|python3 -I manifests/check_prose_counts.py"
  # Item 6 (digital partition) is discharged by a recorded
  # `not_applicable`, which klt signoff hash-binds to two JSON files under
  # spec/. klt cannot see that those files are a projection of the ratified
  # Markdown, so this binds that last link: it re-derives the row
  # projection from spec/modulator-adc.md section 1.1 and fails if the
  # Markdown no longer hashes to the value recorded in the projection.
  # Editing the ratified spec therefore invalidates the claim loudly.
  # Runs before the workflow's byte-compare step so the failure names the
  # cause.
  ".|python3 -I -m unittest discover -s spec -p 'test_*.py'"
  # Behavioural model unit tests.
  ".|python3 -I -m unittest discover -s sim/bmodel -p 'test_*.py'"
  # The gates that decide whether a settling record is written at all, and
  # the runner paths that admit a result into one (issue #94). Fixtures
  # only: no fleet, no ngspice, no klt.
  ".|python3 -I -m unittest discover -s sim -p 'test_settling*.py'"
  ".|python3 -I -m unittest discover -s sim/integrator-settling -p 'test_*.py'"
  # The charge-injection bench's record-admission gates and derivations
  # (issue #102), plus the checks that the committed decks/requests still
  # match their generator and that the pre-#92 comparison fixture still
  # matches the commit it names. Fixtures only: no fleet, no ngspice, no klt.
  ".|python3 -I -m unittest discover -s sim/integrator-ci -p 'test_*.py'"
  # The DC-gain and thermal-noise benches' record-admission gates and the
  # derivations their records depend on (issue #126): V/V -> dB and the
  # binding corner for the gain bench; the input referral, the V^2 -> FS^2
  # conversion, the two in-band links and the per-corner budget verdicts
  # for the noise bench. Plus the checks that the committed decks and
  # requests still match their generators. Fixtures only: no fleet, no
  # ngspice, no klt.
  ".|python3 -I -m unittest discover -s sim/ota-gain -p 'test_*.py'"
  ".|python3 -I -m unittest discover -s sim/integrator-noise -p 'test_*.py'"
  # The OTA swing/compression bench's derivations and record-admission gates
  # (issue #331, step 1 of the #148 ruling): the finite-gain inversion, the
  # compression-point interpolation (crossed and never-crossed), the
  # settled-ness and small-signal-reference gates, and the checks that the
  # committed deck/request still match their generator and the request is the
  # DR-002 anchor set. Fixtures only: no fleet, no ngspice, no klt.
  ".|python3 -I -m unittest discover -s sim/ota-swing -p 'test_*.py'"
  # The comparator bench's derivations (model-B unit conversion, the
  # offset/hysteresis inversion, the decision-time limit), the staircase
  # geometry, and the gates that decide whether its record is written at
  # all (issue #127). Fixtures only: no fleet, no ngspice, no klt.
  ".|python3 -I -m unittest discover -s sim/comparator-decision -p 'test_*.py'"
  # The short full-modulator transient's record-admission gates (issue
  # #125): a partial grid, a missing measurement, a short per-clock sample
  # set, a clock that did not run at fs, or two power routes that
  # disagree must each refuse the record. Also checks the committed deck
  # and request still match their generator. Fixtures only: no fleet, no
  # ngspice, no klt.
  ".|python3 -I -m unittest discover -s sim/modulator-tran -p 'test_*.py'"
  # The digital-partition P&R runner's PDK-pin refusal (issue #158): the gate
  # reads the stamp klt records at provenance.pdk.version, so a report whose
  # PDK differs from sim/pdk.json -- or that records no PDK at all -- refuses
  # with exit 2 instead of admitting an unpinned route as pinned evidence.
  # Fixtures only: subprocess.run is patched, no klt, no openroad, no PDK.
  ".|python3 -I -m unittest discover -s layout/digital -p 'test_*.py'"
  # All layout/analog suites in one directory-scoped run (issue #211
  # collapsed the two per-suite steps that overlapped here):
  # - the analog generators' DRC-verdict guard (issue #164): `klt drc` exits
  #   3 on violations but the call site passes check=False to capture the
  #   report, so the verdict is re-asserted in-process and a non-clean
  #   report aborts the flow. Fixtures only: synthetic report dicts.
  # - the shared extracted-netlist parsers in layout/analog/layout_common.py
  #   (issue #191): parse_extract_devices and extract_nets turn `klt extract`
  #   output into the device- and net-count evidence both analog cells commit
  #   (extract-device-count.json), and since #179 nothing else executes them.
  #   The suite asserts the parsers against real captured netlists
  #   (layout/analog/fixtures/) and each cell's committed evidence, and pins
  #   the _symmetric_terminals/_is_model_token predicates -- a regression in
  #   either parser restates that evidence for every analog cell at once.
  # - the Router geometry core (issue #228) and the Router methods #201
  #   unified into the shared base (issue #201): pure geometry over the
  #   shared `Router`, no fixtures.
  # Fixtures only: no klt, no PDK, no network.
  ".|python3 -I -m unittest discover -s layout/analog -p 'test_*.py'"
  # The switch probes' pure parts: that the issue #106 pass-gate sweep still
  # covers the spec row 11 input range at the resolution it claims, and that
  # the probed device pair still matches design/integrator/integrator.spice.
  # Fixtures only: no fleet, no ngspice, no klt.
  ".|python3 -I -m unittest discover -s sim/switch-probe -p 'test_*.py'"
  # Decimator whole-chain response, spec rows 8-9.
  "verification/decimator|python3 response.py"
)

# The klt attestation re-hash steps, as bare commands. Each is run through
# the pinned klt resolved below, so a pass uses exactly the klayout-tools
# version CI installs (.github/klt-version). Nothing else here may call klt:
# a full re-attest executes the bench and stays out of this gate.
KLT_CHECKS=(
  "klt signoff --attest 9 --inventory attestation/item9-inventory.json --check attestation/item9-envelope.json"
  "klt signoff --attest 10 --inventory attestation/item10-inventory.json --check attestation/item10-envelope.json"
)

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
# Pinned klt: the attestation --check steps must run the klayout-tools
# version CI installs (.github/klt-version). A PATH klt that reports exactly
# that version is used directly; anything else -- typically a host dev
# build -- goes through `uvx --from` the pin, so a local pass means the
# same producer version. Fail loudly when neither is available: these
# checks are never skipped.
# ---------------------------------------------------------------------------
if [ ! -f ".github/klt-version" ]; then
  echo "check:ci: FAIL - .github/klt-version not found; cannot pin the klt attestation checks" >&2
  exit 1
fi
KLT_PIN_VERSION="$(tr -d '[:space:]' < .github/klt-version)"
KLT_PIN="klayout-tools==$KLT_PIN_VERSION"

KLT_CMD=""
if command -v klt >/dev/null 2>&1; then
  # `klt --version` prints one line: "klt X.Y.Z" for a tagged release,
  # "klt X.Y.(Z+1).devN+g<sha>" for a dev build. Requiring the exact
  # "klt <pin>" string keeps a host dev build out of the gate.
  klt_on_path="$(klt --version 2>/dev/null || true)"
  if [ "$klt_on_path" = "klt $KLT_PIN_VERSION" ]; then
    KLT_CMD="klt"
  fi
fi

if [ -z "$KLT_CMD" ]; then
  if ! command -v uvx >/dev/null 2>&1; then
    cat >&2 <<EOF
check:ci: FAIL - no klt matching the pin on PATH and uvx is not available.

The item-9 and item-10 attestation re-hash steps (klt signoff --check) run
the klayout-tools version CI installs (.github/klt-version = $KLT_PIN_VERSION).
The klt on PATH (if any) is not that version, so they must go through
"uvx --from $KLT_PIN". These checks are not skipped: the gate fails so a
local pass cannot mean "the attestation checks did not run".

Either install uv, which provides uvx, and re-run:

  curl -LsSf https://astral.sh/uv/install.sh | sh

(or your package manager's uv package -- nothing is installed host-wide;
uvx resolves the pinned version into its own cache) -- or make the pin
itself the klt on PATH, so \`klt --version\` prints "klt $KLT_PIN_VERSION".
EOF
    exit 1
  fi
  KLT_CMD="uvx --from '$KLT_PIN' klt"
fi

# ---------------------------------------------------------------------------
# The tool-free checks, in order, stopping at the first failure. Plus the
# committed-JSON parse the gate has always done.
# ---------------------------------------------------------------------------
total=$(( ${#CHECKS[@]} + ${#KLT_CHECKS[@]} + 1 ))
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

# The klt --check steps, right after the JSON parse: --check only re-hashes,
# so these are the fastest detectors of the inventory/envelope drift that
# failed PR #306's CI twice, and failing here spares the python suites.
# The entries carry a bare leading "klt " (the command uvx would run);
# "$KLT_CMD" is that command in both branches, so the prefix is stripped
# and re-prefixed with the resolved runner.
for entry in "${KLT_CHECKS[@]}"; do
  run_step "pinned-klt step: $entry" "." "$KLT_CMD ${entry#klt }"
done

for entry in "${CHECKS[@]}"; do
  cwd="${entry%%|*}"
  cmd="${entry#*|}"
  run_step "$cmd" "$cwd" "${cmd/#python3/$PY}"
done

printf '\ncheck:ci: PASS - %d checks\n' "$total"

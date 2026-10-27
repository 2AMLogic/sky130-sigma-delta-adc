#!/bin/sh
# Cold-start invocation for the T1 item-9 testbench inventory
# (attestation/item9-inventory.json). Chains the documented bench commands from
# README "Reproduce", sim/README.md and verification/README.md; nothing new is
# measured here. Needs ngspice, iverilog, yosys, klt and uv on PATH and the
# pinned PDK (sim/pdk.json). Writes no committed record: every runner is called
# without --record, and the model-B record goes to a scratch directory.
set -eu
cd "$(dirname "$0")/.."

[ -x .venv/bin/python ] || {
    uv venv .venv
    uv pip install --python .venv/bin/python cocotb==2.1.0 -r sim/bmodel/requirements.txt
}

python3 sim/smoke/run_smoke.py
.venv/bin/python verification/smoke/run_smoke.py

scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
.venv/bin/python -I sim/bmodel/run.py --params sim/bmodel/ideal.json --out-dir "$scratch"
.venv/bin/python -I -m unittest discover -s sim/bmodel -p 'test_*.py'

.venv/bin/python verification/decimator/response.py
.venv/bin/python verification/decimator/run_synth.py

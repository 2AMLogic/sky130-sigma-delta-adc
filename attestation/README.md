# attestation

Committed evidence envelopes for the T1 tier: `item9-envelope.json`
(testbenches shipped), `item10-envelope.json` (repo hygiene) and
`item8-envelope.json` (characterization). Regenerate an envelope in the same
change that moves anything it binds; CI (`.github/workflows/signoff.yml`)
re-attests each one and byte-compares the committed tier-verdict record.

## Regenerating under the pin

Always regenerate the `--attest` envelopes under the CI pin — the same
`klayout-tools` version `.github/klt-version` declares — never under whatever
`klt` the host happens to have installed:

    uvx --from "klayout-tools==$(cat .github/klt-version)" klt signoff \
        --attest 9 --inventory attestation/item9-inventory.json \
        -o attestation/item9-envelope.json

    uvx --from "klayout-tools==$(cat .github/klt-version)" klt signoff \
        --attest 10 --inventory attestation/item10-inventory.json \
        -o attestation/item10-envelope.json

A `provenance.klt_version` that differs from `.github/klt-version` — typically
a git dev build such as `0.9.3.dev29+g…` — is a defect: it names a producer a
third party cannot reinstall from the pin, and the field oscillates between
regenerations on different hosts. If a committed envelope carries one,
regenerate it under the pin; never hand-edit the field.

Item 8 has no `--attest` in the pinned klt; `item8_envelope.py` plays that
role (regenerate with `python3 -I attestation/item8_envelope.py`). It binds
its inputs by explicit sha256 and carries no `provenance` block, so the pin
rule above does not apply to it.

## Notes for the full form

- The pre-push check is `scripts/check-ci.sh`: it is the same gate
  `.github/workflows/signoff.yml` runs (the workflow calls the script for
  its no-EDA steps, so the commands exist in exactly one place). Its item-9
  and item-10 `--check` re-hash steps run the pinned klayout-tools — the
  PATH `klt` when it reports exactly the `.github/klt-version` version, else
  `uvx --from` the pin (no bench) — so an inventory or bench-file edit
  without a regenerated envelope fails locally instead of in CI.
- Without `--check`, item 9 runs the cold_start bench
  (`cold_start_item9.sh`): ngspice, iverilog, yosys, uv and the pinned PDK
  (`sim/pdk.json`) must be on the host. `--check` — what CI runs — skips the
  local_only checks and still re-hashes every bench file and the inventory.
- A regeneration may only move `provenance.klt_version`. The check list,
  every `content_hash`, and `provenance.input.content_hash` (which the
  manifest pins at `manifests/sky130-sigma-delta-adc.json`) must come out
  byte-identical; if they moved, the inventory or a bench changed, and that
  change — not the stamp — is what the PR must justify.
- If yosys stalls at its ABC pass during the cold_start bench, check
  `TMPDIR`: the pass hangs when it points into a session-namespaced
  directory and completes in about a second pointed at a plain one
  (`TMPDIR=/tmp/<dir> uvx --from "klayout-tools==$(cat .github/klt-version)" klt …`).

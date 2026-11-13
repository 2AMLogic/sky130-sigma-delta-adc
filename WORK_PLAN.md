# Work Plan

Roadmap generated from current GitHub label state by the Guide role. Only the region between the markers is machine-generated.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#27**: T1 item 1 (design sources, analog partition): xschem schematic and derived netlist of the 2nd-order switched-capacitor modulator
- **#42**: T1 item 1 (analog 4/4): attestation inventory, manifest evidence, regenerated verdict

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#42**: T1 item 1 (analog 4/4): attestation inventory, manifest evidence, regenerated verdict
- **#102**: Extract integrator charge injection after the #92 PMOS switch halves
- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling
- **#110**: B-model records stamp a dirty base commit, not the code that produced the number

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#112**: feat(bmodel): stamp a code_sha256 map in every B-model evidence writer

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#111**: feat(sim): extract the integrator charge-injection residual and correct the sqrt(W L) argument

## Proposed

Issues carrying `loom:curated`.

- **#3**: Track the gap to T1 (klayout-tools design-evidence-tiers.md) *(curated)*
- **#42**: T1 item 1 (analog 4/4): attestation inventory, manifest evidence, regenerated verdict *(curated)*
- **#102**: Extract integrator charge injection after the #92 PMOS switch halves *(curated)*
- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling *(curated)*
- **#110**: B-model records stamp a dirty base commit, not the code that produced the number *(curated)*

## Proposed (Architect / Hermit)

- **#43**: Deduplicate PDK-pin helpers copy-pasted across three runners *(hermit)*
- **#81**: Consolidate 7 copies of the klt pdk find lookup into one helper *(hermit)*
- **#95**: Share the settling measurement list between the OTA and integrator benches: two copies, one already out of step with its request *(hermit)*
- **#96**: Remove sim/toolchain.json: a tool-version pin file that no code reads and that has gone stale *(hermit)*
- **#103**: Prune .gitignore rules that match nothing, and ignore the build scratch the cocotb runners actually leave *(hermit)*
- **#104**: Make npm test run the tool-free tests CI already runs: check:ci parses two JSON files and runs no tests *(hermit)*
- **#105**: Share the pasted helpers in the issue #92 probe runners: three copies of the SPICE line joiner, two of the figure-of-merit block *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 2 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 4 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 1 |
| Curated | 5 |
| Architect / Hermit proposals | 7 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

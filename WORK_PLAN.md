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
- **#92**: Integrator cell does not settle at Vdda=1.62 V (0/15 corners, both load variants): diagnose, then fix the OTA or the switches

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#92**: Integrator cell does not settle at Vdda=1.62 V (0/15 corners, both load variants): diagnose, then fix the OTA or the switches

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#3**: Track the gap to T1 (klayout-tools design-evidence-tiers.md) *(curated)*
- **#42**: T1 item 1 (analog 4/4): attestation inventory, manifest evidence, regenerated verdict *(curated)*
- **#92**: Integrator cell does not settle at Vdda=1.62 V (0/15 corners, both load variants): diagnose, then fix the OTA or the switches *(curated)*

## Proposed (Architect / Hermit)

- **#43**: Deduplicate PDK-pin helpers copy-pasted across three runners *(hermit)*
- **#81**: Consolidate 7 copies of the klt pdk find lookup into one helper *(hermit)*
- **#91**: Fold attest/ and evidence/ into attestation/: three directory conventions for one kind of file *(hermit)*
- **#95**: Share the settling measurement list between the OTA and integrator benches: two copies, one already out of step with its request *(hermit)*
- **#96**: Remove sim/toolchain.json: a tool-version pin file that no code reads and that has gone stale *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 3 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 0 |
| Curated | 3 |
| Architect / Hermit proposals | 5 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

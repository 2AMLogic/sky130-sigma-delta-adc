# Work Plan

Roadmap generated from current GitHub label state by the Guide role. Only the region between the markers is machine-generated.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#23**: docs(spec): grade decimation stopband (row 9): 90 dB in alias bands, 75 dB floor elsewhere, DR-006

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#40**: T1 item 1 (analog 2/4): SC integrator and 1-bit feedback DAC, schematic and netlist

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#18**: Spec owner: confirm row 9 stopband reading (alias bands vs every frequency fout-BW..fs/2)
- **#28**: T1 item 1 (design sources, digital partition): commit the decimator gate-level netlist and attest the RTL + netlist inventory
- **#36**: T1 item 9 (testbenches shipped): testbench inventory over the smoke, model B, decimator and modulator benches, attested with klt signoff --attest 9
- **#48**: Follow-on from PR #45: OTA slew-rate risk (~10 V/us vs 0.45 V per-side worst-case step)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#23**: docs(spec): grade decimation stopband (row 9): 90 dB in alias bands, 75 dB floor elsewhere, DR-006
- **#46**: feat: attest digital T1 item 1 with committed synthesized decimator netlist

## Proposed

Issues carrying `loom:curated`.

- **#3**: Track the gap to T1 (klayout-tools design-evidence-tiers.md) *(curated)*
- **#28**: T1 item 1 (design sources, digital partition): commit the decimator gate-level netlist and attest the RTL + netlist inventory *(curated)*
- **#36**: T1 item 9 (testbenches shipped): testbench inventory over the smoke, model B, decimator and modulator benches, attested with klt signoff --attest 9 *(curated)*
- **#48**: Follow-on from PR #45: OTA slew-rate risk (~10 V/us vs 0.45 V per-side worst-case step) *(curated)*

## Proposed (Architect / Hermit)

- **#43**: Deduplicate PDK-pin helpers copy-pasted across three runners *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 0 |
| Important | 1 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 4 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 2 |
| Curated | 4 |
| Architect / Hermit proposals | 1 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

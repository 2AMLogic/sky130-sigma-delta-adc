# Work Plan

Roadmap generated from current GitHub label state by the Guide role. Only the region between the markers is machine-generated.

<!-- guide:plan-body:start -->
_Generated: 2026-11-28T11:47:17Z (snapshot; compare against live labels)_
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — a human merge decision, or the prerequisite shown, is missing.

- **#402**: chore: resync installed Loom surfaces *(held: champion merge-risk hold)*
- **#257**: feat(design): rescale integrators to C1=C2=0.3 and record DR-007 *(held: champion ratification hold)*
- **#199**: comparator-decision: settle the sf/1.620V/-40C trip corner by measurement (DR-007, grounds reporting) *(held: champion ratification hold)*
- **#175**: docs(spec): add DR-009 amplifier 1/f line to the 5.3 noise budget, total unchanged *(held: champion ratification hold)*
- **#115**: fix(spec): correct the section 5.1 ideal ceiling for the single-bit full-scale convention *(held: champion ratification hold)*

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#148**: Integrator output swing exceeds spec 5.4 at every DR-002 anchor: the loop's 0.5/0.5 scaling rails integrator 1

## Important

`loom:important`; taken before unlabelled work.

- **#29**: T1 item 2 (layout, analog partition): modulator layout per the DR-004 floorplan, generated GDS *(held)*
- **#121**: Analog layout 3/3: generated GDS of the non-overlapping clock generator cell (clkgen) *(held)*
- **#138**: First integrator misses the spec 5.3 total-thermal noise budget by 16-18 dB at all 45 corners: OTA flicker noise dominates, and 5.3 has no 1/f allocation *(held)*
- **#142**: Decision record: add an amplifier 1/f line to the spec 5.3 noise budget without changing the 80 dB total
- **#143**: First integrator: cut OTA flicker noise to the spec 5.3 line (resize the 1/f-dominant devices, or a flicker-cancelling stage) and re-run the OTA-dependent benches *(held)*
- **#330**: Bump the klt pin to the first release containing klayout-tools PR 6059, record the DR-008 re-read, and un-park #121 (clkgen layout) *(held)*

## Ready

Human-approved issues (`loom:issue`) ready for implementation — excluding held (`loom:blocked`/`loom:operator`/`loom:frozen`), `loom:building`, and issues with an open linked PR (native admission `OPEN_PR`; listed under Issues with Open PRs).

_None._

## Issues with Open PRs (Not Dispatchable)

`loom:issue` issues an open linked PR already holds — native admission would refuse them (`OPEN_PR`); listed with the PR and its stage, not counted above.

- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling — open PR #115 (held)

## In Progress

Issues currently being built (`loom:building`).

- **#142**: Decision record: add an amplifier 1/f line to the spec 5.3 noise budget without changing the 80 dB total
- **#150**: comparator-decision: the trip staircase does not bracket the comparator's trip point at sf/1.620V/-40C

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review (`loom:pr`); unmarked PRs are queued for Champion auto-merge, PRs marked `*(held …)*` are not (the hold decides).

- **#402**: chore: resync installed Loom surfaces *(held: champion merge-risk hold)*
- **#257**: feat(design): rescale integrators to C1=C2=0.3 and record DR-007 *(held: champion ratification hold)*
- **#199**: comparator-decision: settle the sf/1.620V/-40C trip corner by measurement (DR-007, grounds reporting) — closes #150 *(held: champion ratification hold)*
- **#175**: docs(spec): add DR-009 amplifier 1/f line to the 5.3 noise budget, total unchanged — closes #142 *(held: champion ratification hold)*
- **#115**: fix(spec): correct the section 5.1 ideal ceiling for the single-bit full-scale convention — closes #108 *(held: champion ratification hold)*

## Proposed

Issues carrying `loom:curated`.

- **#3**: Track the gap to T1 (klayout-tools design-evidence-tiers.md) *(curated)*
- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling *(curated)*
- **#121**: Analog layout 3/3: generated GDS of the non-overlapping clock generator cell (clkgen) *(curated)* *(held)*
- **#142**: Decision record: add an amplifier 1/f line to the spec 5.3 noise budget without changing the 80 dB total *(curated)*
- **#150**: comparator-decision: the trip staircase does not bracket the comparator's trip point at sf/1.620V/-40C *(curated)*
- **#290**: DR-001 decision-record change: ratify the long-record cross-check leg that row 2's remaining evidence waits on *(curated)* *(held)*

## Proposed (Architect / Hermit)

- **#400**: Consolidate Router add_met1, add_met, and columns into layout_common.Router *(hermit)* *(held)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 5 |
| Very important | 1 |
| Important | 6 |
| Ready (`loom:issue`, net of holds/building/open-linked-PRs) | 0 |
| In Progress (`loom:building`) | 2 |
| Held, no other bucket | 16 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 5 |
| Curated | 6 |
| Architect / Hermit proposals | 1 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

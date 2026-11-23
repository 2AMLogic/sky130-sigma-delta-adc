# Work Plan

Roadmap generated from current GitHub label state by the Guide role. Only the region between the markers is machine-generated.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#115**: fix(spec): correct the section 5.1 ideal ceiling for the single-bit full-scale convention
- **#199**: comparator-decision: settle the sf/1.620V/-40C trip corner by measurement (DR-007, grounds reporting)
- **#257**: feat(design): rescale integrators to C1=C2=0.3 and record DR-007

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#148**: Integrator output swing exceeds spec 5.4 at every DR-002 anchor: the loop's 0.5/0.5 scaling rails integrator 1

## Important

`loom:important`; taken before unlabelled work.

- **#29**: T1 item 2 (layout, analog partition): modulator layout per the DR-004 floorplan, generated GDS
- **#121**: Analog layout 3/3: generated GDS of the non-overlapping clock generator cell (clkgen)
- **#138**: First integrator misses the spec 5.3 total-thermal noise budget by 16-18 dB at all 45 corners: OTA flicker noise dominates, and 5.3 has no 1/f allocation
- **#142**: Decision record: add an amplifier 1/f line to the spec 5.3 noise budget without changing the 80 dB total
- **#143**: First integrator: cut OTA flicker noise to the spec 5.3 line (resize the 1/f-dominant devices, or a flicker-cancelling stage) and re-run the OTA-dependent benches
- **#330**: Bump the klt pin to the first release containing klayout-tools PR 6059, record the DR-008 re-read, and un-park #121 (clkgen layout)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#95**: Share the settling measurement list between the OTA and integrator benches: two copies, one already out of step with its request
- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling
- **#142**: Decision record: add an amplifier 1/f line to the spec 5.3 noise budget without changing the 80 dB total
- **#150**: comparator-decision: the trip staircase does not bracket the comparator's trip point at sf/1.620V/-40C
- **#370**: ROADMAP.md's status stamp drifts while its counts are CI-gated
- **#376**: Consolidate PDK-pin resolve_root and REFUSE blocks across 15 runners (re-file of #43)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#366**: refactor: share the settling measurement list in settling_common
- **#371**: docs: drop ROADMAP's drifting status stamp; graded record states as-of-ness
- **#383**: refactor: share every PDK-pin call site as settling_common helpers

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#115**: fix(spec): correct the section 5.1 ideal ceiling for the single-bit full-scale convention
- **#175**: docs(spec): add DR-009 amplifier 1/f line to the 5.3 noise budget, total unchanged
- **#199**: comparator-decision: settle the sf/1.620V/-40C trip corner by measurement (DR-007, grounds reporting)
- **#257**: feat(design): rescale integrators to C1=C2=0.3 and record DR-007

## Proposed

Issues carrying `loom:curated`.

- **#3**: Track the gap to T1 (klayout-tools design-evidence-tiers.md) *(curated)*
- **#95**: Share the settling measurement list between the OTA and integrator benches: two copies, one already out of step with its request *(curated)*
- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling *(curated)*
- **#121**: Analog layout 3/3: generated GDS of the non-overlapping clock generator cell (clkgen) *(curated)*
- **#142**: Decision record: add an amplifier 1/f line to the spec 5.3 noise budget without changing the 80 dB total *(curated)*
- **#150**: comparator-decision: the trip staircase does not bracket the comparator's trip point at sf/1.620V/-40C *(curated)*
- **#290**: DR-001 decision-record change: ratify the long-record cross-check leg that row 2's remaining evidence waits on *(curated)*
- **#370**: ROADMAP.md's status stamp drifts while its counts are CI-gated *(curated)*

## Proposed (Architect / Hermit)

- **#96**: Remove sim/toolchain.json: a tool-version pin file that no code reads and that has gone stale *(hermit)*
- **#367**: Remove the write-only metal-1 placement list from the analog routers *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 3 |
| Very important | 1 |
| Important | 6 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 6 |
| PRs awaiting review | 3 |
| Approved PRs awaiting merge | 4 |
| Curated | 8 |
| Architect / Hermit proposals | 2 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

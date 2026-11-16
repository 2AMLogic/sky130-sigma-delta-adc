# Work Plan

Roadmap generated from current GitHub label state by the Guide role. Only the region between the markers is machine-generated.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#115**: fix(spec): correct the section 5.1 ideal ceiling for the single-bit full-scale convention
- **#175**: docs(spec): add DR-009 amplifier 1/f line to the 5.3 noise budget, total unchanged
- **#199**: comparator-decision: settle the sf/1.620V/-40C trip corner by measurement (DR-007, grounds reporting)
- **#213**: ci: run the item-8 cited-issue check on every push and pull request
- **#220**: chore(loom): resync installed Loom to v0.19.1302

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
- **#162**: T1 item 7, digital only: SDF-annotated klt functional-verification of the routed decimator, cited for 7.digital
- **#169**: Confirm klayout-tools#1962 actually describes the #121 blocker that parks analog items 2, 3, 4, 7, 11

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#204**: parse_extract_devices silently drops an X-line whose model token sits on a SPICE continuation line
- **#210**: test_layout_common.py mis-attributes check.found as a parser-independent source (it is parse_extract_devices' own output)
- **#211**: signoff.yml's two layout/analog unittest steps overlap: the DRC-guard step's test_*.py pattern already runs test_layout_common.py
- **#221**: ROADMAP.md T1 counts and row 4 are stale vs the verdict of record; nothing in CI gates a prose count

## In Progress

Issues currently being built (`loom:building`).

- **#106**: Input sampling switch Sin is ~46% incomplete near vcm at ss/1.620 V/-40 C
- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling
- **#128**: T1 item 5 (analog 4/4): per-corner model B parameters, DR-001 cross-check on the anchors, and the item-5 analog citation
- **#131**: Decimator STA: 35 of the 45 DR-002 corners have no liberty file, and the block-boundary I/O timing budget is undeclared
- **#142**: Decision record: add an amplifier 1/f line to the spec 5.3 noise budget without changing the 80 dB total
- **#148**: Integrator output swing exceeds spec 5.4 at every DR-002 anchor: the loop's 0.5/0.5 scaling rails integrator 1
- **#150**: comparator-decision: the trip staircase does not bracket the comparator's trip point at sf/1.620V/-40C
- **#169**: Confirm klayout-tools#1962 actually describes the #121 blocker that parks analog items 2, 3, 4, 7, 11
- **#187**: CI never runs item8_envelope.py --verify-issues, so characterization.md can cite a closed issue indefinitely
- **#223**: item9-envelope provenance.klt_version now names an unpinned klt dev build; .github/klt-version pins 0.8.0
- **#239**: layout_common.Router: by_net comment says the OTA cell's dict stays empty, but the shared finish_trunks tags every trunk

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#242**: fix: regenerate item9 attest under the klt pin and document the rule

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#115**: fix(spec): correct the section 5.1 ideal ceiling for the single-bit full-scale convention
- **#175**: docs(spec): add DR-009 amplifier 1/f line to the 5.3 noise budget, total unchanged
- **#199**: comparator-decision: settle the sf/1.620V/-40C trip corner by measurement (DR-007, grounds reporting)
- **#213**: ci: run the item-8 cited-issue check on every push and pull request
- **#220**: chore(loom): resync installed Loom to v0.19.1302

## Proposed

Issues carrying `loom:curated`.

- **#3**: Track the gap to T1 (klayout-tools design-evidence-tiers.md) *(curated)*
- **#106**: Input sampling switch Sin is ~46% incomplete near vcm at ss/1.620 V/-40 C *(curated)*
- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling *(curated)*
- **#121**: Analog layout 3/3: generated GDS of the non-overlapping clock generator cell (clkgen) *(curated)*
- **#128**: T1 item 5 (analog 4/4): per-corner model B parameters, DR-001 cross-check on the anchors, and the item-5 analog citation *(curated)*
- **#131**: Decimator STA: 35 of the 45 DR-002 corners have no liberty file, and the block-boundary I/O timing budget is undeclared *(curated)*
- **#142**: Decision record: add an amplifier 1/f line to the spec 5.3 noise budget without changing the 80 dB total *(curated)*
- **#148**: Integrator output swing exceeds spec 5.4 at every DR-002 anchor: the loop's 0.5/0.5 scaling rails integrator 1 *(curated)*
- **#150**: comparator-decision: the trip staircase does not bracket the comparator's trip point at sf/1.620V/-40C *(curated)*
- **#162**: T1 item 7, digital only: SDF-annotated klt functional-verification of the routed decimator, cited for 7.digital *(curated)*
- **#169**: Confirm klayout-tools#1962 actually describes the #121 blocker that parks analog items 2, 3, 4, 7, 11 *(curated)*
- **#187**: CI never runs item8_envelope.py --verify-issues, so characterization.md can cite a closed issue indefinitely *(curated)*
- **#204**: parse_extract_devices silently drops an X-line whose model token sits on a SPICE continuation line *(curated)*
- **#210**: test_layout_common.py mis-attributes check.found as a parser-independent source (it is parse_extract_devices' own output) *(curated)*
- **#211**: signoff.yml's two layout/analog unittest steps overlap: the DRC-guard step's test_*.py pattern already runs test_layout_common.py *(curated)*
- **#221**: ROADMAP.md T1 counts and row 4 are stale vs the verdict of record; nothing in CI gates a prose count *(curated)*
- **#223**: item9-envelope provenance.klt_version now names an unpinned klt dev build; .github/klt-version pins 0.8.0 *(curated)*
- **#239**: layout_common.Router: by_net comment says the OTA cell's dict stays empty, but the shared finish_trunks tags every trunk *(curated)*

## Proposed (Architect / Hermit)

- **#43**: Deduplicate PDK-pin helpers copy-pasted across three runners *(hermit)*
- **#81**: Consolidate 7 copies of the klt pdk find lookup into one helper *(hermit)*
- **#95**: Share the settling measurement list between the OTA and integrator benches: two copies, one already out of step with its request *(hermit)*
- **#96**: Remove sim/toolchain.json: a tool-version pin file that no code reads and that has gone stale *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 5 |
| Very important | 1 |
| Important | 7 |
| Ready (`loom:issue`) | 4 |
| In Progress (`loom:building`) | 11 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 5 |
| Curated | 18 |
| Architect / Hermit proposals | 4 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

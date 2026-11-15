# Work Plan

Roadmap generated from current GitHub label state by the Guide role. Only the region between the markers is machine-generated.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#115**: fix(spec): correct the section 5.1 ideal ceiling for the single-bit full-scale convention

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#148**: Integrator output swing exceeds spec 5.4 at every DR-002 anchor: the loop's 0.5/0.5 scaling rails integrator 1
- **#158**: run_pnr.py's PDK-pin refusal can never fire: it reads a top-level `pdk.version` that klt reports do not have

## Important

`loom:important`; taken before unlabelled work.

- **#29**: T1 item 2 (layout, analog partition): modulator layout per the DR-004 floorplan, generated GDS
- **#121**: Analog layout 3/3: generated GDS of the non-overlapping clock generator cell (clkgen)
- **#138**: First integrator misses the spec 5.3 total-thermal noise budget by 16-18 dB at all 45 corners: OTA flicker noise dominates, and 5.3 has no 1/f allocation
- **#142**: Decision record: add an amplifier 1/f line to the spec 5.3 noise budget without changing the 80 dB total
- **#143**: First integrator: cut OTA flicker noise to the spec 5.3 line (resize the 1/f-dominant devices, or a flicker-cancelling stage) and re-run the OTA-dependent benches
- **#161**: T1 item 4, digital only: klt lvs the routed decimator against its as-built netlist and cite it for 4.digital
- **#162**: T1 item 7, digital only: SDF-annotated klt functional-verification of the routed decimator, cited for 7.digital
- **#169**: Confirm klayout-tools#1962 actually describes the #121 blocker that parks analog items 2, 3, 4, 7, 11
- **#172**: gen_ota_fd.py --check cannot pass: the committed ota_fd.gds no longer reproduces under a newer klt

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#105**: Share the pasted helpers in the issue #92 probe runners: three copies of the SPICE line joiner, two of the figure-of-merit block

## In Progress

Issues currently being built (`loom:building`).

- **#106**: Input sampling switch Sin is ~46% incomplete near vcm at ss/1.620 V/-40 C
- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling
- **#125**: T1 item 5 (analog 1/4): short full-modulator transistor-level transient on the DR-002 anchor set, with power and swing limits
- **#131**: Decimator STA: 35 of the 45 DR-002 corners have no liberty file, and the block-boundary I/O timing budget is undeclared
- **#136**: Decimator STA: cite the propagated-clock run so the hold verdict includes clock-tree latency
- **#142**: Decision record: add an amplifier 1/f line to the spec 5.3 noise budget without changing the 80 dB total
- **#155**: Manifest content_hash for item8-envelope.json is stale, and the field's meaning is undefined for a generic envelope
- **#158**: run_pnr.py's PDK-pin refusal can never fire: it reads a top-level `pdk.version` that klt reports do not have
- **#162**: T1 item 7, digital only: SDF-annotated klt functional-verification of the routed decimator, cited for 7.digital
- **#163**: README status and maturity position are stale: state what the verdict of record says, and re-attest item 10
- **#168**: gen_ota_fd.py: one column-reservation site, and a met2_columns that does not count met2 columns (117 vs 105)
- **#174**: Consolidate the triplicated .partials/ staleness gate into settling_common.py
- **#176**: Share the plumbing copy-pasted between gen_ota_fd.py and gen_integrator.py: four identical helpers, and two extract parsers that have already drifted

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#145**: refactor(sim): share the SPICE joiner, figure-of-merit block, deck fill and baseline read across the issue #92 probe runners
- **#149**: feat(sim): short full-modulator transient bench on the DR-002 anchor set
- **#175**: docs(spec): add DR-009 amplifier 1/f line to the 5.3 noise budget, total unchanged
- **#177**: fix(manifest): drop the unverifiable item-8 content_hash pins and gate the pin invariant
- **#178**: fix: one column-reservation site; route summaries report reserved met2 columns
- **#180**: docs: README status matches the verdict of record; item-10 envelope re-attested
- **#181**: refactor: share the .partials/ sha staleness gate in settling_common.py

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#115**: fix(spec): correct the section 5.1 ideal ceiling for the single-bit full-scale convention
- **#154**: evidence(sta): grade the decimator with a propagated clock, not an ideal one
- **#160**: docs: roadmap as of 2026-11-13
- **#167**: fix(pnr): refuse on the PDK stamp klt actually records, and test it

## Proposed

Issues carrying `loom:curated`.

- **#3**: Track the gap to T1 (klayout-tools design-evidence-tiers.md) *(curated)*
- **#106**: Input sampling switch Sin is ~46% incomplete near vcm at ss/1.620 V/-40 C *(curated)*
- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling *(curated)*
- **#121**: Analog layout 3/3: generated GDS of the non-overlapping clock generator cell (clkgen) *(curated)*
- **#125**: T1 item 5 (analog 1/4): short full-modulator transistor-level transient on the DR-002 anchor set, with power and swing limits *(curated)*
- **#131**: Decimator STA: 35 of the 45 DR-002 corners have no liberty file, and the block-boundary I/O timing budget is undeclared *(curated)*
- **#136**: Decimator STA: cite the propagated-clock run so the hold verdict includes clock-tree latency *(curated)*
- **#142**: Decision record: add an amplifier 1/f line to the spec 5.3 noise budget without changing the 80 dB total *(curated)*
- **#150**: comparator-decision: the trip staircase does not bracket the comparator's trip point at sf/1.620V/-40C *(curated)*
- **#155**: Manifest content_hash for item8-envelope.json is stale, and the field's meaning is undefined for a generic envelope *(curated)*
- **#161**: T1 item 4, digital only: klt lvs the routed decimator against its as-built netlist and cite it for 4.digital *(curated)*
- **#162**: T1 item 7, digital only: SDF-annotated klt functional-verification of the routed decimator, cited for 7.digital *(curated)*
- **#163**: README status and maturity position are stale: state what the verdict of record says, and re-attest item 10 *(curated)*
- **#169**: Confirm klayout-tools#1962 actually describes the #121 blocker that parks analog items 2, 3, 4, 7, 11 *(curated)*
- **#172**: gen_ota_fd.py --check cannot pass: the committed ota_fd.gds no longer reproduces under a newer klt *(curated)*

## Proposed (Architect / Hermit)

- **#43**: Deduplicate PDK-pin helpers copy-pasted across three runners *(hermit)*
- **#81**: Consolidate 7 copies of the klt pdk find lookup into one helper *(hermit)*
- **#95**: Share the settling measurement list between the OTA and integrator benches: two copies, one already out of step with its request *(hermit)*
- **#96**: Remove sim/toolchain.json: a tool-version pin file that no code reads and that has gone stale *(hermit)*
- **#182**: Share the Rect/Anchor/Router classes copy-pasted between gen_ota_fd.py and gen_integrator.py *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 2 |
| Important | 9 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 13 |
| PRs awaiting review | 7 |
| Approved PRs awaiting merge | 4 |
| Curated | 15 |
| Architect / Hermit proposals | 5 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

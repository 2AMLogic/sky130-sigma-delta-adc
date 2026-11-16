# Work Plan

Roadmap generated from current GitHub label state by the Guide role. Only the region between the markers is machine-generated.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#115**: fix(spec): correct the section 5.1 ideal ceiling for the single-bit full-scale convention
- **#175**: docs(spec): add DR-009 amplifier 1/f line to the 5.3 noise budget, total unchanged

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

- **#169**: Confirm klayout-tools#1962 actually describes the #121 blocker that parks analog items 2, 3, 4, 7, 11
- **#187**: CI never runs item8_envelope.py --verify-issues, so characterization.md can cite a closed issue indefinitely

## In Progress

Issues currently being built (`loom:building`).

- **#106**: Input sampling switch Sin is ~46% incomplete near vcm at ss/1.620 V/-40 C
- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling
- **#125**: T1 item 5 (analog 1/4): short full-modulator transistor-level transient on the DR-002 anchor set, with power and swing limits
- **#131**: Decimator STA: 35 of the 45 DR-002 corners have no liberty file, and the block-boundary I/O timing budget is undeclared
- **#142**: Decision record: add an amplifier 1/f line to the spec 5.3 noise budget without changing the 80 dB total
- **#146**: ota_fd layout: MiM plate orientation differs from the netlist's terminal order for one cap group; README row table quotes ring extents
- **#150**: comparator-decision: the trip staircase does not bracket the comparator's trip point at sf/1.620V/-40C
- **#153**: Two more ngspice-version lookups could reach settling_common.ngspice_version() (log-first variant)
- **#155**: Manifest content_hash for item8-envelope.json is stale, and the field's meaning is undefined for a generic envelope
- **#163**: README status and maturity position are stale: state what the verdict of record says, and re-attest item 10
- **#182**: Share the Rect/Anchor/Router classes copy-pasted between gen_ota_fd.py and gen_integrator.py
- **#190**: comparator-decision: pass_criterion prose claims a +/-3.5 mV span requirement that bracketed() does not enforce
- **#191**: layout/analog/layout_common.py has no CI-executed test: the parsers behind both cells' device-count evidence are never run by signoff.yml
- **#198**: DR-006's Consequences bullet is stale: it says record.json predates the gap line, but the committed record carries it

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#130**: sim: extract Sin input-sampling completeness over PVT and its Ron-vs-input curve
- **#149**: feat(sim): short full-modulator transient bench on the DR-002 anchor set
- **#177**: fix(manifest): drop the unverifiable item-8 content_hash pins and gate the pin invariant
- **#180**: docs: README status matches the verdict of record; item-10 envelope re-attested
- **#205**: test: CI-execute layout_common's extracted-netlist parsers with captured klt fixtures
- **#207**: ota_fd: emit row extents from place_rows, requote the README table, record the cap-plate LVS probe

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#115**: fix(spec): correct the section 5.1 ideal ceiling for the single-bit full-scale convention
- **#156**: spec: record the digital-timing corner set and declare the 35-corner gap
- **#175**: docs(spec): add DR-009 amplifier 1/f line to the 5.3 noise budget, total unchanged
- **#195**: comparator-decision: state the trip gate as implemented in pass_criterion
- **#199**: comparator-decision: settle the sf/1.620V/-40C trip corner by measurement (DR-007, grounds reporting)
- **#206**: docs(spec): corrigendum for DR-006's stale record.json Consequences bullet

## Proposed

Issues carrying `loom:curated`.

- **#3**: Track the gap to T1 (klayout-tools design-evidence-tiers.md) *(curated)*
- **#106**: Input sampling switch Sin is ~46% incomplete near vcm at ss/1.620 V/-40 C *(curated)*
- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling *(curated)*
- **#121**: Analog layout 3/3: generated GDS of the non-overlapping clock generator cell (clkgen) *(curated)*
- **#125**: T1 item 5 (analog 1/4): short full-modulator transistor-level transient on the DR-002 anchor set, with power and swing limits *(curated)*
- **#131**: Decimator STA: 35 of the 45 DR-002 corners have no liberty file, and the block-boundary I/O timing budget is undeclared *(curated)*
- **#142**: Decision record: add an amplifier 1/f line to the spec 5.3 noise budget without changing the 80 dB total *(curated)*
- **#146**: ota_fd layout: MiM plate orientation differs from the netlist's terminal order for one cap group; README row table quotes ring extents *(curated)*
- **#150**: comparator-decision: the trip staircase does not bracket the comparator's trip point at sf/1.620V/-40C *(curated)*
- **#153**: Two more ngspice-version lookups could reach settling_common.ngspice_version() (log-first variant) *(curated)*
- **#155**: Manifest content_hash for item8-envelope.json is stale, and the field's meaning is undefined for a generic envelope *(curated)*
- **#162**: T1 item 7, digital only: SDF-annotated klt functional-verification of the routed decimator, cited for 7.digital *(curated)*
- **#163**: README status and maturity position are stale: state what the verdict of record says, and re-attest item 10 *(curated)*
- **#169**: Confirm klayout-tools#1962 actually describes the #121 blocker that parks analog items 2, 3, 4, 7, 11 *(curated)*
- **#186**: Pin klayout in the --check uvx resolution: the gate degrades to CANNOT VERIFY on the next klayout release *(curated)*
- **#187**: CI never runs item8_envelope.py --verify-issues, so characterization.md can cite a closed issue indefinitely *(curated)*
- **#190**: comparator-decision: pass_criterion prose claims a +/-3.5 mV span requirement that bracketed() does not enforce *(curated)*
- **#191**: layout/analog/layout_common.py has no CI-executed test: the parsers behind both cells' device-count evidence are never run by signoff.yml *(curated)*
- **#192**: sim/ota-settling/request.json is intentionally stale: record-pinned; regeneration drifts by capacity_wait_s *(curated)*
- **#198**: DR-006's Consequences bullet is stale: it says record.json predates the gap line, but the committed record carries it *(curated)*

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
| Operator merge-risk holds | 2 |
| Very important | 1 |
| Important | 7 |
| Ready (`loom:issue`) | 2 |
| In Progress (`loom:building`) | 14 |
| PRs awaiting review | 6 |
| Approved PRs awaiting merge | 6 |
| Curated | 20 |
| Architect / Hermit proposals | 4 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

# Work Plan

Roadmap generated from current GitHub label state by the Guide role. Only the region between the markers is machine-generated.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#115**: fix(spec): correct the section 5.1 ideal ceiling for the single-bit full-scale convention

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#29**: T1 item 2 (layout, analog partition): modulator layout per the DR-004 floorplan, generated GDS
- **#118**: Analog layout 1/3: generated GDS of the fully-differential OTA cell (ota_fd)
- **#119**: Analog layout 2/3: generated GDS of the SC integrator cell with its capacitors and switches
- **#121**: Analog layout 3/3: generated GDS of the non-overlapping clock generator cell (clkgen)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#105**: Share the pasted helpers in the issue #92 probe runners: three copies of the SPICE line joiner, two of the figure-of-merit block
- **#120**: Make the pre-#92 fixture check run in CI: it is skipped on every run because the checkout is shallow

## In Progress

Issues currently being built (`loom:building`).

- **#103**: Prune .gitignore rules that match nothing, and ignore the build scratch the cocotb runners actually leave
- **#104**: Make npm test run the tool-free tests CI already runs: check:ci parses two JSON files and runs no tests
- **#106**: Input sampling switch Sin is ~46% incomplete near vcm at ss/1.620 V/-40 C
- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling
- **#118**: Analog layout 1/3: generated GDS of the fully-differential OTA cell (ota_fd)
- **#121**: Analog layout 3/3: generated GDS of the non-overlapping clock generator cell (clkgen)
- **#123**: T1 item 6 (digital partition): hash-bound not_applicable statement for decimator spec rows 6-10
- **#124**: T1 item 5 (digital): klt sta on the routed decimator across the sky130_fd_sc_hd corners, plus a klt functional-verification report
- **#125**: T1 item 5 (analog 1/4): short full-modulator transistor-level transient on the DR-002 anchor set, with power and swing limits
- **#126**: T1 item 5 (analog 2/4): OTA DC gain and integrator thermal noise over the 45-corner grid, as model B parameters
- **#127**: T1 item 5 (analog 3/4): comparator decision time, systematic offset and hysteresis in the modulator over the 45-corner grid

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#130**: sim: extract Sin input-sampling completeness over PVT and its Ron-vs-input curve
- **#133**: chore: drop never-matched build ignores, ignore the cocotb runners' scratch
- **#134**: feat(signoff): bind a not_applicable record to T1 item 6 (digital)
- **#135**: feat(ci): run the tool-free signoff checks in the local check:ci gate

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#115**: fix(spec): correct the section 5.1 ideal ceiling for the single-bit full-scale convention
- **#132**: feat(verification): grade decimator timing at ten liberty corners and cite item 5 digital

## Proposed

Issues carrying `loom:curated`.

- **#3**: Track the gap to T1 (klayout-tools design-evidence-tiers.md) *(curated)*
- **#106**: Input sampling switch Sin is ~46% incomplete near vcm at ss/1.620 V/-40 C *(curated)*
- **#108**: Ideal B-model peak SNDR sits ~8 dB below the spec section 5.1 quantization-noise ceiling *(curated)*
- **#118**: Analog layout 1/3: generated GDS of the fully-differential OTA cell (ota_fd) *(curated)*
- **#120**: Make the pre-#92 fixture check run in CI: it is skipped on every run because the checkout is shallow *(curated)*
- **#121**: Analog layout 3/3: generated GDS of the non-overlapping clock generator cell (clkgen) *(curated)*
- **#123**: T1 item 6 (digital partition): hash-bound not_applicable statement for decimator spec rows 6-10 *(curated)*
- **#124**: T1 item 5 (digital): klt sta on the routed decimator across the sky130_fd_sc_hd corners, plus a klt functional-verification report *(curated)*
- **#125**: T1 item 5 (analog 1/4): short full-modulator transistor-level transient on the DR-002 anchor set, with power and swing limits *(curated)*
- **#126**: T1 item 5 (analog 2/4): OTA DC gain and integrator thermal noise over the 45-corner grid, as model B parameters *(curated)*
- **#127**: T1 item 5 (analog 3/4): comparator decision time, systematic offset and hysteresis in the modulator over the 45-corner grid *(curated)*

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
| Operator merge-risk holds | 1 |
| Very important | 0 |
| Important | 4 |
| Ready (`loom:issue`) | 2 |
| In Progress (`loom:building`) | 11 |
| PRs awaiting review | 4 |
| Approved PRs awaiting merge | 2 |
| Curated | 11 |
| Architect / Hermit proposals | 4 |
| Active epics | 0 |
<!-- guide:plan-body:end -->

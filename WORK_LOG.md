# Work Log

Chronological record of merged PRs and closed issues, maintained by the Guide role.

### 2026-11-13

- **Issue #27** (closed): T1 item 1 (design sources, analog partition): xschem schematic and derived netlist of the 2nd-order switched-capacitor modulator
- **PR #116**: feat(attest): attest the analog design sources for T1 item 1
- **Issue #42** (closed): T1 item 1 (analog 4/4): attestation inventory, manifest evidence, regenerated verdict
- **PR #112**: feat(bmodel): stamp a code_sha256 map in every B-model evidence writer
- **Issue #110** (closed): B-model records stamp a dirty base commit, not the code that produced the number
- **PR #111**: feat(sim): extract the integrator charge-injection residual and correct the sqrt(W L) argument
- **Issue #102** (closed): Extract integrator charge injection after the #92 PMOS switch halves
- **PR #109**: fix(bmodel): drop the ENBW factor from sndr_db and regenerate the B evidence
- **Issue #107** (closed): B-model SNDR estimator reads 3.0 dB high: sndr_db applies an ENBW factor to a lobe-summed signal
- **PR #100**: refactor(attest): move item-10 inventory and envelope under attestation/
- **Issue #91** (closed): Fold attest/ and evidence/ into attestation/: three directory conventions for one kind of file
- **PR #99**: fix(integrator): give the vcm switches a low-Vth PMOS half so the cell settles at 1.620 V
- **Issue #92** (closed): Integrator cell does not settle at Vdda=1.62 V (0/15 corners, both load variants): diagnose, then fix the OTA or the switches
- **PR #98**: test(sim): refuse a settling record built on a failed submit, and cover the record-validity gates
- **Issue #94** (closed): Settling runner: fixture test for measurements_present(), and surface a failed submit that fell back to a cached partial
- **PR #93**: feat(sim): record 45-corner integrator settling over PVT and extract the B-model settling budget
- **Issue #53** (closed): Settling of the SC integrator with ota_fd over PVT (OTA gm margin at beta 0.50)
- **PR #89**: docs: record klt netlist --check result for vendored comparator
- **Issue #60** (closed): Close klt netlist --check for vendored comparator.sch (needs xschem >= 3.4.5)

### 2026-11-12

- **PR #87**: Bump Repo Skills 0.25.10 -> 0.26.1

### 2026-11-07

- **PR #84**: Bump Repo Skills 0.25.1 -> 0.25.10

### 2026-11-06

- **PR #83**: feat(layout): klt drc the routed decimator and grade 3.digital met
- **Issue #82** (closed): T1 item 3, digital only: klt drc the routed decimator GDS and cite it for 3.digital

### 2026-11-01

- **PR #78**: fix: refresh item-9 attestation envelope for updated response.py hash
- **Issue #77** (closed): main red: item-9 attestation drifted (response.py hash stale after DR-006)
- **PR #75**: test(decimator): end-to-end B-bitstream check and re-recorded row 9 floor
- **Issue #74** (closed): DR-006 follow-ups: record the 75 dB 'row 9 elsewhere' line durably; row 9 evidence column claims B evidence that does not exist
- **PR #23**: docs(spec): grade decimation stopband (row 9): 90 dB in alias bands, 75 dB floor elsewhere, DR-006
- **Issue #18** (closed): Spec owner: confirm row 9 stopband reading (alias bands vs every frequency fout-BW..fs/2)
- **PR #72**: Bump Repo Skills 0.24.7 -> 0.25.1

### 2026-10-28

- **PR #68**: feat(measurements): characterization report with item-8 envelope and CI re-check
- **Issue #67** (closed): T1 item 8 (characterization report): per-row characterization report with decimator Fmax/area/power and a klt signoff --attest 8 envelope

### 2026-10-27

- **PR #65**: feat(layout): reproducible routed GDS and item-2 envelope for the decimator
- **Issue #30** (closed): T1 item 2 (layout, digital partition): place-and-route of the decimator on VDDD/VSSD, committed routed GDS
- **PR #63**: refactor: share klt sim runner and request builder across settling benches
- **Issue #57** (closed): Consolidate duplicated klt-sim runner logic in sim/*-settling
- **PR #59**: feat(design): add clkgen, vendored comparator and top-level modulator schematic
- **Issue #41** (closed): T1 item 1 (analog 3/4): clock phases, pinned comparator import, top-level modulator schematic
- **PR #46**: feat: attest digital T1 item 1 with committed synthesized decimator netlist
- **Issue #28** (closed): T1 item 1 (design sources, digital partition): commit the decimator gate-level netlist and attest the RTL + netlist inventory
- **PR #58**: feat(design): linear resistive CMFB sense and doubled tail/branch currents close OTA step settling at 45 corners
- **Issue #51** (closed): OTA: CMFB sense and branch currents fail the 45-corner step-settling record
- **PR #56**: feat(sim): add integrator+ota_fd settling bench and 45-corner runner
- **PR #52**: feat(sim): OTA step-settling bench with failing 45-corner record
- **PR #47**: feat: attest T1 item 9 testbench inventory with klt signoff --attest
- **PR #54**: feat(design): add fully-differential SC integrator with 1-bit feedback DAC
- **Issue #48** (closed): Follow-on from PR #45: OTA slew-rate risk (~10 V/us vs 0.45 V per-side worst-case step)
- **Issue #36** (closed): T1 item 9 (testbenches shipped): testbench inventory over the smoke, model B, decimator and modulator benches, attested with klt signoff --attest 9
- **Issue #40** (closed): T1 item 1 (analog 2/4): SC integrator and 1-bit feedback DAC, schematic and netlist
- **PR #45**: feat(design): add fully-differential folded-cascode OTA with CMFB
- **PR #44**: feat: attest T1 item 10 repo hygiene with klt 0.8.0 and refresh README
- **Issue #38** (closed): T1 item 1 (analog 1/4): fully-differential OTA with CMFB, schematic and netlist
- **Issue #37** (closed): T1 item 10 (repo hygiene): README status and full reproduction, hygiene inventory attested with klt signoff --attest 10

### 2026-10-24

- **Issue #20** (closed): Remove digital smoke fixture verification/smoke: superseded by decimator runner

### 2026-10-23

- **PR #19**: feat(sim): behavioural second-order delta-sigma model B with SNDR records
- **PR #17**: feat(rtl): CIC4 + 41-tap FIR decimation filter with cycle model, cocotb tests and synthesis record
- **Issue #15** (closed): Behavioural modulator model (B): discrete-time 2nd-order 1-bit loop with T-parameter inputs and a §1.2-conformant SNDR report
- **Issue #16** (closed): Decimation filter RTL: CIC3 + FIR to 80 kSps, 16-bit output, bit-exact against a fixed-point model with cocotb

### 2026-10-21

- **PR #13**: fix: make npm check scripts validate manifest JSON instead of always passing
- **PR #10**: Bump Repo Skills 0.24.3 -> 0.24.7
- **Issue #12** (closed): Replace vacuous always-pass package.json check scripts

### 2026-10-20

- **PR #6**: ci: grade T1 state with klt signoff and commit the verdict of record
- **Issue #5** (closed): T1 item 10: add CI and a klt signoff block manifest as the verdict of record

### 2026-10-17

- **PR #8**: feat: pin sky130 PDK and tools, add analog and digital smoke runs
- **PR #7**: docs(spec): ratify sky130 delta-sigma ADC target spec and decision records
- **PR #1**: chore(loom): Install Loom 0.19.1181
- **Issue #4** (closed): Pin the sky130 PDK and both simulation flows, and commit analog and digital smoke runs (T1 item 9 groundwork)
- **Issue #2** (closed): Draft and ratify the target spec

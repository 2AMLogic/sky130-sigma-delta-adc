# Work Log

Chronological record of merged PRs and closed issues, maintained by the Guide role.

### 2026-10-27

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

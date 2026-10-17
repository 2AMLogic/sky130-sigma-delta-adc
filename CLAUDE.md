# sky130-sigma-delta-adc — agent instructions

Open-source canary block: a switched-capacitor delta-sigma ADC on SkyWater
sky130, designed and verified by AI agents. **Mixed-signal** — an analog
modulator and a synthesized decimation filter — so both flows apply.

- **PDK**: SkyWater sky130 (open PDK, google/skywater-pdk). Analog: xschem +
  ngspice. Digital: cocotb + Icarus, Yosys, OpenROAD. Layout, DRC, and LVS
  through klayout-tools (`klt`) in both cases.
- **The evidence method is the point, and the risk.** A resolution claim
  needs a long output record, and a transistor-level transient of that
  length is expensive. Decide and record, before the first result, how the
  evidence is split: a behavioural modulator model for long-record SNDR,
  transistor-level runs for the non-idealities (integrator settling, finite
  gain, charge injection, kT/C noise, comparator offset), and an explicit
  cross-check that the model reproduces the transistor-level behaviour where
  both exist. Every SNDR number names which of these produced it, the record
  length, the window, and the bin bandwidth.
- **Switching noise is a layout problem.** The decimation filter sits on the
  same die as the integrators. Plan the supply, substrate, and clock
  separation in the floorplan and grade the modulator post-layout with the
  digital block in place. Expect the tools to be weakest at mixed-signal
  floorplanning and extraction, and file accordingly.
- **Scope discipline.** The reference and bias are inputs at the boundary.
  On this PDK, `sky130-opamp`, `sky130-comparator`, and `sky130-bandgap`
  build sub-blocks this converter needs: adopt them by pinned reference
  (`reuse.lock.json`) or write the decision record saying why this repo
  keeps its own. `sky130-sar-adc` is a different architecture, not a
  duplicate.
- **Friction protocol (the canary's job)**: every time klayout-tools is
  awkward, missing a capability, or wrong for what you need, file an issue at
  `2AMLogic/klayout-tools` describing the tool gap generically — that tracker
  is scoped to the tool, so keep design-specific detail out of it and describe
  the gap, not the design.
- **Verification is the product**: no claim without a testbench. PVT corners
  on every recorded analog result; recorded results are append-only
  evidence. A simulated number is never called measured.
- Spec changes go through `spec/` with a decision record; agents do not relax
  the ratified spec to make results pass.
- **80 dB in 20 kHz is the target.** 70 dB is the fallback and 90 dB a
  stretch. Do not let a higher-order or multi-bit modulator drive the
  architecture before the second-order single-bit design closes.

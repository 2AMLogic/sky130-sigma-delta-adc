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

<!-- BEGIN LOOM ORCHESTRATION -->
This repository uses [Loom](https://github.com/rjwalters/loom) for AI-powered development orchestration — see the Loom repository for the full guide (roles, labels, worktrees, configuration). When installed, Loom also writes a locally-substituted copy of that guide to `.loom/CLAUDE.md`.

Work is coordinated through `loom:` labels on issues and pull requests, and the same roles run either under `loom-daemon` or by hand in an attended session — daemon mode is optional. Create the labels once with `.loom/scripts/sync-labels.sh` (an install ships `.github/labels.yml` but does not create the labels on the forge). A pull request ready for review carries `loom:review-requested`; Judge reviews it and applies `loom:pr` (approved) or `loom:changes-requested`; Doctor fixes a `loom:changes-requested` pull request and returns it to `loom:review-requested`. Only a `loom:pr` pull request gets merged, and always via this repo's merge script (`.loom/scripts/merge-pr.sh`) — never a raw forge merge command such as `gh pr merge`. Full state machine: `.loom/docs/label-state-machine.md`.
<!-- END LOOM ORCHESTRATION -->

<!-- BEGIN REPO-SKILLS -->
This repository has [Repo Skills](https://github.com/rjwalters/repo) v0.24.3 installed —
general repository hygiene and environment commands invoked as `/repo:<command>`. Run
`/repo:help` for the command list, or see `.claude/skills/repo/SKILL.md` for the full
guide. Hygiene commands apply safe, reversible fixes by default and report each
change; run with `--ask` to review first, and `--prune` to allow irreversible
removals. Managed by `install.sh` — edit outside the markers only.
<!-- END REPO-SKILLS -->

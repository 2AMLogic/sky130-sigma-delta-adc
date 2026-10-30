# spec

The ratified specification and its decision history for the sky130
delta-sigma ADC.

- [`modulator-adc.md`](modulator-adc.md) — the target specification: every
  parameter as target / fallback / stretch, with rationale, the evidence type
  that backs it, and the arithmetic behind each derived figure.
- [`decisions/`](decisions/) — decision records. A record is required
  whenever a spec value or approach is set, changed or scoped. Never edit a
  ratified record; supersede it with a new one.
  - [DR-001](decisions/DR-001-evidence-split.md) — evidence split:
    behavioural model, transistor-level runs, cross-check, SNDR convention
  - [DR-002](decisions/DR-002-pvt-corners.md) — PVT corners
  - [DR-003](decisions/DR-003-sibling-reuse.md) — reuse of `sky130-opamp`,
    `sky130-comparator`, `sky130-bandgap`
  - [DR-004](decisions/DR-004-mixed-signal-floorplan.md) — supply,
    substrate and clock separation; post-layout grading plan
  - [DR-005](decisions/DR-005-reference-bias-boundary.md) — reference and
    bias boundary
  - [DR-006](decisions/DR-006-decimation-stopband-reading.md) — decimation
    stopband (row 9) graded in the alias bands, with a gap floor

Pinned sibling references live in [`../reuse.lock.json`](../reuse.lock.json).

Ratified means the pull request carrying the spec is Judge-approved and
merged. Later changes go through a new decision record, never an in-place
relaxation.

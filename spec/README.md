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
  - [DR-006 corrigendum 01](decisions/DR-006-corrigendum-01.md) — corrects
    DR-006's stale Consequences bullet about `record.json` predating the gap
    line; DR-006's Decision is unchanged
  - [DR-008](decisions/DR-008-digital-timing-corners.md) — digital-partition
    timing corners are the ten shipped `sky130_fd_sc_hd` liberty corners; the
    other 35 DR-002 points are a declared gap and the block-boundary I/O
    budget is the assembled top's
  - [DR-008 corrigendum 01](decisions/DR-008-corrigendum-01.md) — records
    that DR-008's first `klt characterize` ground holds at the 0.8.0 pin
    but its combinational-arcs clause does not on the
    `0.9.3.dev181+g2f281f0d605c` host dev build (released `0.9.2` still
    prints the 0.8.0 Scope line), and adds the missing klt-pin reopen
    trigger on `.github/klt-version`; DR-008's Decision is unchanged
  - [DR-008 corrigendum 02](decisions/DR-008-corrigendum-02.md) — the
    klt-pin reopen trigger's first discharge, at the `0.9.2` pin: the
    first `klt characterize` ground still stands verbatim there; DR-008's
    Decision is unchanged

Pinned sibling references live in [`../reuse.lock.json`](../reuse.lock.json).

Ratified means the pull request carrying the spec is Judge-approved and
merged. Later changes go through a new decision record, never an in-place
relaxation.

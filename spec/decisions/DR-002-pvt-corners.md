# DR-002: PVT corner set for recorded analog results

- **Status**: proposed; ratified when the PR carrying it (issue #2) is
  Judge-approved and merged
- **Date**: 2026-10-17
- **Decided by**: Builder agent, issue #2

## Context

`CLAUDE.md` requires PVT corners on every recorded analog result. The corner
set must come from what the PDK ships; none may be invented.

## Decision

**Process corners.** `tt`, `ss`, `ff`, `sf`, `fs`: the five MOS corners the
sky130 model library ships for the 1.8 V core devices. Read on 2026-10-17
from the installed PDK's `libs.tech/combined/sky130.lib.spice`, which defines
`.lib tt`, `sf`, `ff`, `ss`, `fs` (and further variants `ll`, `hh`, `hl`,
`lh`, `ss_ll`…`fs_hh` for other device classes, **not adopted**).

**Temperature.** −40, 27, 125 °C.

**Supply.** 1.62, 1.80, 1.98 V (1.8 V ± 10 %).

**Sets.**

- *Full grid* — 5 × 3 × 3 = 45 points: required for the small
  single-mechanism T runs (settling, gain, noise, comparator).
- *Anchor set* — for the expensive runs (the short full-modulator
  transient, Monte Carlo): `tt/27 °C/1.80 V`, `ss/125 °C/1.62 V`,
  `ss/−40 °C/1.62 V`, `ff/−40 °C/1.98 V`, `ff/125 °C/1.98 V`,
  `sf/27 °C/1.80 V`, `fs/27 °C/1.80 V`. The anchors are a starting guess
  at the extremes; after the first full-grid run the binding corners are
  looked up and the anchor set is amended by a new record if they differ.
- Mismatch / Monte Carlo: the PDK's own mismatch models only, with `N`
  stated per run.

**PDK revision referenced.** The installed `sky130A` was built from
open_pdks commit `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` (the `SOURCES`
file of the installed tree, 2026-10-17). It is a reference for this record,
not the pin: pinning the PDK is
[#4](https://github.com/2AMLogic/sky130-sigma-delta-adc/issues/4). If the
pin differs, corner names are re-checked against it.

## Alternatives considered

- **Typical corner only.** Fails `CLAUDE.md`. Not chosen.
- **Full 45-point grid on every run.** The short full-modulator transient
  and Monte Carlo would be too expensive; the full grid is kept for the
  cheap runs. Not chosen for the expensive ones.
- **Corner set copied from `sky130-opamp` (a 15-point grid).** Its
  supply points are fixed by its own record; this converter's
  supply row (row 12) is ± 10 %, so the supply axis is stated here.
- **Adding the `ll`/`hh`/`hl`/`lh` variants.** These are for other device
  classes; not shipped for the 1.8 V core flavor used here. Not chosen.

## Spec lines affected

§2 of `modulator-adc.md`; rows 2, 12, 13.

## Consequences

Every recorded analog result names a corner from this set (or an anchor from
it). Reduced anchor sets are acceptable only for the runs named above; a
result from an anchor subset states that it is a subset.

# DR-004: Mixed-signal floorplan separation and post-layout grading plan

- **Status**: proposed; ratified when the PR carrying it (issue #2) is
  Judge-approved and merged
- **Date**: 2026-10-17
- **Decided by**: Builder agent, issue #2

## Context

The decimation filter is a synthesized digital block on the same die as the
integrators, and its switching current sits next to the most sensitive
analog nodes (the first integrator's summing nodes). `CLAUDE.md` requires
the supply, substrate and clock separation to be planned in the floorplan
and the modulator to be graded post-layout with the digital block in place.
This record is a plan; none of it has been laid out or extracted, and the
tools are expected to be weakest here.

## Decision

1. **Supplies.** Separate rails `VDDA`/`VSSA` (modulator) and
   `VDDD`/`VSSD` (decimation filter and control) with separate pins/pads;
   they meet only at the boundary, at a single star point off the block.
   This is also what makes `P_ana` and `P_dig` separately reportable (row 13
   of the spec).
2. **Substrate.** Analog and digital regions separated by a guard region:
   a p+ guard ring on the analog side tied to `VSSA`, and a deep-n-well
   (where the PDK's deep n-well option is used) around the analog NMOS
   region that needs isolation. The digital region has no connection to
   `VSSA` other than through the die substrate, which is accepted as a
   coupling path and graded, not assumed away.
3. **Placement.** Integrators, comparator and capacitors in one compact
   analog block, first integrator on the side far from the digital block,
   the digital block on the opposite side with the bitstream crossing
   through one shielded route. Capacitor arrays are common-centroid.
4. **Clock.** The non-overlapping clock generator is on `VDDA` beside the
   switches it drives. The digital block's clock is derived from the
   modulator clock through a buffer on `VDDD`; the modulator clock is not
   routed through the digital block. The quantizer output crosses the
   boundary in the digital direction only.
5. **Grading.** Per row 14 of the spec: extract parasitics from the full
   layout with the digital block placed, simulate the modulator with a
   digital activity vector (the decimation filter switching on a modulator
   bitstream) at the [DR-002](DR-002-pvt-corners.md) anchor corners, compare
   against the pre-layout T run through the DR-001 cross-check, and report
   row 2 and row 13 as "post-layout simulated". A cross-check failure here
   is a finding.
6. **Tool gaps.** Mixed-signal floorplanning and extraction are expected to
   be weak points of the open tools. Each gap found while doing this is
   filed at `2AMLogic/klayout-tools` as a generic tool gap under the
   `CLAUDE.md` friction protocol. No gap is filed from this record: none has
   been exercised yet.

## Alternatives considered

- **Single shared supply with decoupling only.** Cheapest; offers no
  isolation against the digital block's current spikes at the pins. Rejected
  as the starting point.
- **Separate dies/off-chip decimation.** Outside the scope of one block;
  removes the mixed-signal question instead of answering it.
- **Triple-well isolation everywhere.** Costs area, and whether it is needed
  is a measurable question; deferred until the post-layout grading shows it
  is. It stays an available mitigation, decided by a new record.
- **Gate the digital clock to quiet windows of the modulator.** Interesting
  mitigation if grading shows coupling; adds control complexity before
  there is evidence it is needed.

## Spec lines affected

Row 13 (power reporting) and row 14 (signoff) of `modulator-adc.md`.

## Consequences

Two rail pairs and a guard region add pins and area, and the floorplan is a
constraint on the layout issues that follow. Whether the separation is
enough is only known at post-layout grading.

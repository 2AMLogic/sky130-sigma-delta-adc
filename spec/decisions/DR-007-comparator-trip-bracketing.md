# DR-007: The comparator's offset is not separately bracketable at
`sf`/1.620 V/−40 °C — the corner stays filed, with a one-sided simulated bound

- **Status**: proposed; ratified by the operator's approval of the PR that
  lands it (issue #150)
- **Date**: 2026-11-15
- **Decided by**: Builder agent, issue #150
- **Evidence**: `sim/comparator-decision/record.json` (2026-11-13 grid),
  `sim/comparator-decision/trip-probe-i150.json` (single-corner probe,
  2026-11-15), `sim/integrator-settling/record.json`
- **Evidence class**: **simulated** (ngspice, transistor-level), never
  measured — the standing disclaimer of every bench cited above
  (`sim/comparator-decision/README.md`). "Measured" below means measured in
  the bench, not in silicon.

## Context

The `trip` variant of the comparator-decision bench (issue #127) walks the
comparator's input across its trip point in 500 µV design steps, up and then
down, and reads the systematic offset and the hysteresis width off the two
flips. At 44 of the 45 DR-002 corners the sweep brackets the trip. At
**`sf`/1.620 V/−40 °C** it does not: `record.json` names it in
`corners_without_a_bracketed_trip`, publishes no offset or hysteresis from
it, and reports
`pass_by_claim.trip_points_bracketed_so_offset_and_hysteresis_are_bounded.pass
= false` because of it. The decision-time claim passes at all 45 corners and
is unaffected.

The record's grading (`bracket_failures`, now carried in the record and its
generator) shows the corner fails on **three** grounds at once:

1. `flip_up` = 0 — the decision never changed on the way up;
2. `k_dn` = 12, a full clock below the falling search window 15 … 23;
3. `step_dn` = +576.4 µV — positive, where a falling step must be negative.

Before this record the repo's README stated the direction as fact ("the trip
sits above the top of the ±2.25 mV sweep"), but no committed measurement
established it: `flip_dn` = 1 was read both ways, and the corner also carries
`singular_matrix` / `nonconvergence` diagnostics. Issue #150 asked for the
direction to be settled **by measurement, not inference**, before any
45-corner widening was paid for.

## What was measured

A single-corner probe (`sim/comparator-decision/run_trip_probe.py` →
`trip-probe-i150.json`) ran the committed `trip` deck at exactly this corner,
locally, and kept the per-clock held values of `v(o1d)`, `v(o2d)`, the
decision `dd` and the comparator outputs `cmpd` — the evidence the grid run
does not keep. Its cross-check block reproduces all fourteen record values
at the corner (the six grading rows bit-exactly, including both sentinels:
`tflip_up` = `tedge(12)`, `tflip_dn` = `tedge(13)` − 0.1 ns), so the probe
is the same measurement the record grades, not a second bench.

**The direction is measured: the threshold lies above every value the sweep
delivered.** At every clock 0 … 23 the decision held `dd` = −1.6200 V and the
comparator itself resolved `cmpd` ≈ −1.617 V — y = −1 at every decision of
the run, and no resolution to y = +1 anywhere. On the graded up sweep every
presented differential was negative: foot −6.909 mV (clock 4) → top
−1.410 mV (clock 12); even the turn-around value at clock 13 (−0.842 mV)
stayed negative. So `flip_up` = 0 is the sweep never reaching the threshold,
and `flip_dn` = 1 is not a falling trip at all: the `m_dn` detector
(`dd` ≤ −0.5·vdda) is satisfied by an already-low decision the moment its
window opens — which is why `tflip_dn` sits 0.1 ns before `tedge(13)`, the
window's opening, and why `k_dn` collapses to the sentinel clock 12.

**The staircase itself is malformed at this corner, which is why widening is
the wrong answer.** Integrator 1 does not deliver its commanded targets: it
held ≈ +1.357 … 1.368 mV against the designed +1.000 mV through the up sweep
(error +357 … 368 µV) and ≈ −0.4115 … −0.4195 mV against −1.000 mV through
the down sweep (error +580 … 589 µV, i.e. barely 41 % of the commanded
magnitude). The staircase step is `(Cs/Ci)·o1d`, so the falling steps came
out −164.6 … −170.4 µV instead of the designed −500 µV — monotonic and in
the right direction, but the falling half contracted to
`span_dn` = −1.505 mV against ≈ −4.5 mV at healthy corners (`step_dn` ≈
−501 µV there). The rising steps are likewise off design (576 µV at the
trip, ~723 µV mid-sweep, against 500 µV designed) and the whole delivered
sweep sits several millivolts below where it was designed to sit: a sweep
designed to straddle zero presented nothing above −0.842 mV.

This is the same condition `sim/integrator-settling` records
independently: against `err_phase` ≤ 1e-4, variant `int1` fails 16 of 45
corners — **all 15 of the VDDA = 1.620 V corners among them** — and `int2`
fails 35 of 45, likewise including all 15 at 1.620 V. Both variants' `pass`
is `false`. The comparator sits behind integrator 2; where the integrator
ahead of it does not hold its commanded output, this bench grades the
integrator's behaviour, not the comparator's.

## Decision

1. **The comparator's systematic offset is not separately bracketable at
   `sf`/1.620 V/−40 °C by this bench**, and no widening of the designed
   sweep is undertaken for it. A wider or larger-step staircase would
   measure the integrator's failure to track its commanded targets at a
   corner where `sim/integrator-settling` already fails — a wider sweep
   cannot make the stimulus well-formed.
2. **The bound that holds instead is one-sided, measured**: at this corner
   the comparator's threshold lies above the sweep as delivered,
   `v_trip` > −1.410 mV (equivalently `comparator_offset` > −1.41 mV =
   −1.17e-3 FS). No upper bound on the offset and no bound on the
   hysteresis exists at this corner. The grid-level model-B parameters are
   unchanged: `comparator_offset` ≤ 1.0e-04 FS and `comparator_hysteresis`
   ≤ 5.8e-04 FS (upper bound) remain bounds **over the 44 bracketed
   corners**, exactly as published.
3. **`record.json` stays `pass = false` and the corner stays named in
   `corners_without_a_bracketed_trip`** (DR-003: a failing corner is filed,
   not papered over). The record carries `bracket_failures` =
   `["flip_up", "k_dn", "step_dn"]` for the corner, plus pointers to this
   record and the probe — and its generator now emits the same grounds for
   any future unbracketed corner, so a bare `False` never again stands in
   for the explanation.
4. **The README's direction sentence is corrected to cite this
   measurement.** The claim "the trip sits above the top of the ±2.25 mV
   sweep" is superseded by the measured statement: the threshold lies above
   the sweep **as delivered** (top −1.410 mV at the last graded decision),
   and the sweep as delivered was itself several millivolts below design.

**What would change this disposition**: a settling fix in
`sim/integrator-settling` at VDDA = 1.620 V (its own open work), after which
this bench's grid is re-run. If a future grid brackets all 45 corners, this
record is superseded and the offset bound becomes a two-sided 45-corner one.

## Rejected alternatives

- **Widen by more clocks at 500 µV resolution** — the delivered sweep is not
  merely short: its falling half collapsed to ~170 µV steps and its whole
  span sits ~4–5 mV below design. More clocks extend a staircase whose
  stimulus is malformed; it cannot bracket anything reliably.
- **Widen by a larger step** — coarsens a resolution that already dominates
  the offset error elsewhere, and does nothing about the stimulus.
- **Two-stage coarse-then-fine sweep** — the right design for a sweep that
  is merely short; it adds a deck and a fine-stage grid derivation to chase
  one corner whose upstream integrator does not settle. Revisit only if the
  integrator settles at 1.620 V and the corner still fails.
- **Treat the corner's `vos_V` = +1.41 mV as an offset measurement** —
  that value is the sentinel artefact `bracketed()` already suppresses: both
  "trip points" are the same held value at clock 12.

## Scope guards

No spec row is relaxed and none is graded on this corner's behaviour; the
comparator cell is untouched and not re-vendored (DR-003); DR-002's
45-corner grid definition is unchanged. The `loop` variant (decision time,
kickback) passes at all 45 corners and is untouched.

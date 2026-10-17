# DR-003: Sibling-block reuse (op-amp, comparator, reference)

- **Status**: proposed; ratified when the PR carrying it (issue #2) is
  Judge-approved and merged
- **Date**: 2026-10-17
- **Decided by**: Builder agent, issue #2

## Context

`CLAUDE.md` requires each sub-block this converter needs to be adopted by
pinned reference, or the reason for keeping an own copy recorded. The
sibling `spec/` content was read at these commits (2026-10-17):

| Sibling | Commit read |
|---|---|
| `2AMLogic/sky130-opamp` | `6bb27c0a9806613c4092812f808c32bc6a56f71c` |
| `2AMLogic/sky130-comparator` | `a0767fa5a4bedc9128a7e95b8b512075536522c8` |
| `2AMLogic/sky130-bandgap` | `f6ad34ec46d7b40c12aaebdb7d5b0b71d7a42801` |

`sky130-sar-adc` is a different architecture and is not a candidate.

## Decision

### Integrator amplifier — keep an own copy (`sky130-opamp` not adopted)

Reasons, each read from the sibling's `spec/target-spec.md` at the commit
above:

1. **Contract mismatch.** The sibling publishes the ports
   `vdd vss inn inp out ibias`: a differential input and a **single-ended**
   output. This converter's signal path is fully differential (row 11 of
   [`modulator-adc.md`](../modulator-adc.md)), which needs a
   differential-output amplifier with common-mode feedback. Using the
   sibling as-is means a pseudo-differential pair of single-ended
   integrators, which doubles the amplifier count and throws away the
   even-order and common-mode rejection the differential choice is made for.
2. **Open rows that this converter depends on.** The sibling's PSRR row is
   `[TBD]`, its input-referred offset is OPEN, and its CMRR target (≥ 50 dB,
   DC – 1 kHz) is `proposed` there. Supply and substrate noise from the
   decimation filter on the same die is this design's main risk
   ([DR-004](DR-004-mixed-signal-floorplan.md)); adopting a block whose PSRR
   is unspecified would put the first unknown on the critical path.
3. **Settling.** Its GBW target is ≈ 16 MHz into 2 pF. A fully-differential
   SC integrator at `fs` = 5.12 MHz has about 98 ns per phase; a first-order
   settling estimate with a feedback factor near 0.5 is about 5 time
   constants. That is plausible but not comfortable, and the sampling and
   load capacitors here differ from its 2 pF. It must be re-derived for this
   block, not inherited.

What is reused is the *method and numbers as reference points*, not the
design: the 1.8 V core flavour, its −40…125 °C corner convention (matched in
[DR-002](DR-002-pvt-corners.md)), and its sizing data (≈ 117 µW at 1.8 V
quiescent, ≈ 1.39 V<sub>pp</sub> output swing, 61.6 dB worst-case DC gain)
as sanity bounds for the power row (row 13) and the swing check (§5.4 of the
spec). **Revisit trigger**: if the sibling publishes a fully-differential
variant with a ratified PSRR row, a new record supersedes this one.

### Quantizer comparator — adopt `sky130-comparator` by pinned reference

Pin: `2AMLogic/sky130-comparator` at
`a0767fa5a4bedc9128a7e95b8b512075536522c8`, recorded in
[`reuse.lock.json`](../../reuse.lock.json) under `imports`.

Why: a single-bit quantizer needs a clocked differential comparator
whose offset is suppressed by the loop gain ahead of it, so the sibling's
ratified rows (input-referred noise ≤ 1.0 mV rms differential, kickback
≤ 5 mV) are the rows that matter and are stated there, and a second
comparator would be sized by accident. Its
design is a static preamplifier ahead of a latch, which also addresses
kickback onto the first integrator's summing node.

Checks owed (not claims): the comparator's decision time against this
clock's half-period (97.7 ns at 5.12 MHz, 78.1 ns at 6.4 MHz) at the
[DR-002](DR-002-pvt-corners.md) corners, and its kickback against the
integrator amplifier input. If either fails, the failure is recorded and a
superseding record decides between a constraint on `fs`, a modified copy,
or an own comparator; the spec rows are not relaxed to fit.

### Reference — `sky130-bandgap` not instantiated

The reference and bias are inputs at the boundary (`CLAUDE.md`,
[DR-005](DR-005-reference-bias-boundary.md)), so this repo builds neither
an own reference nor an adopted instance, and `reuse.lock.json` has no entry
for it. The sibling's ratified table is used only as a source for the
boundary assumption (1.20 V ± 2 % untrimmed, TC < 50 ppm/°C, PSRR > 60 dB
DC – 1 kHz; commit above). Its primary supply is 3.3 V ± 10 % and its
1.8 V-core variant is a stretch there, so the reference reaching this block
is expected from outside the 1.8 V domain.

## Alternatives considered

- **Adopt `sky130-opamp` as two instances per integrator
  (pseudo-differential).** Rejected for the reasons above: doubles amplifier
  power against a 1 mW target row and moves common-mode rejection onto a
  block whose CMRR is proposed and PSRR is open.
- **Adopt `sky130-opamp` now and change later.** Rejected: pinning a block
  whose contract is already known not to fit gives a false "adopted" claim.
- **Own comparator.** Rejected: no reason found that the sibling's rows fail
  this use; the open items above are checks, not evidence of mismatch.
- **Instantiate `sky130-bandgap`.** Rejected: out of scope, and a different
  supply domain.

## Spec lines affected

Rows 11, 12 and 13 of `modulator-adc.md` (as constraints on the amplifier
and comparator); no numeric value changes.

## Consequences

- An own fully-differential amplifier with common-mode feedback will be
  designed and verified in this repo; that is the largest analog design item
  and gets its own issue.
- The comparator is a pinned dependency; its pin bumps need a record.
- Issue #4 (flows and PDK pin) should treat `reuse.lock.json` as the
  place pins live.

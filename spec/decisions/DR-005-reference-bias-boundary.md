# DR-005: Reference and bias boundary

- **Status**: proposed; ratified when the PR carrying it (issue #2) is
  Judge-approved and merged
- **Date**: 2026-10-17
- **Decided by**: Builder agent, issue #2

## Context

The voltage reference and bias generation are inputs at the block boundary
and out of scope (`CLAUDE.md`, README). The modulator's accuracy still
depends on what those inputs do, so the assumptions need to be written
down: a testbench drives them as ideal or modelled sources, and a later
integration claim is only valid where the real source meets them.

## Decision

The block assumes at its boundary:

| Input | Assumption | Basis |
|---|---|---|
| Differential reference span `VREF` | 1.20 V planning value (`VREFP − VREFN`), static in the signal band | The `sky130-bandgap` ratified output (1.20 V ± 2 % untrimmed, commit `f6ad34ec46d7b40c12aaebdb7d5b0b71d7a42801`) is the reference point, not a dependency. The spec's budgets scale with the real value. |
| Reference accuracy | Gain error of ± 2 % is acceptable: it scales the full scale, not the noise floor. SNDR is quoted relative to the stated dBFS input. | A single-bit loop's SNR depends on the ratio of signal to reference, not on the reference accuracy. |
| Reference noise | In-band (0 – `BW`) noise referred to `VREF` below 15 µV rms, planning value: 25 % of the power of the 30 µV rms thermal share in spec §5.3 (15² / 30²). The real figure comes from the behavioural model's reference-noise term. | planning allocation, replaced only through a new record |
| Reference settling | The reference is delivered to the feedback capacitors through a source whose impedance and decoupling make the reference node settle within the sampling phase (97.7 ns at 5.12 MHz) to a level the B model sets (starting point 0.01 %). | planning value |
| Bias current | A DC bias current reference for the amplifier and comparator tail currents, with accuracy ± 10 % assumed in testbenches, whose own power is excluded from `P_ana` and whose draw by the block is included. | row 13 |
| Common mode | Input and output common mode `VCM` = 0.9 V = `VDD`/2, supplied at the boundary. | planning value; the amplifier's input range is an own-amp row |
| Supply | `VDDA`, `VDDD` as in row 12 with the separation of [DR-004](DR-004-mixed-signal-floorplan.md). | |

Out of scope, not designed here: the reference, bias generation, `VCM`
generation, and any anti-alias filter ahead of the sampler.

## Alternatives considered

- **State no reference noise/settling assumption.** Leaves the testbench with
  arbitrary values; the SNDR numbers could not be compared run to run.
- **Include an own reference or bias.** Out of scope per `CLAUDE.md`.
- **Assume an ideal reference throughout.** Overstates every result; kept
  as the first testbench case only, and labelled ideal.

## Spec lines affected

Rows 11, 12, 13 of `modulator-adc.md`; §5.3 budget inputs.

## Consequences

Every testbench states its reference source (ideal, or the model with the
numbers above). A result with an ideal source does not substitute for one
with the assumed noise and settling.

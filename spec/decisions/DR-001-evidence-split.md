# DR-001: Evidence split between behavioural model and transistor-level runs

- **Status**: proposed; ratified when the PR carrying it (issue #2) is
  Judge-approved and merged
- **Date**: 2026-10-17
- **Decided by**: Builder agent, issue #2

## Context

A resolution claim needs a long output record. 2^16 output samples at
`OSR` = 128 is 8.4 M modulator clocks; a transistor-level ngspice transient
of that length is not a practical routine run. `CLAUDE.md` requires the
split between a behavioural model and transistor-level runs to be decided
and recorded before the first result.

## Decision

1. **Behavioural model (B)** produces the long-record SNDR numbers (row 2 of
   [`modulator-adc.md`](../modulator-adc.md)): at least 2^16 output samples,
   swept input amplitude, coherent tone, window and bin bandwidth stated
   (§1.2 of the spec). B is a discrete-time model of the second-order
   single-bit loop whose non-ideality parameters are *inputs taken from T*:
   finite DC gain, integrator settling error, charge-injection offset and
   gain error, kT/C noise power, comparator offset and hysteresis, clock
   jitter.
2. **Transistor-level runs (T)** produce those non-ideality parameters, one
   mechanism at a time, on the real schematic in ngspice: integrator
   settling and finite gain (a single integrator step and AC response),
   charge injection (switch transient), kT/C and amplifier noise (`.noise`
   or sampled-noise transient), comparator offset and decision time.
   T also runs a **short** full-modulator transient (record length stated,
   expected to be a small fraction of B's) as the cross-check vehicle.
3. **Cross-check (mandatory).** For each corner in
   [DR-002](DR-002-pvt-corners.md), the B model, loaded with that corner's
   T-extracted parameters, is run on the *same* input and clock sequence as
   the short T transient. The two output bitstreams are compared; the model
   is accepted at that corner only if the in-band SNDR of the two agrees to
   within **3 dB** over the same short record, and the integrator output
   waveforms agree. The 3 dB figure is a starting tolerance for a short,
   noisy record; tightening it needs a new record, loosening it too. An
   SNDR from B at a corner without a passing cross-check is reported as
   **uncross-checked** and is not used for a row 2 claim.
4. **Post-layout (P)** repeats T's extraction and the short full-modulator
   transient on extracted parasitics with the digital block placed; the B
   parameters are refreshed from it and row 2 is re-evaluated.
5. **Every SNDR number** states: source (B, T, P), record length,
   window, bin bandwidth, input amplitude in dBFS, corner, and cross-check
   status. The recorded results are append-only.
6. **Compute.** T runs that are grids (corners, Monte Carlo) go through
   `klt sim`'s batch backend; this record sets the split, not the
   scheduling.

## Alternatives considered

- **Transistor-level only, long record.** Honest by construction, but the
  record needed for a 80 dB claim at bin resolution is beyond a routine
  ngspice run, and a handful of corners would multiply it. Not chosen.
- **Behavioural model only, parameters from hand calculation.** Cheap, but
  the parameters would be unfalsified; the cross-check is the point. Not
  chosen.
- **Verilog-A / Verilog-AMS mixed model of the loop in ngspice.** Possible
  in principle; adds an unvalidated model language to the toolchain the
  canary is meant to exercise. Not chosen for the first pass; may be
  revisited by a new record.
- **Tolerance of 1 dB in the cross-check.** Rejected for the short record:
  the SNDR estimate of a short noisy record has a spread of that order
  by itself.

## Spec lines affected

Rows 2, 3, 5, 14 and §1.2 of `modulator-adc.md` (the definition of an SNDR
number).

## Consequences

- Every B result depends on T having produced its parameters first; the
  rungs of the maturity ladder are ordered accordingly.
- A failed cross-check is a finding about the model, not a license to relax
  a row.
- The 3 dB tolerance and the "short record" length are the first things to
  revisit when the first cross-check runs; changing them is a new record.

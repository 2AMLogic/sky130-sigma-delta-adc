# DR-006: Decimation stopband (row 9) is graded in the alias bands, with a gap floor

- **Status**: proposed; ratified by the operator's approval of the PR that
  lands it (issue #18), after the EE and market key reviews
- **Date**: 2026-10-24; revised 2026-10-25
- **Decided by**: Builder agent, issue #18, carrying the operator's ruling
  (rjwalters, 2026-10-24, fleet:decide round 20261024-r1, q28 option 1: open a
  spec PR with option (a); key reviews first, then operator ratification),
  revised by the Doctor agent on the operator's ruling of 2026-10-25
  (fleet:decide round 20261024-r1, q38) to add a gap floor, after the market
  key escalated the alias-band-only reading

## Context

Row 9 of `modulator-adc.md` read "≥ 90 dB from `fout − BW` to `fs/2`". The
decimator (PR #17) is gated on the alias bands `k·fout ± BW`, k = 1 … 32 (the
last clipped at `fs/2`), and passes at **93.91 dB** worst, at 300 kHz. Over
the literal range 60 kHz … `fs/2` the worst attenuation is **79.20 dB** at
284.5 kHz, in a gap between two alias bands. Both numbers are printed by
`verification/decimator/response.py` (50 Hz grid). Both are B-class, analytic, from the quantized
coefficients in `rtl/decimator_coef.v`; nothing here is measured.

Agents may not relax the ratified spec, so PR #17 left `spec/` untouched and
issue #18 asked the spec owner which reading is intended.

## Decision

Row 9 is graded in two parts across the whole stopband:

- **Alias bands**: attenuation of at least 90 dB (target) at every frequency in
  `[k·fout − BW, k·fout + BW]`, k = 1 … `fs/(2·fout)`, the last band clipped at
  `fs/2`.
- **Elsewhere**: attenuation of at least **75 dB** at every other frequency from
  `fout − BW` (60 kHz) to `fs/2`, i.e. the gaps between alias bands.

The row text in `modulator-adc.md` is reworded accordingly; fallback (80 dB)
and stretch (100 dB) keep their values on the alias bands, and the 75 dB gap
floor applies at all three levels. `response.py` gates both lines.

Why 90 dB is only needed in the alias bands: decimating by `fout`-spaced steps
folds a component at frequency `f` to `|f − k·fout|`. Only components within
`BW` of some `k·fout` land in the graded SNDR band `[0, BW]`. A component in a
gap between alias bands lands in `(BW, fout/2]`, which SNDR (§1.2) does not
integrate. Rationale 8–10 already states the purpose of the stopband: alias
leakage of the shaped quantization noise into the signal band.

Why the gaps carry a floor at all: the market key found the alias-band-only
reading left the gaps with no stated value, whereas every public decimating
converter it compared (TI PCM4220, PCM1808, PCM1863, ADS1271) states one
stopband figure over its whole stopband, gaps included. A graded floor makes
the row comparable to those parts.

Why 75 dB: it is set against the 79.20 dB analytic minimum at 284.5 kHz of the
filter in PR #17, which it clears with 4.2 dB of margin, and it is the
−75 dB of the PCM1863 low-latency response, the floor the market key named as
sufficient for a competitive finding. A stricter floor (80 dB, which 79.20 dB
misses) or the literal 90 dB would need the filter redesign of option (c).

**Stated consequence: 75 dB is the most the spec promises between alias
bands.** A future filter change must keep both lines passing, and a gap figure
under 75 dB fails the row. Out-of-band content that lands in `(BW, fout/2]` is
outside the 0 – `BW` output band the spec defines.

## Alternatives considered

- **(a) Alias bands only, gaps ungraded** (this record's first version).
  Superseded: the market key could not find it competitive, since no public
  part leaves any stopband frequency without a stated figure.
- **(b) Split row 9: alias bands ≥ 90 dB gated, gaps gated at a stated floor.**
  **Adopted**, with a 75 dB floor rather than the 80 dB first floated, because
  79.20 dB does not meet 80 dB; the 75 dB is justified under "Decision".
- **(c) Keep the literal row; restructure the decimator to ≥ 90 dB everywhere.**
  Strictest, no spec change. Rejected: per `rtl/DESIGN_NOTE.md` it needs a much
  longer FIR at the input rate or a different decimation structure, spending
  area and power for attenuation in bands that carry no aliased noise into
  0 – `BW`, and it would not change the in-band result.

## Spec lines affected

Row 9 (all three columns) and rationale 8–10 of `modulator-adc.md`. No other
row changes; row 10 (CIC order ≥ 3) is untouched.

## Consequences

- `response.py` gates both lines (alias bands ≥ 90 dB, gaps ≥ 75 dB) and
  `rtl/DESIGN_NOTE.md` describes this reading.
- `verification/decimator/record.json` was recorded before the gap line
  existed and is left as recorded (append-only evidence); regenerate it at the
  next RTL or filter change. The gap figure is reproducible by running
  `response.py` on the committed coefficients.
- A future filter change is graded on both lines.
- If the operator does not ratify, the literal row stands and the decimator
  needs the redesign of option (c).

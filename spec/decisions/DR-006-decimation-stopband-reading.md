# DR-006: Decimation stopband (row 9) is graded in the alias bands

- **Status**: proposed; ratified by the operator's approval of the PR that
  lands it (issue #18), after the EE and market key reviews
- **Date**: 2026-10-24
- **Decided by**: Builder agent, issue #18, carrying the operator's ruling
  (rjwalters, 2026-10-24, fleet:decide round 20261024-r1, q28 option 1: open a
  spec PR with option (a); key reviews first, then operator ratification)

## Context

Row 9 of `modulator-adc.md` read "≥ 90 dB from `fout − BW` to `fs/2`". The
decimator (PR #17) is gated on the alias bands `k·fout ± BW`, k = 1 … 32 (the
last clipped at `fs/2`), and passes at **93.91 dB** worst, at 300 kHz. Over
the literal range 60 kHz … `fs/2` the worst attenuation is **79.20 dB** at
284.5 kHz, in a gap between two alias bands. Both numbers are printed by
`verification/decimator/response.py` (50 Hz grid; the second is
informational, not gated). Both are B-class, analytic, from the quantized
coefficients in `rtl/decimator_coef.v`; nothing here is measured.

Agents may not relax the ratified spec, so PR #17 left `spec/` untouched and
issue #18 asked the spec owner which reading is intended.

## Decision

Row 9 is graded **in the alias bands**: attenuation of at least 90 dB (target)
at every frequency in `[k·fout − BW, k·fout + BW]`, k = 1 … `fs/(2·fout)`, the
last band clipped at `fs/2`. The row text in `modulator-adc.md` is reworded
accordingly; fallback (80 dB) and stretch (100 dB) keep their values and the
same band definition.

Why this is the intent, not a relaxation: decimating by `fout`-spaced steps
folds a component at frequency `f` to `|f − k·fout|`. Only components within
`BW` of some `k·fout` land in the graded SNDR band `[0, BW]`. A component in a
gap between alias bands lands in `(BW, fout/2]`, which SNDR (§1.2) does not
integrate. Rationale 8–10 already states the purpose of the stopband: alias
leakage of the shaped quantization noise into the signal band.

**Stated consequence: frequencies in the gaps between alias bands are not
graded by row 9.** The worst gap figure (79.20 dB at 284.5 kHz as of the
filter in PR #17) is reported by `response.py` as information and is not a
pass/fail number. Out-of-band content that lands in `(BW, fout/2]` is outside
the 0 – `BW` output band the spec defines.

## Alternatives considered

- **(b) Split row 9: alias bands ≥ 90 dB gated, full range gated at a stated
  floor (e.g. 80 dB).** Keeps a gated number over the whole range and 79.20 dB
  nearly meets 80 dB. Rejected: the floor is a new spec number that needs its
  own justification, and no downstream consumer of the 0 – `BW` band depends on
  it.
- **(c) Keep the literal row; restructure the decimator to ≥ 90 dB everywhere.**
  Strictest, no spec change. Rejected: per `rtl/DESIGN_NOTE.md` it needs a much
  longer FIR at the input rate or a different decimation structure, spending
  area and power for attenuation in bands that carry no aliased noise into
  0 – `BW`, and it would not change the in-band result.

## Spec lines affected

Row 9 (all three columns) and rationale 8–10 of `modulator-adc.md`. No other
row changes; row 10 (CIC order ≥ 3) is untouched.

## Consequences

- `response.py` and `rtl/DESIGN_NOTE.md` already implement and describe this
  reading; the open "to be confirmed by the spec owner" note in the design
  note is closed by this record once ratified (a follow-up edit to that note is
  outside this PR).
- A future filter change is graded on the alias bands at ≥ 90 dB; the
  gap-band informational figure must keep being reported so a regression there
  stays visible.
- If the operator does not ratify, the literal row stands and the decimator
  needs the redesign of option (c).

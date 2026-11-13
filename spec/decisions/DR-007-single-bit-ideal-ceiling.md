# DR-007: The section 5.1 ideal ceiling is corrected for the single-bit full-scale convention

- **Status**: proposed; ratified by the operator's approval of the PR that
  lands it (issue #108)
- **Date**: 2026-11-13
- **Decided by**: Builder agent, issue #108
- **Supersedes**: the quantizer term of §5.1 of `modulator-adc.md` as ratified
  on 2026-10-17, and the figures derived from it (listed under
  [Spec lines affected](#spec-lines-affected)). No ratified row value changes.

## Context

§5.1 of `modulator-adc.md` states the ideal quantization-noise ceiling as

    SQNR = 6.02·N + 1.76 − 10·log10(π^(2L)/(2L+1)) + (2L+1)·10·log10(OSR)

and reports 100.2 dB at full scale and **94.2 dB at the −6 dBFS input of
row 11** for `L` = 2, `N` = 1, `OSR` = 128. Rationale row 2 reads "80 dB
leaves about 20 dB for all non-idealities" off that derivation, §4 reads the
reachability of the 90 dB stretch off it, and §5.3 takes its quantization
share from it.

With the estimator fix of #107 on `main`, ideal behavioural model B reads
**86.17 dB** at the same operating point (source B, simulated, N = 2^16
output samples, 4-term Blackman-Harris, bin 1.2207 Hz, 0–20 kHz,
`sim/bmodel/records/20261113T142853Z-f8b2fa44.json`). That is 8.08 dB below
the stated ceiling, and before this record the gap was unexplained (#108).
A ceiling the architecture cannot approach is not a usable headroom argument,
so the gap had to be attributed before any non-ideality budget read against
it could mean anything.

`sim/bmodel/ceiling_gap.py` (added by this change) generates one bitstream at
the row-11 operating point and reads it three ways. Its record is
append-only evidence under `sim/bmodel/records/`; everything in it is
**simulated**, source B, and not cross-checked against T.

    spec 5.1 as written                      94.25 dB   (closed form)
      level-count corrected                  88.23 dB   (closed form)
    brick-wall reading of the bitstream       85.02 dB   (measured)
    committed sinc^3 path                     86.17 dB   (measured)

    deficit, spec 5.1 to sinc^3                8.08 dB
      1. formula full-scale convention        +6.02 dB
      2. single-bit loop                      +3.20 dB
      3. sinc^3 decimator                     -1.15 dB

The three terms are successive differences along one chain of four figures, so
their closure is algebraic; the content is the two measured intermediate
figures. Both are cross-checked:

- The sinc^3 figure is **predicted from the full-rate spectrum** by folding it
  through the decimator's own `(sin(πj/N)/(D·sin(πj/ND)))^3` response:
  86.25 dB against 86.17 dB measured (+0.08 dB). Splitting that prediction
  into its `m` = 0 and `m` ≥ 1 folds gives 86.88 dB from passband droop alone
  and an alias power of 0.154 of the drooped in-band noise power.
- The single-bit term is cross-checked against a describing-function model
  using the loop's **measured** effective quantizer gain and error variance
  (2.510 and 0.3062, against the 4.0 and 1/3 the unscaled derivation assumes):
  84.54 dB against 85.02 dB measured (−0.48 dB).
- The small-angle step in the closed form is ruled out as a contributor: the
  exact band integral of `|(1−z^-1)^2|^2` differs from it by 0.0003 dB.

At N = 2^13 the three terms are +6.02 / +3.20 / −1.24 dB, so none of this is a
record-length artefact.

**One asymmetry is disclosed rather than corrected.** The sinc^3 path is
`run.run_point` unchanged, and `sndr.sinc3_decimate` returns two output samples
fewer than the requested record length after the warm-up slice, so that path
analyses 65534 samples and its tone sits at 1638.95 cycles instead of 1639. The
brick-wall path analyses exactly `n_out`·64 clocks and is exactly coherent. The
record states the analysed length and the tone residual for each path. The
difference is left in place deliberately: the sinc^3 figure here is then
bit-identical to the committed `run.py` figure (86.17050637350252 dB), which is
what the decomposition has to explain. The residual is carried entirely by the
`sinc3_decimator` term and is bounded by the fold cross-check's +0.08 dB.
Whether `run.py` should analyse the full requested length is a separate
question about that script, not about this ceiling, and is filed separately.

### Why the formula is 6.02 dB high at `N` = 1

`6.02·N + 1.76` is `10·log10(1.5·2^(2N))`: signal power `A²/2` with
`A = 2^(N−1)·Δ` over an error variance `Δ²/12`. That amplitude is the edge of
the *conversion range*, half a step beyond the outermost quantizer level. For
`N` = 1 it is `Δ`, i.e. **twice** the ±1 feedback level that
`sim/bmodel/model.py` and row 11 define as full scale — a single-bit quantizer
has no level at ±Δ to reach. Taking the amplitude the outer levels actually
reach, `((2^N − 1)/2)·Δ`, gives `10·log10(1.5·(2^N − 1)²)`. The two forms
differ by `20·log10(2^N/(2^N − 1))`: 6.02 dB at `N` = 1, 0.001 dB at `N` = 13,
0.0003 dB at `N` = 16.

So the error is specific to the single-bit case, which is exactly the
architecture row 3 ratifies. §5.5's 16-bit arithmetic is unaffected.

### Why the remaining 3.2 dB is the loop, not the model's parameters

The brick-wall reading is 3.20 dB below the corrected closed-form bound. That
bound assumes a quantizer error that is white with variance `Δ²/12` = 1/3 and
a loop whose NTF is exactly `(1−z^-1)^2`. The 0.5/0.5 loop's NTF is
`(1−z^-1)^2 / (1 + (a2·k − 2)z^-1 + (1 − a2·k + a1·a2·k)z^-2)` for a quantizer
of gain `k`; only `k = 1/(a1·a2)` = 4 makes the denominator 1. The loop's own
measured gain is 2.510, which does not, and its error variance is 0.3062
rather than 1/3. The describing-function prediction from those two measured
numbers lands 0.48 dB from the brick-wall figure.

**Not traced further.** The describing-function model is a
minimum-mean-square linearisation, not a derivation: the 0.48 dB residual is
not accounted for, the error spectrum's whiteness was not checked, and the
amplitude dependence was not measured away from −6 dBFS. The *term* is
measured; its *attribution* to the effective gain is indicative. This does
not affect the decision below, which rests on the measured brick-wall figure.

### The decimator flatters the figure

The leading hypothesis in #108 was that the sinc^3 decimator's finite
stopband aliases out-of-band shaped noise into 0–20 kHz, costing SNDR. It is
refuted: the committed path reads **1.15 dB higher** than a brick wall, not
lower. The CIC's passband droop reaches −2.74 dB at 20 kHz, where the shaped
noise is largest, and that attenuation (+1.86 dB on the in-band noise power)
exceeds what aliasing gives back (0.154 of the drooped in-band noise power,
−0.71 dB). Row 10 is untouched and no droop compensation is added.

## Decision

1. §5.1's quantizer term is **corrected** to `10·log10(1.5·(2^N − 1)²)`. For
   `L` = 2, `N` = 1 the derivation becomes `1.76 − 12.90 + 5·10·log10(OSR)`,
   and the table becomes 79.2 / 94.2 / 109.3 dB at full scale for
   `OSR` = 64 / 128 / 256, i.e. **88.2 dB** at the −6 dBFS input of row 11 at
   `OSR` = 128.
2. §5.1 states, next to the corrected formula, the figure ideal model B
   actually reaches at that operating point (86.2 dB, simulated) and points at
   this record for the split. **The headroom sentence of rationale row 2 uses
   the corrected bound at the row-11 input, 88.2 dB** — not the full-scale
   figure, and not the model's measured figure, which is evidence rather than
   a bound.
3. Every line listed below is corrected to match. A bare "94.2 dB" predating
   this record means the superseded −6 dBFS figure; after it, 94.2 dB is the
   *full-scale* ceiling at `OSR` = 128. The coincidence is called out in
   §5.1 so the two cannot be confused.
4. **No ratified row value changes.** The 80 dB target, 70 dB fallback, 90 dB
   stretch, `OSR`, the coefficients, the modulator order, row 10's CIC order
   and row 11's input ceiling all stand exactly as ratified. The §5.3 thermal
   allocation and its `Cs` = 0.38 pF / 1 pF results stand.

### Stated consequences

- **The headroom shrinks by 6 dB.** At the ratified operating point the ideal
  ceiling is 88.2 dB, so the 80 dB target leaves **8.2 dB** for all
  non-idealities, not the "about 20 dB" rationale row 2 claimed. Against the
  86.2 dB ideal model B actually reaches, the margin is **6.2 dB**. Correcting
  arithmetic is not a relaxation: the margin was always this, and the spec
  mis-stated it.
- **The 90 dB stretch is out of reach at the target bandwidth too.** §4
  previously said it could be pursued at `BW` = 20 kHz "with the
  non-idealities held 10 dB tighter". The corrected ceiling at the row-11
  input is 88.2 dB, below 90 dB, so no tightening of non-idealities reaches it
  with a second-order single-bit loop at an input of 0.5·`VREF`. The stretch
  column of row 2 keeps its ratified value and now depends on row 3's stretch
  architecture (or on a ratified change to row 11); this record does not
  adjust a row to fit.
- **Quantization takes a larger share of the §5.3 budget.** At the corrected
  ceiling the in-band quantization power at −6 dBFS is 2.7 × 10⁻¹⁰ V²
  (4.3 × 10⁻¹⁰ V² taking ideal model B's simulated figure instead of the
  bound), against the 6.9 × 10⁻¹¹ V² §5.3 quoted. It therefore consumes about
  30 % of the 9.0 × 10⁻¹⁰ V² "everything else" half of the allocation (48 %
  from the model figure), against about 8 % before. The allocation still
  closes and is **not** re-cut here; §5.3 says measured shares replace the
  split through a decision record, and that is a separate decision.
- **Nothing is owed by the decimator.** Row 10 and the committed sinc^3 path
  are vindicated, not implicated: both the droop and the aliasing are
  quantified and the net is favourable.
- `sim/bmodel/test_bmodel.py`'s `IdealVsFormula` no longer pins an
  unexplained deficit against the uncorrected bound. It asserts the corrected
  bound, the 6.02 dB convention error, that the two conventions agree at
  `N` = 16, and the three decomposition terms against the committed record.
- Existing records under `sim/bmodel/records/` are left as recorded
  (append-only). None of them quoted a §5.1 figure.

## Alternatives considered

- **(a) Leave §5.1 as written and add a note saying the B figure is
  legitimately below it.** Rejected. The formula is wrong for the ratified
  architecture by 6.02 dB, and rationale row 2, §4 and §5.3 quote numbers
  derived from it. A note would leave wrong figures in the rows that cite
  them, and would leave the headroom argument standing on a ceiling 6 dB
  above the real one.
- **(b) Correct §5.1 and also re-cut the §5.3 allocation to the new
  quantization share.** Rejected as scope. §5.3 fixes its split as a planning
  allocation to be replaced through its own decision record; the allocation
  still closes with the corrected share, so there is no forcing reason to
  re-cut it inside an arithmetic correction. The consequence is stated above
  instead.
- **(c) Respond to the smaller margin by changing the design** (raising row
  11's input ceiling toward full scale, raising `OSR`, rescaling the
  coefficients, or going higher-order / multi-bit). Rejected as scope and as
  premature: `CLAUDE.md` holds the second-order single-bit design as the one
  that must close first, and all four are ratified-row changes. This record
  states the consequence; acting on it is a separate ratified decision.
- **(d) Replace the sinc^3 decimator or add droop compensation**, on the
  original hypothesis that aliasing caused the gap. Rejected: the measurement
  refutes the hypothesis, and row 10 fixes the CIC order.
- **(e) Design a long-FIR brick-wall decimator for the comparison.**
  Rejected: an FFT of the bitstream at `fs`, summed over the same band with
  the same window and exclusions, is the same measurement with no filter
  design to defend. It reuses `sndr.sndr_db` unchanged, called with
  `fout_hz = fs`.

## Spec lines affected

In `modulator-adc.md`, as of `a85df18`:

| Line(s) | Was | Becomes |
|---|---|---|
| 82–84 (rationale row 2) | ceiling 100.2 dB at full scale, "80 dB leaves about 20 dB for all non-idealities" | ceiling 94.2 dB full scale / 88.2 dB at the row-11 input; 80 dB leaves about 8 dB, and about 6 dB against ideal model B |
| 173–181 (§4, first bullet) | `OSR` = 64 ceiling 85.2 dB; the 90 dB stretch "can still be pursued at the target bandwidth, where the ceiling is 100.2 dB" | `OSR` = 64 ceiling 79.2 dB full scale / 73.2 dB at the row-11 input; a second bullet records that the target-bandwidth stretch claim is now false |
| 195–207 (§5.1) | `6.02·N + 1.76`; `7.78 − 12.90 + 5·10·log10(OSR)`; 85.2 / 100.2 / 115.3 dB; "subtract 6 dB: 94.2 dB" | `10·log10(1.5·(2^N − 1)²)`; `1.76 − 12.90 + 5·10·log10(OSR)`; 79.2 / 94.2 / 109.3 dB with a −6 dBFS column; "subtract 6 dB: 88.2 dB", plus the measured model B figure and the 94.2 dB coincidence warning |
| 228 (§5.3) | quantization 6.9 × 10⁻¹¹ V² at −6 dBFS | 2.7 × 10⁻¹⁰ V² from the corrected bound (4.3 × 10⁻¹⁰ V² from ideal model B), with the share of the allocation it now takes |

No row of §1.1 changes. §5.2, §5.4 and §5.5 are unaffected; §5.5 is checked
above and its `N` = 16 arithmetic is within 0.0003 dB either way.

Outside `spec/`, `measurements/characterization.md` cited the superseded
94.2 dB ceiling and called the gap unexplained; its row-2 note is corrected to
cite this record, and `attestation/item8-envelope.json` is regenerated for the
new report bytes.

## Consequences if not ratified

The uncorrected §5.1 stands, and with it a headroom claim 6 dB larger than the
architecture can support, a §4 statement that the 90 dB stretch is reachable
at the target bandwidth, and a §5.3 quantization share four times too small.
`sim/bmodel/ceiling_gap.py` and its record stand either way — they are
measurements, not a spec change — and `IdealVsFormula` would have to go back
to pinning an unexplained deficit.

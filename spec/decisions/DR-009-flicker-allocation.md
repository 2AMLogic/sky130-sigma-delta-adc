# DR-009: An explicit amplifier 1/f line in the §5.3 budget; the 80 dB total is unchanged

- **Status**: proposed; ratified when the PR carrying it (issue #142) is
  Judge-approved and merged
- **Date**: 2026-11-14
- **Decided by**: Builder agent, issue #142 (step 2 of 3 of #138)
- **Supersedes**: nothing. No ratified decision record is edited; §5.3 of
  `modulator-adc.md` is amended only to point here.

## Context

§5.3 of `spec/modulator-adc.md` budgets 1.8 × 10⁻⁹ V² of in-band noise for
the 80 dB target and splits it: 9.0 × 10⁻¹⁰ V² thermal (of which
4.5 × 10⁻¹⁰ V² sampling-switch kT/C, the amplifier's thermal share the
remaining 4.5 × 10⁻¹⁰ V² implicitly), and the other 9.0 × 10⁻¹⁰ V² to
"quantization ..., switch charge injection, settling, clock jitter,
comparator offset leakage, output rounding, leakage and everything else".
Amplifier 1/f noise is named nowhere in that split (read on
`origin/main` @ `72a4837`, 2026-11-13).

The first transistor-level noise extraction
(`sim/integrator-noise/record.json`, issue #126 via PR #139) found the
amplifier's in-band noise flicker-dominated, so a flicker result had no
line to be graded against and was compared with the thermal-only line
"conservatively" — which is not a verdict. §5.3 itself provides the path:
"This split is a planning allocation ... measured shares replace it through
a decision record, not in place."

Issue #140 then measured the flicker/thermal split at the DR-002 anchor
corner with a sampled-data-correct referral
(`sim/integrator-noise/record-i140.json`, PR #171, merged 2026-11-14, on
`main` @ `6ce52dc`). This record consumes that evidence.

## The measured evidence

All figures are **T, simulated** (a simulated number is never called
measured), from `sim/integrator-noise/record-i140.json`: 45 corners of the
DR-002 grid, `.noise` integrals over **[1 Hz, 100 GHz]** with every band
integral starting at a **1 Hz** lower edge (`method.lower_edge`;
`var_audio_band_V2` repeats the baseband integral from 20 Hz so the edge
sensitivity is visible). The anchor corner is `tt/1.800V/27C`.

**Referral naming** (`budget.reported_twice`): the record reports the
amplifier verdict twice — the pre-#140 **static** treatment and the #140
**accumulating** referral — against the same budgets. Every total-thermal
number below names which referral it uses. The flicker/thermal split
applies to the accumulating figure.

**Unit trap, stated so nobody re-derives it wrong.** The per-device split
(`device_split.blocks.*`) is at the raw `nqci` node; the per-corner
`ampq.*` figures are **input-referred** (`input_referral` = 2.0, ×4 in
power). `flicker_share` is used here as a **dimensionless fraction**
applied to the input-referred **baseband** part only — the folded part
above BW is essentially thermal.

At the anchor `tt/1.800V/27C`, accumulated referral:

| quantity | value | band / edge |
|---|---|---|
| `ampq.var_baseband_V2` | 1.1280 × 10⁻⁸ V² | 1 Hz … 20 kHz, input-referred |
| `ampq.var_aliased_V2 / OSR` | 7.640 × 10⁻¹⁰ V² | folded above 20 kHz |
| `ampq.inband_V2` | 1.2044 × 10⁻⁸ V² | sum |
| `flicker_share` of the baseband part | 0.9979 | anchor-only split |
| **amplifier flicker, in-band** | **1.1257 × 10⁻⁸ V²** (93.5 % of `inband_V2`) | |
| **amplifier thermal + shot, in-band** | **7.876 × 10⁻¹⁰ V²** | incl. the folded part |

The split exists at **one corner only** (`device_split.one_corner_only`;
70 devices, the four named ones carrying 95.7 % against a 0.9 coverage
target): `klt sim` has no measurement form for ngspice's per-device,
per-mechanism vectors across a grid — filed under the friction protocol as
2AMLogic/klayout-tools#5553. A **per-corner thermal verdict is therefore
not available**, and nothing below extrapolates the anchor's 0.21 %
thermal share across the grid.

Grid-wide (45 corners, same record, same 1 Hz edge):

- **kT/C**: 8.206 × 10⁻¹¹ V² (`sf/1.980V/-40C`) to 1.568 × 10⁻¹⁰ V²
  (`fs/1.800V/125C`) against the 4.5 × 10⁻¹⁰ V² line — **45/45 pass**,
  7.39 dB to 4.58 dB of margin. No referral ambiguity: this integral is
  thermal by construction.
- **Total thermal, accumulated referral**: margins **−9.81 dB**
  (`sf/1.620V/-40C`) to **−12.72 dB** (`fs/1.980V/125C`), **0/45 pass**.
  The **static** referral reports **−15.62 dB** to **−18.41 dB**, also
  0/45; the accumulated referral buys **5.68–5.86 dB**
  (`accumulated_vs_static_db`). The "16–18 dB" quoted by #138 is the
  static read.
- **1 Hz vs 20 Hz edge**: the measured baseband integral falls
  1.2092×–1.2175× between the edges (mean 1.2132× over all 45 corners;
  0.84 dB at the anchor). The ratio's grid stability is why the edge is a
  real budget decision and not noise.

## Decision

§5.3's non-thermal half (9.0 × 10⁻¹⁰ V²) carries an explicit **amplifier
1/f line of 4.5 × 10⁻¹⁰ V²**, carved from the "everything else" remainder.
The budget for the 80 dB target column:

| line | V² | µV rms | status |
|---|---|---|---|
| total in-band noise for 80 dB | 1.8 × 10⁻⁹ | 42.4 | **unchanged** |
| thermal share | 9.0 × 10⁻¹⁰ | 30.0 | **unchanged** |
| — sampling-switch kT/C | 4.5 × 10⁻¹⁰ | 21.2 | unchanged (45/45 pass above) |
| — amplifier thermal (implicit in §5.3) | 4.5 × 10⁻¹⁰ | 21.2 | unchanged; see the finding below |
| non-thermal share | 9.0 × 10⁻¹⁰ | 30.0 | unchanged |
| — quantization at −6 dBFS, OSR 128 | 6.9 × 10⁻¹¹ | 8.3 | unchanged |
| — **amplifier 1/f (new)** | **4.5 × 10⁻¹⁰** | **21.2** | **added by this record** |
| — other named terms (charge injection, settling, clock jitter, comparator offset leakage, output rounding, leakage) | 3.81 × 10⁻¹⁰ | 19.5 | stated remainder (a number, not "the rest") |

Check: 4.5 + 4.5 + 0.69 + 4.5 + 3.81 = 18.0, i.e. the lines sum to
1.8 × 10⁻⁹ V². The single donor is the former "everything else" line: it
gives up 4.5 × 10⁻¹⁰ V² of its 8.31 × 10⁻¹⁰ V² (9.0 × 10⁻¹⁰ −
6.9 × 10⁻¹¹) and keeps 3.81 × 10⁻¹⁰ V². The thermal and kT/C lines give up
nothing and are not loosened.

**Lower band edge (part of the budget, since 1/f diverges downward).** The
flicker line is graded over **[1.22 Hz, 20 kHz]**: the lower edge is the
§1.2 bin bandwidth `fout / N` at the DR-001 minimum record length
(`fout` = 4·BW = 80 kSps for this column, N ≥ 2¹⁶ → 1.2207 Hz). The edge
is fixed at 1.22 Hz for the line regardless of a run's record length, so
the line stays one number a circuit can be designed against; a longer
record's extra sub-1.22 Hz resolution is reported alongside, not graded
into this line. The landed evidence integrals start at 1 Hz, which is
**within 0.09 dB** of 1.2207 Hz on a pure-1/f integral at N = 2¹⁶ (2.0 %
of the integral) — they are cited as-is above, no re-run needed. The
**20 Hz** edge is rejected: it would credit the line 0.84 dB it has not
earned (the grid-stable 1.209–1.218× ratio above is the measure of that).

**Why 4.5 × 10⁻¹⁰.** (i) It follows the budget's own planning convention:
§5.3 splits unevidenced allocations in halves (total → thermal /
non-thermal, thermal → kT/C / amplifier), and this is that split applied
once more. (ii) The only quantified need among the other non-thermal terms
is quantization's ratified 6.9 × 10⁻¹¹ V²; the carve leaves them
3.81 × 10⁻¹⁰ V², 5.5× that figure, so no known need is squeezed.
(iii) The measured evidence says the exact split inside this half does not
change any verdict today (below), so finer precision would be spurious.
(iv) Per §5.3's own rule, measured shares replace planning allocations
through a future record.

## What the evidence says about the present design (findings, not relaxations)

- **No carve-out makes the present OTA pass.** Even the entire
  8.31 × 10⁻¹⁰ V² remainder would be exceeded by the anchor's measured
  flicker by **11.32 dB**; against the new 4.5 × 10⁻¹⁰ V² line the miss is
  **14.0 dB** at the anchor (a measured 1.1257 × 10⁻⁸ V² is 12.5× the
  whole non-thermal half). That is the expected outcome, not a failed
  deliverable: the line is sized from what the other terms need, and
  closing the gap is #143's job (step 3). The allocation is deliberately
  not sized to the present OTA.
- **The amplifier's thermal-only share already misses its implicit line.**
  §5.3 gives the amplifier 9.0 × 10⁻¹⁰ − 4.5 × 10⁻¹⁰ = 4.5 × 10⁻¹⁰ V²
  implicitly. The anchor's measured thermal-and-shot in-band figure is
  7.876 × 10⁻¹⁰ V² — **2.43 dB over**, with no flicker in it (it does fit
  the whole 9.0 × 10⁻¹⁰ thermal half, by 0.58 dB, but the switches take
  half of it). The thermal line is **not** loosened to absorb this; the
  miss is recorded here as a distinct, separately-sourced finding for
  #143. Per-corner thermal verdicts are unavailable (single-corner split,
  above), so this finding is stated at the anchor only.
- The kT/C line passes everywhere and is left alone.

## Alternatives considered

- **Sizing the flicker line to what the present OTA measures.** Rejected
  (the issue's guidance rejects it too): 1.1257 × 10⁻⁸ V² would consume
  the whole non-thermal half 12.5× over and strand every other named term
  at zero.
- **Taking the flicker line out of the thermal half.** Rejected: it would
  shrink the thermal allocation below its ratified 9.0 × 10⁻¹⁰ V² without
  evidence that the amplifier's thermal share needs relief — and the
  measured thermal-only figure already misses the *existing* implicit
  line, so the opposite of relief is warranted.
- **Raising the total or lowering the 80 dB target.** Rejected: a
  relaxation. If the evidence eventually says the target is unreachable,
  that is an operator decision, not this record.
- **Grading from 20 Hz.** Rejected above: 0.84 dB unearned.

## Spec lines affected

- `spec/modulator-adc.md` §5.3: one added sentence pointing to this record
  for the split of the non-thermal half. No row of §1.1 changes; the
  total, the thermal line and the kT/C line keep their values.
- `spec/README.md`: index entry.
- No ratified decision record is edited; DR-001, DR-002 and DR-005 are
  cited only.

## Scope

Target column only. The fallback (70 dB, OSR 256) and stretch (90 dB)
columns keep §5.3's undivided non-thermal half: their `fout` differs
(40 / 200 kSps), so the bin-bandwidth edge does not fall out for free, and
no flicker evidence exists at their operating points. A future record sets
their lines if needed.

## Consequences

- Future amplifier-noise benches grade against both amplifier lines
  (thermal 4.5 × 10⁻¹⁰ V²; flicker 4.5 × 10⁻¹⁰ V² over [1.22 Hz, 20 kHz])
  instead of comparing a flicker result with the thermal-only line
  "conservatively".
- #143 designs against the flicker line and the 2.43 dB thermal finding;
  the 3.81 × 10⁻¹⁰ V² remainder bounds what the other non-thermal terms
  may ask of that work.
- The flicker/thermal split remains single-corner
  (2AMLogic/klayout-tools#5553); a grid-wide mechanism split needs a
  `klt sim` measurement form, and if it changes this allocation it goes
  through a new record.

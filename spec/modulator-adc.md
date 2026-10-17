# Target specification — sky130 delta-sigma ADC

- **Status**: ratified on merge of the pull request that carries it (issue
  #2). Later changes go through a new decision record under
  [`decisions/`](decisions/), never an in-place edit of a row.
- **Date**: 2026-10-17
- **Design under spec**: second-order, single-bit, switched-capacitor
  delta-sigma modulator plus a decimation filter, on SkyWater sky130
  1.8 V core devices (`sky130_fd_pr__*_01v8`).

## How to read this document

- **Target / fallback / stretch** follow `CLAUDE.md`: 80 dB in 20 kHz is the
  target, 70 dB the fallback, 90 dB the stretch. The columns are not
  independent knobs; see [§4 Consistency of the columns](#4-consistency-of-the-columns).
- **Evidence** names what will back each row, using the split in
  [DR-001](decisions/DR-001-evidence-split.md): **B** behavioural modulator
  model, **T** transistor-level ngspice, **P** post-layout simulation with the
  digital block in place, **D** DRC, **L** LVS.
- **Wording.** Every result in this repo is "simulated" or "post-layout
  simulated". Nothing is called measured until silicon exists
  (`measurements/` is empty until then).
- **SNDR convention.** Every SNDR number carries four things: the evidence
  source (B / T / P), the output-record length in samples, the analysis
  window, and the bin bandwidth (see [§1.2](#12-sndr-definition)). A number
  without them is not evidence.
- Arithmetic for every derived figure is in [§5](#5-derivations); where a
  number is a budget, the budget is shown.

## 1. Parameters

### 1.1 Table

| # | Parameter | Target | Fallback | Stretch | Evidence |
|---|---|---|---|---|---|
| 1 | Signal bandwidth, `BW` | 20 kHz | 10 kHz | 50 kHz | B, T, P |
| 2 | Peak SNDR over `BW` (simulated) | ≥ 80 dB | ≥ 70 dB | ≥ 90 dB | B (long record), T (non-idealities, cross-checked), P |
| 3 | Modulator | 2nd-order, single-bit, switched-capacitor | same | higher order or multi-bit (does not drive the architecture; see §4) | B, T |
| 4 | Oversampling ratio, `OSR = fs / (2·BW)` | 128 | 256 | 64 (at the 50 kHz bandwidth) | B, T |
| 5 | Modulator clock, `fs` | 5.12 MHz | 5.12 MHz (`BW` = 10 kHz, `OSR` = 256) | 6.4 MHz (`BW` = 50 kHz, `OSR` = 64) | B, T, P |
| 6 | Output word rate, `fout = 4·BW` | 80 kSps (decimate by 64) | 40 kSps (decimate by 128) | 200 kSps (decimate by 32) | B, RTL sim |
| 7 | Output word | 16-bit, two's complement | 16-bit | 16-bit (see §4) | RTL sim |
| 8 | Decimation passband | 0 – `BW`, ripple ≤ 0.1 dB | same | same | RTL sim |
| 9 | Decimation stopband | ≥ 90 dB from `fout − BW` to `fs/2` | ≥ 80 dB | ≥ 100 dB | RTL sim, B |
| 10 | Decimation filter order | CIC order ≥ 3 (= modulator order + 1), then FIR to `fout` | same | CIC order ≥ 4 if the modulator order rises | RTL sim |
| 11 | Input | fully differential, peak differential input ≤ 0.5 · `VREF` | same | same | B, T, P |
| 12 | Supply | `VDD` = 1.8 V ± 10 % (1.62 – 1.98 V), 1.8 V core devices only | same | same | T, P |
| 13 | Analog power, `P_ana` | ≤ 1 mW | ≤ 2 mW | ≤ 0.5 mW | T, P |
| 14 | Signoff | DRC + LVS clean, post-layout re-verified with the digital block in place | same | same | D, L, P |

Fallback and stretch columns of rows 1, 4, 5, 6 and 9 are one operating
point each (a bandwidth with its own OSR), not a free mix.

### 1.2 SNDR definition

SNDR is signal power over the sum of all other power in `[0, BW]`, from the
decimated output record, with a single-tone input at the stated amplitude.

- **Evidence source** — stated as B, T or P. B and T numbers are never
  quoted without the cross-check status of [DR-001](decisions/DR-001-evidence-split.md).
- **Record length** — a power-of-two number of *output* samples (target at
  least 2^16 = 65 536 for B; the T record length is whatever the cost
  allows and is stated per run, with its shorter-record limits).
- **Window** — Blackman-Harris 4-term (or the named alternative) with
  coherent sampling of the input tone to an integer number of cycles in the
  record, stated per run.
- **Bin bandwidth** — `fout / N` for `N` output samples, stated per run, with
  the tone-bin and leakage-bin exclusion used.
- **Input amplitude** — stated per run in dBFS; "peak SNDR" is the maximum
  over an amplitude sweep, reported with the amplitude at which it occurs.

"Peak SNDR (simulated) ≥ 80 dB" means row 2 is met by the B model, the
T-extracted non-idealities in the B model *and* the cross-check of DR-001 at
every corner in DR-002. It does not mean a T transient of the full record.

### 1.3 Row rationale

1. **Signal bandwidth.** The `CLAUDE.md` target is 20 kHz; 10 kHz is the
   fallback because it halves the in-band noise bandwidth and doubles `OSR`
   at an unchanged clock (§5.2), the cheapest way to buy back margin. 50 kHz
   is the stretch.
2. **Peak SNDR.** From `CLAUDE.md`. The ideal second-order, single-bit
   quantization-noise ceiling at `OSR` = 128 is 100.2 dB at full scale
   (§5.1), so 80 dB leaves about 20 dB for all non-idealities.
3. **Modulator.** Second-order single-bit is the architecture that must
   close first (`CLAUDE.md`). A higher order or multi-bit modulator does
   not drive any other row until it does.
4. **OSR.** From the README draft: 128 / 256 / 64. Defined as
   `fs / (2·BW)`.
5. **Clock.** `fs = 2·BW·OSR`: 5.12 MHz, 5.12 MHz, 6.4 MHz. The target and
   fallback share a clock on purpose: the fallback is a digital-filter
   change (a longer decimation chain), not an analog change. Whether the
   adopted comparator's decision time fits the half-period (97.7 ns at
   5.12 MHz, 78.1 ns at 6.4 MHz) is a check owed by
   [DR-003](decisions/DR-003-sibling-reuse.md), not a claim made here.
6. **Output rate.** Decided here as `4·BW`. A rate of `2·BW` leaves no
   transition band between the signal edge and the first alias, which would
   force a brick-wall filter. At `4·BW` the transition band is `BW` to
   `3·BW`, and aliases into the signal band come only from above
   `fout − BW = 3·BW`.
7. **Output word.** Answered in §5.5: 13 bits would just carry the 80 dB
   target (ENOB 13.0), so 16 bits is **headroom**, kept so the output
   rounding noise is not the dominant term; it is a convention, not a
   requirement of the 80 dB target.
8–10. **Decimation filter.** The passband ripple budget is 0.1 dB (1.2 % of
   amplitude, far below the SNDR budget; it is a gain error, not a noise
   term). The stopband is set so alias leakage from the shaped
   quantization noise lands well below the thermal floor of §5.3: 90 dB
   against the 80 dB target. The CIC order of (modulator order + 1) is the
   standard minimum to keep aliased shaped noise from dominating. Anything
   finer (stage split, coefficient widths) is RTL design, not spec.
11. **Input.** Differential at the boundary, decided here as a fraction of
    the reference: the peak differential input is at most **0.5 · `VREF`**
    (−6 dBFS), where `VREF` is the differential reference span at the
    boundary ([DR-005](decisions/DR-005-reference-bias-boundary.md)). A
    single-bit second-order loop is stable well above this; 0.5 leaves
    margin for the non-ideal loop and keeps the integrator swings inside the
    swing a 1.8 V core amplifier offers (§5.4). The fraction does not fix
    the reference *value*; the SNDR is measured relative to the stated
    amplitude in dBFS.
12. **Supply.** 1.8 V core only; no I/O (thick-oxide) devices. ± 10 % is the
    fleet convention (`sky130-opamp`).
13. **Analog power.** Counted on the analog rail `VDDA`: integrator
    amplifiers, comparator, bias branches inside the block, switch drivers
    and the non-overlapping clock generator when supplied from `VDDA`, plus
    the current the block draws from the reference. Not counted: the
    reference and bias generator themselves (out of scope). The decimation
    filter and control are on `VDDD` and are **reported separately** as
    `P_dig`, alongside `P_ana`, never summed into it and never omitted.
    Both are simulated (T / P), never measured.
14. **Signoff.** "DRC + LVS clean" means the `klt` DRC and LVS flows of the
    pinned toolchain ([#4](https://github.com/2AMLogic/sky130-sigma-delta-adc/issues/4))
    report zero violations / a matched netlist on the full-block layout.
    "Post-layout re-verified" means: parasitics extracted from that layout
    *including the placed-and-routed decimation filter*, the modulator
    re-simulated across the DR-002 corners with the extracted parasitics
    and a digital activity vector, and rows 2 and 13 re-checked. A
    modulator graded without the digital block in place does not satisfy the
    row ([DR-004](decisions/DR-004-mixed-signal-floorplan.md)).

## 2. Operating conditions

| Condition | Value |
|---|---|
| Supply | 1.62 / 1.80 / 1.98 V |
| Temperature | −40 / 27 / 125 °C |
| Process corners | `tt`, `ss`, `ff`, `sf`, `fs` (sky130 1.8 V-core MOS corners) |
| Output load | the decimation filter's input; no off-chip load is specified |

Corner definitions and the anchor subset are in
[DR-002](decisions/DR-002-pvt-corners.md).

## 3. Open questions, answered

- **kT/C against the target.** Yes, with a sampling capacitor of at least
  about 0.4 pF at 125 °C, if sampled thermal noise takes half of the total
  thermal share. Derivation in §5.3. The planning value is **1 pF**; it is
  a budget result, not a layout commitment.
- **Single-ended or differential sampling.** Differential (row 11). Reason
  and the consequence for the integrator amplifier in
  [DR-003](decisions/DR-003-sibling-reuse.md).
- **16-bit output.** Headroom, see row 7 and §5.5.

## 4. Consistency of the columns

Two rows are not jointly reachable with the architecture ratified here, and
this document says so rather than leaving it to be discovered:

- **Stretch SNDR at stretch bandwidth.** A second-order single-bit loop at
  `OSR` = 64 has an ideal quantization-noise ceiling of 85.2 dB (§5.1),
  below the 90 dB stretch SNDR. The stretch SNDR therefore needs a higher
  order or multi-bit modulator (row 3, stretch column). It cannot be met by
  the second-order design at `OSR` = 64, and per `CLAUDE.md` it does not
  drive the architecture. The 90 dB stretch **can** still be pursued at the
  *target* bandwidth, where the ceiling is 100.2 dB, only with the
  non-idealities held 10 dB tighter; that is a smaller claim and gets its
  own decision record if attempted.
- **Stretch SNDR and the 16-bit word.** 16 bits at 0.5 · `VREF` input rounds
  to a 92.1 dB SNR (§5.5); a 90 dB claim would be limited by the word. A
  stretch attempt widens the word through a decision record, not here.

Neither is a relaxation of a ratified row; they are the arithmetic stating
where the stretch column is out of reach of this architecture.

## 5. Derivations

All numbers are arithmetic from the stated assumptions, not simulation.

### 5.1 Ideal quantization-noise ceiling

For an `L`-th order, `N`-bit modulator at oversampling ratio `OSR`:

`SQNR = 6.02·N + 1.76 − 10·log10(π^(2L) / (2L + 1)) + (2L + 1)·10·log10(OSR)`

With `L` = 2, `N` = 1: `7.78 − 12.90 + 5·10·log10(OSR)`

| OSR | `10·log10(OSR)` | SQNR at full scale |
|---|---|---|
| 64 | 18.06 dB | 85.2 dB |
| 128 | 21.07 dB | 100.2 dB |
| 256 | 24.08 dB | 115.3 dB |

At the −6 dBFS input of row 11, subtract 6 dB: 94.2 dB at `OSR` = 128.

### 5.2 Clock and rates

`fs = 2·BW·OSR`: 2 × 20 kHz × 128 = 5.12 MHz; 2 × 10 kHz × 256 = 5.12 MHz;
2 × 50 kHz × 64 = 6.4 MHz. `fout = 4·BW`: 80 / 40 / 200 kSps; decimation
`fs / fout` = 64 / 128 / 32.

### 5.3 kT/C budget (target column)

Assumptions, each stated so it can be challenged:

- Peak differential input 0.5 · `VREF` with `VREF` = 1.2 V, so the peak
  differential input is 0.6 V and the signal power is
  (0.6 V)² / 2 = 0.18 V². (`VREF` = 1.2 V is the planning value taken from
  the boundary, [DR-005](decisions/DR-005-reference-bias-boundary.md); the
  budget scales with the real value.)
- Total in-band noise allowed for 80 dB: 0.18 V² / 10^8 = 1.8 × 10⁻⁹ V²
  (42.4 µV rms).
- Half of that, 9.0 × 10⁻¹⁰ V² (30 µV rms), is the thermal share (sampling
  switches and amplifier); half of the thermal share, 4.5 × 10⁻¹⁰ V², is
  the sampling-switch kT/C share. The rest (quantization 6.9 × 10⁻¹¹ V² at
  −6 dBFS, switch charge injection, settling, clock jitter, comparator
  offset leakage, output rounding, leakage and everything else) takes the
  other half. This split is a planning allocation. It is fixed here so the
  row has a budget; measured shares replace it through a decision record,
  not in place.
- Worst-case temperature 125 °C = 398.15 K, so `kT` = 5.497 × 10⁻²¹ J.
- Sampled noise on a differential input, counting the input and the
  reference sampling phases and both sides: `4·kT / Cs`, spread over
  `fs / 2` and filtered to `BW`, so in-band power `4·kT / (Cs · OSR)`.

`Cs ≥ 4·kT / (OSR · 4.5 × 10⁻¹⁰ V²)` = 4 × 5.497 × 10⁻²¹ /
(128 × 4.5 × 10⁻¹⁰) = **0.38 pF**.

Planning value `Cs` = 1 pF gives 1.72 × 10⁻¹⁰ V² (13.1 µV rms), a
kT/C-only SNR of 90.2 dB, a 4 dB margin over the 86.0 dB the allocation
needs at 0.38 pF. The area implication (a 1 pF MIM capacitor is of the order
of a few hundred µm² at roughly 2 fF/µm²) is to be confirmed against the
installed PDK capacitor models when the capacitors are drawn, and is not
used in any ratified number. At the 70 dB fallback (`OSR` = 256, the same
`Cs`) the in-band kT/C power halves, so the fallback is easier on this term.

The same arithmetic would need a 4× larger `Cs` for each additional 6 dB;
that is the cost of the 90 dB stretch at the target bandwidth.

### 5.4 Integrator swing

Peak differential input 0.6 V against a 1.2 V differential reference puts
each side within ± 0.3 V of the common mode at the input. The integrator
outputs of a second-order single-bit loop at this input stay well inside the
≈ 1.39 V<sub>pp</sub> output swing `sky130-opamp` reports at its worst
corner; this is checked in the behavioural model and the transistor-level
runs, not assumed.

### 5.5 Output word

ENOB for 80 dB: (80 − 1.76) / 6.02 = 13.0 bits. A 16-bit output with the
peak input at 0.5 of full scale has SNR = 6.02 × 16 + 1.76 − 6 = 92.1 dB.
Output rounding noise therefore consumes about 6 % of the 80 dB noise
budget (10^(−92.1/10) against 10^(−80/10)), which is why it is listed in the
"everything else" half of §5.3, and why 16 bits is headroom rather than a
requirement.

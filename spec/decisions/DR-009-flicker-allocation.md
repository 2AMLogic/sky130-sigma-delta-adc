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

Issue #140 then simulated the baseband flicker/thermal split at the DR-002
anchor corner with a sampled-data-correct referral
(`sim/integrator-noise/record-i140.json`, PR #171, merged 2026-11-14, on
`main` @ `6ce52dc`). This record cites that archived evidence as context
for adding a planning 1/f line to §5.3 without altering any ratified spec
row.

## Simulated evidence (pre-change integrator revision `6ce52dc`)

All figures below are **T, simulated** (ngspice `.noise`, transistor-level;
a simulated number is never called measured), from
`sim/integrator-noise/record-i140.json`: 45 corners of the DR-002 grid,
`.noise` sweeps over **[1 Hz, 100 GHz]** with every baseband integral
taken over **[1 Hz, 20 kHz]** (`method.lower_edge` = 1 Hz;
`var_audio_band_V2` repeats the baseband integral over **[20 Hz, 20 kHz]**
so the lower-edge sensitivity is visible). The anchor corner is
`tt/1.800V/27C`.

**Provenance and freshness (pre-change integrator cell).**
`record-i140.json` pins `integrator_netlist_sha256` =
`18fc51475f667eea993fbef4e9a3abe7eaa35863ae88f86c25bfb56bc4074d53`
(`design/integrator/integrator.spice` at `c94680c` / `6ce52dc`) and
`ota_netlist_sha256` =
`7f4724e9631c05760bc98d161100c41b06928b98e0526c027e6a9271d70f7977`
(`design/ota/ota_fd.spice`). On the current branch and `main`,
`design/ota/ota_fd.spice` still hashes to `7f4724e9…` (unchanged), but
`design/integrator/integrator.spice` now hashes to
`6857c4ca5422d9736e6e18a898ab873a7fab9cc1bc89e3e395abe55ab66e1c9d` after
three later commits: `9b222a3` (adding PMOS halves to `Sci`/`Scr` and the
`phi1eb` inverter, issue #147), `69b14ee` (changing both `Sin` input
transmission gates to low-Vth devices with PMOS L = 0.35 µm, per DR-010),
and merge `6cb1075`. Those switch-network changes alter switch
on-resistance and parasitic capacitances in the sampled-noise transfer.
Consistent with DR-010's Consequences (`sim/integrator-noise/record*.json`
classified as pre-change-cell evidence pending #266), **every simulated
figure below applies to the tested `6ce52dc` integrator revision and its
static-phase `.noise` bench model — not to the current integrator
netlist**. Current-integrator kT/C and amplifier-noise margins remain
**open** until `sim/integrator-noise` is re-run on the updated cell (#266;
and after OTA redesign in #143).

**Referral naming** (`budget.reported_twice`): `record-i140.json` reports
the composite grid comparison twice — the pre-#140 **static** treatment
and the #140 **accumulating** referral — against the same budgets. Every
grid number below names which referral it uses. The baseband
flicker/thermal split applies to the accumulating figure (`ampq`).

**Unit trap and mechanism-split scope.** The per-device split
(`device_split.blocks.inband_nqci`) is recorded at the raw `nqci` node;
the per-corner `ampq.*` figures are **input-referred** (`input_referral` =
2.0, ×4 in power). `flicker_share` and `thermal_and_shot_share` are used
here as **dimensionless fractions** applied to the input-referred
**baseband `[1 Hz, 20 kHz]`** variance only. Crucially,
`device_split.blocks` contains **no mechanism or device split for the
folded above-band term `var_aliased_V2 / OSR` (`[20 kHz, 100 GHz]`)**, and
the phase-2 `ampq` probe includes both OTA devices and `phi2` switches
(`record-i140.json` `leaves_out` notes that `phi2` switches contribute in
the aliased band). Assigning all of `var_aliased_V2 / OSR` to OTA
thermal + shot therefore gives an **upper bound**, not a verified
thermal-only variance.

At the `6ce52dc` anchor `tt/1.800V/27C`, accumulated referral (T,
simulated, 1 Hz lower edge):

| quantity | value | band / scope |
|---|---|---|
| `ampq.var_baseband_V2` | 1.1280 × 10⁻⁸ V² | `[1 Hz, 20 kHz]`, input-referred |
| `ampq.var_aliased_V2 / OSR` | 7.640 × 10⁻¹⁰ V² | folded from `[20 kHz, 100 GHz]`, unsplit by mechanism or device |
| `ampq.inband_V2` | 1.2044 × 10⁻⁸ V² | sum (`[1 Hz, 100 GHz]` sweep, 1 Hz edge) |
| `flicker_share` (baseband only) | 0.9979 | anchor-only split over `[1 Hz, 20 kHz]` |
| `thermal_and_shot_share` (baseband only) | 0.0021 | anchor-only split over `[1 Hz, 20 kHz]` |
| **amplifier baseband flicker** | **1.1257 × 10⁻⁸ V²** (93.5 % of `inband_V2`) | `[1 Hz, 20 kHz]` |
| **amplifier baseband thermal + shot** | **2.368 × 10⁻¹¹ V²** (5.3 % of implicit 4.5 × 10⁻¹⁰ line) | `[1 Hz, 20 kHz]` |
| **amplifier thermal + shot upper bound** | **7.876 × 10⁻¹⁰ V²** | baseband thermal + shot + 100 % of unsplit folded term (conditional upper bound; thermal-only verdict unresolved) |

The baseband mechanism split exists at **one corner only**
(`device_split.one_corner_only`; 70 devices, the four named OTA devices
carrying 95.7 % against a 0.9 coverage target): `klt sim` has no
measurement form for ngspice's per-device, per-mechanism vectors across a
grid — filed under the friction protocol as
`2AMLogic/klayout-tools#5553`. A **per-corner thermal-only verdict is
therefore not available**, and nothing below extrapolates the anchor's
0.21 % baseband thermal share across the grid.

Grid-wide on the pre-change `6ce52dc` integrator (45 corners,
`record-i140.json`, `[1 Hz, 100 GHz]` sweep, 1 Hz lower edge):

- **Sampling-switch kT/C (pre-change `6ce52dc` cell)**: 8.206 × 10⁻¹¹ V²
  (`sf/1.980V/-40C`) to 1.568 × 10⁻¹⁰ V² (`fs/1.800V/125C`) against the
  4.5 × 10⁻¹⁰ V² line — **45/45 pass** on the tested `6ce52dc` revision,
  7.39 dB to 4.58 dB of margin (thermal by construction). Current-cell
  kT/C margins after the #147 / DR-010 switch updates are **open** until
  re-run (#266).
- **Composite kT/C + full amplifier noise (thermal + flicker) graded
  against the 9.0 × 10⁻¹⁰ V² thermal allowance (pre-change `6ce52dc`
  cell)**: margins under the **accumulated** referral
  (`total_thermal_accumulated_*`) run **−9.81 dB** (`sf/1.620V/-40C`) to
  **−12.72 dB** (`fs/1.980V/125C`), **0/45 pass**. Under the pre-#140
  **static** referral (`total_thermal_*`) they run **−15.62 dB** to
  **−18.41 dB**, also 0/45; the accumulated referral buys **5.68–5.86 dB**
  (`accumulated_vs_static_db`). The "16–18 dB" quoted by #138 is the
  static composite read. Because `ampq.inband_V2` sums amplifier flicker
  and thermal noise together, **this 0/45 composite comparison does not
  establish a per-corner thermal-only failure**.
- **1 Hz vs. 20 Hz lower edge (`6ce52dc`, 45 corners)**: the simulated
  `ampq` baseband integral falls 1.2092×–1.2175× between `[1 Hz, 20 kHz]`
  and `[20 Hz, 20 kHz]` (mean 1.2132× over all 45 corners; 1.2130× =
  0.84 dB at the anchor, compared with 1.56 dB for a pure `1/f` spectrum,
  confirming the simulated spectrum is flatter than pure `1/f` toward the
  top of the band).

## Decision

This record ratifies a **target-column planning allocation** and a
**grading band** inside §5.3's unchanged total. It makes no current-cell
measurement claim and does **not** accept or ratify any failing simulation
result as passing; the 80 dB target and all §1.1 rows stay in force.

§5.3's non-thermal half (9.0 × 10⁻¹⁰ V²) carries an explicit **amplifier
1/f planning line of 4.5 × 10⁻¹⁰ V²**, carved from the "everything else"
remainder. The planning budget for the 80 dB target column:

| line | V² | µV rms | status |
|---|---|---|---|
| total in-band noise for 80 dB | 1.8 × 10⁻⁹ | 42.4 | **unchanged** |
| thermal share | 9.0 × 10⁻¹⁰ | 30.0 | **unchanged** |
| — sampling-switch kT/C | 4.5 × 10⁻¹⁰ | 21.2 | unchanged (45/45 pass on pre-change `6ce52dc`; current-cell margin open until re-run) |
| — amplifier thermal (implicit in §5.3) | 4.5 × 10⁻¹⁰ | 21.2 | unchanged (thermal-only verdict unresolved; see below) |
| non-thermal share | 9.0 × 10⁻¹⁰ | 30.0 | unchanged |
| — quantization at −6 dBFS, OSR 128 | 6.9 × 10⁻¹¹ | 8.3 | unchanged |
| — **amplifier 1/f (new)** | **4.5 × 10⁻¹⁰** | **21.2** | **added by this record (planning allocation)** |
| — other named terms (charge injection, settling, clock jitter, comparator offset leakage, output rounding, leakage) | 3.81 × 10⁻¹⁰ | 19.5 | stated planning residual (includes §5.5 output rounding of 1.11 × 10⁻¹⁰ V²; leaves 2.70 × 10⁻¹⁰ V² for unquantified terms) |

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
into this line. Preserve the distinction between this **[1.22 Hz, 20 kHz]**
grading band and `record-i140.json`'s historical **[1 Hz, 20 kHz]**
simulated baseband: for an **ideal pure-`1/f` spectrum** (variance
proportional to `ln(f_hi / f_lo)`), shifting the lower edge from 1 Hz to
1.2207 Hz reduces the integral by 2.01 %, i.e. **0.088 dB** ("within
0.09 dB"). Because the simulated spectrum is flatter than ideal `1/f` at
the top of the band (0.84 dB simulated vs. 1.56 dB ideal `1/f` between
1 Hz and 20 Hz), 0.088 dB is a conservative upper bound on the edge shift,
and the archived 1 Hz integrals are cited as-is with their 1 Hz edge
named. The **20 Hz** edge is rejected: on the `6ce52dc` grid it would
credit the line 0.84 dB it has not earned (the grid-stable 1.209–1.218×
ratio above).

**Why 4.5 × 10⁻¹⁰ V².** (i) **Planning convention, not a derived physical
value:** §5.3 splits unevidenced allocations in halves (total → thermal /
non-thermal, thermal → kT/C / amplifier), and 4.5 × 10⁻¹⁰ V² is that
equal-halving planning convention applied once more (half of the
9.0 × 10⁻¹⁰ V² non-thermal half goes to amplifier 1/f; the other
4.5 × 10⁻¹⁰ V² covers quantization's 6.9 × 10⁻¹¹ V² plus the
3.81 × 10⁻¹⁰ V² residual). (ii) **Consistency with both quantified
non-thermal terms in the spec:** `spec/modulator-adc.md` quantifies two
non-thermal terms — modulator quantization at −6 dBFS, OSR 128
(6.9 × 10⁻¹¹ V², §5.1/§5.3, already separated out) and 16-bit output
rounding at 92.1 dB SNR (0.18 V² × 10^(−92.1/10) = **1.11 × 10⁻¹⁰ V²**,
10.5 µV rms, ~6.2 % of the 80 dB total, §5.5, which §5.3 explicitly lists
in the non-thermal half). Output rounding takes **29.1 %** of the
3.81 × 10⁻¹⁰ V² residual (covered **3.4×**), leaving **2.70 × 10⁻¹⁰ V²**
(16.4 µV rms) for the remaining unquantified terms (charge injection,
settling, clock jitter, comparator offset leakage, leakage). Neither
quantified term is squeezed; the residual is an arithmetic planning budget
and establishes no individual margin for the unquantified terms.
(iii) **Insensitivity on the archived evidence:** on the pre-change
`6ce52dc` anchor evidence, baseband flicker alone exceeds even the entire
8.31 × 10⁻¹⁰ V² former remainder by 11.32 dB, so finer precision inside
the non-thermal half would be spurious. (iv) **Replacement rule:** per
§5.3 ("measured shares replace it through a decision record, not in
place"), a future record replaces this planning split once current-cell,
per-mechanism evidence exists.

## What the pre-change-cell evidence shows (historical findings, not relaxations and not current-cell margins)

All findings below come from `sim/integrator-noise/record-i140.json` on
the **pre-change integrator (`6ce52dc`, SHA-256 `18fc5147…`)** with the
unchanged OTA (`7f4724e9…`). Current-integrator margins are **open** until
re-run on the updated cell (`6857c4ca…`, #266 / #143). None of these
findings is accepted as passing; the 80 dB target stays in force.

- **No carve-out made the `6ce52dc` integrator/OTA pass on flicker.** At
  the `6ce52dc` anchor (`tt/1.800V/27C`, `[1 Hz, 20 kHz]` simulated
  baseband), baseband flicker alone (1.1257 × 10⁻⁸ V², 6.25× the entire
  1.8 × 10⁻⁹ V² converter noise budget — a flicker-only ceiling of
  ~72.0 dB before any other noise or distortion) exceeds the entire former
  8.31 × 10⁻¹⁰ V² remainder by **11.32 dB** and the new 4.5 × 10⁻¹⁰ V²
  line by **14.0 dB** (12.5× the whole non-thermal half). That is the
  expected outcome of setting an unrelaxed planning bar: closing the
  flicker gap is #143's job (step 3), and the allocation is deliberately
  not sized to the OTA.
- **Amplifier thermal-only verdict is unresolved (conditional upper bound
  +2.43 dB at the `6ce52dc` anchor).** §5.3 leaves
  9.0 × 10⁻¹⁰ − 4.5 × 10⁻¹⁰ = 4.5 × 10⁻¹⁰ V² implicitly for amplifier
  thermal noise. At the `6ce52dc` anchor (`tt/1.800V/27C`, 1 Hz edge),
  simulated baseband thermal + shot is 2.368 × 10⁻¹¹ V², while the folded
  above-band term (`[20 kHz, 100 GHz]` divided by OSR = 128) is
  7.640 × 10⁻¹⁰ V² with **no recorded mechanism or device split** (the
  phase-2 `ampq` probe sums OTA devices and `phi2` switches together).
  Assigning 100 % of that folded term to OTA thermal + shot gives an
  **upper bound** of 7.876 × 10⁻¹⁰ V² (**+2.43 dB** over 4.5 × 10⁻¹⁰ V²;
  0.58 dB inside the 9.0 × 10⁻¹⁰ V² thermal half). Establishing an OTA
  thermal-only miss against 4.5 × 10⁻¹⁰ V² requires showing that **more
  than 55.8 %** of the folded variance is OTA thermal + shot. Because
  neither a folded-band split nor a per-corner mechanism split
  (`2AMLogic/klayout-tools#5553`) is recorded, **the amplifier
  thermal-only verdict is unresolved** even at the `6ce52dc` anchor. The
  9.0 × 10⁻¹⁰ V² thermal line and implicit 4.5 × 10⁻¹⁰ V² share are kept
  unchanged (neither loosened nor declared passed), and isolating OTA
  thermal + shot in the folded band on the updated integrator is left to
  #143 / #266.
- **Sampling-switch kT/C passed 45/45 on `6ce52dc`; current-cell margin is
  open.** On the pre-change `6ce52dc` integrator, kT/C passed 45/45 with
  4.58–7.39 dB of margin, giving no basis to alter the 4.5 × 10⁻¹⁰ V²
  line. Because #147 and DR-010 changed the `Sin` and `Sci`/`Scr` switches
  (`integrator.spice` `18fc5147…` → `6857c4ca…`), current-integrator kT/C
  margins remain **open** until `sim/integrator-noise` is re-run (#266).

## Alternatives considered

- **Sizing the flicker line to the `6ce52dc` anchor's simulated OTA
  flicker.** Rejected (the issue's guidance rejects it too):
  1.1257 × 10⁻⁸ V² would consume the whole non-thermal half 12.5× over and
  strand every other named term at zero.
- **Taking the flicker line out of the thermal half.** Rejected: it would
  shrink the thermal allocation below its ratified 9.0 × 10⁻¹⁰ V² without
  evidence that the amplifier's thermal share has headroom — at the
  `6ce52dc` anchor the conditional thermal + shot upper bound already
  reaches 7.876 × 10⁻¹⁰ V² (+2.43 dB over the implicit 4.5 × 10⁻¹⁰ V²
  line), and the thermal-only verdict is unresolved.
- **Raising the total or lowering the 80 dB target.** Rejected: a
  relaxation. If future evidence after redesign says the target is
  unreachable, that is an operator decision, not this record.
- **Grading from 20 Hz.** Rejected above: 0.84 dB unearned on the
  `6ce52dc` grid.

## Spec lines affected

- `spec/modulator-adc.md` §5.3: one added bullet pointing to this record
  for the split of the non-thermal half. No row of §1.1 changes; the
  total, the thermal line and the kT/C line keep their values.
- `spec/README.md`: index entry.
- No ratified decision record is edited; DR-001, DR-002, DR-005 and DR-010
  are cited only.

## Scope

Target column only. The fallback (70 dB, OSR 256) and stretch (90 dB)
columns keep §5.3's undivided non-thermal half: their `fout` differs
(40 / 200 kSps), so the bin-bandwidth edge does not fall out for free, and
no flicker evidence exists at their operating points. A future record sets
their lines if needed.

## Consequences

- Future amplifier-noise benches on the updated integrator (#266, #143)
  grade against both amplifier lines (thermal 4.5 × 10⁻¹⁰ V²; flicker
  4.5 × 10⁻¹⁰ V² over `[1.22 Hz, 20 kHz]`) instead of comparing a flicker
  result with the thermal-only line "conservatively".
- #143 designs against the 4.5 × 10⁻¹⁰ V² flicker line and resolves the
  open amplifier thermal-only question by isolating OTA thermal + shot in
  the folded band; #266 re-runs `sim/integrator-noise` on the updated
  (`6857c4ca…`) integrator to close the open current-cell kT/C and noise
  margins.
- The 3.81 × 10⁻¹⁰ V² residual bounds the other non-thermal terms
  (including §5.5's 1.11 × 10⁻¹⁰ V² output rounding, leaving
  2.70 × 10⁻¹⁰ V² for the remaining unquantified terms) and is replaced
  when those terms are extracted.

# sim/integrator-ci — integrator switch charge injection (issue #102)

**Simulated, transistor-level** (ngspice on `design/integrator/integrator.spice`
with `design/ota/ota_fd.spice`; not the behavioural model). Question: how large is
the integrator's switch charge-injection residual with the shipped switch sizes,
and what did issue #92's low-Vth + PMOS-half change cost? DR-001 item 2 assigns
this to a transistor-level run; this is that run, and it gives model B's
`ci_offset` / `ci_gain_error` (`sim/bmodel/model.py`) their first
transistor-level value.

**Answer: the differential residual is far too small to cost resolution, and the
sqrt(W L) growth the design notes predicted is not what dominates it.**

| Quantity | Result | Source |
|---|---|---|
| Differential residual per clock, nominal, zero input | ≤ **2.265e-07 V** over all 45 DR-002 points (`ci_offset` 1.89e-07 FS) | `record.json` |
| … same, pre-#92 cell | ≤ 2.902e-07 V | `record.json` |
| Both of the above against the bench's own floor | `vntol` = 1e-7 V — so **nominal cannot distinguish the two cells**, which is what a cell drawn symmetric should give | — |
| Common-mode step per clock | ~1e-06 V, and **no systematic growth post-#92** (per-anchor ratios scatter 0.47–2.13 about 1, not the 5.7× channel-area factor) | `record.json` |
| Common-mode accumulation | none — the OTA's common-mode feedback absorbs it | — |
| Differential σ under PDK mismatch, raw | 1.3–5.8 mV per clock | `record-mc.json` |
| … of which the **OTA's own input offset** | r = **0.9999**, slope ≈ 1.01 | `record-mc.json` |
| … leaving the **switch-attributable** σ | **59–90 µV** per clock (4.9e-05 … 7.5e-05 FS) | `record-mc.json` |
| … post/pre ratio of that σ | **1.84× – 3.61×** (mean 2.56, per-anchor SE 0.19–0.37) — *faster* than either sqrt(W L) prediction (1.333× / 1.929×) | `record-mc.json` |
| Signal-dependent part (`ci_gain_error`) | **below this bench's resolution**; the measured slope is accounted for by the drawn capacitor ratio, the finite-gain leak and, at the slow/cold corners, incomplete *input* sampling (#106) | `record.json` |
| **Cost in model B** | **0.17 dB** of peak SNDR: 86.00 dB against the 86.17 dB ideal record | `sim/bmodel/records/20261113T145641Z-a793a24d.json` |
| *Input* sampling completeness (a **different** mechanism, issue #106) | worst **0.5432** of a 0.2 V differential input unsampled at `ss`/1.620 V/−40 °C, and strongly **input-level dependent** (0.0083 at 0.6 V); no SNDR consequence claimed | `record-i106.json` |

Everything here is **simulated**, never measured, and the records carry no
pass/fail criterion: no spec row bounds this residual. **Read "Limits" at the
bottom before quoting any number from here** — in particular, the mismatch σ is
a total that the pre/post comparison, not a single cell, attributes to the
switches.

## What is measured, and why that is the observable

The cell is clocked for `N_CYC = 6` complete phi1/phi2 cycles at the spec row-5
rate (5.12 MHz, T = 195.3125 ns). Both outputs are read as the **mean over a
fixed 10 ns window, [78, 88] ns into each cycle** — inside the phi1 hold, where
`Sti`/`Str` are open, `Ci` holds its charge and the OTA is in pure capacitive
feedback. The change between two consecutive windows is the net charge one whole
cycle delivered to `Ci`:

| edge in that cycle | switches | where its charge goes |
|---|---|---|
| `phi1e` falls | `Sci`, `Scr` | the floating top plate; transferred in the next phi2 |
| `phi1` falls | `Sin`, `Sr` | the floating bottom plate; partly transferred |
| `phi2` rises | `Sbi`, `Sbr`, `Sti`, `Str` (+ PMOS halves) | drawn *from* the terminals |
| `phi2` falls | same | `Sti`/`Str` dump onto the summing node, straight onto `Ci` |

so a window-to-window difference captures every one of them. A single-edge probe
would not.

**Why a windowed mean and not an interpolated point.** ngspice emits duplicate
timepoints at breakpoints, so `sim/integrator-settling`'s
`v[k-1] + (t-time[k-1])/(time[k]-time[k-1])*…` idiom can divide by a zero-width
bracket. A mask-and-mean cannot, and it averages the solver's own numerical noise
down as well. `w_<tag>` (the fraction of stored points inside each window) is
recorded, so an empty window cannot hide in a record.

**Why the differential part is the one that matters.** The common-mode injection
is signal-independent and the OTA's common-mode feedback pulls it back to an
equilibrium, so it does not accumulate. The differential part has no such loop:
the integrator integrates it, clock after clock, exactly as model B's `ci_offset`
does. That is why the headline numbers are differential, and why the per-clock
step is extracted as a **slope over three clocks**
(`dvod_mean = (vod_c5 - vod_c2)/3`) rather than one difference — a slope divides
the solver noise and any one-off reset-release disturbance by three.

**Model-B units.** Model B advances integrator 1 by `k*(u - y) + ci_offset` with
`k = C1 = 0.5` and `y = ±1` at full scale; in the cell one clock moves the
differential output by `(Cs/Ci)*(vin_diff + vdac_diff) = 0.5*(vin_diff + vdac_diff)`
with `vdac_diff = ±(VREFP - VREFN) = ±1.2 V`. Equating the two makes one `x1`
unit **1.2 V of differential output**, so

    ci_offset [FS] = differential output step [V] / 1.2 V

`ci_gain_error` is dimensionless: the fitted slope `d(step)/d(vin_diff)` is
`0.5*(1 + ci_gain_error)`.

## Nulling the DAC

The primary variants hold `VREFP = VREFN = VCM = 0.9 V`. The 1-bit DAC has no
"zero" state — with the spec references it transfers ±0.6 V differentially every
clock — so nulling the reference branch is what makes the ideal transfer zero and
the measured step *be* the residual, instead of the difference of two large
numbers.

Every switch in the reference branch still operates and still injects: only the
voltages it switches change. That matters least where it matters most, because
the turn-off injection that reaches `Ci` happens with `bpr` held at `vcm` by
`Sbr` and `tpr` at the summing node, i.e. at `vcm`, in both cases. The
`alternating` variant below measures what nulling costs rather than asserting it.

## Which switches actually land on Ci

`design/integrator/SIZING.md` frames the sqrt(W L) growth over all four
phi2-gated `vcm` switches. Only two of them inject where it accumulates:

- **`Sti`/`Str`** gate the **summing node**. Their turn-off charge lands on `Ci`
  and is output error immediately.
- **`Sbi`/`Sbr`** gate the **bottom plate**. At phi2 turn-off that plate floats,
  but the next phi1 re-drives it from `vinp` / `rsel` through `Sin` / `Sr`, so
  the charge is discarded before any transfer.

`Sbi`/`Sbr` are the pair that grew 5.7× in channel area; `Sti`/`Str` grew 1.78×.
So the prediction that applies to the output is **sqrt(1.78) = 1.33×**, not the
sqrt of the all-four ratio (**1.93×**). `run_ci.py` reads both off the two
simulated netlists — never off a comment — and writes both into the record next
to the measured sigma ratio, so the measurement decides between them.

Neither factor is a complete prediction: the #92 delta also swaps
`nfet_01v8` → `nfet_01v8_lvt` on those switches, which changes the channel charge
at equal area. The record says so.

## What else is in the step

The per-clock differential step is not switch injection alone. Under mismatch it
also contains the OTA's input offset, referred through `Cs/Ci`: during phi1 the
top plate is held at exactly `vcm` by `Sci`, while during phi2 the summing node
sits at `vcm + Vos`, so each transfer carries `Cs*Vos` as well.

Three things keep that honest rather than hidden:

1. `vod_rst` reads the OTA's differential output while the bench reset holds it
   in unity feedback — an independent handle on `Vos` at every corner/sample.
2. `dvod_leak` is the differential drift across 28 ns of hold with **no clock
   edge** in between, scaled to a whole clock: leakage and drift, separated from
   injection by construction.
3. The **pre/post comparison** is what isolates the switch change. Both cells use
   the identical `ota_fd`, the identical `Cs`/`Ci`, the same deck, the same base
   seed, the same `N` and `seed_scope: "point"` — they differ only in the cell
   netlist. The *change* in sigma between them is attributable to the switches in
   a way neither run's absolute sigma is.

**Measured, over the committed Monte Carlo campaign: the OTA offset is almost all
of it.** The raw per-clock differential sigma is 1.3–5.8 mV, and at six of the
seven DR-002 anchors it correlates with the same sample's `vod_rst` at
**r = 0.9999** with a slope of ~1.01. Regressing it out leaves:

| anchor | σ raw | σ(OTA offset) | r | σ switch-attributable |
|---|---|---|---|---|
| `tt_mm`/1.800 V/27 °C | 4.794e-3 V | 4.725e-3 V | 0.9999 | **7.22e-5 V** |
| `ff_mm`/1.980 V/−40 °C | 4.127e-3 | 4.067e-3 | 0.9999 | 5.93e-5 |
| `ff_mm`/1.980 V/125 °C | 5.620e-3 | 5.563e-3 | 0.9999 | 7.50e-5 |
| `fs_mm`/1.800 V/27 °C | 5.270e-3 | 5.195e-3 | 0.9999 | 6.13e-5 |
| `sf_mm`/1.800 V/27 °C | 4.502e-3 | 4.453e-3 | 0.9999 | 7.67e-5 |
| `ss_mm`/1.620 V/125 °C | 5.779e-3 | 5.675e-3 | 0.9999 | 9.01e-5 |
| `ss_mm`/1.620 V/−40 °C | 1.271e-3 | 4.019e-3 | 0.614 | **not separable** |

so the switch-attributable sigma is **59–90 µV per clock**, i.e. 4.9e-5 … 7.5e-5
in `ci_offset` FS units — about 60× below the raw number. The regression is
reported with its slope and `r` so the separation can be judged rather than
trusted, and below `|r| = 0.95` **no** switch-only sigma is published: that is
what happens at `ss_mm`/1.620 V/−40 °C, the anchor whose charge transfer is
itself incomplete (#106).

The record therefore reports the total, the measured offset, the regression, and
the residual — and the post/pre ratio both ways. `sqrt(W L)` is a claim about the
switches, so it is read against the **OTA-removed** ratio; the raw ratio would be
near 1 at both cells simply because the same OTA dominates both.

## Variants

| variant | cell | `vin_diff` | DAC | what it is for |
|---|---|---|---|---|
| `post_v0` | shipped | 0 | nulled | the residual itself (criterion 1) |
| `post_v0p1` | shipped | +0.1 V | nulled | signal dependence (criterion 2) |
| `post_v0p2` | shipped | +0.2 V | nulled | signal dependence (criterion 2) |
| `post_dac` | shipped | 0 | spec refs, `dn` toggled every clock | what nulling costs; DC-gain cross-check |
| `pre_v0` | pre-#92 (`e310b5f`) | 0 | nulled | the #92 baseline (criterion 5) |

Load is 0.1 pF per side — `sim/integrator-settling`'s `int1` case-B load, since
`ci_offset` is a model-B **integrator 1** parameter.

`integrator_pre_i92.spice` is a verbatim copy of
`design/integrator/integrator.spice` at `e310b5f` (the first parent of the #92
merge `31c2da9`) with a provenance header. `test_run_ci.py` re-checks it against
that blob whenever git history is available, so it cannot drift from the commit
it names. Its `.subckt` port order predates `klt netlist`'s port-type regrouping
(`voutp`/`voutn` at positions 5–6, not last — see
`sim/integrator-settling/README.md` → "Port-order drift"), which is why the deck
template carries a per-cell `Xint` line.

## Bench validity: sensitivity, step independence, DAC cross-check

A bench whose only output is "approximately zero" proves nothing unless it is
shown to respond to the thing it measures. All three checks below were run
locally at `tt`/27 °C/1.80 V, and the first two are reproducible commands.

**Sensitivity — `run_ci.py --self-test`.** Runs the shipped cell and a copy with
`Sti_p`'s PMOS half 10 % wider (generated from the shipped netlist on every run,
so there is no committed duplicate to drift; it refuses if the substitution does
not hit exactly one instance).

| cell | differential step per clock |
|---|---|
| shipped, symmetric | −4.3e-11 V |
| `Sti_p` PMOS half W 4 → 4.4 | +4.736e-05 V |

a ratio of **1.1e6**, and the skewed cell's accumulation is linear to 0.15 %
across the measured cycles. `--self-test` exits non-zero below 100×. So the
symmetric cell's ~1e-11 V is the bench's noise floor, and the nominal-grid zero
is a measurement.

**Step independence — `run_ci.py --probe-step post_v0`.** The same corner at
50 ps and 20 ps maximum internal step:

| quantity | 50 ps | 20 ps |
|---|---|---|
| `dvod_mean` | −4.34e-11 V | +3.92e-10 V |
| `dvoc_mean` | 9.2459e-07 V | 9.2358e-07 V |
| `voc_swing` | 0.1171892 V | 0.1171832 V |

The real quantities move by ~0.1 % and 5e-5 relative; the differential residual
stays below 1e-9 V in both. The committed requests use 50 ps.

**Why the deck tightens `.options`.** The residual sought is tens of microvolts
on a 0.9 V node, which ngspice's default `reltol=1e-3 vntol=1e-6` cannot resolve.
The deck sets `reltol=1e-5 vntol=1e-7 abstol=1e-13 chgtol=1e-16`. `gmin` and
`trtol` are left alone: overriding them (1e-15 / 1) made the operating point
singular and aborted the analysis.

**DAC cross-check (`post_dac`) — a negative result, kept.** With `dn` toggled
every clock, the DAC's ±1.2 V transfer cancels over two clocks *in a linear
circuit*, so `dvod_2clk` was meant to show the residual with the references live.
It does not. Measured at `tt`/27 °C/1.80 V: the two-clock residual is
**−896 µV**, essentially constant across cycles, and it is the integrator's
**finite-gain leak** of the ±0.598 V per-clock transfer.

For an alternating transfer `±S`,
`vod[k+2] - vod[k] = -(1-p)·[(1+p)·vod[k] + s[k]]`, and the bracket is `≈ S`
whichever state cycle `k` is — `S` when `vod[k] ≈ 0` and `s[k] = +S`, and
`2S - S = S` when `vod[k] = S` and `s[k] = -S`. So the divisor is the per-clock
**transfer**, not any one cycle's output; dividing by a fixed cycle's `vod`
lands on the small state half the time and reads `A` two orders of magnitude
low. Over the committed 45-point grid:

| | implied OTA DC gain |
|---|---|
| `tt`/27 °C/1.80 V | **56.51 dB** |
| grid range | 40.85 dB (`fs`/1.620 V/−40 °C) … 59.50 dB (`ss`/1.980 V/−40 °C) |
| independently recorded | ~55 dB, `design/ota/SIZING.md` |

The low outliers are the slow/cold corners where the transfer itself is
incomplete (#106), so the leak estimate is contaminated there — the figure is a
cross-check of this bench against an independent result, not a DC-gain
extraction, and the record does not present it as one.

Two things follow, and the record carries both:

- the variant is **not** an injection measurement, and is not reported as one;
- it is the measured justification for nulling the DAC — with the spec
  references live, the leak is ~2e7 × the nulled bench's noise floor, so
  injection is simply unobservable — and, read as a gain measurement, an
  independent check of the OTA DC gain.

## Monte Carlo and mismatch

A nominal corner cannot show the differential residual: the cell is drawn
symmetric, so every nominal point returns the noise floor. The mismatch-driven
part needs the PDK's own per-instance variation.

`klt sim` supports this directly (`monte_carlo`, `vary: "mismatch"`), so **no
klayout-tools gap had to be filed for it** — the escape hatch in the issue's last
acceptance criterion was not needed. Two things about the request are
deliberate:

- **sky130 selects mismatch by `.lib` section**, not by a parameter, so the MC
  request's `corners.units` name `tt_mm`, `ss_mm`, `ff_mm`, `sf_mm`, `fs_mm`
  (verified present in the pinned
  `libs.tech/ngspice/sky130.lib.spice`). A plain `tt` section would run `N`
  identical samples and report sigma = 0 — which is exactly `klt`'s documented
  negative control, and `test_run_ci.py` pins that a flat sample set reads as
  sigma exactly `0`.
- **`corners.units`** gives the DR-002 anchor set as 7 explicit points instead of
  a 45-point cross product minus 38 exclusions, and **`seed_scope: "point"`**
  keys each sample's seeds on the point's own identity plus `sample_index`, so
  the separately-submitted pre-#92 and post-#92 campaigns draw the same sample
  sequence at the same anchors.

`N = 100` per anchor point. The sigma of 100 samples carries a
`1/sqrt(2*99)` = 7.1 % relative standard error, so the post/pre sigma **ratio**
lands within about 10 % — enough to separate 1.33× from 1.93×. The record states
`N`, the base seed, the estimator, and that standard error. A re-run at larger
`N` is a new append-only record, not an edit of the old one.

**What the ratio came back as, and the verdict on sqrt(W L).** Per anchor, from
`record-mc.json`:

| anchor | σ raw post/pre | σ switch-attributable post/pre |
|---|---|---|
| `ff_mm`/1.980 V/−40 °C | 1.147 | 2.037 ± 0.206 |
| `ff_mm`/1.980 V/125 °C | 1.044 | 1.838 ± 0.186 |
| `fs_mm`/1.800 V/27 °C | 1.039 | 2.092 ± 0.211 |
| `sf_mm`/1.800 V/27 °C | 1.013 | 2.937 ± 0.297 |
| `ss_mm`/1.620 V/125 °C | 1.060 | 3.610 ± 0.365 |
| `tt_mm`/1.800 V/27 °C | 1.109 | 2.859 ± 0.289 |
| `ss_mm`/1.620 V/−40 °C | 0.707 | not separable (#106) |

The **raw** ratios are all ≈ 1: at that level the two cells look identical,
because the same OTA offset dominates both. A record quoting the raw ratio would
have concluded #92 cost nothing at all.

The **switch-attributable** ratios are 1.84×–3.61×, i.e. **faster than either
sqrt(W L) framing**: three anchors sit within half a standard error of the
all-four prediction (1.929×) and three are 3–4.6 standard errors above it, and
the corner-to-corner spread exceeds the measurement error, so the ratio is
genuinely corner-dependent. The term neither prediction contains is the
standard-Vth → low-Vth swap #92 also made on these switches, which raises
channel charge at equal area — `sqrt_wl_prediction.note` flags it as
unaccounted, and the measurement says it matters. **The scaling argument is
refuted as a quantitative prediction; the engineering conclusion that the fix
was cheap stands, on the absolute number and the 0.17 dB.**

`family_mismatch` from the response is kept in the record and summarised under
`derived.mismatch_coverage`: it states, per device family actually instantiated,
whether that family's mismatch is structurally active in the selected deck.
Measured on the committed campaign:

| family | reported | consequence |
|---|---|---|
| `mosfet` | `active: true` | the switches and the OTA do vary per instance |
| `resistor` | `active: true` | — |
| `capacitor` (`cap_mim_*`) | `active: null` | **unverified, not off** |
| `other` | `active: null` | unverified |

So **capacitor mismatch is not inside these sigmas** — `null` means klt does not
independently verify that family for sky130, so any spread it contributes is
unconfirmed. It stays a separate owed mechanism
(`design/integrator/SIZING.md` → "Not simulated (owed)"), and
`derived.mismatch_coverage.not_covered` lists it so the record cannot be read as
an all-mechanisms number.

## Input sampling completeness (issue #106)

The sections above read the integrator's **output** in the phi1 hold. Issue #106
asked the opposite-side question: how much of the differential input did the
`Sin` pass gate actually deliver onto `Csi` before the sample was frozen? That
is a different mechanism from charge injection, and this bench's decks already
contain everything needed to see it, so the measurement lives here rather than
in a bench of its own.

**Where the sample is frozen.** `Sci` (gated by `phi1e`) holds the top plate at
`vcm` until `phi1e` falls 90.5 ns into the cycle; `Sin` (gated by `phi1`) drives
the bottom plate from `vinp`/`vinn` until `phi1` falls at 92.5 ns. The charge on
`Csi` stops changing at the **`phi1e`** fall: the 2 ns that follow move both
plates of `Csi` together, which cannot change the charge between them. So the
input path has **90.4 ns** (phi1 closing `Sin` at 0.1 ns to `phi1e` opening
`Sci` at 90.5 ns), not the full 92.3 ns `phi1` is high, and the quantity to read
is the differential across `Csi` at that instant.

`sampling_measurements()` reads it as a mean over the last 0.8 ns of `phi1e`
(not a point interpolated across the fall — that fall is a solver breakpoint,
and ngspice emits duplicate timepoints at breakpoints). Because `Sci` holds both
top plates at `vcm` right up to the fall, the across-`Csi` differential there is
also `v(xint.bpi_p) − v(xint.bpi_n)`, the form issue #106 reported; both are
recorded. Taking it across the capacitor removes any difference between the two
sides' top-plate hold, so the number is the sampled charge and not a sum of the
sampled charge and a top-plate offset.

A **control** reads the same charge again in the 4.7 ns non-overlap gap after
`phi1` opens and before `phi2` closes, where both plates float and nothing is
moving. Its difference from the headline reading is the `phi1`/`Sin` turn-off
injection onto the floating bottom plate — *this* bench's own mechanism, not
#106's — so the record carries `frozen_minus_sampled_V` and the two cannot be
confused.

**Two amplitudes**, because a sampling error that is the same *fraction* at both
is a gain error while one that is not is distortion:

| request | `vinp`/`vinn` | differential | deck |
|---|---|---|---|
| `request_i106_post_v0p2.json` | 1.0 / 0.8 V | 0.2 V | the existing `post_v0p2` deck, reused unchanged |
| `request_i106_post_v0p6.json` | 1.2 / 0.6 V | 0.6 V | `integrator_ci_post_v0p6.cir` (new) — spec row 11's full input range |

Each is the DR-002 full 45-point grid, submitted to the batch fleet. With the
DAC nulled nothing cancels the input, so at 0.6 V the differential output ramps
0.3 V per clock and leaves the OTA's range before the last cycle. That is
accepted deliberately and stated in the record: the sampled charge is set while
`Sci` holds the top plate at `vcm` and `Sti` is open, so the bottom-plate
measurement does not depend on the output — and **no output number from the
`post_v0p6` variant is read or reported.**

**The reference line is not a limit.** No ratified spec row bounds input-sampling
completeness, and this change adds none. The record states the per-corner error
`1 − sampled/ideal` and compares it against **1e-4 relative** — the starting
level `sim/integrator-settling` grades DR-005 settling against — purely so the
number has a scale this repo already uses. Accordingly **no measurement in either
`request_i106_*.json` carries `limits`**: the fleet is never asked to return a
pass/fail on this quantity, because a "fail" status would read as a verdict the
spec does not support. A corner listed in `corners_over_reference_line` has not
failed anything.

**Why the issue #102 requests were not simply extended.** `record.json` records
the `request_sha256` and `deck_sha256` it was produced from. Adding measurements
to `request_post_*.json` would move those hashes and break that record's
provenance, so the sampling measurements live in separate request files over the
**same** decks. `make_request.py` regenerates every issue #102 deck and request
byte-for-byte; `test_run_sampling.py` pins both facts.

### What it measured

From `record-i106.json` (fleet jobs `klt-sim-b7f6bc6865de` and
`klt-sim-c515728d5338`, ngspice-47, pinned sky130A, 45 corners each, cycle 4 of
6). **Simulated, never measured. No spec row is graded here and none exists.**

| | ±0.1 V per side (0.2 V diff) | ±0.3 V per side (0.6 V diff) |
|---|---|---|
| worst corner | **`ss`/1.620 V/−40 °C** | **`fs`/1.620 V/−40 °C** |
| error `1 − sampled/ideal` there | **0.5432** (sampled 0.09135 V of 0.2 V) | **0.1340** (sampled 0.51959 V of 0.6 V) |
| corners over the 1e-4 reference line | 8 of 45 | 2 of 45 |
| every 1.980 V corner | exact to the reported precision | exact to the reported precision |

**The filing is confirmed.** It reported ~46 % of a ±0.1 V input sampled at
`ss`/1.620 V/−40 °C; the grid gives 45.7 % complete (0.09135 V of 0.2 V) at that
corner, from a separate measurement on the same deck.

**The error is input-level dependent, which is the new result.** Corner by
corner:

| corner | error at 0.2 V | error at 0.6 V |
|---|---|---|
| `ss`/1.620 V/−40 °C | 0.5432 | 0.00828 |
| `sf`/1.620 V/−40 °C | 0.2843 | 0 |
| `fs`/1.620 V/−40 °C | 0.0868 | **0.1340** |
| `ss`/1.800 V/−40 °C | 0.0830 | 0 |
| `tt`/1.620 V/−40 °C | 0.0165 | 0 |
| `ss`/1.620 V/27 °C | 0.00516 | 1.7e-07 |
| `tt`/1.800 V/−40 °C | 0.00058 | 0 |
| `sf`/1.620 V/27 °C | 0.00056 | 0 |

At `ss`/1.620 V/−40 °C the error falls from 0.543 to 0.008 when the input grows
three-fold. A pure gain error would hold the *fraction* constant; this does not,
so the mechanism is **level-dependent**, consistent with a gate whose resistance
peaks at `vcm` and falls away on both sides. That is the signature of
distortion rather than a gain error — but this bench measures the level
dependence only. **It does not convert it into a distortion, THD, SNDR or
resolution figure, and none is claimed: nothing here has been through model B.**

**The binding corner depends on the amplitude.** `ss` binds at the small
amplitude, `fs` at the large one, and `fs` is the only corner where the error
*grows* with amplitude. So neither skew can be called "the" worst case for this
mechanism, and a fix cannot be graded at one of them alone.

**The per-side deficit is asymmetric, and differs by skew.** At
`ss`/1.620 V/−40 °C and 0.2 V the bottom plate heading up to 1.0 V falls 36.2 mV
short while the one heading down to 0.8 V falls 64.7 mV short; at
`sf`/1.620 V/−40 °C only the upward side misses (56.7 mV, the downward side
reaching its target). Each half of the gate is strong on one side of `vcm` and
weak on the other, and which half is weaker moves with the skew.

**Read `sampled_V`, not `sampled_bpi_only_V`.** The two are not the same number
at a slow/cold corner: `Sci` is resistive there too, so the top plates are not
exactly at `vcm` when `phi1e` opens, and the bottom-plate-only reading exceeds
the across-`Csi` reading by exactly that top-plate differential — 0.09912 V
against 0.09135 V at the binding corner, a 7.8 mV gap. What `phi2` transfers
onto `Ci` is the charge on `Csi`, i.e. the across-plate value, and that is also
the one that matches the ~46 % per-clock output step the filing measured. Both
forms and their errors are in the record (`error_rel`, `error_rel_bpi_only`).

**The turn-off control is small.** `frozen_minus_sampled_V` — the `phi1`/`Sin`
turn-off injection on the floating bottom plate, read in the following
non-overlap gap — is 7.4e-05 V at the binding corner against a 0.109 V sampling
deficit, and at most 1.8e-03 V anywhere on either grid. The headline numbers are
not an artefact of the turn-off edge.

**The deficit is steady, not a start-up transient.** At the binding corner the
per-cycle error runs 0.5395 / 0.5398 / 0.5413 / 0.5432 / 0.5455 over cycles
1–5 — every cycle, not a settling tail (`error_rel_by_cycle`).

**The mechanism, separately.** `sim/switch-probe/probe-i106.json` sweeps the
`Sin` pass gate's DC `Ron` against the voltage it passes, over the five process
skews at `Vdda` = 1.620 V / −40 C, and reports each half's share of the current.
That is the *mechanism* behind the sampling error; the magnitude over PVT is
`record-i106.json`, measured on the cell. A DC `Ron` times `Cs` against a phase
length is an order-of-magnitude argument, not a settling calculation.

## Running it

```bash
# bench debugging and validity, all local, no record:
python3 -I sim/integrator-ci/make_request.py            # regenerate decks + requests
python3 -I sim/integrator-ci/run_ci.py --probe post_v0  # one tt/27C/1.8V corner
python3 -I sim/integrator-ci/run_ci.py --self-test      # sensitivity check
python3 -I sim/integrator-ci/run_ci.py --probe-step post_v0

# the recorded runs; both go to the batch fleet (never a local grid):
python3 -I sim/integrator-ci/run_ci.py --record         # 5 variants x 45 DR-002 points
python3 -I sim/integrator-ci/run_ci.py --mc --record    # 2 cells x 7 anchors x N=100

# input sampling (issue #106): same decks, same grid, the phi1e-fall measurement
python3 -I sim/integrator-ci/run_sampling.py --probe post_v0p2  # 1 local corner
python3 -I sim/integrator-ci/run_sampling.py --record   # 2 amplitudes x 45 points

# record-admission unit tests (no fleet, no ngspice, no klt):
python3 -I -m unittest discover -s sim/integrator-ci -p 'test_*.py'
```

Grids are expressed as `klt sim` requests and submitted to the batch fleet with
`--wait-for-capacity` (`settling_common.CAPACITY_WAIT_S`); only the single-corner
probes run locally. `run_ci.py` never falls back to a local grid.

**The Monte Carlo campaign is one job of `anchors × N` units**, and the fleet
kills a job still running at its whole-job ceiling, reporting every unit
`batch_job_timeout`. The batch receipt's `job_ceiling` block says whether a
submission is near it. If it warns, split the campaign with
`run_ci.py --mc --hosts N`: sharding is a submission choice, so it does not
change the request file and a partial from an unsharded run of the same request
stays valid. (For reference, the 45-unit nominal grid came back in 106 s of
fleet time on one `m7i.4xlarge`.)

Each completed variant is cached under `.partials/` (gitignored), keyed on the
request **and** deck sha256, so a capacity refusal on one variant does not
discard another's corners — re-run the missing one with `--variant`. A variant
requested in *this* invocation is never served from `.partials/`: a failed submit
must not become a result (the issue #94 rule, pinned by
`test_run_ci.py`). Raw `klt` reports and batch receipts land in `.artifacts/`
(gitignored) *before* any admission gate, so a partial or failed grid is still
inspectable.

## Records

Append-only JSON, one file per campaign:

| file | campaign | runner |
|---|---|---|
| `record.json` | nominal grid, 5 variants × 45 DR-002 points | `run_ci.py --record` |
| `record-mc.json` | Monte Carlo mismatch, 2 cells × 7 anchors × N = 100 | `run_ci.py --mc --record` |
| `record-i106.json` | input sampling, 2 amplitudes × 45 DR-002 points | `run_sampling.py --record` |

Each names the bench, the netlist sha256s (shipped cell, pre-#92 fixture,
`ota_fd`), the PDK `SOURCES` stamp and pin, the `klt` version, the corner set or
seed set, and the fleet job id; and each is refused unless

- **every** grid point came back (45 nominal, `anchors × N` for Monte Carlo), and
- **every** point actually produced the campaign's sentinel measurement
  (`dvod_mean`; `samp_s4` for the sampling record), and
- *(sampling record only)* **every** window-occupancy divisor is a positive
  fraction of the stored timepoints — a window with no stored point in it makes
  each plate reading a 0/0 rather than a measurement, which the sentinel gate
  alone cannot catch.

A fleet job that dies still returns one entry per point, so the count gate alone
would turn an empty grid into a "record"; the second gate is what separates
"simulated and small" from "never simulated". Both are
`sim/settling_common.py`'s, shared with the settling benches and covered by
fixture tests.

## Limits

- **Nothing here is measured.** Every number is ngspice on the pinned sky130A
  models.
- **The differential residual is a total, not an attribution.** Under mismatch it
  contains the OTA input offset referred through `Cs/Ci` as well as switch
  injection; only the pre/post comparison isolates the switch change. See "What
  else is in the step".
- **`ci_gain_error_bound` is an upper bound**, and at `tt`/27 °C/1.80 V two other
  mechanisms account for the whole of it with ~0.1 % left over for everything
  else, injection included. From the committed `record.json`:

  | | slope, V/V | vs model B's 0.5 | vs the drawn ratio |
  |---|---|---|---|
  | drawn capacitor ratio `Cs/Ci` = 22.17²/31.43² | 0.497557 | **−0.489 %** | — |
  | measured slope from `dvod_mean` (includes the leak) | 0.495836 | −0.833 % | −0.346 % |
  | measured slope from the **first** clock (leak-free) | 0.498077 | −0.385 % | **+0.105 %** |

  so the −0.833 % total splits into −0.489 % drawn capacitor ratio, −0.450 %
  finite-DC-gain leak across the three-clock measurement window, and +0.105 %
  for everything else — real-vs-drawn capacitance (fringe), charge transfer and
  injection together. The leak term is independently corroborated: the
  `dac_crosscheck` variant gives 56.51 dB (A ≈ 670) at this corner from a
  completely different measurement.

  Two further facts bound injection's share of that +0.105 %. The three-point
  fit is **linear to 4.2 ppm** of the step (`fit_max_residual_V` = 4.2e-7 V), so
  there is no resolvable curvature for a signal-dependent injection term to live
  in; and the switches that reach `Ci` turn off with their terminals at the
  summing node (≈ `vcm`) whatever the input is, which is why the absolute
  zero-input residual is 4e-11 V here. The record therefore states that the
  signal-dependent part of charge injection is **below this bench's resolution**
  and does not report the slope as `ci_gain_error`.

- **Input sampling, not charge transfer, is what limits the slow/cold corners —
  and it is a different mechanism.** At `ss`/1.620 V/−40 °C the bottom plate
  reaches only 0.968 V of its 1.0 V target in 90 ns of phi1, so a ±0.1 V
  differential input is sampled ~46 % complete, while the *integrate* phase at
  that same corner settles exactly (`tpi_p` = `sump` to 6 digits well before
  phi2 falls). The cause is the `Sin` switch near `vcm`: at 1.62 V its NMOS half
  is off and its PMOS half has ~0.1 V of overdrive. At `tt`/27 °C/1.80 V the same
  sampling is exact to six digits, so this is corner-specific and not a property
  of the bench. It is **not** charge injection: a per-corner
  `ci_gain_error_bound` from the slow/cold corners is dominated by it and must
  not be read as a gain error of the charge-transfer path. It is now extracted
  over the full grid at two input amplitudes in `record-i106.json` (issue #106,
  see "Input sampling completeness" above), with the switch mechanism in
  `sim/switch-probe/probe-i106.json`. `record.json` itself is unchanged by that
  extraction, and neither record bounds the sampling error against a spec row —
  none exists. **Whether to change the cell, lengthen `phi1`, or accept and bound
  the error is #129**, filed from those numbers; issue #106 deliberately did not
  decide it.
- **Clocks are behavioural**, rail-to-rail with 200 ps edges and ≥ 4.7 ns
  non-overlap from `PULSE` shape sources. There is no non-overlap generator, so
  clock feedthrough from real `clkgen` skew — including a `Sti`/`Str` half left
  briefly open into the summing node — is **not** covered here and is owed to the
  clock-generator timing work, the same gap `sim/integrator-settling/README.md`
  names.
- **The reset is bench-only** (ideal 1 Ω switches across `Ci` until 40 ns); the
  cell has none. Its release is a one-off disturbance, which is why the reported
  step is a slope over later cycles.
- **Not covered**: kT/C and amplifier noise; capacitor mismatch as a separate
  mechanism; comparator, clock-generator and reference-mux injection; the
  reference node settling through the mux; post-layout extraction; the DR-001
  item 3 cross-check of model B against a full-modulator transient; any row-2
  SNDR claim.
- **The model-B runs are source B and uncross-checked** (DR-001 item 5). They
  report what the extracted parameters do to SNDR in the behavioural model; they
  are not transistor-level SNDR numbers and do not become them. Both use
  `sim/bmodel/run.py`, N = 2^16 output samples, a Blackman-Harris 4-term window,
  1.2207 Hz bins, the 0–20 kHz band, and the peak over the amplitude sweep at
  −6 dBFS, against the committed ideal record
  `20261113T142853Z-f8b2fa44.json` (**86.17 dB**). That is the post-issue-#107
  ideal: #107 removed a 3.02 dB ENBW over-statement from `sndr_db`, so any
  comparison against the older 89.19 dB ideal record is on the superseded
  formula. These runs are on the corrected one.

  | parameters | `ci_offset` FS | `ci_gain_error` | peak SNDR | loss |
  |---|---|---|---|---|
  | `bmodel-ci-injection.json` | 2.252e-04 | 0 | **86.00 dB** | **0.17 dB** |
  | `bmodel-ci-worst-bound.json` | 1.183e-02 | −0.5395 | 79.22 dB | 6.95 dB |

  The `worst_bound` run lands just **below** the 80 dB target. That is not a
  charge-injection result: its `ci_gain_error` is #106's incomplete input
  sampling (−54 % at `ss`/1.620 V/−40 °C) and its `ci_offset` is the OTA's own
  offset mismatch. Read the right way round, it says #106 is worth fixing —
  which is an argument for that issue, not a verdict on these switches.

  `injection` is what this bench attributes to the switches: 3σ of the worst
  OTA-removed spread, with `ci_gain_error` at 0 because the signal-dependent part
  is below resolution. `worst_bound` deliberately over-states it — its
  `ci_offset` is the OTA's own offset mismatch and its `ci_gain_error` is #106's
  input sampling, neither of them charge injection — and it is there only to
  answer "even at the bound?". Both parameter files and their provenance are
  committed beside the bench, derived from the records by
  `run_ci.py --bmodel-params`, never hand-typed.

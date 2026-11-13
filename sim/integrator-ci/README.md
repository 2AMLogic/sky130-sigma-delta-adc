# sim/integrator-ci — integrator switch charge injection (issue #102)

Transistor-level extraction of the charge-injection residual of
`design/integrator/integrator.spice`, and of what issue #92's low-Vth +
PMOS-half switch change cost. Everything here is **simulated**, never measured.

DR-001 item 2 assigns charge injection to a transistor-level run; this is that
run for the integrator. It feeds model B's `ci_offset` and `ci_gain_error`
(`sim/bmodel/model.py`), which had never been given a transistor-level value.

**What this bench does not cover** is in "Limits" at the bottom — read it
before quoting any number from here.

<!-- toc -->
- [What is measured, and why that is the observable](#what-is-measured-and-why-that-is-the-observable)
- [Nulling the DAC](#nulling-the-dac)
- [Which switches actually land on Ci](#which-switches-actually-land-on-ci)
- [What else is in the step](#what-else-is-in-the-step)
- [Variants](#variants)
- [Bench validity: sensitivity, step independence, DAC cross-check](#bench-validity-sensitivity-step-independence-dac-cross-check)
- [Monte Carlo and mismatch](#monte-carlo-and-mismatch)
- [Running it](#running-it)
- [Records](#records)
- [Limits](#limits)
<!-- /toc -->

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

The record therefore reports the total and names what is in it; it does not quote
a switch-injection-only sigma that the bench cannot separate at a single cell.

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
**finite-gain leak** of the ±0.598 V intermediate state —
0.598 / 896e-6 → A ≈ 667 (**56.5 dB**), against the ~55 dB
`design/ota/SIZING.md` records from an unrelated measurement.

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

`family_mismatch` from the response is kept in the record: it states, per device
family actually instantiated, whether that family's mismatch is structurally
active in the selected deck. `cap_mim_*` is reported as a capacitor family, so
capacitor mismatch is **not** part of these numbers — it is a separate mechanism
and separately owed (`design/integrator/SIZING.md` → "Not simulated (owed)").

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

Append-only JSON, one file per campaign. Each names the bench, the netlist
sha256s (shipped cell, pre-#92 fixture, `ota_fd`), the PDK `SOURCES` stamp and
pin, the `klt` version, the corner set or seed set, and the fleet job id; and
each is refused unless

- **every** grid point came back (45 nominal, `anchors × N` for Monte Carlo), and
- **every** point actually produced a `dvod_mean`.

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
- **`ci_gain_error_bound` is an upper bound**, and at `tt`/27 °C/1.80 V three
  other mechanisms account for the whole of it with nothing left for injection:

  | mechanism | size at `tt`/27 °C/1.80 V | where it is recorded |
  |---|---|---|
  | drawn capacitor ratio `Cs/Ci` = 0.497557, not model B's 0.5 | −0.489 % | `derived.drawn_cap_ratio` |
  | finite-DC-gain leak over the measurement window | fits A = 672 | per-clock droop; `dac_crosscheck` gives 667 independently |
  | everything else (real vs drawn cap ratio, fringe, transfer, injection) | +0.104 % | `slope_vs_drawn_cap_ratio_rel` |

  The measured transfer coefficient is 0.498075 V/V against a drawn ratio of
  0.497557. For injection to be producing a gain error of order 1e-3 it would
  have to vary the injected charge by ~1e-4 V per 0.1 V of input, which is three
  orders of magnitude above the 2.3e-7 V absolute residual measured at zero
  input — and the switches that reach `Ci` turn off with their terminals at the
  summing node (≈ `vcm`) whatever the input is. So the signal-dependent part of
  charge injection is **below this bench's resolution**, which is what the record
  states; the slope is not reported as `ci_gain_error`.

- **Input sampling, not charge transfer, is what limits the slow/cold corners —
  and it is a different mechanism.** At `ss`/1.620 V/−40 °C the bottom plate
  reaches only 0.968 V of its 1.0 V target in 90 ns of phi1, so a ±0.1 V
  differential input is sampled ~46 % complete, while the *integrate* phase at
  that same corner settles exactly (`tpi_p` = `sump` to 6 digits well before
  phi2 falls). The cause is the `Sin` switch near `vcm`: at 1.62 V its NMOS half
  is off and its PMOS half has ~0.1 V of overdrive. At `tt`/27 °C/1.80 V the same
  sampling is exact to six digits, so this is corner-specific and not a property
  of the bench. It is **not** charge injection, it is out of scope for this
  issue, and it is filed as **#106** — a per-corner `ci_gain_error_bound` from
  the slow/cold corners is dominated by it and must not be read as a gain error
  of the charge-transfer path.
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
- **The model-B run this bench feeds is source B and uncross-checked.** It
  reports what the extracted `ci_offset`/`ci_gain_error` do to SNDR in the
  behavioural model; it is not a transistor-level SNDR number and does not
  become one.

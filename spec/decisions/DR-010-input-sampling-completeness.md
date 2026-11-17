# DR-010: Input-sampling completeness line

- **Status**: proposed; ratified when the PR carrying it (issue #129) is
  Judge-approved and merged
- **Date**: 2026-11-17
- **Decided by**: Builder agent, issue #129, from the measurements in #106
  (PR #130) and the sizing sweep and re-graded grid this record lands with

## Context

Issue #106 measured the second-order modulator's first-integrator input
sampling and found it grossly incomplete at the slow/cold corners: at
`ss`/1.620 V/−40 °C only 45.7 % of a 0.2 V differential input had reached
`Csi`'s bottom plates when `phi1e` froze the sample (error
`1 − sampled/ideal` = 0.5432 across `Csi`, 0.5044 on the bottom-plate-only
reading), and the error was strongly input-level dependent — the signature of
distortion at the modulator's input, not of a gain error. The mechanism is
`Sin`, the input transmission gate: both halves were standard-`Vth`
(`nfet_01v8` W 4 + `pfet_01v8` W 8, L 0.15), so near `vcm` at a low supply
neither half has overdrive and the gate's peak `Ron` is 584 kΩ at
`ss`/1.620 V/−40 °C (`sim/switch-probe/probe-i106.json`) — a 584 ns
`Ron·Cs` time constant against the 90.4 ns the input path gets. No ratified
spec row bounded input-sampling completeness; #106 added none and graded
nothing.

Issue #129 is the decision and the change. Every number in it is
**simulated** (ngspice-47, pinned sky130A, open_pdks
`f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`), never measured, and no SNDR,
ENOB or resolution consequence is claimed anywhere: nothing here has been
through model B.

## Decision

**Fix the cell, and grade it against an explicit design-level line.**

1. **The line.** Input-sampling completeness is graded at error
   `1 − sampled/ideal` ≤ **1e-4** at both recorded amplitudes (0.2 V and
   0.6 V differential; 0.6 V is the row-11 peak input) over the DR-002
   45-corner grid, **on `error_rel_bpi_only`** — the bottom-plate-only
   reading `sim/integrator-ci/run_sampling.py` carries beside its
   across-`Csi` headline. The bottom-plate reading is the one a `Sin`-only
   remedy acts on: the across-`Csi` headline also contains the `Sci`
   top-plate-hold term, which is **#147** and which no `Sin` change moves.
   1e-4 is the level `sim/integrator-settling` already grades DR-005 charge
   transfer against. This is a **starting level, not a final bound**: as
   DR-005 words its own 0.01 % settling line, the number is to be confirmed
   or tightened by model B later — a level-dependent residual at the
   modulator input is distortion the loop does not shape, and what it costs
   in band is a model-B question. The line adds a limit where none existed;
   it relaxes nothing and changes no row of `spec/modulator-adc.md` §1.1.

2. **The cell change.** `Sin` becomes a low-Vth transmission gate, the same
   remedy #92 applied to the phi2 `vcm` switches: NMOS
   `nfet_01v8_lvt` W 4 / L 0.15, PMOS `pfet_01v8_lvt` W 8 / L 0.35 (the lvt
   PMOS model's minimum length; the standard-Vth PMOS at L 0.15 cannot simply
   be re-flavoured). The widths are unchanged from the previous gate — this
   is the smallest candidate in the committed sizing sweep
   (`sim/switch-probe/probe-i129.json`), chosen because its worst-case peak
   `Ron` (3158 Ω at `ss`/1.620 V/−40 °C, at Vin = 0.85 V) already leaves
   ~3× margin against the ~9.8 kΩ the 1e-4 line implies for a 90.4 ns window
   on 1 pF, while adding the least input load and channel charge. The chosen
   size, the sweep it came from, and the before/after binding corners are in
   `design/integrator/SIZING.md` (dated section "Issue #129: the `Sin` low-Vth
   fix").

### Routes rejected

- **Longer `phi1`.** The peak `Ron` of 584 kΩ on 1 pF is a 584 ns time
  constant; reaching 1e-4 takes ~9.2 τ ≈ 5.4 µs against a 195.3 ns clock
  period (row 5 `fs` = 5.12 MHz, ratified). No phase re-split closes a gap
  that size. (Arithmetic treating `Ron` as constant at its peak, which it is
  not: an order-of-magnitude argument, not a simulation.)
- **Width only.** `sim/switch-probe/probe-i92.json` already shows 8× width
  buying 2.5× on a subthreshold device — the deficit is a `Vth` deficit, not
  a `W/L` one.
- **Accept and bound it in model B.** `sim/bmodel/model.py` has no
  input-level-dependent sampling term; its input-path terms are constant
  factors, and fact 1 of issue #129 is that this error is not a constant
  factor. Accepting would mean adding and cross-checking a new nonlinear
  model term, which costs more than the fix. (Inferred, not run.)
- **Bootstrapped switch.** A new sub-circuit; held open only if the low-Vth
  sweep had shown no size that works. It did not.
- **`Sr_*`, `Mra_*`, `Mrb_*`** stay standard-Vth: the reference path sits at
  0.3 / 1.5 V where the #106 sweep reads 0.17–0.74 kΩ even at
  `ss`/1.620 V/−40 °C. Left alone.

## Status against the line at the time of writing

Measured on the changed cell (`sim/integrator-ci/record-i129.json`, DR-002
full grid, both amplitudes, batch fleet; simulated):

- **87 of the 90 corner-amplitude points meet the line** (44/45 at
  0.2 V, 43/45 at 0.6 V) on `error_rel_bpi_only`. The filed
  point improved **5670×**: `ss`/1.620 V/−40 °C at 0.2 V went
  0.5044 → 8.9e-5, under the line. Every `sf` and `tt` corner reads exactly 0.
- **Three corners sit over the line**, all at 1.620 V/−40 °C:
  `fs` at both amplitudes (5.2e-4 at 0.2 V, 2.0e-3 at 0.6 V) and `ss` at
  0.6 V (4.4e-4). The error there is a **p-side bottom-plate shortfall that
  tracks `Sci`'s top-plate anomaly** (#147): it is worst exactly where
  `Sci`'s top-plate hold is worst (78.9 mV off `vcm` at `fs`/1.620 V/−40 °C),
  it sits on the p side only, and it is smallest at `ss` — the opposite of a
  settling-limited mechanism, which is what the sizing sweep addresses. The
  coupling term scales with `1/Ron_Sin`: the sweep's next candidate
  (NMOS W 12 / PMOS W 24, ~3× lower `Ron`) would still leave it ~3× over the
  line, and clearing 1e-4 at `fs`/1.620 V/−40 °C would take roughly a 20×
  width increase, at which point the input load and injection trade collapses.
  **The line is therefore gated by #147 at those three corners, not by `Sin`
  sizing**; this record states that rather than relaxing the line.

## Spec lines affected

None. No row of `spec/modulator-adc.md` changes; §5.3 planning values are
untouched. This record adds a design-level grading line for a quantity no
spec row bounded.

## Consequences

- `sim/integrator-ci/run_sampling.py` reports both bindings (across-`Csi`
  and `error_rel_bpi_only`) and names the binding corner per amplitude on
  the bottom-plate reading; the fleet never carries the line as a limit —
  the line is graded on the record, not by the fleet.
- The charge-injection extraction and its model-B derivations
  (`sim/integrator-ci/record.json`, `record-mc.json`, `bmodel-ci-*.json`,
  `sim/integrator-noise/record*.json`) are pre-change-cell evidence; the
  follow-up (#266) re-extracts them on this cell. Until then
  the model-B `ci_*` parameters carry the pre-change extraction.
- The integrator layout (`layout/analog/integrator/`) is regenerated in the
  same change; a layout that disagreed with its schematic would not be
  shippable evidence.
- Monte Carlo / mismatch on the sampling path remains owed generally and is
  not discharged by this record.

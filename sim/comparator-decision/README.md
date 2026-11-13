# comparator-decision — decision time, systematic offset, hysteresis, kickback

**Simulated** (ngspice, transistor-level), never measured. Issue #127; it
closes the two checks [DR-003](../../spec/decisions/DR-003-sibling-reuse.md)
still owes on the vendored comparator — decision time against this clock's
half-period at the [DR-002](../../spec/decisions/DR-002-pvt-corners.md)
corners, and kickback against the integrator amplifier input — and gives
model B's `comparator_offset` and `comparator_hysteresis` a transistor-level
source over the same 45-point grid.

    python3 -I sim/comparator-decision/make_request.py     # regenerate decks + requests
    python3 -I sim/comparator-decision/run_decision.py --probe loop   # one local corner
    python3 -I sim/comparator-decision/run_decision.py --record      # the 45-point grid

`run_decision.py` submits through `klt sim`, which sends the grid to the batch
fleet; it never falls back to a local grid.

The shared fleet loses shards routinely — a capacity refusal once its vCPU
budget is spent, or a Spot reclaim — and a lost shard returns its corners as
valueless `error` entries, which this bench refuses to write a record from
(and, since that refusal is not a result, refuses to cache in `.partials/`).
Finish such a grid without paying for the whole of it again:

    python3 -I sim/comparator-decision/run_decision.py --work /tmp/cmpdec   # first run
    python3 -I sim/comparator-decision/run_decision.py --work /tmp/cmpdec --resume --record

`--resume` launches only the units the earlier run into that same `--work`
left unrun, and needs the request to be unchanged. `--capacity-wait-s` raises
the per-launch wait above the host rule's 600 s floor when the fleet is
saturated.

Unit tests (no EDA tools, no fleet):

    python3 -I -m unittest discover -s sim/comparator-decision -p 'test_*.py'

## The circuit under test is the whole modulator

Both variants instantiate `design/modulator/modulator.spice` — which carries
`clkgen` and both `integrator` cells in its own body — plus
`design/ota/ota_fd.spice` and the vendored
`design/modulator/comparator/comparator.spice`. **Nothing in the decision path
is substituted**: the comparator's `clk` port is on the real `phi1` out of
`clkgen`, its inputs are the real integrator-2 OTA outputs `o2p`/`o2n`, its
outputs drive the real cross-coupled NAND SR latch, and the latch's `dp`/`dn`/
`bs` inverter buffers drive the reference muxes of **both** integrator cells,
exactly as in the block. That is what "in the loading it has inside the
modulator" means here, and it is why the bench is the modulator rather than a
hand-built comparator testbench: a testbench would have had to re-create the
latch and the buffers, and would have drifted from `modulator.spice`.

What *is* at the boundary is at the boundary for DR-005 reasons, as in every
other bench in `sim/`: `vcm`, `ibias`, the reference pair and the differential
input are ideal sources. The clock is a unit-amplitude `pulse` scaled by
`v(vdda)` so it swings rail-to-rail at all three supply corners while the
analog boundary stays fixed.

## Two variants

| | `loop` | `trip` |
|---|---|---|
| reference pair | 1.5 / 0.3 V (spec) | **nulled**: VREFP = VREFN = VCM = 0.9 V |
| input | 0.06 V DC differential (0.05 FS) | staircase, below |
| transient | 3.07 µs (16 clocks) | 4.83 µs (25 clocks) |
| 45 corners cost | ~45 fleet units | ~45 fleet units |
| gives | decision time, kickback | trip points → offset, hysteresis |

**Why `trip` nulls the reference.** The two quantities model B wants are
properties of the comparator's decision boundary, so the bench has to walk the
comparator's input slowly across it. In the closed loop it cannot: the 1-bit
feedback moves `x2` by half of full scale every clock. Nulling the reference
pair opens the loop **without disconnecting anything** — every switch in the
reference branch still operates and still injects, it just transfers no charge
whichever way `dp`/`dn` go — so the comparator keeps the loading it is being
graded in. `sim/integrator-ci` uses the same device for the same reason
(see that README, "Nulling the DAC").

With the loop open the two integrators are a plain cascade,

    o1d[n] = o1d[n-1] + G*u[n]            (u is sampled during phi1 of clock n)
    o2d[n] = o2d[n-1] + G*o1d[n-1]        (delaying integrators, G = Cs/Ci = 0.5)

and the comparator decides on `o2d[n-1]` at the phi1 rise of clock n. So
holding `o1d` at a constant ±`STEP_V/G` walks the comparator's input by
±`STEP_V` per clock. The input PWL in `make_request.trip_input_pwl()` does
exactly that, and only ever moves between one clock's phi1 and the next
(the cell samples during phi1).

## Staircase

`STEP_V` is 500 µV, so **500 µV is the resolution of both the offset and the
hysteresis width.** The sweep is deliberately offset by half a step, so no
decision is ever taken on an exactly-zero differential: a latch at its own
trip point is metastable, and a metastable clock in the middle of the ramp
would be a bench artefact rather than a measurement.

| clocks | what the comparator is shown |
|---|---|
| 0–3 | start-up: a two-clock approach to −2.25 mV |
| 4–12 (`trip_up`) | −1.75 mV → +2.25 mV, rising in 500 µV steps |
| 13 | turn-around |
| 14–23 (`trip_dn`) | +2.25 mV → −2.25 mV, falling in 500 µV steps |

Only the *targets* are designed here. The step the bench actually delivered is
measured at the trip itself (`step_up`, `step_dn`, from the held value one
clock earlier), so a `Cs/Ci` that is not exactly 0.5 changes the resolution
and nothing else. Bench-validity gates — not spec limits — make a sweep that
failed to bracket the trip a graded failure rather than a quiet number:
`flip_up`/`flip_dn` (the decision changed at all), `k_up`/`k_dn` (it changed
*strictly inside* the staircase, not on its first or last clock), and
`span_up`/`span_dn`, `step_up`/`step_dn` (it moved, and in the intended
direction).

**The delivered step is not 500 µV at every corner, and that is not a
failure.** The step is `(Cs/Ci)·o1d`, so it is only as large as the cell's
charge transfer. At the low-supply, slow, cold corners that transfer
collapses — the same corners `sim/integrator-settling` already records as
unsettled at VDDA = 1.620 V — and the first fleet run measured a 5.6 µV step
at `ss`/1.620 V/−40 °C against 500 µV at the fast corners, a factor of ~90.
A narrower sweep in finer steps is a **finer** measurement inside a
**narrower** bracket, not a wrong one, and what a trip point actually rests
on is bracketing: `k_up`/`k_dn` say the decision changed strictly inside the
swept clocks. So the direction gates are a floor at `SWEEP_FLOOR_V` = 2 µV —
twice ngspice's default `vntol`, i.e. the smallest move that is a move rather
than solver noise — and not an absolute span. An absolute span would have
failed those corners for the *integrator's* behaviour rather than the
comparator's.

The record carries `staircase_step_V` per corner and a
`resolution_range_V` naming the coarsest and finest corner, so no single
resolution figure stands in for corners it was not measured at. Corners that
also carry `singular_matrix` / `nonconvergence` diagnostics keep them in the
record: at 1.620 V this hierarchy makes ngspice work for its operating
point, and a reader should weigh those corners accordingly.

## Model-B units

Model B advances integrator 2 by `k2*(x1 - y)` with `k2 = C2 = 0.5` and
`y = ±1` at full scale (`sim/bmodel/model.py`). The cell moves its
differential output by `(Cs/Ci)*(v_o1_diff + vdac_diff) = 0.5*(v_o1_diff +
vdac_diff)` per clock, with `vdac_diff = −y*(VREFP − VREFN) = −y*1.2 V`.
Substituting `x1 = v_o1_diff / S` makes the two agree for **S = 1.2 V**, so

    one model-B x2 unit = 1.2 V of differential output at integrator 2
    comparator_offset [FS]     = offset [V] / 1.2 V
    comparator_hysteresis [FS] = hysteresis width [V] / 1.2 V

This is the same factor `sim/integrator-ci/README.md` derives for `x1` at
integrator 1, which is expected: both stages are the same cell, with the same
`Cs/Ci` and the same 1-bit DAC. (The curator's note asked for this to be
derived or cited rather than assumed; the derivation above is the one the
record carries, and `make_request.FS_VOLTS` is the only place the number
lives.)

**Sign convention.** Model B holds `y = +1` until `x2 + off ≤ −h/2` and
`y = −1` until `x2 + off > +h/2`, so a rising sweep trips at `x2 = +h/2 − off`
and a falling one at `x2 = −h/2 − off`. Inverting,

    off = −(x2_up + x2_dn)/2        h = x2_up − x2_dn

`run_decision.offset_hysteresis()` is that inversion and the fixture tests
pin it. A **negative** `h` — a falling trip *above* the rising one — cannot
come from hysteresis; it is reported as measured rather than clamped to zero,
so a run in which the staircase resolution is the dominant term shows that
rather than hiding it.

### What a staircase can and cannot say

A staircase shows the comparator only grid points one step `Δ` apart, so with
a true threshold `t` and a true width `h`:

    the up sweep flips at the first grid point above t + h/2
        -> v_up in (t + h/2,     t + h/2 + Δ]
    the down sweep flips at the first grid point below t - h/2
        -> v_dn in [t - h/2 - Δ, t - h/2)

Subtracting and averaging those:

    h in (v_up - v_dn - 2Δ,  v_up - v_dn)
    t in ((v_up + v_dn)/2 - Δ/2,  (v_up + v_dn)/2 + Δ/2)

So **the offset is resolved to ±Δ/2, and `v_up − v_dn` is an upper bound on
the hysteresis, not a measurement of it** — a comparator with no hysteresis
at all reads one whole step here. The first fleet run measured exactly that
shape: 522 µV at `tt`/1.800 V/27 °C against a 500 µV step, i.e. 1.04 steps.
The record therefore carries a `quantization` block per corner with the step
and both hysteresis bounds, and `comparator_hysteresis` is the raw
difference — the upper bound, and the conservative value to hand model B.
`run_decision.quantization()` is that arithmetic and the fixture tests pin
it, including the hysteresis-free case reading one step.

Each corner also carries `bracket_margin_clocks`: how many clocks separate
each trip from the nearer end of its own sweep. Zero means the staircase only
just reached the trip, so that corner's numbers rest on the sweep's own edge.

## Decision time, and the limit it is held to

The measurement is the delay from the **phi1 rising edge** (50 % of `v(vdda)`,
located at the corner being measured — the clkgen delay is corner-dependent)
to **`dp`/`dn` carrying the new decision**, which are the nets the integrators'
reference mux actually consumes. The comparator's own outputs (`outp`/`outn`)
and the SR latch (`q`/`qb`) are reported as intermediate crossings.

Only a clock on which the decision *changes* can show that delay: the NAND SR
latch holds `dp`/`dn` between decisions, so on a repeat decision there is
nothing to observe. The record therefore grades the worst delay over the
clocks that did flip (`tdec_worst`), and `n_flip ≥ 2` is itself a graded row —
a corner that never changed `dp`/`dn` carries no decision-time evidence and
cannot pass by default.

**The limit is the phi1 high time the bench actually delivers at that corner,
measured in the same transient.** DR-003 words the owed check as "decision
time against this clock's half-period", but the half-period (97.65625 ns) is
not what the comparator is given: `clkgen` spends part of each half on the
non-overlap gaps, and the phi1 buffer chain is not symmetric, so the delivered
width is close to but not equal to 97.65625 ns. The graded row is therefore
`tdec_frac = tdec_worst / phi1_width ≤ 1`.

**No settling reservation is subtracted.** The curator's note allows one:
`design/modulator/README.md` ("Decision path and timing") says the reference
node must settle inside phi1 after `dp`/`dn` change, so in principle the
decision-time budget is the phi1 width *less* whatever that settling needs.
No committed record in this repo bounds that time — `sim/integrator-settling`
grades the phi2 integrate phase, not the phi1 reference node — so, as the
issue instructs, **the limit is stated as the bare delivered phi1 width and
labelled as such.** Narrowing it is work for whoever first records the
reference-node settling time.

**At the trip point itself** the overdrive is a fraction of a millivolt and
the latch is near-metastable. The `trip` variant reports `tdec_up` / `tdec_dn`
there as numbers, **ungraded**: every regenerative latch is slow at its own
trip point, and putting a limit on it would be inventing a spec row rather
than checking one.

Decision time is resolved to the solver's own local timestep around the edge
(tens of picoseconds here), which is immaterial against a ~97 ns limit but is
why the numbers are not quoted to more than three figures.

## Kickback

Reported on **both** nodes, with the node named on every number:

- `o2p`, `o2n` and their difference — the comparator's own inputs, where the
  disturbance lands, and where issue #127 puts the check;
- `xi2.sump`, `xi2.sumn` and their difference — the integrator-2 OTA summing
  (virtual-ground) nodes, which is how DR-003 words the owed check.

Each number is the peak deviation of that node, inside a 40 ns window after
the clk edge, from the value the node holds through the same phi1 once the
disturbance has settled. That held value *is* the pre-edge value — the
integrator holds its output across the non-overlap gap — and it is read late
in phi1 rather than just before the edge because the gap is only ~0.6 ns wide,
too narrow to sample reliably at every corner.

**What the number is, exactly.** The phi1 edge carries two superposed
disturbances, and this bench does not run the comparator's clock separately
from the integrator's, so it reports their sum and the evidence for splitting
it rather than a single unattributed figure:

- the integrator's **own** phi2 → phi1 switch transition, which is symmetric
  across the two sides and therefore essentially common-mode;
- the comparator's **kickback**, which is driven by its input pair and
  therefore scales with the differential that pair sees.

Both the single-ended nodes and their differences are measured, at *two*
clocks whose differentials differ (`make_request.LOOP_KICK_CLKS`), and the
record keeps both clocks. On the development probe (tt / 27 °C / 1.8 V) the
single-ended deviation was ~90 mV at both clocks — flat, as a signal-
independent switch transition should be — while the differential deviation
was 1.5 mV at a −78 mV input differential and 7.0 mV at +608 mV: it tracks
the differential, as kickback should. **The differential numbers are
therefore the ones that are about the comparator**, and they are the ones
that matter to the integrator, whose common-mode feedback rejects the rest.

**No pass limit is invented for kickback.** This repo has no kickback row of
its own. The sibling's ratified 5 mV row is against *its* bench — ideal input
sources through 1 kΩ, a different open_pdks pin — not this loading, so it is
context, not a limit here.

## The sibling's records are context, not evidence

`reuse.lock.json` pins `2AMLogic/sky130-comparator` at
`a0767fa5a4bedc9128a7e95b8b512075536522c8`. Read at that commit on
2026-11-13 (`gh api repos/2AMLogic/sky130-comparator/contents/<path>?ref=<commit>`):

- its `sim/pdk.json` carries `open_pdks_commit`
  `c6d73a35f524070e85faff4a6a9eef49553ebc2b`, while this repo's `sim/pdk.json`
  pins `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` — **different PDK revisions**,
  so its numbers cannot be evidence for this repo's corners;
- `sim/characterization-report.md` grades seven process/temperature points,
  not the DR-002 45-point grid;
- its kickback bench biases `VINP`/`VINN` at `VCM` through an explicit 1 kΩ
  series resistor each, not from an integrator output;
- `grep -i hysteres` on that report matches nothing: there is no hysteresis
  row to cite at all.

So the "cite the sibling and measure only what the in-situ loading changes"
branch of the issue's implementation guidance does not apply, and **all 45
points are measured here.** Its row 3 (decision time, 0.7725 ns at 50 mV
overdrive, worst `fs`/125 °C) and row 4 (kickback, 3.1989 mV into 1 kΩ, worst
`sf`/−40 °C) are quoted only as the order of magnitude to expect. Its kickback
*definition* — peak absolute deviation from each node's own settled pre-edge
value — is the same one used here, which is why the magnitudes are
comparable even though the loading is not.

## Results

<!-- results:begin -->
Not yet recorded: `record.json` is written by
`python3 -I sim/comparator-decision/run_decision.py --record`.
<!-- results:end -->

## Files

| file | what it is |
|---|---|
| `comparator_decision.cir.tmpl` | the deck, one template for both variants |
| `comparator_decision_loop.cir`, `comparator_decision_trip.cir` | generated; do not hand-edit |
| `make_request.py` | timing grid, staircase design, measurement lists, both requests |
| `request_loop.json`, `request_trip.json` | generated `klt sim` requests (DR-002 full grid) |
| `run_decision.py` | submits, gates, derives, writes the record |
| `test_run_decision.py` | fixture tests for the derivations and the gates |
| `record.json` | the append-only record |

`.partials/` (one completed variant, so a fleet capacity refusal on the other
does not discard 45 corners) and `.artifacts/` (the raw `klt sim` report and
the batch receipt) are gitignored.

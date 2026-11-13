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
fleet; it never falls back to a local grid. Unit tests (no EDA tools, no
fleet):

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
and nothing else. Three bench-validity gates — not spec limits — make a sweep
that failed to bracket the trip a graded failure rather than a quiet number:
`flip_up`/`flip_dn` (the decision changed at all), `k_up`/`k_dn` (it changed
*strictly inside* the staircase, not on its first clock), and
`span_up`/`span_dn` (the sweep really covered ±3.5 mV).

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

**No pass limit is invented for kickback.** This repo has no kickback row of
its own. The sibling's ratified 5 mV row is against *its* bench — ideal input
sources through 1 kΩ, a different open_pdks pin — not this loading, so it is
context, not a limit here.

## The sibling's records are context, not evidence

`reuse.lock.json` pins `2AMLogic/sky130-comparator` at
`a0767fa5a4bedc9128a7e95b8b512075536522c8`. At that commit the sibling's
`sim/pdk.json` pins open_pdks `c6d73a35…`, while this repo pins `f6eeac7d…`
(`sim/pdk.json`); it grades seven process/temperature points, not the DR-002
45-point grid; it drives its comparator's inputs from ideal sources through
1 kΩ rather than from an integrator; and it publishes no hysteresis row at
all. So the "cite the sibling and measure only what changes" branch of the
issue's implementation guidance does not apply, and **all 45 points are
measured here.** The sibling's 0.7725 ns decision time (50 mV overdrive,
worst at `fs`/125 °C, extracted DUT) and 3.1989 mV kickback (worst at
`sf`/−40 °C) are quoted only as the order of magnitude to expect.

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

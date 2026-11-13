# sim/integrator-settling — integrator + ota_fd settling bench (issue #53)

**Simulated, transistor-level** (ngspice on `design/integrator/integrator.spice`
with `design/ota/ota_fd.spice`; not the behavioural model). Question: does the
97.66 ns integrate phase (spec row 5) close to 0.01 % (DR-005) for the full
integrator cell, with both sampling caps on the summing node (beta = 0.496,
hand-calc in `design/integrator/SIZING.md`)?

**Answer: no.** `record.json` holds the 45-point DR-002 grid for both variants
(90 points, all simulated on the batch fleet). `int1` passes 29/45, `int2`
passes 10/45, and **every corner at Vdda = 1.620 V fails, for both variants**.

## Bench (`integrator_settling.cir.tmpl` -> `integrator_settling_{int1,int2}.cir`)

The full cell, including switch Ron and the DAC cap on the summing node.
Boundary (DR-005): VCM 0.9 V, VREFP/VREFN 1.5/0.3 V, ibias 5 uA, all ideal.
Stimulus: vin diff +0.6 V and `dn` = 1 (y = -1), the worst-case first-integrator
step: ideal charge transfer `0.5 * (0.6 + 1.2)` = 0.9 V differential
(0.45 V per side, the same step as `sim/ota-settling`).
Phi1/phi1b/phi1e/phi2/dn are behavioural rail-to-rail sources on Vdda with
200 ps edges and no non-overlap generator (clock generation is out of scope).
A bench-only ideal reset (1 ohm, across `Ci`, closed until 31 ns) starts `Ci`
discharged; the cell has no reset. phi2 stays high after its edge at 35 ns; the
tail gives the settled value.

**Stage phasing.** The integrators are delaying (`sim/bmodel`): while integrator
1 integrates (phi2) integrator 2 only samples in phi1, so its `Sin` is off and
integrator 1's output sees only parasitics: **case B** of `SIZING.md`
(236 uS needed). The `int1` variant uses 0.1 pF per side. The `int2` variant
adds 1 pF per side, the **case A** bound (449 uS needed), because the
comparator input and feedback network loading is not defined yet. Both use the
same cell and step; `int2` is a load bound, not a separate circuit.

## Measurements

Same definitions as `sim/ota-settling`, sampled 97.66 ns after the phi2
mid-edge: `err_phase` (**pass <= 1e-4**), `t_1e4/t_1e3/t_1e2`, `slope_pk`,
`t_slew`, `slew_frac`, and the reference-validity gates `end_ripple_rel`
<= 1e-3 and `step_err_vs_ideal` <= 0.05.

## Result (record.json, 2026-11-13)

Jobs `klt-sim-8ea68b4baa34` (int1) and `klt-sim-761cf51b44ee` (int2), AWS batch
fleet, ngspice 47, klt 0.9.2.dev885+ge4c446bd91f2, open_pdks
f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7. Both receipts read `state: failed`:
that is `klt sim` exit code 3, **corners missing their limits**, not a fleet
failure — all 90 points returned measurements.

Worst `err_phase` per process corner (all at 1.620 V / -40 C, the binding
PVT point for both variants):

| Process | int1 pass | int1 worst | int2 pass | int2 worst |
|---|---|---|---|---|
| tt | 6/9 | 0.672 | 2/9 | 0.679 |
| ss | 6/9 | 0.739 | 2/9 | 0.746 |
| ff | 6/9 | 0.551 | 2/9 | 0.562 |
| sf | 6/9 | 0.485 | 4/9 | 0.497 |
| fs | 5/9 | **0.777** | 0/9 | **0.784** |

The grid separates cleanly by **supply**, not by process:

| Vdda | int1 pass | int2 pass |
|---|---|---|
| 1.620 V | 0/15 | 0/15 |
| 1.800 V | 14/15 | 2/15 |
| 1.980 V | 15/15 | 8/15 |

At 1.620 V the cell does not settle at all: `t_1e4` sits at 300 ns (the whole
transient window), `slew_frac` reaches 0.89, and the two validity gates are
violated at the 8 worst corners per variant — so `err_phase` there reads "never
settled", not a precise residual. Among the 37/45 corners per variant where
both gates hold, the worst `err_phase` is 0.107 (int1) and 0.151 (int2).

**Versus the hand-calc** (`SIZING.md`, beta = 0.496, gm 302 uS at the smoke
bias point), at the nominal tt/1.800 V/27 C corner:

| Case | Hand-calc | Measured | Verdict |
|---|---|---|---|
| B (`int1`, 0.1 pF) | 1.1e-5, needs 236 uS | **6.4e-6** | passes 1e-4, as predicted |
| A (`int2`, 1.1 pF) | 1.6e-3, needs 449 uS | **2.3e-4** | misses 1e-4, as predicted |

The hand-calc is confirmed in structure and conservative in magnitude (7x on
case A). The OTA alone passes all 45 corners on its own bench
(`sim/ota-settling/record-i51-rcm2M-cff100f.json`, worst 6.8e-5, same
`ota_fd.spice` sha256 `7f4724e9...` this run used): the loss is the integrator
cell's beta = 0.496 loading, exactly the gap #53 was filed to measure.

## B-model comparison (`bmodel-threshold.json`)

    python3 -I sim/integrator-settling/bmodel_threshold.py --records

Largest behavioural-model `settling_error` keeping peak SNDR >= 80 dB:
**0.57** (peak 80.06 dB at -6 dBFS; 0.58 gives 79.57 dB and fails), quoted to a
0.01 grid. Record length 2^16 output samples, Blackman-Harris 4-term window,
bin bandwidth 1.2207 Hz, band 0-20 kHz, OSR 128. Behavioural model B,
uncross-checked. Canonical records: `sim/bmodel/records/20261113T094826Z-1e74d78e.json`
(0.57) and `20261113T094837Z-aa4731a8.json` (0.58). The sweep is deterministic:
with every noise parameter zero the result is seed-independent (verified over
seeds 1-5).

**This threshold does not license a 57 % settling error.** `settling_error` is
a *linear* gain factor `(1 - settling_error)` applied equally to both integrator
inputs and constant over the record, so it prices only the signal-independent
part of incomplete settling — a second-order loop at OSR 128 absorbs a uniform
loop-gain deficit very well, which is why the number is so large. The failures
measured here are **slew-limited** (`slew_frac` up to 0.89), hence
signal-dependent and distortion-generating, which this parameter cannot
represent. Comparing the two:

- At **1.800 V and above**, the measured error (1.9e-4 int1, 2.9e-3 int2 worst)
  sits far inside the 0.57 linear budget. This answers the open risk
  `SIZING.md` leaves to the B-model: case A's 1.6e-3 is **not** what limits
  SNDR at nominal supply. Necessary, not sufficient — the distortion term is
  not modelled.
- At **1.620 V** the measured 0.37-0.78 exceeds even that loose linear budget,
  and the settling is nonlinear there anyway. This is a hard failure on any
  reading, and DR-005's 1e-4 criterion is unchanged by it.

## Running

    python3 -I sim/integrator-settling/make_request.py              # regenerate decks + requests
    python3 -I sim/integrator-settling/run_settling.py --probe int1 # 1 corner, local
    python3 -I sim/integrator-settling/run_settling.py --record     # 2 x 45 corners, batch fleet
    python3 -I sim/integrator-settling/run_settling.py --variant int2 --record  # one variant

The runner refuses a PDK whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2), never falls back to a local grid, refuses to write a record unless
all 45 points of both variants returned **and every corner produced an
`err_phase`** (a dead fleet job returns 45 empty points, which the count gate
alone would accept), and refuses to overwrite a record (append-only; use
`--record-name`). Each variant is one `klt sim` request (DR-002 full grid,
5 process x -40/27/125 C x 1.62/1.80/1.98 V) submitted with
`--wait-for-capacity 600`, so a refused launch waits with backoff instead of
failing the run.

`--variant` runs one variant; each completed variant is cached under
`.partials/` (gitignored, keyed to the request and deck sha256) so a capacity
refusal on one variant does not discard the other's 45 corners — re-run the
missing variant and `--record` assembles both. The raw `klt` report, batch
receipt and stderr land in `.artifacts/` (gitignored) *before* the completeness
gate, so a failed or partial grid is still inspectable.

## Limits

Noise, charge injection, clock-generator timing, Monte Carlo, layout parasitics
and the model-versus-transistor cross-check (DR-001) are not covered. `int2`'s
1 pF is a bound, not an extracted comparator input capacitance. The B-model
threshold covers the linear part of settling only (above). The remedy for the
1.620 V failure is an OTA change, tracked in #92 — not a relaxation of DR-005
or of the spec.

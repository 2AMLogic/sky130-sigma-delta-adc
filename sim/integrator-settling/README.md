# sim/integrator-settling — integrator + ota_fd settling bench (issue #53)

**Simulated, transistor-level** (ngspice on `design/integrator/integrator.spice`
with `design/ota/ota_fd.spice`; not the behavioural model). Question: does the
97.66 ns integrate phase (spec row 5) close to 0.01 % (DR-005) for the full
integrator cell, with both sampling caps on the summing node (beta = 0.496,
hand-calc in `design/integrator/SIZING.md`)?

**Status: bench and runner only. No 45-point record exists yet.** The batch
submit failed (see "Batch status"); nothing was run as a local grid. The only
simulation behind this directory is a single local debug probe (below).

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

## Running

    python3 -I sim/integrator-settling/make_request.py            # regenerate decks + requests
    python3 -I sim/integrator-settling/run_settling.py --probe int1   # 1 corner, local
    python3 -I sim/integrator-settling/run_settling.py --record       # 2 x 45 corners, batch fleet

The runner refuses a PDK whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2), never falls back to a local grid, refuses to write a record unless
all 45 points of both variants returned, and refuses to overwrite a record
(append-only; use `--record-name`). Each variant is one `klt sim` request
(DR-002 full grid, 5 process x -40/27/125 C x 1.62/1.80/1.98 V).

## Batch status

`--record` on 2026-10-27 reached the batch submit and failed at the first
upload: `aws s3 cp ... InvalidAccessKeyId: The AWS Access Key Id you provided
does not exist in our records` (job `klt-sim-3f9377199b90`, never started). This
is a worker credential gap, not a design result. The record is still owed.
`options.timeout_s` is 60 s so that 45 serial units fit the fleet's 3600 s
job ceiling.

## Debug probe (not evidence)

One local tt / 27 C / 1.8 V point, `int1`: `err_phase` 0.074, `end_ripple_rel`
0.050 and `step_err_vs_ideal` 0.065, so both validity gates fail and the
waveform has not settled. This matches the baseline on `main`: the
`ota_fd` fails the 45-corner `sim/ota-settling` record at every corner (issue
#51). One corner, not a PVT result; do not quote it as the settling error.

## Limits

Noise, charge injection, clock-generator timing, Monte Carlo, layout parasitics
and the model-versus-transistor cross-check (DR-001) are not covered. The
B-model `settling_error` threshold (`sim/bmodel/run.py`) is not yet extracted.

# sim/ota-settling — OTA step-settling bench (issue #48)

**Simulated, transistor-level** (ngspice on `design/ota/ota_fd.spice`; not the
behavioural model). Question: does the 97.66 ns integrate phase (spec row 5)
close for the worst-case first-integrator step, with slew and linear settling
sharing the phase?

## Bench (`ota_fd_step.cir`)

Closed-loop integrate-phase configuration of `design/ota/SIZING.md`: Cs = 1 pF
(step side), Ci = 2 pF, Cp = 35 fF per summing node, 1.1 pF external load per
side (the Ci series network supplies the rest of the ~1.8 pF `CL,eff`),
`ibias` = 5 uA and VCM = 0.9 V ideal (DR-005). Feedback pairs `inp` with
`outn` (M1 folds into `outn`). Ideal reset switches close the loop until
2 ns; at 3 ns (mid-edge) the Cs plates step by +/-0.9 V per side, which is
+/-0.45 V per side at the outputs after charge transfer. The bench includes
the instantaneous capacitive feedthrough of the step, so the output must
travel further than the 0.45 V ideal step.

## Measurements (`make_request.py` -> `request.json`)

Sample point is 97.66 ns after the step mid-edge, interpolated on ngspice's
non-uniform output grid.

- `err_phase`: residual error at the sample point relative to the settled
  differential step (`vod_end`, value at 300 ns). **Pass: <= 1e-4 (0.01 %)** at
  every corner.
- `t_1e4`, `t_1e3`, `t_1e2`: time from the step to the last excursion beyond
  that error level.
- `slope_pk`, `t_slew`, `slew_frac`: peak output slope (after the step edge),
  duration at >= 80 % of it, and its share of `t_1e4`. Meaningful only where
  the waveform settles to the right place.
- Reference-validity gates (not spec rows; they stop a run that never
  settles from passing against its own end value): `end_ripple_rel` <= 1e-3
  (last 20 ns) and `step_err_vs_ideal` <= 0.05 (final step within 5 % of
  the ideal 0.9 V).

## Running

    python3 -I sim/ota-settling/run_settling.py --probe     # 1 corner, local
    python3 -I sim/ota-settling/run_settling.py --record    # 45 corners, batch fleet

The runner refuses a PDK whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2). The full grid is one `klt sim` request (`corners` block, 5 process x
-40/27/125 C x 1.62/1.80/1.98 V, DR-002) and goes to the batch fleet; the job
id is in the record's `remote` field. It never falls back to a local grid.
`--record` refuses to overwrite an existing record (append-only); use
`--record-name record-<label>.json` for a re-run after a sizing change.
`python3 -I sim/ota-settling/make_request.py` regenerates `request.json`.

## Records

- `record.json` - issue #48, the original sizing (square-law CMFB sense, 40 uA
  tail): fails at all 45 corners. Kept unchanged.
- `record-i51-rcm2M-cff100f.json` - issue #51, resistive CMFB sense, 80 uA
  tail, ~3.9 pF + 5.5 kohm CM compensation: 45 of 45 corners pass, worst
  `err_phase` 6.8e-5.

The fleet runner has been klt 0.7.0; a newer client's submit fails with
`batch_job_failed` (exit 87) and nothing is simulated. Run with a throwaway
`uv venv` holding `klayout-tools==0.7.0` first on `PATH` until the runner is
updated; do not install it host-wide.

## Limits

Open-loop gain, GBW, PM, CMFB stability, noise, swing, Monte Carlo and
layout parasitics are not covered. Ideal switches (no charge injection, no
Ron), ideal Cs/Ci (no mismatch), no behavioural-model cross-check.

# sim/ota-gain — OTA open-loop DC-gain bench (issue #126)

**Simulated, transistor-level** (ngspice on `design/ota/ota_fd.spice`; not the
behavioural model). Question: what is the open-loop differential DC gain of
`ota_fd` at the bias it has inside the integrator, over all 45 DR-002 corners,
and which corner binds?

This is source **T** for model B's `dc_gain` (`sim/bmodel/model.py`: the
integrator amplifier DC gain `A` in V/V, which sets the leaky pole
`p = A/(A+1)`). DR-001 item 2 names "settling and finite gain (a single
integrator step and AC response)" as a transistor-level extraction, and
rejects hand calculation: before this bench, `dc_gain` was the one B parameter
with no corner record of its own.

## Why an `ac` sweep and not a `dc` one

An open-loop fully differential OTA has no stable open-loop operating point —
there is no DC sweep to read the gain off. The deck therefore separates the two
jobs with networks that are each other's dual:

- `Lfp`/`Lfn`, 1e12 H, carry the **DC** feedback (`outn`->`inp`, `outp`->`inn`,
  the pairing `integrator.sch` wires through Ci). A short at DC, so `.op`
  solves with the OTA in unity feedback: `vod` = 0, both inputs at the CMFB
  common mode, which is the summing-node potential VCM = 0.9 V the integrator
  gives them. At 1 Hz the inductor is 6.3e12 ohm against the ~1 Mohm output
  resistance, so it is gone from the swept solution.
- `Cfp`/`Cfn`, 1 F, carry the **AC** drive. Open at DC, 0.16 ohm at 1 Hz, so a
  1 V differential drive (`Vid` split antiphase by two ideal VCVSs) reaches the
  gates without touching the bias.

The gain is read at 1 Hz, the bottom of a `dec 10 1 1k` sweep. That it is the
DC asymptote and not a band value is **gated per corner**, not assumed: see
`a0_flat_rel` below.

Load is 1.8 pF per side, the `CL,eff` `design/ota/SIZING.md` derives for the
integrator and the value its own single-corner probe used. The DC gain does
not depend on the load — only the bandwidth does — so this is for
comparability, not for the number.

## Measurements (`make_request.py` -> `request.json`)

- `a0_lo`: `|vod|` at 1 Hz with a 1 V differential drive, i.e. the DC gain in
  **V/V**. The runner also records it in dB. Gated `>= 10 V/V`: a loop that
  failed to open would read about 1.
- `a0_min`, `a0_max`, `a0_flat_rel`: the band extremes and
  `(max - min)/min`. **Gated `<= 1e-2`.** This is the gate that makes the
  reading a DC gain: a rising band edge would mean the DC-feedback inductor is
  still shunting the output, a falling one that the dominant pole is inside the
  band. Observed at tt/27 C/1.80 V: 1.0e-4.
- `vid_mag`: the differential drive as solved, 1.000000000 V by construction.
  Gated to 1 +/- 1e-9 — a different value scales every gain above it.
- `acm_max`, `acm_rel`: common-mode output response to the differential drive,
  absolute and relative to `a0_lo`. **Gated `<= 1e-3`.** A purely differential
  drive should not move the output common mode; if it does, the CMFB loop is
  not holding or the feedback pairing is wrong, and `a0_lo` is not a
  differential gain.

The last three are **reference-validity** gates, not spec rows. `pass` in the
record is their verdict.

## There is no spec budget for DC gain

`spec/modulator-adc.md` §5.3 budgets **noise**, not gain, and no ratified row
gives a DC-gain limit. So this record reports the per-corner value and its
binding corner and makes **no pass/fail against the spec**.
`design/ota/SIZING.md` says the same thing from the other side: "whether
~55 dB is enough against the 80 dB target is a T-tier check, **not decided
here**". Issue #128 loads these values into model B and answers it. Relaxing
or inventing a spec row to make a result pass is not this bench's business.

## Comparison column

`sim/integrator-ci/record.json`
(`derived.dac_crosscheck.per_corner.implied_dc_gain_db`) carries an implied OTA
DC gain at the same 45 points, from the finite-gain leak of that bench's
`post_dac` variant. Its own README calls that figure "a cross-check of this
bench against an independent result, not a DC-gain extraction", and its
slow/cold outliers are contaminated by the incomplete input sampling of
**#106**. It is carried here as `integrator_ci_implied_db` /
`integrator_ci_delta_db` for comparison only: a disagreement at those corners
is **expected, and is reported rather than reconciled**.
`design/ota/SIZING.md` lines 161-168 give a single-corner probe (56.7 dB at
tt/27 C/1.80 V, explicitly not a recorded result) that this bench reproduces
to 0.05 dB.

## Running

    python3 -I sim/ota-gain/run_gain.py --probe     # 1 corner, local
    python3 -I sim/ota-gain/run_gain.py --record    # 45 corners, batch fleet

The runner refuses a PDK whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2). The full grid is one `klt sim` request (`corners` block, 5 process x
-40/27/125 C x 1.62/1.80/1.98 V, DR-002) submitted to the batch fleet with
`--wait-for-capacity 600`; the job id is in the record's `remote` and
`batch_receipt`. It never falls back to a local grid. Both record-validity
gates of `sim/settling_common.py` apply before anything is written:
`grid_complete` (all 45 points returned) and `measurements_present(key=
"a0_lo")` (every one of them actually produced a gain, so a dead fleet job
cannot become a record). `--record` refuses to overwrite an existing record
(append-only); use `--record-name record-<label>.json` after a sizing change.
`python3 -I sim/ota-gain/make_request.py` regenerates `request.json`.

Unit tests (no EDA tools):

    python3 -I -m unittest discover -s sim/ota-gain -p 'test_*.py'

## Records

- `record.json` — issue #126, first full-grid extraction (batch job
  `klt-sim-20eba6712e75`). 45/45 corners measured and all three validity gates
  pass. DC gain **52.07 dB** (`ff`/1.620 V/125 °C, the binding corner) to
  **59.73 dB** (`ss`/1.980 V/-40 °C); 56.74 dB at tt/27 °C/1.80 V, against the
  56.7 dB of `design/ota/SIZING.md`'s single-corner probe. Worst band
  flatness 1.6e-4. Agreement with the `integrator-ci` comparison column has a
  **median of 0.25 dB** across the grid, and the only large deviations are the
  slow/cold corners that bench's README already flags as contaminated by #106
  (`fs`/1.620 V/-40 °C: 53.78 dB here against 40.85 dB there, 12.93 dB; then
  `ss`/1.620 V/-40 °C at 11.61 dB). That pattern is the expected one and is
  reported, not reconciled.

## Limits

Gain-bandwidth, phase margin and CMFB loop response are not covered here
(`sim/ota-settling` and `design/ota/SIZING.md` own those). No mismatch (this is
the nominal grid, no Monte Carlo), no layout parasitics (DR-001 item 4), no
noise (`sim/integrator-noise`), no swing or distortion. The gain is read with
the output at the common mode and a small signal: gain compression over the
output swing is not measured.

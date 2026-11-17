# Characterization report (T1 item 8)

Per-spec-row performance against [`spec/modulator-adc.md`](../spec/modulator-adc.md) §1.1,
with the evidence record each verdict rests on. Everything here is **simulated**
(B = behavioural model, T = transistor-level ngspice, RTL sim = cocotb/Icarus,
synthesis = Yosys via `klt`); nothing is measured. `measurements/` holds no
silicon data.

This file is hand-assembled and is the only place a verdict is written down. It
is bound to its evidence by `attestation/item8-envelope.json`, generated and
re-checked by `attestation/item8_envelope.py` (CI: `.github/workflows/signoff.yml`).
`klt signoff --attest` does not accept item 8 in the pinned klt (0.8.0 offers
only items 1, 9 and 10), so the pin-compatible form is the bare generic
envelope that item 8 is graded on; see the CI step for what `--check` covers.

**State as of this report: item 8 is not met.** Rows listed `pending` wait on
the loop-scaling and noise work (#148, #138), Monte Carlo and post-layout
(#34, #35), the uncovered STA corners (a declared gap under DR-008,
`spec/decisions/DR-008-digital-timing-corners.md`) and DRC/LVS (#31, #32).
The item-5 tracker #33 closed 2026-11-17 on a Curator verdict of record
(item 5 analog `unmet`, digital `met`); its remaining work is owned by #148
and #138,
with Monte Carlo (#34) and post-layout (#35) out of its scope, and the
per-row mapping below carries that verdict. This report records that state;
it does not relax a spec row.

## Per-row characterization

Verdict is one of `evidenced` (the cited record covers the row as far as its
evidence column says, and passes), `partial` (a cited record covers part of the
row; the rest is named), `pending` (no record yet). A `pending` or `partial`
row names the open issue that supplies the rest. "Binding corner" is the worst
corner in the cited record, or the only one it has.

| Row | Parameter | Verdict | Binding corner | Evidence | Remaining |
|---|---|---|---|---|---|
| 1 | Signal bandwidth 20 kHz | partial | none (band is the analysis configuration every record stamps) | `sim/bmodel/item5-model-run.json` (B, rows 1 and 4, all seven DR-002 anchors; band 0-20 kHz) | T-level band evidence waits on the bench re-run (#148); post-layout: pending (#35) |
| 2 | Peak SNDR >= 80 dB | partial | ss/1.620V/125C (71.35 dB) | `sim/bmodel/item5-model-run.json`, `sim/bmodel/xcheck-record.json` (B with T-extracted corner parameters, N = 2^16) | every B number uncross-checked (DR-001 cross-check incomplete at the 1024-clock T record; the long-record cross-check leg needs a DR-001 decision-record change), all seven anchors 6.8-8.7 dB under target, parameters invalidated while #148 and #138 are open |
| 3 | 2nd-order single-bit SC modulator | partial | all seven DR-002 anchors (1024-clock transient) | `sim/modulator-tran/record.json`, `sim/bmodel/xcheck-record.json`, `sim/bmodel/model.py` | long-record T behaviour and the DR-001 in-band SNDR leg (not computable at 1024 clocks) wait on the bench re-run (#148) and the noise fix that invalidates today's parameters (#138) |
| 4 | OSR 128 | evidenced | all seven DR-002 anchors (B) | `sim/bmodel/item5-model-run.json` (rows 1 and 4) | none |
| 5 | Modulator clock 5.12 MHz | partial | all seven DR-002 anchors (1024 clock edges) | `sim/modulator-tran/record.json` (phi1_edges, bs_edges pass at every anchor) | raw klt sim report not retained, so no envelope cites it; envelope credit waits on #148 (or upstream klt row-scoped citation credit, klayout-tools issue 6027) |
| 6 | Output rate 80 kSps | evidenced | tt/27C/1.80V (RTL sim) | `verification/decimator/record.json` | none for function; corner timing evidenced at the ten declared liberty corners (`layout/digital/sta-decimator.report.json`), which DR-008 sets as the digital partition's corner set; the other 35 DR-002 points are a declared gap under DR-008, not evidenced and not closable by a further STA run |
| 7 | 16-bit two's complement word | evidenced | tt/27C/1.80V (RTL sim) | `verification/decimator/record.json` | none |
| 8 | Passband ripple <= 0.1 dB | evidenced | analytic (0.0401 dB peak-to-peak) | `verification/decimator/record.json` | none |
| 9 | Stopband >= 90 dB (alias bands), >= 75 dB (gaps) | evidenced | analytic (93.91 dB at 300 kHz alias bands, 79.20 dB at 284.5 kHz gaps) | `verification/decimator/record.json` | none |
| 10 | CIC order >= 3, then FIR | evidenced | none (structure; CIC order 4, 41-tap FIR) | `rtl/decimator.v` | none |
| 11 | Differential input <= 0.5 VREF | partial | all seven DR-002 anchors (swing measured and failing) | `sim/modulator-tran/record.json` (o1/o2_swing_pp fail the 1.39 Vpp section 5.4 bound at every anchor, worst 3.500 Vpp; #148) | swing failure recorded, not fixed (#148); raw klt sim report not retained, so no envelope cites it; envelope credit also waits on #148 (klayout-tools issue 6027 upstream) |
| 12 | Supply 1.62-1.98 V | partial | 1.62 V and 1.98 V anchors (transient ran) | `sim/modulator-tran/record.json` (seven anchors spanning the supply range; no row-12-tagged limit) | no row-12-tagged measurement in any committed envelope; the spec_row 12 tagging is deferred to the next justified re-run, owned by #148 |
| 13 | P_ana <= 1 mW, P_dig reported | partial | ff/1.980V/125C (0.5804 mW, pass) | `sim/modulator-tran/record.json` (p_ana tagged row 13, pass at all seven anchors) | raw klt sim report not retained, so no envelope cites it; envelope credit waits on #148 (klayout-tools issue 6027 upstream); P_dig and post-layout power: pending (#35) |
| 14 | DRC + LVS clean, post-layout | pending | none | none | DRC pending (#31), LVS pending (#32), post-layout pending (#35) |

### Notes on the cited records

- **Rows 1, 2, 4 (B with T-extracted corner parameters), added 2026-11-16
  (#128).** `sim/bmodel/item5-model-run.json` (the klt `model-run` envelope,
  generated by `sim/bmodel/make_item5_envelope.py`) cites seven long records,
  one per DR-002 anchor: `sim/bmodel/records/20261116T202*.json`, each N =
  65 536 output samples, Blackman-Harris 4-term window, coherent tone (1639
  cycles, 2000.73 Hz), bin bandwidth 1.2207 Hz, band 0-20 kHz with the DC and
  tone-lobe bins excluded, OSR 128, fs 5.12 MHz, 12-point amplitude sweep
  peaking at the -6 dBFS ceiling. Parameters come from
  `sim/bmodel/corners/<anchor>.json` (generated by
  `sim/bmodel/make_corners.py` from the committed T records: OTA DC gain
  `sim/ota-gain/record.json`, settling `sim/integrator-settling/record-i92.json`,
  charge injection `sim/integrator-ci/record.json`, thermal noise
  `sim/integrator-noise/record-i140.json`, comparator offset and hysteresis
  `sim/comparator-decision/record.json`; every parameter names its record and
  hash, and `ci_gain_error` and `jitter_rms_s` are declared no-T-source, not
  defaulted). Peak SNDR: 73.24 dB (sf), 73.20 (ff/-40C), 72.39 (tt), 72.39
  (ss/-40C), 72.20 (ff/125C), 71.56 (fs), 71.35 (ss/125C) — **every corner
  below the 80 dB row-2 target and every corner uncross-checked**: DR-001
  item 3's cross-check is incomplete at every anchor
  (`sim/bmodel/xcheck-record.json` — the committed T record is 1024 clocks,
  at which the in-band SNDR leg is not computable), so none of these numbers
  carries row 2 (spec section 1.2). They are recorded as the per-corner B
  results the spec asks the model to provide; the rows the envelope does
  carry are 1 and 4 (band and OSR configuration). The ideal-parameter record
  below remains the DR-001 item 1 baseline. #148 (integrator swing) and #138
  (integrator-1 thermal noise over the 5.3 budget) were open when these
  numbers were recorded at tree commit 9fa9dd8; either landing changes the
  parameters and requires a re-run of `make_corners.py`, the cross-check and
  the sweeps.
- **Row 2's cross-check (#128).** `sim/bmodel/xcheck-record.json`: model B,
  loaded with each anchor's corner parameters, run on the committed
  per-clock input sequence of the short T transient
  (`sim/modulator-tran/samples/`, 1024 clocks), integrator waveforms and
  in-band power compared per corner. In-band power agrees within 0.11 dB at
  every anchor (limit 3 dB, DR-001's tolerance verbatim); loop duty within
  0.05; integrator span within 10 % at five anchors, failing at
  ss/1.620V/125C (o1 16.9 %, o2 29.9 %) and ss/1.620V/-40C (o1 11.2 %) — the
  span failures are consistent with #106 (input sampling ~46 % incomplete at
  ss/-40C) and #148, recorded not fixed. Every corner is reported
  `incomplete` (never passed): DR-001's in-band SNDR leg is not computable at
  this record length. Sample-wise bitstream agreement is recorded but not
  gated (a single-bit loop is chaotic;
  `sim/modulator-tran/README.md`). Lengthening the T record is a DR-001
  decision-record change and is not done here.
- **Row 3 (#128 update).** The assembled modulator's transistor-level
  behaviour is now recorded beyond the tt load check:
  `sim/modulator-tran/record.json` ran the full netlist stack
  (`design/modulator/modulator.spice` with the cell netlists) at all seven
  DR-002 anchors for 1024 clocks, and `sim/bmodel/xcheck-record.json`
  compares model B against those bitstreams and integrator waveforms. Still
  partial: no long-record T transient exists, so row 2's DR-001 cross-check
  remains incomplete (the first-revisit item DR-001 itself flags).
- **Rows 5, 11, 12, 13 (T, #125 through #128).**
  `sim/modulator-tran/record.json`: ngspice, seven DR-002 anchors, 1024
  clocks each, every measurement carrying `limits` and a `spec_row` tag. Row
  5: phi1_edges 1024 of 1024 and bs_edges within limits at every anchor.
  Row 11: o1_swing_pp up to 3.500 V and o2_swing_pp up to 2.256 V against
  the 1.39 Vpp bound — failing at every anchor (#148). Row 13: p_ana worst
  0.5804 mW at ff/1.980V/125C against the 1 mW limit — passing at every
  anchor; the vcm source is reported as p_vcm and is not in the sum. Row 12:
  no row-tagged measurement. The bench's raw `klt sim` report was not
  retained (`sim/modulator-tran/.artifacts/` is gitignored), so the manifest
  declares these rows gaps with those findings in the gap reasons rather
  than citing an envelope that does not exist; re-running the bench to
  regenerate a citable report is out of scope (#125's bench). Per the #33
  verdict of record, rows 5 and 13 pass their limits at all seven anchors
  but klt 0.9.2 credits no per-row coverage from a failing envelope
  (2AMLogic/klayout-tools#6027), so they resolve when #148 lands or klt
  gains row-scoped citation credit.
- **Rows 1, 2, 4, 11 (B, ideal parameters).**
  `sim/bmodel/records/20261113T142853Z-f8b2fa44.json`:
  source B, ideal parameters (no finite gain, settling, charge injection, kT/C
  noise or comparator offset), uncross-checked against transistor level. Record
  65 536 output samples, Blackman-Harris 4-term window, coherent tone (1639
  cycles, 2000.73 Hz), bin bandwidth 1.2207 Hz, band 0-20 kHz with the DC bins
  0-4 and tone-lobe bins 1635-1643 excluded, OSR 128, fs 5.12 MHz, input
  -6 dBFS. Peak SNDR **86.17 dB** (simulated), at the top of the amplitude
  sweep. That is a quantization-limited ideal-model number, not a claim that
  row 2 is met: DR-001 and spec §1.2 require the T-extracted non-idealities and
  the cross-check at every DR-002 corner.

  **Supersedes 89.19 dB** from `sim/bmodel/records/20261023T172440Z-f8b2fa44.json`
  (kept as evidence, not cited as a result). `sim/bmodel/sndr.py` multiplied the
  lobe-summed signal-to-noise ratio by the window's equivalent noise bandwidth,
  so every behavioural-model SNDR read 10*log10(2.004) = 3.02 dB high; issue
  #107 removed the factor. The parameters are unchanged (same `params_sha256`
  `f8b2fa44...`) — only the estimator moved. Margin to the 80 dB target of
  row 2 is correspondingly 3.02 dB smaller than previously recorded wherever B
  is cited. The corrected figure sits 8.03 dB below the spec §5.1 ideal
  quantization-noise ceiling of 94.2 dB; that gap is unexplained and tracked in
  #108.
- **Rows 5, 12 (T, OTA settling bound).** `sim/ota-settling/record-i51-rcm2M-cff100f.json`: ngspice,
  `design/ota/ota_fd`, DR-002 full grid (45 corners), 45 of 45 pass
  `err_phase <= 1e-4`, worst 6.84e-05 at sf/1.620V/125C. The bench uses ideal
  reset switches and ideal Cs/Ci, so it bounds the OTA step only, not the
  integrator cell, the comparator or the clock generator. Its predecessor
  `sim/ota-settling/record.json` failed 45 of 45 for the previous sizing and is
  kept as evidence, not cited as a result.
- **Rows 6-9 (RTL sim).** `verification/decimator/record.json`: cocotb/Icarus,
  8 testcases, 0 failed, at the single corner the RTL simulation has (functional,
  no timing). The row 8 and 9 figures are analytic from the quantized
  coefficients (`verification/decimator/response.py`), 50 Hz grid. Row 9 is
  graded on the two lines DR-006 (`spec/decisions/DR-006-decimation-stopband-reading.md`)
  ratified: at least 90 dB in the alias bands `k·fout ± BW` (worst 93.91 dB at
  300 kHz) and at least 75 dB elsewhere from fout - BW to fs/2 (worst 79.20 dB
  at 284.5 kHz). `response.py` gates and reports both lines, and both pass on
  the cited record.
- **Row 3.** The structure matches model B (`design/modulator/README.md`). The
  only transistor-level run of the assembled netlist is a load and phase check
  at tt/27C/1.80V that writes no record and makes no SNDR claim
  (`sim/modulator-load-check/README.md`).

## Decimator Fmax, area and power (digital partition)

Spec §2 corners (DR-002): 45 points, process {tt, ss, ff, sf, fs} x
temperature {-40, 27, 125 C} x supply {1.62, 1.80, 1.98 V}. The standard-cell
library is `sky130_fd_sc_hd`.

| Quantity | Value | Corner | Evidence | Status |
|---|---|---|---|---|
| Cell area (synthesized) | 49 062.05 um^2, 5 390 instances | corner-independent (cell areas) | `verification/decimator/record.json` | evidenced (synthesis) |
| Placed die / core area | 129 758 um^2 die, 121 877 um^2 core, 42.4 % utilization | corner-independent | `layout/README.md`, `layout/digital/decimator.gds` | evidenced (place-and-route) |
| Fmax at the ten declared `sky130_fd_sc_hd` liberty corners | 26.69 MHz worst, 109.79 MHz best; every declared corner clears the 5.12 MHz clock | ss/-40C/1.60V binds (setup slack 157.838 ns of the 195.3125 ns period) | `layout/digital/sta-decimator.report.json` | evidenced (STA on the routed DEF; propagated clock, no SPEF) |
| Fmax at the other 35 DR-002 corners | none | the sf, fs, 1.98 V, 125 C and 27 C points | none | declared-gap per `spec/decisions/DR-008-digital-timing-corners.md`: the pinned PDK ships no liberty file for these points, so no STA run can close it. Not evidenced, and outside the digital partition's corner set per that record; it reopens only if a PDK pin bump brings new liberty files |
| Power at each of the 45 corners | none | all 45 | none | pending (#35) |

- **Fmax.** `klt sta` (0.8.0, OpenROAD `26Q3-1510-g6cb3f2b704`) on the committed
  routed DEF, one fixed geometry characterized at ten corners in one request
  (`layout/digital/sta_request.json`, `pdk.corners`), clock `clk` at 195.3125 ns
  (fs = 5.12 MHz, spec row 5). Every corner reports
  `timing_status: "constrained"` with non-negative setup and hold slack and zero
  setup/hold violations; worst setup is 157.838 ns at `ss_n40C_1v60`
  (Fmax 26.69 MHz), worst hold 0.2698 ns at `ff_n40C_1v95`. The Fmax figures are
  OpenSTA's extrapolated `1/(T - WNS)`, not a bisected search. The clock is
  **propagated** (`clock_mode: "propagated"`, `constraints.propagated_clock: true`),
  so the DEF's own clock tree carries insertion delay into both the launch and the
  capture edge: the per-corner `clock_propagation` block reports worst network
  latency from 0.3204 ns at `ff_n40C_1v95` to 0.9745 ns at `ss_n40C_1v60`. The
  superseded ideal-clock run of the same DEF gave worst setup 157.898 ns
  (Fmax 26.73 MHz) and worst hold 0.2586 ns — propagation costs setup and earns
  hold, and the verdict is unchanged. There is no SPEF: routed-DEF timing with no
  extracted wire parasitics, so the insertion delay above is estimated from the
  DEF's interconnect rather than extracted; parasitic-annotated timing is #35.
  Every corner reports
  `constraint_completeness: "incomplete"` — 17 unconstrained endpoints
  (`dout[15:0]`, `dout_valid`), because no block-boundary I/O delay budget is
  declared, so this is register-to-register timing only. DR-008
  (`spec/decisions/DR-008-digital-timing-corners.md`) assigns that budget to the
  assembled top (#122), so `incomplete` is the expected value for the standalone
  block rather than a defect; the same record sets the ten declared corners as
  the digital partition's corner set and declares the other 35 DR-002 points a
  gap no further run can close. The router's
  max-transition and max-capacitance violations against the library limits
  reappear here at one corner only, `ss_n40C_1v60` (660 max-transition, 7
  max-capacitance); they are electrical-rule violations, not slack violations,
  and they are not addressed by this item.
- **Power.** No power analysis exists. P_dig is reported separately from P_ana
  (spec row 13), never summed into it. Post-layout activity-based power is
  covered by #35.
- **Area.** Synthesized cell area is the Yosys figure at `tt_025C_1v80`; cell
  area does not depend on the corner. The placed figures are from the routed
  flow of `layout/digital/`, not a signoff extraction.

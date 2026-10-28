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
the corner, Monte Carlo and post-layout work (#33, #34, #35) or on the row 9
reading (#18). This report records that state; it does not relax a spec row.

## Per-row characterization

Verdict is one of `evidenced` (the cited record covers the row as far as its
evidence column says, and passes), `partial` (a cited record covers part of the
row; the rest is named), `pending` (no record yet). A `pending` or `partial`
row names the open issue that supplies the rest. "Binding corner" is the worst
corner in the cited record, or the only one it has.

| Row | Parameter | Verdict | Binding corner | Evidence | Remaining |
|---|---|---|---|---|---|
| 1 | Signal bandwidth 20 kHz | partial | none (ideal B parameters) | `sim/bmodel/records/20261023T172440Z-f8b2fa44.json` (B; band 0-20 kHz) | T-level and post-layout: pending (#33) |
| 2 | Peak SNDR >= 80 dB | partial | none (ideal B parameters) | `sim/bmodel/records/20261023T172440Z-f8b2fa44.json` | cross-check, T-extracted non-idealities, corners: pending (#33) |
| 3 | 2nd-order single-bit SC modulator | partial | tt/27C/1.80V (load check only) | `design/modulator/modulator.spice`, `sim/bmodel/model.py` | transistor-level behaviour of the assembled modulator: pending (#33) |
| 4 | OSR 128 | evidenced | none (arithmetic and B config) | `sim/bmodel/records/20261023T172440Z-f8b2fa44.json` | none |
| 5 | Modulator clock 5.12 MHz | partial | sf/1.62V/125C (OTA only) | `sim/ota-settling/record-i51-rcm2M-cff100f.json` | integrator-cell and comparator-decision settling over the grid: pending (#33) |
| 6 | Output rate 80 kSps | evidenced | tt/27C/1.80V (RTL sim) | `verification/decimator/record.json` | none for function; corner timing: pending (#33) |
| 7 | 16-bit two's complement word | evidenced | tt/27C/1.80V (RTL sim) | `verification/decimator/record.json` | none |
| 8 | Passband ripple <= 0.1 dB | evidenced | analytic (0.0401 dB peak-to-peak) | `verification/decimator/record.json` | none |
| 9 | Stopband >= 90 dB | partial | analytic (93.91 dB at 300 kHz, alias-band reading) | `verification/decimator/record.json` | row reading unconfirmed: pending (#18) |
| 10 | CIC order >= 3, then FIR | evidenced | none (structure; CIC order 4, 41-tap FIR) | `rtl/decimator.v` | none |
| 11 | Differential input <= 0.5 VREF | partial | none (ideal B parameters, -6 dBFS) | `sim/bmodel/records/20261023T172440Z-f8b2fa44.json` | T-level swing over corners: pending (#33) |
| 12 | Supply 1.62-1.98 V | partial | sf/1.62V/125C (OTA only) | `sim/ota-settling/record-i51-rcm2M-cff100f.json` | assembled modulator and decimator over the supply range: pending (#33) |
| 13 | P_ana <= 1 mW, P_dig reported | pending | none | none | no block power record: pending (#33) |
| 14 | DRC + LVS clean, post-layout | pending | none | none | DRC pending (#31), LVS pending (#32), post-layout pending (#35) |

### Notes on the cited records

- **Rows 1, 2, 4, 11 (B).** `sim/bmodel/records/20261023T172440Z-f8b2fa44.json`:
  source B, ideal parameters (no finite gain, settling, charge injection, kT/C
  noise or comparator offset), uncross-checked against transistor level. Record
  65 536 output samples, Blackman-Harris 4-term window, coherent tone (1639
  cycles, 2000.73 Hz), bin bandwidth 1.2207 Hz, band 0-20 kHz with the DC bins
  0-4 and tone-lobe bins 1635-1643 excluded, OSR 128, fs 5.12 MHz, input
  -6 dBFS. Peak SNDR 89.19 dB, at the top of the amplitude sweep. That is a
  quantization-limited ideal-model number, not a claim that row 2 is met: DR-001
  and spec §1.2 require the T-extracted non-idealities and the cross-check at
  every DR-002 corner.
- **Rows 5, 12 (T).** `sim/ota-settling/record-i51-rcm2M-cff100f.json`: ngspice,
  `design/ota/ota_fd`, DR-002 full grid (45 corners), 45 of 45 pass
  `err_phase <= 1e-4`, worst 6.84e-05 at sf/1.620V/125C. The bench uses ideal
  reset switches and ideal Cs/Ci, so it bounds the OTA step only, not the
  integrator cell, the comparator or the clock generator. Its predecessor
  `sim/ota-settling/record.json` failed 45 of 45 for the previous sizing and is
  kept as evidence, not cited as a result.
- **Rows 6-9 (RTL sim).** `verification/decimator/record.json`: cocotb/Icarus,
  8 testcases, 0 failed, at the single corner the RTL simulation has (functional,
  no timing). The row 8 and 9 figures are analytic from the quantized
  coefficients (`verification/decimator/response.py`), 50 Hz grid. Row 9 uses the
  alias-band reading; the literal reading (every frequency from fout - BW to
  fs/2) is reported by `response.py` and not gated. Which reading is the spec's
  is #18.
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
| Fmax at each of the 45 corners | none | all 45 | none | pending (#33) |
| Power at each of the 45 corners | none | all 45 | none | pending (#33) |

- **Fmax.** No static timing analysis has been run, so no Fmax is claimed at any
  corner. The routed design is clocked at 195.3125 ns (fs = 5.12 MHz,
  `layout/digital/pnr_request.json`); the router reports max-transition and
  max-capacitance violations against the library limits, concentrated in the slow
  corners (`layout/README.md`), and those are unaddressed. Timing closure is
  #33's decimator STA.
- **Power.** No power analysis exists. P_dig is reported separately from P_ana
  (spec row 13), never summed into it. Post-layout activity-based power is
  covered by #35.
- **Area.** Synthesized cell area is the Yosys figure at `tt_025C_1v80`; cell
  area does not depend on the corner. The placed figures are from the routed
  flow of `layout/digital/`, not a signoff extraction.

# ota_fd — sizing trace

Fully-differential folded-cascode OTA with continuous-time CMFB (resistive
common-mode sense), 1.8 V core devices only. Schematic `ota_fd.sch`, symbol `ota_fd.sym`, netlist
`ota_fd.spice` (`klt netlist --block`; `--check` gates drift). Ports:
`vdda vssa inp inn outp outn vcm ibias`.

**Labelling.** *spec* = a ratified row/section; *DR-n* = a decision record;
*hand-calc* = arithmetic here, not simulated. The only simulation is the
single-point operating-point **smoke check** in `sim/ota-op-smoke/` (tt, 27 C,
1.8 V), which shows the bias point is sane, and the 45-corner step-settling
record in `sim/ota-settling/` (below). Both are *simulated*, never measured.
The smoke check is not a gain, GBW, PSRR, swing or noise result, and no Monte
Carlo has been run. "Probe" numbers (single-corner `ngspice` runs used while
sizing) are design aids, not recorded evidence. Everything marked "not
simulated" below is owed to later T-tier evidence.
`sky130-opamp` numbers are sanity bounds only (DR-003).

## Boundary inputs (DR-005)

| Input | Value | Source |
|---|---|---|
| `VCM` (inputs, `vcm` pin) | 0.9 V | DR-005 |
| `ibias` into `MB1` | 5 uA, +/-10 % assumed | DR-005 |
| Supply `vdda` | 1.8 V (+/-10 %) | spec row 12 |

## Requirement trace to the 97.7 ns phase (hand-calc, not simulated)

- Phase: `1 / (2 * 5.12 MHz)` = 97.66 ns (spec row 5).
- `Cs` = 1 pF planning value (spec §5.3); model coefficient C1 = C2 = 0.5
  (`sim/bmodel/model.py:41-42`) gives `Ci` = `Cs` / 0.5 = 2 pF.
- Input parasitic at the summing node: `M1` gate, 2/3 * W * L * Cox with
  Cox ~ 8.4 fF/um2 (hand-calc) = 22 fF, plus overlap ~ 10 fF: `Cp` ~ 0.035 pF.
- Feedback factor in the integrate phase:
  `beta = Ci / (Ci + Cs + Cp)` = 2 / 3.035 = 0.66.
- Effective load per side: next-stage `Cs` 1 pF plus the series
  `Ci * (Cs + Cp) / (Ci + Cs + Cp)` = 0.68 pF plus ~0.1 pF output parasitics:
  `CL,eff` ~ 1.8 pF.
- Settling target: 0.01 % (the starting level DR-005 uses for the reference
  node) needs ln(1e4) = 9.2 time constants, so `tau <= 97.7 / 9.2` = 10.6 ns.
  `tau = CL,eff / (beta * gm)` gives `gm >= 1.8 pF / (0.66 * 10.6 ns)` =
  **257 uS**.
- Initial choice (before the settling record): `Iin` = 18-20 uA per input
  device at gm/Id ~ 15 gives gm ~ 270-300 uS (hand-calc from a single-device
  gm/Id probe); at 300 uS: tau = 9 ns, 10.8 tau in 97.7 ns, linear settling
  error ~ 2e-5. That linear-only estimate omitted slew; the settling record
  (below) is what sized the final currents. Current design: `Iin` = ~36 uA
  (smoke OP) per input device, `gm(M1)` ~ 631 uS.
- **Step settling / slew: simulated, PASSES at all 45 corners.**
  `sim/ota-settling/record-i51-rcm2M-cff100f.json` (transistor-level,
  ngspice, DR-002 full grid as one `klt sim` request on the batch fleet, job
  `klt-sim-3d1c5abb801b`; see its `notes` for the fleet caveats): with the
  0.45 V per-side worst-case step in the closed-loop integrate configuration
  above, the residual error 97.66 ns after the step is at most 6.8e-5
  (`sf`, 1.62 V, 125 C; target 1e-4) and 8.8e-9 at best; the output reaches
  within 0.2 to 1.0 % of the ideal final step (`step_err_vs_ideal`, finite DC
  gain). The failing record it replaces as the open item is kept:
  `sim/ota-settling/record.json` (0.5 to 1.3 of the step left at every corner).
  What changed, and why (causes were first seen in single-corner probes):
  1. *CM sense made linear.* The square-law `MCS1`/`MCS2` pair turned a large
     differential swing into a common-mode error and the CM ran away. `MCS`
     (2x one old sense device) now senses `cmx`, the average of `outp`/`outn`
     through `Rcm1`/`Rcm2`.
  2. *Slew.* In a folded cascode each side slews at about `Itail / 2 / CL,eff`
     (up-going side limited by `Ip - Ibottom`, down-going by `Ibottom - (Ip - Itail)`;
     the two sum to `Itail`). The old 40 uA tail and 20 uA branches gave
     ~10 V/us per side against ~0.78 V of travel (0.45 V ideal plus the
     step's capacitive feedthrough, which sends the outputs ~0.65 V the wrong
     way first). The tail is now 80 uA (`MT` x16, `M1`/`M2` W 16), top sources
     80 uA (`MP` x8), bottom sinks 40 uA (`MN` x8) with cascodes at 40 uA, so
     each side slews at ~20 V/us and the step is linear by ~60 ns.
  3. *CM-loop compensation.* See "CMFB sense and stability" below.
  The small-step case still settles as before; the sizing intent
  (gm >= 257 uS, `beta` = 0.66) is met with margin: the smoke check reports
  `gm(M1)` ~ 631 uS (bias-point number, not a GBW claim).

## Swing vs spec §5.4 (hand-calc from the smoke-check bias point)

At the smoke operating point the output cascodes have Vds margins
(Vds - Vdsat) of about 0.57 V (PMOS) and 0.64 V (NMOS), so each output sits
inside roughly 0.26 V to 1.47 V: about +/-0.57 V around 0.9 V per side,
~2.3 V peak-to-peak differential of static headroom. That comfortably exceeds
the ~1.39 Vpp `sky130-opamp` figure §5.4 compares against, but it is headroom
read from one bias point, **not a simulated swing or gain-compression
result**.

## Power (from the smoke check; sanity only)

`I(vdda)` ~ 172 uA (incl. the 5 uA `ibias`) = ~310 uW per OTA at tt, 27 C,
1.8 V; two integrators ~ 0.62 mW of the 1 mW `P_ana` row (spec row 13, not
relaxed). That leaves ~0.38 mW for the comparator, clocking and anything else
analog. The earlier 100 uA (181 uW) sizing did not close settling; the extra
current is the tail doubling and the 2x branch currents above (the CMFB and
bias legs are unchanged, ~25 uA of the total). The smoke-check `I(vdda)` band
was edited from 50-150 uA to 100-250 uA for this reason (recorded in
`sim/ota-op-smoke/run_op.py`). Corner power (ff / 1.98 V will be highest):
**not simulated**. If the comparator and clocking budget cannot fit in the
remaining ~0.38 mW at the worst corner, that is a PO-level decision (spec row
13 needs a decision record to change), not something this sizing settles.

## Device sizes

All `L` and `W` in um; `W` is per finger, `nf` = 1. Currents are the design
intent from the ratios; "OP" is the smoke-check value.

| Device | W / L x mult | Role | Source of size |
|---|---|---|---|
| `MB1` | 2 / 0.5 x 1 | bias diode, 5 uA | unit device; ibias DR-005; density from gm/Id probe (hand-calc) |
| `MT` | 2 / 0.5 x 16 | input tail, 16 x 5 = 80 uA (OP 72) | mirror ratio of `MB1`; tail sets slew, `Itail/2/CL,eff` per side (settling record) |
| `M1`, `M2` | 16 / 0.5 x 1 | input pair, ~40 uA each (OP 36) | doubled with the tail to keep gm/Id (gm(M1) OP 631 uS, trace needs >= 257 uS); L = 0.5 for gm/Id and Cp. Cp is hand-calc'd as 35 fF for W = 8; W = 16 puts it near 70 fF (not re-run in the bench, which keeps 35 fF) |
| `MN1`, `MN2` | 2 / 0.5 x 8 | bottom sinks, 40 uA (OP 35.6) | 8 x `MB1`; branch current sets the slew (settling record) |
| `MNC1`, `MNC2` | 7 / 0.5 x 2 | NMOS cascodes, 40 uA | scaled with the branch current, same bias leg C (OP margin 0.64 V) |
| `MP1`, `MP2` | 10 / 0.5 x 8 | top sources, 80 uA, gate = `cr` (OP 71.8) | `Ip` = `Itail` for full steering; 16 x `MCPS`, so the CMFB mirror still lands near the needed Vsg (OP `cr` ~ 0.73 V) |
| `MPC1`, `MPC2` | 10 / 0.5 x 4 | PMOS cascodes, 40 uA | PMOS density from a pfet probe (hand-calc), scaled with the branch (OP margin 0.57 V) |
| `MBP1`, `MBN1` | 5 / 0.5, 2 / 0.5 | bias leg B: PMOS diode `vbpd`, 5 uA | 1 x `MB1` current (hand-calc) |
| `MBP2`, `MBCN` | 5 / 0.5; 0.42 / 1.0 | leg C: `vcn` from a narrow diode | W/L ~ 1/4 of the cascode, so Vds(`MN`) ~ Vdsat + margin (hand-calc; tuned against OP margins) |
| `MBCP`, `MBN2` | 0.42 / 0.6; 2 / 0.5 | leg D: `vcp` from a narrow PMOS diode | same rule for the PMOS side (hand-calc; tuned against OP margins) |
| `MCS` | 2 / 0.5 x 2 | CMFB sense, gate `cmx` | one device equal to `MCR`, balance at `cmx` = `vcm`; replaces the old `MCS1`/`MCS2` pair (see below) |
| `Rcm1`, `Rcm2` | `res_xhigh_po_0p35` L = 350 | `outp`/`outn` to `cmx`, ~2 Mohm each | CM average onto a gate-only node (no DC current); L from a one-point resistance probe, 5.7 kohm/um (hand-calc) |
| `Cff1`, `Cff2` | `cap_mim_m3_1` 7.07 x 7.07 | across each `Rcm`, ~100 fF | keeps the sense wideband so `Rcm` x gate cap is not a pole inside the CM loop (see below) |
| `MCR` | 2 / 0.5 x 2 | CMFB reference, gate `vcm` | 2 x one sense device, balance at output CM = `vcm` (hand-calc) |
| `MCT` | 2 / 0.5 x 2 | CMFB tail, 10 uA | 2 x `MB1` (hand-calc) |
| `MCPS`, `MCPR` | 5 / 0.5 x 1 | CMFB mirror load | 1:1 mirror (hand-calc) |
| `Rz` | `res_high_po_0p35` L = 4.5 | in series with `Ccm`, ~5.5 kohm | LHP zero for CM-loop phase margin (AC probe sweep, below; resistance from a one-point probe) |
| `Ccm` | `cap_mim_m3_1` 44.2 x 44.2 | `cr` to `vdda` via `Rz`, ~3.9 pF | CM-loop compensation. 0.5 pF (the old value) and 1-2 pF were unstable or ringing in transient probes; ~4 pF is ~7.7 x the old cell area (~1950 um2 at ~2 fF/um2, hand-calc) |

## CMFB sense and stability (simulated probes; hand-calc where stated)

*Why not widen the old sense pair.* `MCS1`/`MCS2` (gates on `outp`/`outn`)
sensed `outp + outn` through a square law; a differential swing therefore
looked like a common-mode shift. Resizing cannot remove that (the error does
not depend on W/L), so the sense was made linear: `Rcm1`/`Rcm2` average the
outputs onto `cmx`, which drives one sense device equal to `MCR`.

*Gain budget (single-corner AC probe, not a recorded result).* The resistors
load each output for the differential signal, since `cmx` is a virtual
ground there. Open-loop differential gain at 100 Hz into 1.8 pF per side:

| Case | A0 (dB) | GBW (MHz) |
|---|---|---|
| old sizing, gate sense (probe) | 62.4 | 25 |
| `Rcm` = 200 kohm each (probe) | 40.9 | 52 |
| `Rcm` = 1 Mohm each (probe) | 52.8 | 52 |
| **final, `Rcm` = 2 Mohm, tt / 27 C / 1.8 V** (probe) | **56.7** | 49 |
| final, ss / 125 C / 1.62 V (probe) | 54.8 | 39 |

So the resistive sense costs ~6 dB of DC gain against the old sizing (the
higher branch currents and the cascode output resistance give back part of
it). 200 kohm would have cost ~21 dB and a 1.4 % static step error; 2 Mohm
was chosen as the largest value that still gives CM-loop phase margin (next
paragraph) with a practical resistor length. The modulator behavioural model
carries `dc_gain` (`sim/bmodel/model.py`); whether ~55 dB is enough against
the 80 dB target is a T-tier check, **not decided here**.

*CM-loop stability (AC probe with the loop broken at `cr`, not a recorded
result).* The loop has ~105 dB of DC gain (output node and `cr` node both near
integrators), so it needs a zero. The probe sweep, fs / -40 C / 1.98 V (the
tightest corner) unless noted:

| Change | Phase margin |
|---|---|
| `Ccm` 0.5 pF, no `Rz`, `Rcm` = 200 kohm (tt) | negative (transient oscillates) |
| `Ccm` 3.9 pF, `Rz` 5.5 kohm, `Rcm` = 200 kohm | ~30 deg |
| same with `Rz` ~ 8.6 kohm | ~2 deg (HF loop gain stays above 0 dB) |
| `Rcm` = 1 Mohm, no `Cff` | negative (sense pole `Rcm` x gate cap) |
| `Rcm` = 1 Mohm + `Cff` 100 fF | ~56 deg |
| **final: `Rcm` = 2 Mohm, `Cff` 100 fF, `Ccm` 3.9 pF, `Rz` 5.5 kohm** | **~56 to 61 deg** (tt, ss/125 C/1.62 V, fs/-40 C/1.98 V, ff/-40 C/1.98 V; fu 20 to 30 MHz) |

The first full-grid attempt (`Rcm` = 200 kohm, no `Cff`; 41 of 45 points
passed, the four failures were -40 C corners at 1.2e-4 to 1.8e-4 from CM
ringing) is why `Cff` and the larger `Rcm` exist. That intermediate run is not
kept as a record: it was a different netlist from the one committed here.
CMFB stability as a recorded multi-corner result (loop-gain sweep, step into
the CM) is still owed.

## Smoke-check result (what it does and does not say)

`python3 -I sim/ota-op-smoke/run_op.py` (record in `sim/ota-op-smoke/record.json`,
regenerated for the current netlist): output common mode 0.8998 V at `VCM` =
0.9 V with zero differential input (the CMFB loop finds the DR-005 common
mode), all 23 transistors in saturation (smallest Vds - Vdsat margin 64 mV,
on `MN1`/`MN2`; 82 mV on `MP1`/`MP2`), `I(vdda)` 172.4 uA. That is the whole
claim: a sane bias point at one corner.

## Not simulated (owed)

Recorded open-loop gain and GBW (the table above is probe-only), phase margin
of the amplifier, CMFB loop stability and gain as a recorded multi-corner
result, PSRR, CMRR, input offset, noise (amplifier share of the §5.3 thermal
budget), output swing and gain compression, corner power, Monte Carlo, layout
and parasitics (including the resistor and capacitor parasitics of `Rcm`,
`Cff`, `Rz`, `Ccm`). The step-settling bench uses ideal switches, ideal
Cs/Ci and a fixed 35 fF summing-node parasitic; it does not include the
larger `M1`/`M2` gate capacitance or a behavioural-model cross-check.

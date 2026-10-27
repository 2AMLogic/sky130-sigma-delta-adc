# ota_fd — sizing trace

Fully-differential folded-cascode OTA with continuous-time CMFB, 1.8 V core
devices only. Schematic `ota_fd.sch`, symbol `ota_fd.sym`, netlist
`ota_fd.spice` (`klt netlist --block`; `--check` gates drift). Ports:
`vdda vssa inp inn outp outn vcm ibias`.

**Labelling.** *spec* = a ratified row/section; *DR-n* = a decision record;
*hand-calc* = arithmetic here, not simulated. The only simulation is the
single-point operating-point **smoke check** in `sim/ota-op-smoke/` (tt, 27 C,
1.8 V): it shows the bias point is sane. It is not a gain, GBW, PSRR, swing,
noise or settling result, and no corner or Monte Carlo has been run.
Everything marked "not simulated" below is owed to later T-tier evidence.
Step settling/slew is simulated and failing: `sim/ota-settling/`.
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
- Choice: `Iin` = 18-20 uA per input device at gm/Id ~ 15 gives
  gm ~ 270-300 uS (hand-calc from a single-device gm/Id probe). The smoke
  check reports `gm(M1)` ~ 302 uS at its operating point; that is a bias-point
  number, not a GBW claim. At 300 uS: tau = 9 ns, 10.8 tau in 97.7 ns,
  linear settling error ~ 2e-5. **Not simulated.**
- **Step settling / slew: simulated, FAILS at all 45 corners.**
  `sim/ota-settling/record.json` (transistor-level, ngspice, DR-002 full
  grid, batch job `klt-sim-a81ff92498fc`; see its `notes` for the fleet
  caveats): with the 0.45 V per-side worst-case step in the closed-loop
  integrate configuration above, the residual error 97.66 ns after the step
  is 0.5 to 1.3 of the step at every point (target 1e-4), and the output does
  not reach the ideal final step (`step_err_vs_ideal` 0.17 to 0.47). Two
  causes seen in single-corner (tt, 27 C, 1.8 V) probes, not recorded
  evidence: (1) the CMFB sense pair (`MCS1`/`MCS2` on the outputs) is
  square-law, so a large differential output swing reads as a common-mode
  shift; `cr` rises, the top sources starve, the fold nodes collapse and the
  common mode runs away. (2) With the CM sensed linearly (scratch probe:
  500 k resistors), slewing is ~10 V/us per side as the hand-calc said, but
  the step's instantaneous capacitive feedthrough moves the outputs ~0.65 V
  the wrong way first, so each side travels ~0.78 V, not 0.45 V, and the
  phase still does not close (error ~1e-2). The sizing needs a CMFB sensing
  change plus more bottom/top current; that is not done here (follow-up).
  The small-step case (50 mV per side) does settle (error ~1.4e-4 at 97.66 ns).

## Swing vs spec §5.4 (hand-calc from the smoke-check bias point)

At the smoke operating point the output cascodes have Vds margins
(Vds - Vdsat) of about 0.57 V (PMOS) and 0.64 V (NMOS), so each output sits
inside roughly 0.26 V to 1.47 V: about +/-0.57 V around 0.9 V per side,
~2.3 V peak-to-peak differential of static headroom. That comfortably exceeds
the ~1.39 Vpp `sky130-opamp` figure §5.4 compares against, but it is headroom
read from one bias point, **not a simulated swing or gain-compression
result**.

## Power (from the smoke check; sanity only)

`I(vdda)` ~ 100 uA (incl. the 5 uA `ibias`) = ~181 uW per OTA; two integrators
~ 0.36 mW of the 1 mW `P_ana` row. `sky130-opamp` quiescent 117 uW (DR-003)
is the sanity bound for a single-ended two-stage; this block is larger by
design (CMFB + bias legs). Corner power: not simulated.

## Device sizes

All `L` and `W` in um; `W` is per finger, `nf` = 1. Currents are the design
intent from the ratios; "OP" is the smoke-check value.

| Device | W / L x mult | Role | Source of size |
|---|---|---|---|
| `MB1` | 2 / 0.5 x 1 | bias diode, 5 uA | unit device; ibias DR-005; density from gm/Id probe (hand-calc) |
| `MT` | 2 / 0.5 x 8 | input tail, 8 x 5 = 40 uA (OP 36) | mirror ratio of `MB1` (hand-calc) |
| `M1`, `M2` | 8 / 0.5 x 1 | input pair, ~20 uA each (OP 18) | gm >= 257 uS trace above (hand-calc); L = 0.5 for gm/Id and Cp |
| `MN1`, `MN2` | 2 / 0.5 x 4 | bottom sinks, 20 uA (OP 17.8) | 4 x `MB1` (hand-calc) |
| `MNC1`, `MNC2` | 7 / 0.5 x 1 | NMOS cascodes | same current density as `M1` (hand-calc) |
| `MP1`, `MP2` | 10 / 0.5 x 4 | top sources, 40 uA, gate = `cr` (OP 35.8) | 8 x `MCPS`, so the CMFB mirror lands near the needed Vsg (hand-calc) |
| `MPC1`, `MPC2` | 10 / 0.5 x 2 | PMOS cascodes, 20 uA | PMOS density from a pfet probe (hand-calc) |
| `MBP1`, `MBN1` | 5 / 0.5, 2 / 0.5 | bias leg B: PMOS diode `vbpd`, 5 uA | 1 x `MB1` current (hand-calc) |
| `MBP2`, `MBCN` | 5 / 0.5; 0.42 / 1.0 | leg C: `vcn` from a narrow diode | W/L ~ 1/4 of the cascode, so Vds(`MN`) ~ Vdsat + margin (hand-calc; tuned against OP margins) |
| `MBCP`, `MBN2` | 0.42 / 0.6; 2 / 0.5 | leg D: `vcp` from a narrow PMOS diode | same rule for the PMOS side (hand-calc; tuned against OP margins) |
| `MCS1`, `MCS2` | 2 / 0.5 x 1 | CMFB sense, gates `outp`/`outn` | half the reference device each (hand-calc) |
| `MCR` | 2 / 0.5 x 2 | CMFB reference, gate `vcm` | 2 x one sense device, balance at output CM = `vcm` (hand-calc) |
| `MCT` | 2 / 0.5 x 2 | CMFB tail, 10 uA | 2 x `MB1` (hand-calc) |
| `MCPS`, `MCPR` | 5 / 0.5 x 1 | CMFB mirror load | 1:1 mirror (hand-calc) |
| `Ccm` | `cap_mim_m3_1` 15.62 x 15.62 | `cr` to `vdda`, ~0.5 pF | dominant-pole choice for the CMFB loop, same cell size `sky130-opamp` uses for 0.5 pF (hand-calc) |

## Smoke-check result (what it does and does not say)

`python3 -I sim/ota-op-smoke/run_op.py` (record in `sim/ota-op-smoke/record.json`):
output common mode 0.8998 V at `VCM` = 0.9 V with zero differential input
(the CMFB loop finds the DR-005 common mode), all 24 transistors in
saturation (smallest Vds - Vdsat margin 64 mV, on `MN1`/`MN2`), `I(vdda)`
100.5 uA. That is the whole claim: a sane bias point at one corner.

## Not simulated (owed)

Open-loop gain, GBW, phase margin, CMFB loop stability and gain, PSRR, CMRR,
input offset, noise (amplifier share of the §5.3 thermal budget), a step
settling result that closes (the 45-corner record fails), output swing and gain compression, corners, Monte Carlo,
layout and parasitics.

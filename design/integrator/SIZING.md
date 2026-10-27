# integrator — sizing trace

Fully-differential switched-capacitor integrator with a 1-bit feedback DAC.
Schematic `integrator.sch`, symbol `integrator.sym`, netlist `integrator.spice`
(`klt netlist --block`; `--check` gates drift). It instantiates the OTA symbol
`design/ota/ota_fd.sym`, whose netlist is `design/ota/ota_fd.spice` and is
`.include`d separately (the OTA symbol is `type=primitive` so the integrator
netlist does not descend into, or redefine, the OTA). One cell serves both
integrators: model B uses C1 = C2 = 0.5.

Ports: `vdda vssa vinp vinn voutp voutn vrefp vrefn vcm ibias phi1 phi1b phi1e
phi2 dp dn`.

**Labelling.** *spec* = a ratified row/section; *DR-n* = a decision record;
*model B* = `sim/bmodel/model.py`; *hand-calc* = arithmetic here, not
simulated; *probe* = one DC small-signal point (10 mV drop) in ngspice at `tt`,
27 C, 1.8 V, bulk at ground, no corners or Monte Carlo. The only simulations
behind this block are those probes and `sim/integrator-load-check/` (switch
states and polarity wiring, DC). No settling, noise, charge-injection, gain or
SNDR result exists yet; everything marked "not simulated" is owed to later
T-tier evidence.

## Structure

Per side (p shown; n is the mirror image with the DAC rails swapped):

- **Input path.** `vinp` -> transmission gate `Sin_p` (`phi1`/`phi1b`) -> bottom
  plate `bpi_p` of `Csi_p`. Bottom plate to `vcm` through `Sbi_p` (`phi2`).
  Top plate `tpi_p` to `vcm` through `Sci_p` (`phi1e`) and to the summing node
  `sump` through `Sti_p` (`phi2`).
- **DAC path.** Reference mux `Mra_p`/`Mrb_p` (transmission gates driven only
  by `dn`/`dp`) put `vrefp` or `vrefn` on `rsel_p`; `Sr_p` (`phi1`) samples it
  on `Csr_p`, with `Sbr_p`, `Scr_p`, `Str_p` as for the input path.
  `dp` = 1 (decision y = +1) selects `vrefn` on the p side and `vrefp` on the
  n side (feedback -VREF); `dn` = 1 (y = -1) the opposite. `dp`/`dn` are the
  comparator decision and its complement.
- **Integrating cap** `Ci_p` from `sump` to `voutp`. The OTA inverts from `inn`
  to `outp` (and `inp` to `outn`), so the p-side caps sum at `inn`/`sump`:
  `voutp - voutn` steps by `0.5 * (vin_diff + rsel_p - rsel_n)`, i.e.
  `+0.5 * (u - y) * VREF` as in model B.
- **Reference from boundary ports only (DR-005).** `vrefp`, `vrefn`, `vcm`,
  `ibias` are ports; nothing in the cell generates them. The reference node
  must settle through the mux and `Sr` within the phase, which is the DR-005
  reference-settling assumption (starting level 0.01 %).
- **Bottom-plate sampling.** `phi1e` is an early copy of `phi1`; the top-plate
  switches open before the bottom-plate switch, so the signal-dependent charge
  of the sampling transmission gate does not reach the held charge. All
  `vcm`-referenced NMOS switches inject a signal-independent amount (offset or
  common-mode, mismatch-limited). Clock generation and timing are out of scope.

## Capacitors (spec §5.3, model B)

| Cell | Value | Source |
|---|---|---|
| `Csi_*`, `Csr_*` (`cap_mim_m3_1`, 22.17 x 22.17 um) | 1.000 pF | spec §5.3 planning value; the minimum is 0.38 pF. §5.3 counts the input and the reference sampling phases on both sides (`4 kT / Cs`), which is why both are 1 pF |
| `Ci_*` (31.43 x 31.43 um) | 2.000 pF | `Ci = Cs / 0.5`, model B `C1 = C2 = 0.5` (`sim/bmodel/model.py:41-42`) |

**Cs/Ci = 0.5**, equal to the model coefficient for both the input and the
feedback path. kT/C figure is the spec's own: 1 pF gives 1.72e-10 V^2
(13.1 uV rms), kT/C-only SNR 90.2 dB, 4 dB over the 86.0 dB the allocation
needs (§5.3); not recomputed or simulated here. Capacitance is the nominal
`2 fF/um^2 * W*L + 0.38 fF/um * (W+L)` shown by the xschem symbol; the ngspice
model value and the area (about 490 um^2 per 1 pF, 990 um^2 per 2 pF, 3.9e3
um^2 per cell) are to be confirmed at layout, as §5.3 already states. The
amplifier-side plate of each capacitor is drawn on the MIM top plate (`c0`)
to keep the substrate parasitic off the summing node (to be confirmed in
layout).

## Switch sizes (hand-calc scaled from probes)

All `L` = 0.15 um, `nf` = 1, 1.8 V core devices (`nfet_01v8`/`pfet_01v8`).

| Switch | W (um) | Probe Ron | Role |
|---|---|---|---|
| NMOS to `vcm`: `Sbi`, `Sci`, `Sti`, `Sbr`, `Scr`, `Str` (both sides) | 12 | 0.57 kohm at 0.9 V (0.07 at 0.3 V, 0.11 at 0.6 V) | bottom plate and top plate reset to `vcm`, top plate to summing node |
| Transmission gate `Sin_*`, `Sr_*`, `Mra_*`, `Mrb_*` | NMOS 4, PMOS 8 | 1.73 kohm worst (at 0.9 V); 0.21 at 0.3 V, 0.36 at 0.6 V, 1.08 at 1.2 V, 0.51 at 1.5 V | input sample, reference sample, DAC reference mux |

The NMOS switches only ever connect nodes near `vcm` (0.9 V, Vgs about 0.9 V);
the transmission gates cover the full input and reference range (assumed
`vrefp` 1.5 V, `vrefn` 0.3 V about `vcm`; DR-005 fixes only the 1.2 V span).

## Settling in the 97.7 ns phase (hand-calc, not simulated)

Phase = `1 / (2 * 5.12 MHz)` = 97.66 ns (spec row 5), target 0.01 % = 9.2 time
constants, so the total time constant must be <= 10.6 ns. Non-overlap and the
`phi1e`/`phi1` skew take part of the phase and are not allocated here.

- **Sampling, input path.** Loop `Sin` (1.73 kohm) + `Sci` (0.57 kohm) times
  `Cs` = 2.3 ns; 9.2 tau = 21 ns.
- **Sampling, DAC path (upper bound).** `Mr*` + `Sr` at their worst 1.73 kohm
  each, plus `Scr` 0.57 kohm = 4.0 ns; 9.2 tau = 37 ns. In practice the last
  part of the exponential happens near a rail, where the transmission gates
  are 0.2-0.5 kohm.
- **Integration, switch part.** Bottom-plate and top-plate switches in series
  with `Cs` (0.57 + 0.57 kohm, 1 pF) = 1.15 ns, added to the OTA time constant.
- **Integration, OTA part.** In the integrate phase both `Csi` and `Csr` are on
  the summing node, so the feedback factor is
  `beta = Ci / (Ci + 2 Cs + Cp)` = 2 / 4.035 = **0.496**, with `Cp` = 0.035 pF
  from `design/ota/SIZING.md`. That is **not the 0.66** `design/ota/SIZING.md`
  uses (one `Cs`), so the OTA sizing trace understates the load for this cell.
  Series load of `Ci`: `Ci (2 Cs + Cp) / (Ci + 2 Cs + Cp)` = 1.01 pF, plus
  about 0.1 pF output parasitics.

| Case | `CL,eff` | OTA tau at 302 uS | + switches | Error `exp(-97.7/tau)` | `gm` for 0.01 % |
|---|---|---|---|---|---|
| A: next stage's `Cs` (1 pF) also loads the output, as `design/ota/SIZING.md` assumes | 2.11 pF | 14.1 ns | 15.2 ns | 1.6e-3 | 449 uS |
| B: both integrators on the same phases, nothing else on the output during integrate | 1.11 pF | 7.4 ns | 8.5 ns | 1.1e-5 | 236 uS |

302 uS is `gm(M1)` at the OTA smoke-check bias point, a bias-point number, not
a GBW result. Which case applies depends on the stage phasing, which belongs to
the modulator-level issue, not this cell. **Open risk: in case A the OTA as
built does not reach the 0.01 % level used for DR-005; whether 1.6e-3 is
acceptable is for the B-model `settling_error` extraction to decide. This block
does not relax anything.** Not simulated.

## kT/C and charge injection

Sampling-switch kT/C does not depend on the switch size; it is set by `Cs`
above. The reset switches are tied to `vcm` and so inject independent of the
signal; their size (12 um x 0.15 um, about 15 fF of channel capacitance each)
sets an offset term for model B's `ci_offset`/`ci_gain_error`, to be extracted,
not estimated here.

## Not simulated (owed)

Transient charge transfer and settling, kT/C and switch noise, charge
injection and clock feedthrough, switch Ron across corners and temperature,
capacitor mismatch, the reference-node settling through the mux, OTA
loading in the integrate phase, corners, Monte Carlo, layout and parasitics.

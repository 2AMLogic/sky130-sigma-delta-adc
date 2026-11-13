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
simulated; *probe* = one DC small-signal point (10 mV drop) in ngspice, at `tt`,
27 C, 1.8 V, bulk at ground unless the row says otherwise, no corners or Monte
Carlo. Behind this block there are now, besides those probes and
`sim/integrator-load-check/` (switch states and polarity wiring, DC):
`sim/integrator-settling/record.json` and `record-i92.json` (settling over the
DR-002 full grid, 45 corners per load variant, batch fleet) and
`diag-i92.json` (the single-corner 1.620 V mechanism probe). All simulated,
none measured. Noise, charge injection, gain and SNDR results still do not
exist; everything marked "not simulated" is owed to later T-tier evidence.

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
  `vcm`-referenced switches inject a signal-independent amount (offset or
  common-mode, mismatch-limited) -- that holds for the PMOS halves issue #92
  added to the phi2-gated ones too, since they also close on `vcm`. Clock
  generation and non-overlap timing are out of scope; the `phi2b` those halves
  need is inverted from the `phi2` port inside this cell, so no new clock phase
  crosses the block boundary.

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

| Switch | Devices | W (um) | Probe Ron | Role |
|---|---|---|---|---|
| `vcm`/summing-node NMOS: `Sbi`, `Sci`, `Sti`, `Sbr`, `Scr`, `Str` (both sides) | `nfet_01v8_lvt`, L 0.15 | 12 | 0.57 kohm at 0.9 V, 1.8 V (0.07 at 0.3 V, 0.11 at 0.6 V) | bottom plate and top plate reset to `vcm`, top plate to summing node |
| PMOS half of the four phi2-gated families: `Sbi`, `Sbr` | `pfet_01v8_lvt`, L 0.35 | 24 | see the 1.620 V table below | carries the integrate-phase transfer at the low rail |
| PMOS half of the four phi2-gated families: `Sti`, `Str` | `pfet_01v8_lvt`, L 0.35 | 4 | see the 1.620 V table below | as above, deliberately small (summing-node capacitance) |
| Transmission gate `Sin_*`, `Sr_*`, `Mra_*`, `Mrb_*` | `nfet_01v8` + `pfet_01v8`, L 0.15 | NMOS 4, PMOS 8 | 1.73 kohm worst (at 0.9 V); 0.21 at 0.3 V, 0.36 at 0.6 V, 1.08 at 1.2 V, 0.51 at 1.5 V | input sample, reference sample, DAC reference mux |

The `vcm`/summing-node switches only ever connect nodes near `vcm` (0.9 V);
the transmission gates cover the full input and reference range (assumed
`vrefp` 1.5 V, `vrefn` 0.3 V about `vcm`; DR-005 fixes only the 1.2 V span).

`phi2b`, the complement the PMOS halves need, is generated inside this cell by
one inverter (`Iphi2b_n`/`Iphi2b_p`, NMOS W 2 / PMOS W 4, both m = 4) from the
`phi2` port. That keeps the block's port list and `design/clkgen` unchanged;
clock generation and non-overlap timing remain out of this cell's scope. The
inverter drives about 0.34 pF of PMOS gate capacitance (4 x 24 + 4 x 4 um at
L = 0.35), which costs roughly 5.6 uW of dynamic power at 5.12 MHz on a 1.8 V
rail -- a clock-node cost, not a signal-path one. Not separately simulated;
the inverter is in the netlist behind every settling number below.

## Why the `vcm` switches need a PMOS half (issue #92)

**Simulated, one corner** (`sim/integrator-settling/run_diag.py` ->
`diag-i92.json`, local, `fs`/1.620 V/-40 C, the binding point of
`record.json`). Not measured.

An NMOS passing `vcm` is gated rail-to-rail on `Vdda`, so its overdrive is
`Vdda - vcm - Vth`. At `Vdda` = 1.620 V that is 0.72 V against a Vth of
**0.924 V** (0.9 V of source-body bias plus -40 C), i.e. **-0.21 V of
overdrive**: the switch is in subthreshold. The probe measures `Sti` passing
111 nA and `Sbi` 116 nA, leaving the input cap's bottom plate stranded at
**1.181 V** instead of `vcm` (a 0.281 V drop across `Sbi`), so the charge
transfer collapses -- `step_dv` 0.068 V against an ideal 0.9 V and `err_phase`
0.776, reproducing the 0.777 in `record.json`.

A PMOS half fixes this because its gate drive does not depend on `Vdda`:
sitting at `vssa` with its source at `vcm`, its `Vsg` is 0.9 V at every supply.
The standard `pfet_01v8` is still subthreshold there (0.946 V of Vth at
`fs`/-40 C), which is why the low-Vth flavour is used; `pfet_01v8_lvt` has no
model bin below L = 0.35 um, hence the longer channel. Switching the NMOS half
to `nfet_01v8_lvt` is free -- identical geometry, so no added capacitance --
and its simulated off-state leakage is unchanged (129.1 pA as `nfet_01v8`
against 129.3 pA as `nfet_01v8_lvt` at `ff`/1.980 V/125 C with 0.3 V across
it -- `leak_nfet_w12_ff` / `leak_nfet_lvt_w12_ff` -- against the ~0.92 nA that
would droop 1 pF by 1e-4 of 0.9 V in one phase).

**Switch Ron at `Vdda` = 1.620 V, passing 0.9 V, -40 C** (DC probes, 10 mV
drop, one operating point each; ohms). Bench: `sim/switch-probe/run_probe.py`,
results in `sim/switch-probe/probe-i92.json` (`ron_*` rows; simulated, local):

| Leg | fs | sf | ss | ff | tt |
|---|---|---|---|---|---|
| `nfet_01v8` W 12 (as built) | 456 k | 41.5 k | 312 k | 64.2 k | 134 k |
| `nfet_01v8_lvt` W 12 | 17.4 k | 770 | 10.5 k | 1.12 k | 3.24 k |
| `pfet_01v8_lvt` W 48, L 0.35 (probe width) | 189 | 663 | 495 | 206 | 296 |

The PMOS row is probed at W 48 for comparability; Ron scales as 1/W here
(simulated at `fs`: 755 / 378 / 189 ohm at W 12 / 24 / 48 --
`ron_pfet_lvt_w{12,24,48}_fs`), so the W 24 and W 4 devices the cell actually
uses are 2x and 12x those numbers.

Every leg is subthreshold at 1.620 V on its own; the pair is not, and the two
legs fail at opposite process skews, which is what flattens the result across
the corner. **Widening the NMOS alone does not work**: W 12 -> 96 moves `fs`
from 456 k only to 180 k (`ron_nfet_w96_fs`), because the device is
subthreshold, not resistive.

**The PMOS halves are sized small on purpose.** Their junction capacitance
lands on the summing node (`Sti`/`Str`) or on the sampling-cap bottom plate in
series with `Cs` (`Sbi`/`Sbr`), lowering beta and costing settling at the
*high* rail, where the NMOS half is already strong and the PMOS half is pure
load. The 1.620 V end wants them big and the 1.980 V end wants them small, so
the size is a compromise, and it was found by measuring both ends on the full
grid rather than by calculation. Two earlier sizings are kept as records:

Four sizings were taken over the full grid; all four are kept as records.

| Record | `Sbi`/`Sbr` | `Sti`/`Str` | `Sci`/`Scr` | `int1` | worst, and where |
|---|---|---|---|---|---|
| `record-i92-sz1.json` | W 96 m 2 | W 16 | W 48 | 42/45 | 1.43e-4 at `ff`/1.980 V/27 C |
| `record-i92-sz2.json` | W 48 | W 8 | none | 44/45 | 1.01e-4 at `ss`/1.980 V/125 C |
| `record-i92-sz3.json` | W 24 | W 8 | none | 44/45 | 1.37e-4 at `sf`/1.800 V/125 C |
| **`record-i92.json`** (this cell) | **W 24** | **W 4** | **none** | **45/45** | **5.89e-5 at `ss`/1.620 V/-40 C** |

All four closed all 15 corners at 1.620 V on the first try. What took three
more iterations was the *other* end: each of the first three failed one to three
corners at 1.800-1.980 V and 27-125 C that the as-built cell passed, because the
PMOS halves are pure capacitance there. The failing corner moved between
neighbouring sizings (`ff`/1.980 V/27 C, then `ss`/1.980 V/125 C, then
`sf`/1.800 V/125 C), which is the signature of a design sitting on a ~1e-4
plateau rather than of one specific corner being special -- so the fix was to
get off the plateau by shrinking, not to chase the corner.

Halving `Sti`/`Str` from W 8 to W 4 did it. Comparing the `sz3` and final
records corner-for-corner (same cell otherwise, both 45-corner fleet grids):

| Corner | `Sti`/`Str` W 8 | W 4 |
|---|---|---|
| `sf`/1.800 V/125 C (what failed `sz3`) | 1.37e-4 | **4.16e-5** |
| `sf`/1.980 V/125 C | 6.34e-5 | 1.19e-5 |
| `ss`/1.620 V/-40 C (the new binding corner) | 1.04e-6 | 5.89e-5 |

The last row is the cost, not a bonus: shrinking the half trades low-rail
margin for high-rail margin, and `ss`/1.620 V/-40 C went from 1.0e-6 to 5.9e-5
to buy it. That is why W 4 is the floor and not a starting point -- another
halving would reopen 1.620 V.

Two reference points bound how small the halves can be, both single-corner
probes at `sf`/1.800 V/125 C (bench: `sim/integrator-settling/run_variants.py`,
results in `variants-i92.json`): ideal 1 ohm switches give 3.43e-7, and the
cell with no PMOS halves at all gives 4.45e-6 as plain `nfet_01v8` or 3.15e-5
with the low-Vth NMOS. That last pair is worth noting -- **the low-Vth NMOS
swap costs margin at 125 C** (7x here) even though it is what rescues `ss` and
`fs` at 1.620 V/-40 C, so it is not a free change, just a worthwhile one. The
`W 24`/`W 4` halves land at 4.39e-5 at that corner, 1.4x the no-PMOS low-Vth
cell and 10x the plain-`nfet_01v8` one: that is the price of 1.620 V
operation, and all four are two to three orders inside the 1e-4 criterion.

`Sci`/`Scr` get **no** PMOS half: they only reset the top plate to `vcm`
during `phi1e`, and the probe shows the top plate already reaches 0.8993 V at
1.620 V with the subthreshold NMOS alone (`tpi_smp` in `diag-i92.json`,
as-built run) -- the sampling path never needed the charge the integrate path
does, so a PMOS half there would be capacitance for nothing.

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

Recomputed at `gm(M1)` = **631.1 uS** (`sim/ota-op-smoke/record.json`), the
value on `main` since #51 doubled the tail and branch currents. The 302 uS
column is kept because the rest of this section was written against it, and
because it is what the pre-#51 trace used -- it is **not** the current device.

| Case | `CL,eff` | OTA tau at 302 uS | at 631.1 uS | + switches (631.1) | Error `exp(-97.7/tau)` at 631.1 | `gm` for 0.01 % |
|---|---|---|---|---|---|---|
| A: next stage's `Cs` (1 pF) also loads the output, as `design/ota/SIZING.md` assumes | 2.11 pF | 14.1 ns | 6.74 ns | 7.89 ns | 4.2e-6 | 449 uS |
| B: both integrators on the same phases, nothing else on the output during integrate | 1.11 pF | 7.4 ns | 3.55 ns | 4.70 ns | 9.3e-10 | 236 uS |

The `gm` requirement is unchanged by the recompute (it does not depend on the
`gm` the cell has): 449 uS for case A, 236 uS for case B, both met by 631.1 uS.
What the recompute changes is the predicted error, from 1.6e-3 / 1.1e-5 to
4.2e-6 / 9.3e-10 -- so the **open risk the previous revision recorded here, that
case A would miss the 0.01 % level, is withdrawn: it rested on the stale
302 uS.** 631.1 uS is `gm(M1)` at the OTA smoke-check bias point, a bias-point
number, not a GBW result. Which case applies depends on the stage phasing,
which belongs to the modulator-level issue, not this cell.

**This single-pole hand-calc is now optimistic by orders of magnitude and must
not be read as a prediction.** The measured case-B error at the nominal
tt/1.800 V/27 C corner is 4.56e-6 (`sim/integrator-settling/record-i92.json`;
6.4e-6 for the as-built cell in `record.json`), against the 9.3e-10 above --
four orders of magnitude out. The model prices only the dominant pole, and at
these time constants the OTA's non-dominant poles, its finite DC gain and the
switch nonlinearity set the residual instead. Use the `gm` column as a sizing
floor and the recorded grid as the result. Not simulated in this table.

## Settling over PVT (simulated, 45 corners per load variant)

`sim/integrator-settling/record-i92.json`, batch fleet, ngspice 47, this cell's
`integrator.spice` (`sha256` `18fc5147...4074d53`) with an unchanged
`design/ota/ota_fd.spice`. Nothing measured.

| Variant | Load per side | Pass | Worst `err_phase` | Nominal tt/1.800 V/27 C |
|---|---|---|---|---|
| `int1` (case B) | 0.1 pF | **45/45** | 5.89e-5 at `ss`/1.620 V/-40 C | 4.56e-6 |
| `int2` (case-A bound) | 1.1 pF | 13/45 | 1.42e-3 at `fs`/1.620 V/125 C | 1.06e-4 |

`int1` closes the 97.66 ns phase to 1e-4 at every DR-002 corner, including all
15 at 1.620 V, with 1.7x margin at the binding corner; `t_1e4` is 52.5-92.5 ns
everywhere, i.e. inside the phase. Both reference-validity gates hold at all 90
points of both variants. As built, `int1` was 29/45 with 0/15 at 1.620 V.

### Open item: `int2` does not pass, and is not claimed to

`int2` is **not** a second circuit -- it is this cell with 1 pF per side added,
the case-A bound for the next stage's `Cs` plus the comparator input. It passes
13/45, worst 1.42e-3, with the residual spread over PVT (1.1e-4 to 1.4e-3,
worst at 125 C) rather than concentrated at the low rail. Three things are true
about it and none of them make it acceptable:

- It is a **bound, not a load.** Whether case A applies at all depends on the
  comparator input capacitance, which is not extracted. 1 pF is a placeholder
  chosen by #53 to be pessimistic.
- It **improved by 550x** in the worst residual (0.784 -> 1.42e-3) and all eight
  non-settling corners per variant are gone; every `err_phase` is now a real
  residual, not a "never settled" reading.
- It is still **14x over** the DR-005 1e-4 level at its worst corner, and
  **must not** be argued away with the B-model `settling_error` threshold of
  0.49: that threshold is a linear gain factor and does not price a
  signal-dependent settling shortfall (`sim/integrator-settling/README.md`).
  (That threshold was quoted as 0.57 until issue #107 corrected a 3.02 dB ENBW
  error in the B-model SNDR estimator; the argument it must not be used for is
  unaffected by which number it is.)

Closing `int2` needs the comparator input capacitance first -- if the real load
is nearer case B, the question dissolves; if it is nearer case A, the OTA needs
more gm (its own bench passes 45/45, so this is a load problem, not a defect).
That decision belongs to the modulator/comparator level, not to this cell, and
is out of scope for #92 by its own terms.

## kT/C and charge injection

Sampling-switch kT/C does not depend on the switch size; it is set by `Cs`
above. The reset switches are tied to `vcm` and so inject independent of the
signal; their size sets an offset term for model B's
`ci_offset`/`ci_gain_error`.

**Extracted (issue #102), no longer owed.** Bench `sim/integrator-ci`; records
`sim/integrator-ci/record.json` (five variants x the DR-002 full 45-point grid,
225 corners) and `record-mc.json` (7 DR-002 anchors x N=100 x two cells, 1400
samples, sky130 `_mm` mismatch sections, base seed 20261113). Simulated on the
batch fleet, never measured. Per switch the channel area did go from the NMOS
half alone (12 x 0.15 = 1.8 um2) to that plus a PMOS half of 24 x 0.35 = 8.4 um2
on `Sbi`/`Sbr` and 4 x 0.35 = 1.4 um2 on `Sti`/`Str`, and #92 also swapped
`nfet_01v8` for `nfet_01v8_lvt` on all six. What that cost:

| | result |
|---|---|
| Differential residual, nominal, zero input | <= 2.265e-07 V per clock over all 45 points (`ci_offset` 1.89e-07 FS); the pre-#92 cell gives 2.902e-07 V. Both sit at the bench's solver floor (`vntol` 1e-7 V), so **the nominal grid cannot distinguish the two cells** -- as a cell drawn symmetric should give |
| Differential sigma under PDK mismatch, switch-attributable | **59 to 90 uV per clock** (4.9e-05 to 7.5e-05 FS) |
| ... post/pre ratio | **1.84x to 3.61x**, mean 2.56, per-anchor standard errors 0.19 to 0.37 |
| Signal-dependent part (`ci_gain_error`) | below the bench's resolution; the measured slope is the drawn `Cs/Ci` ratio (0.497557, not 0.5), the finite-gain leak, and at the slow/cold corners the incomplete *input* sampling of #102's spin-off #106 |
| Cost in model B | **0.17 dB** of peak SNDR (89.02 dB against the 89.19 dB ideal record), source B, uncross-checked, N = 2^16, 1.2207 Hz bins, 0-20 kHz, -6 dBFS |

**Three things in the argument this section used to make are wrong, and the
measurement is why:**

- *"The common-mode part grows with it."* It does not, measurably. The
  common-mode step is ~1e-06 V per clock at **both** cells and shows no
  systematic growth post-#92 (per-anchor post/pre ratios scatter 0.47 to 2.13
  about 1, nothing like the 5.7x area factor): the complementary NMOS + PMOS
  halves inject opposite-sign channel charge and largely cancel. It also does
  not accumulate at all -- the OTA's common-mode feedback pulls it back to an
  equilibrium -- so it does **not** land in `ci_offset`, which model B shapes
  through an integrator. Only the differential part accumulates.
- *"The differential residual grows as sqrt(W L)."* It grows faster. Measured
  1.84x to 3.61x against sqrt(W L) predictions of 1.333x (the `Sti`/`Str` pair,
  see below) and 1.929x (all four switches). Three anchors sit within half a
  standard error of 1.929x and three are 3 to 4.6 standard errors above it. The
  term the area-only argument omits is the standard-Vth -> low-Vth swap, which
  raises channel charge at equal area.
- *"Per switch ... 5.7x and 1.8x"* conflates two pairs that do not both reach
  the output. Only `Sti`/`Str` gate the **summing node**, where turn-off charge
  lands on `Ci` and is output error; `Sbi`/`Sbr` gate the **bottom plate**, which
  the next phi1 re-drives from `vinp`/`rsel`, discarding their charge before any
  transfer. The 5.7x pair is the one whose charge is thrown away; the pair that
  matters grew 1.78x.

**The engineering conclusion is unchanged: the #92 fix was cheap.** 0.17 dB
against an 80 dB target is not a reason to revisit the `W 24`/`W 4` sizing, and
PR #99 establishes `W 4` as the floor for 1.620 V settling. Not covered by these
numbers: capacitor mismatch (klt reports the `cap_mim_*` family's mismatch as
unverified for sky130, so it is outside the sigma above), clock feedthrough from
a real non-overlap generator, and post-layout extraction. See
`sim/integrator-ci/README.md` -> "Limits".

The off-state leakage this adds was simulated and is small: 129 pA per NMOS half
(129.1 pA standard against 129.3 pA low-Vth, so the swap does not change it) and
22.5 pA for a W 16 PMOS half at `ff`/1.980 V/125 C with 0.3 V across it -- the
W 24 and W 4 halves the cell uses bracket that -- against the ~0.92 nA that would
droop 1 pF by 1e-4 of 0.9 V in one 97.66 ns phase. One operating point each, not
a corner sweep; bench `sim/switch-probe/run_probe.py`, results in
`sim/switch-probe/probe-i92.json` (`leak_*` rows). Simulated, not measured.
The DC wiring check `sim/integrator-load-check` still holds its original 1e-6 V bound on the
top-plate-to-summing-node drop with these halves in place (measured 1e-7 V), so
the added junction leakage does not disturb it.

## Not simulated (owed)

kT/C and switch noise, clock feedthrough from a real non-overlap generator,
capacitor mismatch (klt reports the `cap_mim_*` family's mismatch as unverified
for sky130, so it is outside the charge-injection sigma above), the
reference-node settling through the mux, layout and parasitics. Monte Carlo is
done for charge injection only (issue #102); every other mechanism here is still
nominal-grid only. Incomplete *input* sampling at the slow/cold corners is owed
as #106 -- a separate mechanism from charge injection, found by the #102 bench.

**No longer owed** (issue #102): charge injection and its mismatch-driven
differential part, over the DR-002 full grid and a Monte Carlo campaign at the
anchors -- see "kT/C and charge injection" above.

**No longer owed** (issue #53, then #92): transient charge transfer and
settling, switch Ron across corners and temperature, and OTA loading in the
integrate phase are all measured over the DR-002 full grid in
`sim/integrator-settling/record.json` (as built) and `record-i92.json` (this
cell), 45 corners per load variant, simulated on the batch fleet. The 1.620 V
mechanism is in `diag-i92.json`.

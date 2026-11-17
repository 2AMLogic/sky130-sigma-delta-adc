# integrator — sizing trace

Fully-differential switched-capacitor integrator with a 1-bit feedback DAC.
Schematic `integrator.sch`, symbol `integrator.sym`, netlist `integrator.spice`
(`klt netlist --block`; `--check` gates drift). It instantiates the OTA symbol
`design/ota/ota_fd.sym`, whose netlist is `design/ota/ota_fd.spice` and is
`.include`d separately (the OTA symbol is `type=primitive` so the integrator
netlist does not descend into, or redefine, the OTA). One cell serves both
integrators: model B uses C1 = C2 = 0.3 (DR-007; it was 0.5 until issue #148).

Ports: `vdda vssa vinp vinn voutp voutn vrefp vrefn vcm ibias phi1 phi1b phi1e
phi2 dp dn`.

**Labelling.** *spec* = a ratified row/section; *DR-n* = a decision record;
*model B* = `sim/bmodel/model.py`; *hand-calc* = arithmetic here, not
simulated; *probe* = one DC small-signal point (10 mV drop) in ngspice, at `tt`,
27 C, 1.8 V, bulk at ground unless the row says otherwise, no corners or Monte
Carlo. Behind this block there are now, besides those probes and
`sim/integrator-load-check/` (switch states and polarity wiring, DC):
`sim/integrator-settling/record.json` and `record-i92.json` (settling over the
DR-002 full grid, 45 corners per load variant, batch fleet), `diag-i92.json`
(the single-corner 1.620 V mechanism probe), `sim/integrator-ci/record.json` and
`record-mc.json` (charge injection over the full grid and under PDK mismatch),
`sim/integrator-ci/record-i106.json` (input-sampling completeness over the full
grid at two input amplitudes) and `sim/switch-probe/probe-i106.json` (the `Sin`
transmission gate's Ron against the voltage it passes, five skews at 1.620 V/
-40 C). All simulated, none measured. Noise, gain and SNDR results still do not
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
  `voutp - voutn` steps by `0.3 * (vin_diff + rsel_p - rsel_n)`, i.e.
  `+0.3 * (u - y) * VREF` as in model B (DR-007).
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
| `Ci_*` (40.64 x 40.64 um) | 3.334 pF | `Ci = Cs / 0.3`, model B `C1 = C2 = 0.3` (`sim/bmodel/model.py`, DR-007). Drawn ratio 1.000/3.334 = 0.29993. Was 31.43 x 31.43 um, 2.000 pF, until issue #148 |

**Cs/Ci = 0.3** (DR-007; 0.5 before issue #148, when integrator 1 railed), equal to the model coefficient for both the input and the
feedback path. kT/C figure is the spec's own: 1 pF gives 1.72e-10 V^2
(13.1 uV rms), kT/C-only SNR 90.2 dB, 4 dB over the 86.0 dB the allocation
needs (§5.3); not recomputed or simulated here. Capacitance is the nominal
`2 fF/um^2 * W*L + 0.38 fF/um * (W+L)` shown by the xschem symbol; the ngspice
model value and the area (about 490 um^2 per 1 pF, 1650 um^2 per 3.334 pF Ci, 5.9e3
um^2 of capacitor per cell; was 990 um^2 and 3.9e3 at Ci = 2 pF) are to be confirmed at layout, as §5.3 already states. The
amplifier-side plate of each capacitor is drawn on the MIM top plate (`c0`)
to keep the substrate parasitic off the summing node (to be confirmed in
layout).

## Switch sizes (hand-calc scaled from probes)

All `L` = 0.15 um, `nf` = 1, 1.8 V core devices (`nfet_01v8`/`pfet_01v8`).

| Switch | Devices | W (um) | Probe Ron | Role |
|---|---|---|---|---|
| `vcm`/summing-node NMOS: `Sbi`, `Sci`, `Sti`, `Sbr`, `Scr`, `Str` (both sides) | `nfet_01v8_lvt`, L 0.15 | 12 | 0.57 kohm at 0.9 V, 1.8 V (0.07 at 0.3 V, 0.11 at 0.6 V); re-measured `tt`/27 C/1.8 V in `probe-i147.json`: **0.25 kohm** at 0.9 V (0.063 / 0.095 at 0.3 / 0.6 V -- see the issue #147 section) | bottom plate and top plate reset to `vcm`, top plate to summing node |
| PMOS half of the four phi2-gated families: `Sbi`, `Sbr` | `pfet_01v8_lvt`, L 0.35 | 24 | see the 1.620 V table below | carries the integrate-phase transfer at the low rail |
| PMOS half of the four phi2-gated families: `Sti`, `Str` | `pfet_01v8_lvt`, L 0.35 | 4 | see the 1.620 V table below | as above, deliberately small (summing-node capacitance) |
| Transmission gate `Sr_*`, `Mra_*`, `Mrb_*` | `nfet_01v8` + `pfet_01v8`, L 0.15 | NMOS 4, PMOS 8 | **`tt`/27 C/1.8 V only** (per "Labelling"): 1.73 kohm at 0.9 V; 0.21 at 0.3 V, 0.36 at 0.6 V, 1.08 at 1.2 V, 0.51 at 1.5 V. **Not a PVT worst case, and 0.9 V is not the peak** -- see "`Sin` over PVT" below (the pair is shared with the pre-#129 `Sin`, so the #106 curve still describes these) | reference sample, DAC reference mux |
| Input sampling gate `Sin_*` | `nfet_01v8_lvt` + `pfet_01v8_lvt`, L 0.15 / 0.35 | NMOS 4, PMOS 8 | **`ss`/1.620 V/-40 C: peak 3.16 kohm at 0.85 V** (probe-i129.json); 5670x the pre-change pair's 0.5044 sampling error at the filed corner is gone -- see "Issue #129: the `Sin` low-Vth fix" below | input sample |

The `vcm`/summing-node switches only ever connect nodes near `vcm` (0.9 V);
the transmission gates cover the full input and reference range (assumed
`vrefp` 1.5 V, `vrefn` 0.3 V about `vcm`; DR-005 fixes only the 1.2 V span).

### `Sin` over PVT: the transmission gate peaks at `vcm`, and hard (issue #106)

The "1.73 kohm worst (at 0.9 V)" entry above was a single `tt`/27 C/1.8 V probe,
which that row now says. It is **not** a worst case over PVT, and "worst" was
the wrong word even at its own condition. Both halves of this gate are
standard-Vth -- unlike the phi2 `vcm` switches issue #92 fixed -- so for an
input near `vcm` the NMOS half has `Vgs` = `Vdda` - `Vin` against a high `Vth`
and the PMOS half only `|Vgs|` = `Vin`, and **neither conducts**.

Swept properly (`sim/switch-probe/probe-i106.json`, 102 points: both halves in
parallel with the netlist's own geometry and bulk ties, gates fully on, 10 mV
across, one local DC operating point each; **simulated, not measured**):

| condition | peak Ron | at `Vin` | Ron at 0.3 V | at 0.6 V | at 0.9 V | at 1.2 V | at 1.5 V |
|---|---|---|---|---|---|---|---|
| `ss`/1.620 V/-40 C | **584 kohm** | 0.90 V | 0.28 k | 1.08 k | 584 k | 2.83 k | 0.71 k |
| `sf`/1.620 V/-40 C | 190 kohm | 0.95 V | 0.17 k | 0.42 k | 47.8 k | 3.69 k | 0.74 k |
| `tt`/1.620 V/-40 C | 87.8 kohm | 0.90 V | 0.22 k | 0.68 k | 87.8 k | 1.38 k | 0.50 k |
| `fs`/1.620 V/-40 C | 33.6 kohm | 0.80 V | 0.29 k | 1.27 k | 10.0 k | 0.73 k | 0.36 k |
| `ff`/1.620 V/-40 C | 15.1 kohm | 0.90 V | 0.18 k | 0.46 k | 15.1 k | 0.82 k | 0.37 k |
| `tt`/27 C/1.800 V | 2.72 kohm | 1.00 V | 0.21 k | 0.37 k | 1.89 k | 1.04 k | 0.50 k |

Three corrections to the row above follow from it:

1. **The PVT peak is 584 kohm, 338x the quoted 1.73 kohm** -- `Ron*Cs` = 584 ns
   against the 90.4 ns the input path actually gets (see "Settling in the
   97.7 ns phase" below).
2. **0.9 V is not where it peaks.** The peak sits at 0.80-1.00 V depending on
   skew, i.e. always *inside* the signal range, and at the row's own
   `tt`/27 C/1.8 V condition it is 2.72 kohm at 1.00 V, not the 0.9 V value.
3. **The quoted 1.73 kohm itself does not quite reproduce**: this bench reads
   1.89 kohm at 0.9 V at that condition. Its 0.3 / 0.6 / 1.2 / 1.5 V values do
   reproduce, to 3 % (0.214 / 0.373 / 1.04 / 0.501 kohm), so the sizing argument
   built on them stands. The residual 9 % at 0.9 V is **unexplained**: the
   original probe's setup is not recorded beyond the "Labelling" convention, and
   that convention's "bulk at ground" cannot be what produced it -- grounding the
   PMOS half's well forward-biases its source junction and reads 20 ohm. Treat
   1.89 kohm as the reproducible number at that condition.

**Which half is failing moves with the skew**, which is what a remedy has to
answer to. From the same sweep, the NMOS half's share of the current at each
condition's peak: `ff` 18 %, `tt`/1.620 V 26 %, `ss` 42 %, `fs` 46 %, `sf` 69 %.
Below ~0.8 V the NMOS half carries essentially all of it and above ~1.0 V the
PMOS half does; the crossover lands on the peak, so at `vcm` **both** halves are
subthreshold and neither can be called the weak one in general. Widening will
not rescue that -- `probe-i92.json` shows an 8x width on a subthreshold NMOS
buying 2.5x (456 k -> 180 k) -- which is the same argument that put a low-Vth
NMOS plus a PMOS half on the phi2 switches in issue #92.

**The transient consequence is simulated, over the DR-002 full grid**, in
`sim/integrator-ci/record-i106.json`: at `ss`/1.620 V/-40 C a 0.2 V differential
input is **54.3 % unsampled** when `phi1e` opens, and the error is strongly
input-level dependent (0.8 % at a 0.6 V input at that same corner). 8 of 45 grid
points exceed 1e-4 at 0.2 V, 2 of 45 at 0.6 V, and the 1.980 V points are
exact to the reported precision — 28 of those 30 read `error_rel` exactly 0,
and the two that do not (`ss` and `sf` at 1.980 V/125 °C, 0.6 V) read
1.7e-7, which is the 7-digit print resolution and three orders below the
reference line.

**Not all of that headline error is this gate**, and the record separates the
two. The headline is the differential across `Csi`; the bottom-plate-only
reading (`error_rel_bpi_only`) isolates `Sin`, and the remainder is the `Sci`
top-plate hold. All three columns below are **relative**, so the last one is
`error_rel` − `error_rel_bpi_only`; the record's volt-valued field of that
remainder is `top_plate_differential_V`, which is this column times `ideal_V`
(0.0388 relative is 0.007768 V at the first row):

| corner | input | headline `error_rel` | `Sin` (bottom plate), `error_rel_bpi_only` | `Sci` (top-plate hold), relative: `error_rel` − `error_rel_bpi_only` |
|---|---|---|---|---|
| `ss`/1.620 V/-40 C | 0.2 V | 0.5432 | **0.5044** | 0.0388 |
| `sf`/1.620 V/-40 C | 0.2 V | 0.2843 | **0.2833** | 0.0010 |
| `fs`/1.620 V/-40 C | 0.6 V | 0.1340 | 0.0026 | **0.1315** |

At 0.2 V the error is this gate, as filed — the top-plate term is at most
0.039 anywhere on that grid. **At 0.6 V the binding corner is not.** At
`fs`/1.620 V/-40 C the bottom plates settle to 1.19849 V / 0.60002 V against
1.2 / 0.6 V targets (0.26 % short, which is what the ~1 kohm this sweep reads
at 0.6 V and 1.2 V predicts); the 13.4 % is the p-side top plate sitting
**78.9 mV above `vcm`** when `phi1e` opens. 98 % of that corner's error is the
top-plate hold, so **`fs`/0.6 V is not a `Sin` result and a `Sin` remedy cannot
move it.** The top-plate term is already 69 mV at cycle 1, when the output has
only reached 0.298 V, so it is not the OTA range excursion either; the
suspected cause -- `XSci_*`'s missing PMOS half, reasoned from the netlist --
was separately simulated and confirmed by issue #147
(`sim/switch-probe/probe-i147.json`), and the cell has since been changed;
see the issue #147 section below.

**No spec row bounds input-sampling completeness, so none of this is a pass/fail
result and no SNDR or resolution consequence is claimed** -- nothing here has
been through model B. The cell is **unchanged by that extraction** (the #106
record and this section up to here describe the pre-#129 cell; the rows above
name `Sin` as one shared pair only up to that point). The two
mechanisms are deferred separately, because they are different switches with
different remedies: the `Sin` bottom-plate term is **#129**, fixed as below;
the `Sci` top-plate hold is **#147**, still open. Both were filed from these
numbers.

### Issue #129: the `Sin` low-Vth fix (2026-11-17)

**Decision (spec/decisions/DR-010): make `Sin` the same low-Vth pair the phi2
`vcm` switches got in #92, sized by a committed sweep.** Both halves change
flavour: `XSin_<p,n>_n` `nfet_01v8` W 4 L 0.15 → **`nfet_01v8_lvt` W 4
L 0.15**, and `XSin_<p,n>_p` `pfet_01v8` W 8 L 0.15 → **`pfet_01v8_lvt` W 8
L 0.35** (the lvt PMOS model has no bin below L = 0.35, the length every lvt
PMOS half in this cell already sits at). Widths are unchanged, so the input
load and the drawn footprint barely move; only the PMOS channel grows
(8 x 0.15 → 8 x 0.35).

**The sweep** (`sim/switch-probe/probe-i129.json`, 312 points, one DC
operating point each, local, simulated; same bench and bias as the #106
sweep): four candidate width pairs, from the #92 `vcm`-switch geometry
(NMOS 12 / PMOS 24) down to the old gate's own widths (4 / 8), each over the
six conditions (five skews at 1.620 V/-40 C, `tt`/27 C/1.8 V) with the
0.7-1.1 V window resolved at 50 mV. Worst-condition peaks, from the record's
`derived` block:

| candidate (NMOS/PMOS W) | worst peak Ron | at condition | at Vin |
|---|---|---|---|
| **4 / 8 (chosen)** | **3158 ohm** | `ss`/1.620 V/-40 C | 0.85 V |
| 6 / 12 | 1931 ohm | `ss`/1.620 V/-40 C | 0.85 V |
| 8 / 16 | 1423 ohm | `ss`/1.620 V/-40 C | 0.85 V |
| 12 / 24 | 945 ohm | `ss`/1.620 V/-40 C | 0.85 V |

The chosen size is the **smallest** candidate: its 3158 ohm peak is ~3x under
the ~9.8 kohm the DR-010 line implies (1e-4 needs ~9.2 tau; tau = Ron x 1 pF
against the 90.4 ns window), so the smaller gate's lower input load and
channel charge win. The larger candidates are committed as the ladder, not as
alternatives that were needed.

**Before/after on the graded grid** (`sim/integrator-ci/record-i106.json` ->
`record-i129.json`, DR-002 full 45 corners at both amplitudes, batch fleet;
simulated, graded on `error_rel_bpi_only` per DR-010):

| corner | input | `error_rel_bpi_only` before | after |
|---|---|---|---|
| `ss`/1.620 V/-40 C | 0.2 V | **0.5044** | **8.9e-5** (5670x) |
| `sf`/1.620 V/-40 C | 0.2 V | 0.2833 | 0.0 |
| `tt`/1.620 V/-40 C | 0.2 V | 0.0138 | 0.0 |
| `fs`/1.620 V/-40 C | 0.6 V | 0.0026 | 0.0020 (still over the 1e-4 line) |
| `ss`/1.620 V/-40 C | 0.6 V | 0.0019 | 0.0004 (still over the 1e-4 line) |

87 of the 90 corner-amplitude points meet the line (44/45 and 43/45); the record names `fs`/1.620 V/-40 C as the
binding corner per amplitude on the bottom-plate reading. **The three
remaining corners are not `Sin` sizing**: their error is a p-side bottom-plate
shortfall that tracks `Sci`'s top-plate anomaly (worst exactly at the 78.9 mV
`fs`/1.620 V/-40 C corner, smallest at `ss` -- backwards for a settling
mechanism), i.e. #147 coupling through `Csi` onto the bottom-plate reading.
It scales with `1/Ron_Sin`; the ladder above shows even the 12/24 candidate
(~3x lower Ron) would leave it over the line, and ~20x width would be needed
-- at which point the input load and injection trade collapses. DR-010 says
this: the line is gated by #147 at those three corners, and #147 is where the
remainder is owned.

**Input capacitance presented by the new gate**: not extracted. The DC probe
records no operating-point capacitances and no transient Cgg extraction was
run for this change; the qualitative statement (unchanged W, PMOS channel
8 x 0.35 vs 8 x 0.15) is not a number and is not offered as one. Owed with
the charge-injection re-extraction (follow-up #266).

**Invalidated records** -- every number taken on the pre-change cell is
marked as such where it lives and named in the #129 PR body; the
re-extraction of charge injection and the model-B `ci_*` parameters is the
follow-up #266's job, the same split #92 -> #102 used.


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

> **Qualifier (issue #106, from `sim/integrator-ci/record-i106.json`): the
> conclusion above is contradicted at the top of the input range.** On the
> DR-002 grid with a 0.6 V differential input, the p-side top plate is
> **78.9 mV above `vcm`** at `fs`/1.620 V/-40 C at the instant `phi1e` opens,
> and that hold error -- not `Sin` -- is 98 % of that corner's sampling error
> (see "`Sin` over PVT" above). So `Sci` does **not** always "already reach
> 0.8993 V with the subthreshold NMOS alone".
>
> The two readings are not the same measurement, and this note does not claim
> to reconcile them: `tpi_smp` is one point of `v(xint.tpi_p)` on the
> *integrator-settling* deck with the DAC live (`vrefp`/`vrefn` 1.5/0.3,
> `dn` 1), probed **20 ns** into the phase, while the #106 figure is on the
> charge-injection deck with the DAC nulled, read at the **90.5 ns** `phi1e`
> fall. Issue #147's sweep below gives the reconciliation its mechanism: the
> hold's discharge time constant is exponentially voltage-dependent, so both
> readings are consistent with the top plate sitting at different heights
> above `vcm` on the two decks. The sizing decision was **replaced** by that
> sweep: the cell now carries the PMOS half.

## The `Sci`/`Scr` top-plate hold, probed and fixed (issue #147, 2026-11-17)

**Every number in this section is simulated** -- DC operating points from
`sim/switch-probe/probe-i147.json` (ngspice-47, pinned sky130A; one corner per
row, the same grid as the `i106` sweep) and transistor-level transients from
`sim/integrator-ci/record-i147.json` and
`sim/integrator-settling/record-i147.json` (the DR-002 45-corner grid, batch
fleet). No SNDR or resolution consequence is claimed for any of them; nothing
here has been through model B.

**The as-built switch was the mechanism, measured.** At `fs`/1.620 V/-40 C the
NMOS-only `Sci` reads 17.4 kohm at `vcm`, 88 kohm at 0.95 V, 0.49 Mohm at
1.0 V, 0.60 Gohm at 1.2 V and open past 1.5 V -- the low-Vth device goes
subthreshold above `vcm` exactly as the #92 diagnosis predicted, with the
body effect (`Vsb` = the held voltage) adding to it. At the 0.97866 V hold
`record-i106.json` pins, the Ron interpolates to ~235 kohm, so the coupled
charge's time constant is ~200 ns against the 90.5 ns `phi1e` phase: the hold
cannot close. Two cross-checks pin the sweep itself: at `tt`/1.620 V/-40 C
the 0.9 V row reads 3240 ohm -- bit-identical to the committed
`probe-i92.json` `ron_nfet_lvt_w12_tt` row -- and the `fs` row at 17.38 kohm
matches `ron_nfet_lvt_w12_fs`. The table row above, though, quoted **0.57
kohm at 0.9 V, 1.8 V**: that figure has no committed provenance (the
committed `probe-i92.json` has no 1.8 V row), and the new sweep measures
**0.25 kohm** there (0.063 kohm at 0.3 V, 0.095 kohm at 0.6 V -- the old
0.07/0.11 bracket reproduced within 15 %, the 0.9 V point did not). The
0.25 kohm figure supersedes it.

**The remedy was measured before it was adopted.** Adding a PMOS half at the
`Sti` precedent (`pfet_01v8_lvt`, W 4, L 0.35 -- the floor size the #92
sizing history bound) holds 1.96 kohm at 0.95 V and stays flat at 0.8-2.0
kohm across the whole half the NMOS loses, with the NMOS keeping 100 % of the
current below `vcm` and ~0 % above it -- the complementary structure the
other `vcm` switches already use. The wider `XSbi` precedent (W 24) reads
0.33 kohm at 0.95 V but buys it with 6x the junction capacitance on a
charge-sensitive node; W 4 is enough (tau ~ 2 ns against 90.5 ns). The
counterfactual -- widening the NMOS alone to W 96 -- buys exactly its width
(8x) and nothing else: 10.9 kohm at 0.95 V, 60 kohm at 1.0 V, still open at
1.5 V, the same not-a-rescue the `Sin` gate's `ron_nfet_w96_fs` row showed.

**Decision: change the cell.** `Sci_p`/`Sci_n`/`Scr_p`/`Scr_n` each gained
the W 4 / L 0.35 `pfet_01v8_lvt` half (drain on the top plate, source `vcm`,
n-well `vdda`), gated on `phi1eb` -- generated in-cell by an
`Iphi1eb_n`/`Iphi1eb_p` inverter pair (nfet W 2 / pfet W 4, m 4, L 0.15),
the same pattern as `phi2b`, so the port list and `design/clkgen` are
untouched. Netlists regenerated with `klt netlist`; the probe runner's
geometry self-check passes against the new netlist.

**The re-grades, both amplitudes, all 45 corners** (`record-i147.json`,
sampling grid, on the changed cell; new record -- `record-i106.json` is
append-only and untouched):

| corner / term | before (#106 cell) | after (#147 cell) |
|---|---|---|
| `fs`/1.620 V/-40 C, 0.6 V: `error_rel` | 0.1340 | **0.0000** |
| same corner: `top_plate_differential_V` | 78.9 mV | **0.0 mV** |
| `ss`/1.620 V/-40 C, 0.6 V: `error_rel` | 0.0083 | 0.0000 |
| worst top-plate term, 0.6 V, whole grid | 78.9 mV | 0.0 mV |
| worst top-plate term, 0.2 V, whole grid | 7.77 mV | **3.03 mV** |

Every 0.6 V corner now reads 0.0000 (print resolution): the top-plate term
this issue owned is gone at the large amplitude, and the small-amplitude
worst improved by 2.5x. The residual `error_rel` at 0.2 V is the `Sin`
bottom-plate term (`error_rel_bpi_only`) -- `Sin`'s 584 kohm gate at
`ss`/1.620 V/-40 C is still the mechanism and #129 still owns the term, but
the move between these two records **is this cell's change, measured**: the
records differ in exactly one input (`integrator_netlist_sha256`; deck,
request, corner set, criterion and simulator identical), and that change
moved `ss` `error_rel` 0.543 -> 0.576 (+0.033, of which bottom-plate-only
0.5044 -> 0.5611, +0.057) and `sf` 0.284 -> 0.300 (+0.016). At `ss` the
bottom plates themselves moved: `bpi_p` shortfall 0.0362 -> 0.0811 V and
`bpi_n` shortfall 0.0647 -> 0.0311 V, leaving the sampled bottom-plate-only
reading 0.09912 -> 0.08778 V against the 0.2 V ideal, ~11 mV further from
it. That cost is accepted: it is small against the 0.6 V result (worst
corner on the whole grid 2.0e-6) and the 0.2 V top-plate improvement
(7.77 mV -> 3.03 mV), and the term itself stays **#129** -- whose own
remedy has since landed as the low-Vth `Sin` pair (the next section;
`record-i129.json` re-grades the term on *that* cell to 8.9e-5 at this
corner). Both of this section's records were taken on the pre-remedy
`Sin`, so the 584 kohm figure and these deltas describe that cell.

The sampling result is what motivated the change; the settling criterion is
what bounds it, because the added halves put junction capacitance on the
top-plate nodes -- which are the summing nodes in `phi2`. Re-graded
(`sim/integrator-settling/record-i147.json`, new record -- `record-i92.json`
untouched): `int1` (case B, the graded variant) still passes **45/45**, worst
`err_phase` 5.26e-5 at `ss`/1.620 V/-40 C against the 1e-4 line -- slightly
*better* than the #92 cell's 5.89e-5. `int2` (the case-A bound, which
`record-i92.json` already did not pass and this file does not claim for it)
went 13/45 to **12/45** passing -- `tt`/1.980 V/27 C (7.367e-5 -> 1.106e-4)
and `ff`/1.980 V/27 C (7.978e-5 -> 1.022e-4) joined the fails while
`ss`/1.980 V/27 C left them (1.422e-4 -> 8.885e-5) -- with its worst
unchanged (1.4166e-3 at `fs`/1.620 V/125 C). That is
the high-rail capacitance cost the #92 sizing history predicted, landing on
a variant that was already failing, not on the criterion.

**What the `tpi_smp` reconciliation keeps open.** The sweep explains why both
old readings were honest: the discharge tau is 17 ns at `vcm` but 88 ns at
+50 mV and ~235 ns at +79 mV, so a deck whose top plate sits near `vcm`
discharges visibly by a 20 ns probe while a deck that leaves it ~79 mV up
cannot discharge even by 90.5 ns. Which deck-side mechanism picks the height
-- the DAC branch's loading through `Scr`, or the offset building through the
phase -- is still not separated, and separating it is now not load-bearing:
on the changed cell the hold completes inside the phase at both amplitudes
over the whole grid, so there is no longer a sampling error awaiting the
answer. The old single-point reading (`tpi_smp` = 0.8993 V, `diag-i92.json`)
stays as filed, hash-pinned to its era.

**Costs and open items carried forward**: the added halves' injected charge
at the `phi1e` fall lands on the sampled value and is inside the re-graded
sampling numbers above (a DC bench cannot see it separately); mismatch
Monte Carlo on the grid has not been re-campaigned for the new devices
(#102's campaign covered the #92 cell, whose `Sti`/`Str`/`Sin`/`Sr` -- the
switches it grades -- are unchanged); `int2`'s case-A bound is open as
before; layout parasitics and any model-B consequence remain out of scope
here. The `i92` sizing-history table above reads `Sci`/`Scr` **none** -- that
is its record of the #92-era cell, superseded by this section.

## Settling in the 97.7 ns phase (hand-calc, not simulated)

Phase = `1 / (2 * 5.12 MHz)` = 97.66 ns (spec row 5), target 0.01 % = 9.2 time
constants, so the total time constant must be <= 10.6 ns. Non-overlap and the
`phi1e`/`phi1` skew take part of the phase and are not allocated here.

- **Sampling, input path.** Loop `Sin` (1.73 kohm) + `Sci` -- re-derived from
  `probe-i147.json`: `Sci` on the #147 cell is 2.0 kohm at `vcm` and
  0.81-2.0 kohm across the hold range at `fs`/1.620 V/-40 C (the as-built
  NMOS alone was 17.4 kohm at `vcm` and collapsed above it, which is what
  98 % of that corner's #106 sampling error was), so the switch loop is
  ~3.7 kohm at the nominal probe point; `Sin`'s own 584 kohm at
  `ss`/1.620 V/-40 C still dominates the path there -- **that term is #129**.
  The phase also delivers less than it looks: the
  sample is frozen when `phi1e` opens, 90.4 ns in, not when `phi1` opens at
  92.5 ns. `sim/integrator-ci/record-i147.json` measures the result over the
  DR-002 grid on the changed cell instead of calculating it, and at that
  corner a 0.2 V differential input is 57.6 % unsampled.
- **Sampling, DAC path (upper bound).** `Mr*` + `Sr` at their worst 1.73 kohm
  each, plus `Scr` -- re-derived from `probe-i147.json` on the #147 cell:
  0.25 kohm at 0.9 V at `tt`/27 C/1.8 V, and 0.81-2.0 kohm across the whole
  reference range at `fs`/1.620 V/-40 C where the NMOS-only switch went from
  71 ohm at 0.3 V to 17.4 kohm at 0.9 V and open above it; 9.2 tau = 37 ns. In practice the
  last
  part of the exponential happens near a rail, where the transmission gates
  are 0.2-0.5 kohm -- and the PVT sweep above bears that out: the same gate is
  0.28 kohm at `vrefn` = 0.3 V and 0.71 kohm at `vrefp` = 1.5 V even at
  `ss`/1.620 V/-40 C, so unlike the input path the reference path never sits on
  the peak. Not separately simulated in the transient.
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
| Cost in model B | **0.17 dB** of peak SNDR (86.00 dB against the 86.17 dB post-#107 ideal record), source B, uncross-checked, N = 2^16, 1.2207 Hz bins, 0-20 kHz, -6 dBFS |

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
PR #99 establishes `W 4` as the floor for 1.620 V settling. (A deliberately
over-stated bound run -- `ci_offset` from the OTA's offset mismatch and
`ci_gain_error` from #106's input sampling, neither of them charge injection --
lands at 79.22 dB, just under the target. That is an argument for fixing #106,
not a cost of these switches.) Not covered by these
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
nominal-grid only.

**No longer owed** (issue #106): incomplete *input* sampling -- a separate
mechanism from charge injection, found by the #102 bench -- is extracted over
the DR-002 full grid at two input amplitudes in
`sim/integrator-ci/record-i106.json`, with the switch mechanism swept over the
five skews in `sim/switch-probe/probe-i106.json`. **No longer owed on it
either** (issue #147, 2026-11-17): the `Sci` sweep exists
(`sim/switch-probe/probe-i147.json`), the decision was taken and the cell
changed -- see the issue #147 section above -- and the sampling grid and the
settling criterion were re-graded on the changed cell
(`sim/integrator-ci/record-i147.json`,
`sim/integrator-settling/record-i147.json`). Still owed on it: Monte Carlo /
mismatch, layout parasitics, any model-B consequence, and the `Sin`
bottom-plate term -- **#129**.

**No longer owed** (issue #102): charge injection and its mismatch-driven
differential part, over the DR-002 full grid and a Monte Carlo campaign at the
anchors -- see "kT/C and charge injection" above.

**No longer owed** (issue #53, then #92): transient charge transfer and
settling, switch Ron across corners and temperature, and OTA loading in the
integrate phase are all measured over the DR-002 full grid in
`sim/integrator-settling/record.json` (as built) and `record-i92.json` (this
cell), 45 corners per load variant, simulated on the batch fleet. The 1.620 V
mechanism is in `diag-i92.json`.

## DR-007 rescale: what was and was not redone (issue #148)

`Ci` was raised from 2.000 to 3.334 pF with `Cs` unchanged. **Every section
above that quotes a settling, load, charge-injection or noise figure was
computed or simulated at `Ci` = 2 pF and has NOT been redone**: the larger `Ci`
changes the OTA's feedback factor (`Ci/(Ci+Cs+Cp)` rises, so loop bandwidth
falls) and its load. Those figures are stale until their benches are re-run on
the new netlist (tracked in DR-007 "Consequences"). Only the swing and power
benches (`sim/modulator-tran/record-c0p3.json`) were re-run for #148.

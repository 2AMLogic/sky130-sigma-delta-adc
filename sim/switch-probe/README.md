# switch-probe — single-device and pass-gate switch probes

On-state resistance and off-state leakage for the integrator's switches, one DC
operating point per row, run locally. **Simulated** (ngspice, sky130 device
models). Not measured, not a record, not a performance claim.

This bench exists so the switch-level numbers in
`design/integrator/SIZING.md` have a committed testbench instead of resting on
prose. It says nothing about settling: the cell-level consequence of these
numbers is `sim/integrator-settling/` (`run_diag.py` for the mechanism,
`run_variants.py` for the switch-isolation cross-check and the PMOS-half size
bounds) and, for the input sampling phase, `sim/integrator-ci/record-i106.json`.

There are two point sets, each with its own result file, selected with `--set`:

| set | what it probes | result file | filed as |
|---|---|---|---|
| `i92` | one device at a time: `ron`, `leakage` | `probe-i92.json` | issue #92 |
| `i106` | the `Sin` complementary pass gate, both halves in parallel, Ron versus the voltage it passes | `probe-i106.json` | issue #106 |

Device geometry is generated from the same rule the committed netlist uses
(`ad = as = 0.29*W`, `pd = ps = 2*W + 0.58`, `nrd = nrs = 0.29/W`), and the
runner **self-checks** that rule against every `XS` switch line in
`design/integrator/integrator.spice` before running anything, for either set —
a geometry drift between this probe and the cell is a refusal, not a silent
wrong number.

## The `i92` set — one device (`switch_probe.cir.tmpl`)

One device, source at `vcm` = 0.9 V, drain biased above it, bulk at the rail
its well sits on (`vdda` for a PMOS half, `vssa` for an NMOS half):

| kind | gate | bias across | reported |
|---|---|---|---|
| `ron` | fully on | 10 mV | `ron_ohm` = bias / I, plus `current_A` |
| `leakage` | fully off | 0.3 V | `current_A` |

`ron` is the job the cell's phi2-gated switches actually do — pass `vcm` onto
the sampling cap's bottom plate or the summing node — so it is the quantity
that collapses as `Vdda` falls toward 1.620 V. `leakage` is the droop the
summing node sees from an open switch over one 97.66 ns phase.

### Points

- **Ron table** at `Vdda` = 1.620 V / -40 C across all five process skews, for
  `nfet_01v8` W 12 (as built), `nfet_01v8_lvt` W 12 (the fix) and
  `pfet_01v8_lvt` W 48 / L 0.35 (probed wide for comparability).
- **Ron 1/W scaling** for `pfet_01v8_lvt` at W 12 / 24 / 48, `fs`.
- **Widening the NMOS alone**: `nfet_01v8` W 96 at `fs`, against its W 12 row.
- **Off-state leakage** at `ff`/1.980 V/125 C for `nfet_01v8` W 12,
  `nfet_01v8_lvt` W 12 (is the low-Vth swap free?) and `pfet_01v8_lvt` W 16.

## The `i106` set — the pass gate (`tg_probe.cir.tmpl`)

The `i92` set probes one device at a time, which cannot answer the question
issue #106 asked: the input sampling switch is a **complementary pass gate**,
and what matters is the parallel conductance of the pair as the voltage it
passes moves across the input range.

`XSin_<p,n>_n` is `nfet_01v8` W 4 / L 0.15 and `XSin_<p,n>_p` is `pfet_01v8`
W 8 / L 0.15 — **neither half is low-Vth**, unlike the phi2 `vcm` switches
issue #92 fixed. The same device pair also builds `Sr_*`, `Mra_*` and `Mrb_*`.
Near `vcm` at a low supply neither half has overdrive: the NMOS half sees
`Vgs` = `Vdda` − `Vin` and the PMOS half `|Vgs|` = `Vin`.

The `tg` kind puts both halves between the swept voltage and 10 mV above it,
NMOS gate at `vdda` and PMOS gate at `vssa` (both fully on), bulks on the
static rails the netlist ties them to. It reports `ron_ohm` = bias / I, and —
through a pair of 0 V ammeters that do not change the topology — each half's
share of the current, `current_nmos_A` / `current_pmos_A` /
`nmos_current_share`. Which half carries the current is what says whether a
remedy should add a low-Vth NMOS half or widen the PMOS half.

**What validates the split: the two shares must sum to the total.** The deck
takes `abs()` of each half's current independently, so if the halves ever ran
counter to one another their currents would be *summed* rather than cancelled
and the shares could exceed 1. The check that rules this out is
`current_nmos_A + current_pmos_A == current_A`, which the deck asserts agrees
to 7 digits and `test_run_probe.py` re-derives on every committed row — all
102 rows of `probe-i106.json` hold it to 1e-6, so no row on this grid is in
that regime. Read a future row whose shares do not sum to the total as the
halves fighting, not as a measurement of either one. (The note belongs here
rather than in `tg_probe.cir.tmpl`: `probe-i106.json` pins the template's
bytes as `tg_deck_sha256`, so editing the deck would move that hash and
invalidate the committed record's provenance.)

### Points

- **Ron versus input** at `Vdda` = 1.620 V / -40 C for all five process skews,
  swept over 0.3 .. 1.5 V: 50 mV steps through 0.6 .. 1.2 V (spec row 11 caps
  the peak differential input at 0.5·`VREF` = 0.6 V, which spec §5.4 spells
  out as each side within ±0.3 V of `vcm` = 0.9 V, so that is the range that
  matters), plus 0.3 V and 1.5 V — the DR-005 reference rails the same gate
  family passes — and 0.45 / 1.35 V between.
- **The same sweep at `tt`/27 C/1.800 V**, the condition `SIZING.md`'s "Probe
  Ron" column was taken at (that file's "Labelling" paragraph), so the
  committed row can be qualified against a reproduction rather than from prose.

`test_run_probe.py` pins the sweep against that range and resolution, and pins
the probed device pair against `integrator.spice`, so a later edit that narrows
the evidence fails a test instead of doing it quietly.

## Running

    python3 -I sim/switch-probe/run_probe.py                    # print both sets
    python3 -I sim/switch-probe/run_probe.py --set i92  --write  # probe-i92.json
    python3 -I sim/switch-probe/run_probe.py --set i106 --write  # probe-i106.json

    # tool-free unit tests (no ngspice, no PDK, no klt):
    python3 -I -m unittest discover -s sim/switch-probe -p 'test_*.py'

The runner refuses a PDK whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2) and refuses to overwrite a result file (append-only; use `--out`).
`--write` needs an explicit `--set`, because each set has its own result file:
the `i106` rows may not be written into `probe-i92.json`.

Every row is one local DC operating point run one at a time — no grid is
hand-launched here. The corner **sweeps** that belong on the batch fleet are
the transient benches' (`sim/integrator-settling`, `sim/integrator-ci`).

## Limits

One operating point per row — not a corner sweep, no Monte Carlo, no
mismatch, no layout parasitics. DC only: these numbers say nothing about
charge injection (issue #102), clock feedthrough, or `phi2b` skew. The bulk
bias is the static rail, not the dynamic well potential. Nothing here is
measured and nothing relaxes DR-005 or the spec.

Specifically for the `i106` set: a DC `Ron` is **not** a sampling error. It is
the small-signal resistance at a fixed passed voltage, whereas a real phi1
charges `Csi` along the whole trajectory from `vcm` to the input, through a
resistance that changes as it goes. The transient consequence over the DR-002
grid is `sim/integrator-ci/record-i106.json`, measured on the cell; this bench
gives that record its mechanism, not its magnitude. `Ron·Cs` quoted against a
phase length is an order-of-magnitude argument, not a settling calculation.

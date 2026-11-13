# switch-probe — single-device switch probes (issue #92)

On-state resistance and off-state leakage for one switch device at one corner,
one DC operating point per row. **Simulated** (ngspice, sky130 device models),
run locally. Not measured, not a record, not a performance claim.

This bench exists so the switch-level numbers in
`design/integrator/SIZING.md` -> "Why the `vcm` switches need a PMOS half"
have a committed testbench instead of resting on prose. It says nothing about
settling: the cell-level consequence of these numbers is
`sim/integrator-settling/` (`run_diag.py` for the mechanism,
`run_variants.py` for the switch-isolation cross-check and the PMOS-half size
bounds).

## Bench (`switch_probe.cir.tmpl`)

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

Device geometry is generated from the same rule the committed netlist uses
(`ad = as = 0.29*W`, `pd = ps = 2*W + 0.58`, `nrd = nrs = 0.29/W`), and the
runner **self-checks** that rule against every `XS` switch line in
`design/integrator/integrator.spice` before running anything — a geometry
drift between this probe and the cell is a refusal, not a silent wrong number.

## Points

- **Ron table** at `Vdda` = 1.620 V / -40 C across all five process skews, for
  `nfet_01v8` W 12 (as built), `nfet_01v8_lvt` W 12 (the fix) and
  `pfet_01v8_lvt` W 48 / L 0.35 (probed wide for comparability).
- **Ron 1/W scaling** for `pfet_01v8_lvt` at W 12 / 24 / 48, `fs`.
- **Widening the NMOS alone**: `nfet_01v8` W 96 at `fs`, against its W 12 row.
- **Off-state leakage** at `ff`/1.980 V/125 C for `nfet_01v8` W 12,
  `nfet_01v8_lvt` W 12 (is the low-Vth swap free?) and `pfet_01v8_lvt` W 16.

## Running

    python3 -I sim/switch-probe/run_probe.py            # print
    python3 -I sim/switch-probe/run_probe.py --write    # save probe-i92.json

The runner refuses a PDK whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2) and refuses to overwrite a result file (append-only; use `--out`).

## Limits

One operating point per row — not a corner sweep, no Monte Carlo, no
mismatch, no layout parasitics. DC only: these numbers say nothing about
charge injection (issue #102), clock feedthrough, or `phi2b` skew. The bulk
bias is the static rail, not the dynamic well potential. Nothing here is
measured and nothing relaxes DR-005 or the spec.

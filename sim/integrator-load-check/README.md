# sim/integrator-load-check — integrator netlist load check

**Load check, not a performance claim.** One `ngspice -b` run loads
`design/integrator/integrator.spice` with `design/ota/ota_fd.spice` at `tt`,
27 C, 1.8 V and solves three static (DC operating point) switch states with
ideal boundary sources (VCM 0.9 V, VREFP 1.5 V, VREFN 0.3 V, vinp/vinn
1.05/0.75 V):

- sample phase with `dp` = 1: the p-side reference cap samples `vrefn`, the
  n side `vrefp`;
- sample phase with `dn` = 1: both swapped (the other DAC polarity);
- integrate phase: bottom plates at `vcm`, top plates on the summing nodes.

No transient, settling, noise, charge-injection, corner or Monte Carlo result
comes from it, and it writes no record.

    python3 -I sim/integrator-load-check/run_load.py [--pdk-root ROOT]

The runner refuses a PDK whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2). Regenerate the netlist first if the schematic changed:
`klt netlist design/integrator/integrator.sch -o design/integrator/integrator.spice --rcfile design/xschemrc --block`.

# clkgen — sizing trace

Non-overlapping two-phase generator for the switched-capacitor modulator.
Schematic `clkgen.sch`, symbol `clkgen.sym`, netlist `clkgen.spice`
(`klt netlist --block`; `--check` gates drift).

Ports: `vdda vssa clk phi1 phi1b phi1e phi2`. On `VDDA` beside the switches it
drives (DR-004 clock item). Input `clk` is 5.12 MHz, 50 % duty (spec row 5);
the 97.7 ns half-period is far longer than every delay here.

**Labelling.** *probe* = one `ngspice -b` transient at `tt`, 27 C, 1.8 V
(`sim/modulator-load-check/`); no corner, Monte Carlo, load-cap or jitter
result exists. Every number below not marked *probe* is a design choice, not a
result.

## Structure

- Cross-coupled NOR core: `core1 = NOR(clkb, p2d)` (phi1 pulse, high when `clk`
  is high and phi2 is already low); `core2 = NOR(clk, p1d)` (phi2 pulse, high
  when `clk` is low and phi1 is already low). `p2d`/`p1d` are `phi2`/`phi1`
  through two `L = 0.5 um` inverters; the NOR plus delay chain is the gap.
- **`phi1e`** (early phi1, bottom-plate sampling): `core1` through two inverters.
  **`phi1`** = `core1 OR delay(core1)` (NOR + inverter, delay = four
  `L = 0.5 um` inverters), so it rises with `phi1e` and falls later.
- `phi1b` = inverter of `phi1`. `phi2` = `core2` through two inverters.
- Loads (read from `design/integrator/integrator.sch`, two integrators): `phi2`
  8 x W12 NMOS per integrator, `phi1e` 4 x W12, `phi1` 4 x W4 NMOS, `phi1b`
  4 x W8 PMOS. Output inverters are sized in that order (`phi2` largest).

| Stage | nfet / pfet W (um) x mult | L (um) | Why |
|---|---|---|---|
| gates inside the NOR core and delay chains | 1 / 2 (NOR pfet stack 4) | 0.15 (delay chains 0.5) | minimum-ish, slow delay chains set the gap |
| `phi1e`, `phi1` output | 6 / 12 x 2 | 0.15 | light gate load |
| `phi1b` output | 6 / 12 x 3 | 0.15 | PMOS gate load |
| `phi2` output | 6 / 12 x 4 | 0.15 | heaviest load |

## Probe result (not a performance claim)

At `tt`, 27 C, 1.8 V, ideal `clk`, modulator loading, threshold crossings at
0.9 V: `phi2` fall -> `phi1e` rise 0.53 ns, `phi2` fall -> `phi1` rise 0.57 ns,
`phi1` fall -> `phi2` rise 0.54 ns, `phi1e` leads `phi1` on the falling edge by
0.67 ns, no sample with both phases above 0.9 V. Gap margin over the other PVT
corners (DR-002), the switch threshold rather than 0.9 V, clock-edge skew
between `phi1` and `phi1b`, and the clock jitter this adds are **not
simulated** and are owed to the T-tier work.

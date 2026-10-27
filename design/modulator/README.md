# modulator — top-level second-order single-bit modulator (issue #41)

Schematic `modulator.sch`, symbol `modulator.sym`, netlist `modulator.spice`
(`klt netlist --block`; `--check` gates drift).

Ports: `vdda vssa vinp vinn vrefp vrefn vcm ibias clk bs`. The reference,
`vcm` and `ibias` are boundary inputs (DR-005); `vinp`/`vinn` are the
differential input, `bs` the bitstream, `clk` the 5.12 MHz modulator clock.
`bs` swings `vssa`..`vdda`; level shifting to `VDDD` for the decimator is not
in this block.

## Structure against model B (`sim/bmodel/model.py:41-42`, `C1 = C2 = 0.5`)

Model B: `x1[n+1] = x1[n] + 0.5*(u[n] - y[n])`, `x2[n+1] = x2[n] + 0.5*(x1[n] - y[n])`,
`y[n] = sign(x2[n])`.

| Model B | Here |
|---|---|
| integrator 1, coefficient 0.5, input `u` and feedback `y` | `xi1`, the `design/integrator` cell (`Cs/Ci` = 0.5), inputs `vinp`/`vinn`, DAC `dp`/`dn` |
| integrator 2, coefficient 0.5, input `x1` and feedback `y` | `xi2`, the same cell, inputs `o1p`/`o1n`, same `dp`/`dn` |
| delaying integrators | one sample-then-integrate step per clock in each cell |
| feedback of `y` to **both** integrators | `dp`/`dn` wired to both `xi1` and `xi2` |
| `y = sign(x2)` | `xcmp` on `o2p`/`o2n`, then an SR latch |
| 2nd-order NTF, `fs` = 5.12 MHz | `xclk` (`design/clkgen`) |

`dp` = 1 means `y` = +1 and selects feedback of `-VREF` in the integrator cell
(see `design/integrator/SIZING.md`).

## Decision path and timing (assumptions, not results)

`xcmp` is clocked by `phi1`: it precharges while `phi2` integrates and
evaluates as `phi1` rises, when both integrator outputs have been held since
the end of `phi2`. The comparator outputs both sit high in reset, which is the
hold state of a cross-coupled NAND SR latch (`Nq`/`Nqb`, `Sb` = `outn`,
`Rb` = `outp`), so `dp`/`dn` stay stable from the decision until the next
`phi1`. The reference mux in the integrator cell sees the new `dp`/`dn` early
in `phi1`, while `Sr` is already closed: the reference node must settle within
`phi1` (the DR-005 settling assumption). Comparator decision time and
kickback (DR-003) are not checked here.

## Consuming the netlists

`modulator.spice` is hierarchical: it carries `.subckt modulator`, `clkgen`
and `integrator` (the symbols for those are `type=subcircuit`) and leaves
`ota_fd` and `comparator` as separate includes (`type=primitive` symbols).
A deck includes exactly:

    design/ota/ota_fd.spice
    design/modulator/comparator/comparator.spice
    design/modulator/modulator.spice

Do **not** also `.include` `design/integrator/integrator.spice` or
`design/clkgen/clkgen.spice`: both define a subcircuit that `modulator.spice`
already defines. They are the standalone block netlists. The `integrator`
subcircuit in `modulator.spice` lists its ports in the symbol's order (`... dp
dn voutp voutn`), the standalone `integrator.spice` in the schematic's order
(`... voutp voutn vrefp ...`); use whichever file matches the instantiation.

## Load and phase check

`python3 -I sim/modulator-load-check/run_load.py` — see that README. It checks
that the hierarchy loads with no unresolved subcircuit, that the phases do not
overlap at `tt`, and that `bs` toggles. It is not an SNDR, settling or noise
result.

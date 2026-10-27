# design

Analog blocks, one directory each, with schematic, symbol, derived netlist and
a `SIZING.md` that traces every size to the spec or a decision record.
`xschemrc` is the project xschem configuration (`klt netlist --rcfile design/xschemrc`).

- `ota/` — fully-differential folded-cascode OTA with CMFB (issue #38).
- `integrator/` — SC integrator and 1-bit feedback DAC, instantiating the OTA (issue #40).
- `clkgen/` — non-overlapping two-phase clock generator, `phi1 phi1b phi1e phi2` (issue #41).
- `modulator/` — top-level second-order single-bit modulator wiring two integrators, the comparator, an SR latch and the clock generator (issue #41); `modulator/comparator/` is the vendored `sky130-comparator` with provenance.

## Regenerating netlists

Netlists are derived, never hand-edited; `--check` exits 0 on `match`, 3 on `drifted`.

    klt netlist design/clkgen/clkgen.sch -o design/clkgen/clkgen.spice --rcfile design/xschemrc --block
    klt netlist design/modulator/modulator.sch -o design/modulator/modulator.spice --rcfile design/xschemrc --block
    design/modulator/comparator/wrap_comparator.sh

Add `--check` (or `wrap_comparator.sh --check`) to gate drift. The vendored
comparator schematic needs xschem >= 3.4.5 to be re-netlisted (`expr()`);
see `modulator/comparator/PROVENANCE.md` for the pin, how it was fetched, and
what is checked.


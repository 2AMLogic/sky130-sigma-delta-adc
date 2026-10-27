# design

Analog blocks, one directory each, with schematic, symbol, derived netlist and
a `SIZING.md` that traces every size to the spec or a decision record.
`xschemrc` is the project xschem configuration (`klt netlist --rcfile design/xschemrc`).

- `ota/` — fully-differential folded-cascode OTA with CMFB (issue #38).
- `integrator/` — SC integrator and 1-bit feedback DAC, instantiating the OTA (issue #40).

# sim/ota-op-smoke — OTA operating-point smoke check

**Smoke check, not a performance claim.** One `ngspice -b` operating point of
`design/ota/ota_fd.spice` at `tt`, 27 C, `vdda` = 1.8 V, `VCM` = 0.9 V on the
inputs and `vcm` pin, `ibias` = 5 uA (DR-005, ideal sources), zero differential
input. It checks the bias point is sane: output common mode within 50 mV of
`VCM`, outputs symmetric, all 23 transistors saturated, `I(vdda)` within a
100-250 uA sanity band (raised from 50-150 uA in issue #51 with the larger tail/branch currents). No gain, GBW, PSRR, swing, noise, settling, corner or
Monte Carlo result comes from it.

    python3 -I sim/ota-op-smoke/run_op.py [--pdk-root ROOT] [--record]

The runner refuses a PDK whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2). `--record` overwrites `record.json`; otherwise the run only prints.
Regenerate the netlist first if the schematic changed:
`klt netlist design/ota/ota_fd.sch -o design/ota/ota_fd.spice --rcfile design/xschemrc --block`.

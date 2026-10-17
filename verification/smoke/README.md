# verification/smoke — digital smoke fixture

**Smoke fixture, not design.** `smoke_acc1.v` is a placeholder 1-bit-input
accumulator. It proves cocotb + Icarus and `klt synthesize` (Yosys against
`sky130_fd_sc_hd`, `tt_025C_1v80`) run at the pinned PDK revision. It is not the
decimation filter and chooses no spec parameter. Excluded from any design-source
inventory by path (`verification/smoke/`).

    python3 -m venv .venv && .venv/bin/pip install cocotb   # version in sim/toolchain.json
    .venv/bin/python verification/smoke/run_smoke.py [--pdk-root ROOT] [--record]

The runner refuses a PDK tree whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2), runs the cocotb test under Icarus, runs `klt synthesize`, and writes
`record.json` (tool versions, PDK revision, cell count, area, netlist sha256).

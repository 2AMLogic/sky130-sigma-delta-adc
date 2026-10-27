# sim/modulator-load-check — modulator netlist load and phase check

**Load check, not a performance claim.** One `ngspice -b` transient loads
`design/modulator/modulator.spice` with `design/ota/ota_fd.spice` and
`design/modulator/comparator/comparator.spice` at `tt`, 27 C, 1.8 V with ideal
boundary sources (VCM 0.9 V, VREFP 1.5 V, VREFN 0.3 V, ibias 5 uA, 5.12 MHz
clock, 60 mV DC differential input) for 2.5 us, and checks:

- the hierarchy loads with no unresolved subcircuit;
- `phi1`/`phi2` and `phi1e`/`phi2` are never both above 0.9 V, and every gap
  (phi2 fall -> phi1e/phi1 rise, phi1 fall -> phi2 rise) exceeds 0.3 ns;
- `phi1e` falls before `phi1`;
- the bitstream node `bs` reaches both rails.

No SNDR, settling, noise, charge-injection, corner or Monte Carlo result comes
from it, it does not show that the bitstream is correct, and it writes no
record. A single corner runs locally, per the host rules; the corner grid is
owed to the T-tier work and goes to `klt sim`.

    python3 -I sim/modulator-load-check/run_load.py

The runner refuses a PDK whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2). Regenerate the netlists first if a schematic changed (commands in
`design/README.md`).

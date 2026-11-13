# sim

PDK and tool pins (`pdk.json`, `toolchain.json`) and the analog smoke fixture in
`smoke/`. See the repo README "Reproduce" section.

`bmodel/` is the behavioural modulator model B (DR-001): `python3 -I sim/bmodel/run.py --params sim/bmodel/ideal.json`
writes an append-only SNDR record to `bmodel/records/`; unit tests: `python3 -I -m unittest discover -s sim/bmodel -p 'test_*.py'` (needs `bmodel/requirements.txt`).

`integrator-ci/` is the integrator charge-injection extraction (issue #102,
DR-001 item 2): the cell is clocked for six complete phi1/phi2 cycles with the
input and the reference branch held at `vcm`, so the per-clock change in the
output is the switch-injection residual rather than an ideal charge transfer. It
reports the differential and common-mode parts separately, in volts and in model
B's `ci_offset` FS units, over the DR-002 full grid, plus a Monte Carlo campaign
over the DR-002 anchor set using sky130's `_mm` mismatch sections — and the same
runs on the pre-#92 cell, so the price of that fix is a number. The bench carries
its own validity evidence (a sensitivity check against a deliberately skewed
cell, a step-independence check, and a DC-gain cross-check): see
`integrator-ci/README.md`.

`modulator-tran/` is the short full-modulator transistor-level transient
(issue #125, DR-001 item 2): the assembled modulator netlist with its OTA and
comparator, a coherent single tone at -6 dBFS and the 5.12 MHz clock, over the
DR-002 **anchor set** (7 points, a declared subset of the 45-point grid) through
the batch fleet. It grades analog power against spec row 13, both integrators'
differential output swing against the only figure the ratified spec gives
(sec 5.4), and a clock/bitstream-activity check against row 5; row 12 is covered
by the anchors spanning 1.62-1.98 V. The record length -- 1024 modulator clocks
after 64 discarded start-up clocks -- was chosen from measured cost and written
down before the first corner ran. It commits the per-clock bitstream and both
integrator outputs per anchor under `modulator-tran/samples/`, which is what the
DR-001 item 3 cross-check consumes. **It computes no SNDR and makes no row 2
claim**: 1024 clocks is 8 output samples at OSR 128, which does not resolve the
20 kHz band. See `modulator-tran/README.md`; its record-admission gates are
covered by fixture tests, no EDA tools needed:
`python3 -I -m unittest discover -s sim/modulator-tran -p 'test_*.py'`.

`settling_common.py` holds the shared `klt sim` plumbing for the transistor-level
benches (`ota-settling`, `integrator-settling`, `integrator-ci`). Its two record-validity gates — `grid_complete()` (all 45 DR-002 grid
points returned) and `measurements_present()` (every one of them produced an
`err_phase`, so a dead fleet job cannot become a record) — are covered by
fixture tests, no EDA tools needed:
`python3 -I -m unittest discover -s sim -p 'test_settling*.py'`. The
charge-injection runner's own gates and derivations are covered the same way:
`python3 -I -m unittest discover -s sim/integrator-ci -p 'test_*.py'`.

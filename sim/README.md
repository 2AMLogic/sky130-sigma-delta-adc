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

`settling_common.py` holds the shared `klt sim` plumbing for the transistor-level
benches (`ota-settling`, `integrator-settling`, `integrator-ci`). Its two record-validity gates — `grid_complete()` (all 45 DR-002 grid
points returned) and `measurements_present()` (every one of them produced an
`err_phase`, so a dead fleet job cannot become a record) — are covered by
fixture tests, no EDA tools needed:
`python3 -I -m unittest discover -s sim -p 'test_settling*.py'`. The
charge-injection runner's own gates and derivations are covered the same way:
`python3 -I -m unittest discover -s sim/integrator-ci -p 'test_*.py'`.

`runner_test_common.py` is the test-side counterpart: the harness those
per-bench runner tests share (loading a runner by path, the DR-002 corner ids,
a `RunnerCase` base that runs `main()` against a temporary `HERE` with
`run_klt`/`pdk_stamp` patched, and the issue #94 admission tests as a mixin each
bench binds to its own variants). It is deliberately not `test_`-prefixed, so no
`unittest discover` pattern collects it with no runner bound.

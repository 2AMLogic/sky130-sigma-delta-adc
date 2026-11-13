# sim

PDK and tool pins (`pdk.json`, `toolchain.json`) and the analog smoke fixture in
`smoke/`. See the repo README "Reproduce" section.

`bmodel/` is the behavioural modulator model B (DR-001): `python3 -I sim/bmodel/run.py --params sim/bmodel/ideal.json`
writes an append-only SNDR record to `bmodel/records/`; unit tests: `python3 -I -m unittest discover -s sim/bmodel -p 'test_*.py'` (needs `bmodel/requirements.txt`).

`settling_common.py` holds the shared `klt sim` plumbing for the settling
benches. Its two record-validity gates — `grid_complete()` (all 45 DR-002 grid
points returned) and `measurements_present()` (every one of them produced an
`err_phase`, so a dead fleet job cannot become a record) — are covered by
fixture tests, no EDA tools needed:
`python3 -I -m unittest discover -s sim -p 'test_settling*.py'`.

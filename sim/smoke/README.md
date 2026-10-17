# sim/smoke — analog smoke fixture

**Smoke fixture, not design.** `sampler_smoke.cir` is a trivial NMOS sampling
switch charging a MIM cap. It proves the ngspice + sky130 model flow runs at the
pinned PDK revision; it is not a sizing, a spec choice, or a sampler design, and
is excluded from any design-source inventory by path (`sim/smoke/`).

Single point: `tt`, 27 C, 1.8 V (one local `ngspice -b`; no corner grid).

    python3 sim/smoke/run_smoke.py [--pdk-root ROOT]

The runner loads `sim/pdk.json`, refuses a PDK tree whose `SOURCES` stamp differs
(exit 2), runs the bench, asserts the held voltage is within tolerance of the
input, and writes `record.json` (ngspice version, PDK revision, model-file
sha256s, measured value). Re-running overwrites the record only with `--record`.

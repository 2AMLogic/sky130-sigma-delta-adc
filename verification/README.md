# verification

- `smoke/` — digital smoke fixture (cocotb + Icarus + `klt synthesize`). See the
  repo README "Reproduce" section.
- `decimator/` — decimation filter (`rtl/decimator.v`): bit-exact cycle model
  (`model.py`), whole-chain frequency response against spec rows 8–9
  (`response.py`, exit non-zero on failure), cocotb tests
  (`test_decimator.py`), FIR design (`design_fir.py`, regenerates
  `rtl/decimator_coef.v`) and the runner that also synthesizes and writes
  `record.json` (`run_synth.py`):

      .venv/bin/python verification/decimator/response.py
      .venv/bin/python verification/decimator/run_synth.py [--record] [--no-synth] [--rtl-dir DIR]

  Needs `numpy` and `scipy` in the venv for `design_fir.py` only (not for the
  tests or the response check).

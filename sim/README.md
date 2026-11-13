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

`ota-gain/` is the OTA open-loop DC-gain extraction (issue #126, DR-001 item 2):
`design/ota/ota_fd` at the bias it has in the integrator's integrate phase, with
the feedback loop open at ac and closed at dc (1e12 H inductors carry the dc
feedback, 1 F capacitors the ac drive), read at the bottom of a 1 Hz - 1 kHz
sweep over the DR-002 full grid. It reports the gain per corner in V/V and dB
and names the binding (lowest-gain) corner, and carries `integrator-ci`'s
finite-gain leak figure as a comparison column only. Band flatness, drive
magnitude and common-mode rejection are gated per corner, which is what makes
the reading a dc gain rather than a band value; there is no ratified spec row
for dc gain, so the record makes no pass/fail against the spec. See
`ota-gain/README.md`.

`integrator-noise/` is the first integrator's thermal-noise extraction (issue
#126, DR-001 item 2): two `.noise` requests over the DR-002 full grid, one with
the cell held in phi1 (the four sampling capacitors, the `4*kT/Cs` quantity
spec 5.3 budgets) and one in phi2 (the OTA with its phi2 switches). It reports
each part per sampling event and in band, in V^2 and in model B's
`ktc_noise_var` FS^2 units with both conversions written out, against the
unchanged 4.5e-10 / 9.0e-10 V^2 budgets of spec 5.3, per corner. Because the
amplifier's spectrum is flicker-dominated it also carries the aliasing-correct
in-band link beside the white `1/OSR` one, and derives an effective sampling
capacitance per corner from the measured variance as a check on the drawn
capacitor value. See `integrator-noise/README.md`.

`settling_common.py` holds the shared `klt sim` plumbing for the transistor-level
benches (`ota-settling`, `integrator-settling`, `integrator-ci`, `ota-gain`,
`integrator-noise`). `request()` builds the common 45-point grid request for a
transient or, since #126, for any other analysis kind. Its two record-validity
gates — `grid_complete()` (all 45 DR-002 grid points returned) and
`measurements_present(key=...)` (every one of them produced the bench's own
sentinel measurement, so a dead fleet job cannot become a record) — are covered
by fixture tests, no EDA tools needed:
`python3 -I -m unittest discover -s sim -p 'test_settling*.py'`. Each runner's
own gates and derivations are covered the same way:

    python3 -I -m unittest discover -s sim/integrator-ci -p 'test_*.py'
    python3 -I -m unittest discover -s sim/ota-gain -p 'test_*.py'
    python3 -I -m unittest discover -s sim/integrator-noise -p 'test_*.py'

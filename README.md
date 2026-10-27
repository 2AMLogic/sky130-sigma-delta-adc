# sky130-sigma-delta-adc

A switched-capacitor delta-sigma ADC on
[SkyWater sky130](https://github.com/google/skywater-pdk), the 130 nm open
PDK — an oversampling modulator of switched-capacitor integrators and a
single-bit quantizer, followed by a digital decimation filter — designed by
AI agents driving [klayout-tools](https://github.com/2AMLogic/klayout-tools),
xschem + ngspice on the analog side and cocotb + Icarus, Yosys/OpenROAD on
the digital side.

**Status: spec ratified; behavioural model and decimation filter committed.** The
behavioural modulator model (B) and the decimation filter RTL are verified and
recorded; there is no transistor-level modulator yet. Every figure here is
simulated, none is measured.

**Built agent-native.** Every specification, decision record, testbench, and
line of documentation here is produced by AI agents working from a ratified
spec and an append-only evidence trail — not human-authored work that agents
merely assisted with. Verification is the product: every claim traces to a
recorded result under PVT corners. Where the agents hit friction with the
open-source tooling — most often
[klayout-tools](https://github.com/2AMLogic/klayout-tools) — that friction is
filed as a public issue against the tool itself, so the fix benefits everyone
using sky130, not just this repo.

## Why this block, on this PDK

The program's converters so far are Nyquist-rate SAR ADCs, which trade
resolution for capacitor matching. A delta-sigma converter makes the
opposite trade: it buys resolution with oversampling and noise shaping, so
its accuracy rests on integrator settling, switch charge injection, kT/C
noise, and the digital filter, not on a matched capacitor array. That moves
the hard part from layout matching to verification.

Verification is the honest centerpiece. A resolution claim needs a long
record — tens of thousands of output samples, each made of many modulator
clocks — and a transistor-level transient run of that length is expensive
in ngspice. How the evidence is split between a behavioural modulator model
and transistor-level runs, and how the two are reconciled, has to be stated
before any number is.

The block is also genuinely mixed-signal. The decimation filter is a
synthesized digital block on the same die, and its switching noise sits next
to the most sensitive analog nodes in the design.

## Scope

- **In scope**: the switched-capacitor modulator (integrators, quantizer,
  feedback DAC, clock generation with non-overlapping phases) and the
  decimation filter to the output word rate.
- **Not in scope**: the voltage reference and bias generation, which are
  inputs at the block boundary, and any anti-alias filtering ahead of the
  sampler beyond what the modulator itself provides.
- **Same-PDK siblings**: `sky130-opamp` (integrator amplifier),
  `sky130-comparator` (quantizer), and `sky130-bandgap` (reference) build
  sub-blocks this converter needs on this PDK. Adopt them or record why not;
  do not size a second one by accident. `sky130-sar-adc` is a different
  converter architecture, not a duplicate.

## Target specification

The ratified target specification is [`spec/modulator-adc.md`](spec/modulator-adc.md):
bandwidth, SNDR, modulator, OSR and clock, output, input range, supply and
analog power, and signoff, each as target / fallback / stretch with its
rationale and the evidence type that backs it. The decision records behind
it are in [`spec/decisions/`](spec/decisions/) (index:
[`spec/README.md`](spec/README.md)). The headline is unchanged: **80 dB SNDR
in 20 kHz** is the target, 70 dB the fallback, 90 dB the stretch. All
figures are simulated; none is measured.

| # | Parameter | Target | Fallback | Stretch |
|---|---|---|---|---|
| 1 | Signal bandwidth | 20 kHz | 10 kHz | 50 kHz |
| 2 | Peak SNDR over BW (simulated) | ≥ 80 dB | ≥ 70 dB | ≥ 90 dB |
| 3 | Modulator | 2nd-order, single-bit, SC | same | higher order or multi-bit |
| 4 | OSR | 128 | 256 | 64 |
| 5 | Modulator clock | 5.12 MHz | 5.12 MHz | 6.4 MHz |
| 6 | Output word rate | 80 kSps | 40 kSps | 200 kSps |
| 12 | Supply | 1.8 V ± 10 % | same | same |
| 13 | Analog power | ≤ 1 mW | ≤ 2 mW | ≤ 0.5 mW |

Rows are numbered as in the spec; the full table is there.

Maturity ladder: spec ratified → behavioural modulator and decimation filter
verified → transistor-level modulator simulated across PVT → layout
DRC/LVS-clean → post-layout re-verification → shuttle seat → measured
silicon. **Current position: spec ratified; behavioural modulator model and decimation filter verified; no transistor-level modulator, layout or silicon yet.**

## T1 evidence

The block's T1 tier state is graded by `klt signoff`, not read by hand. The
manifest is [`manifests/sky130-sigma-delta-adc.json`](manifests/sky130-sigma-delta-adc.json);
the verdict of record is
[`manifests/sky130-sigma-delta-adc.signoff.json`](manifests/sky130-sigma-delta-adc.signoff.json).
CI re-renders it with the `klayout-tools` version pinned in
[`.github/klt-version`](.github/klt-version) and fails on any difference.
Regenerate it with:

```
uvx --from "klayout-tools==$(cat .github/klt-version)" klt signoff \
    --manifest manifests/sky130-sigma-delta-adc.json --format json \
    > manifests/sky130-sigma-delta-adc.signoff.json
```

(`klt signoff` exits 3 while any T1 item is unmet; that is a valid run.)

## Repo layout

```
spec/          ratified spec + decision records
design/        modulator schematics / netlists (xschem)
rtl/           decimation filter and control
sim/           PDK/tool pins, modulator testbenches + PVT corner results (ngspice)
verification/  cocotb testbenches for the decimation filter
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
```

## Reproduce

The PDK revision is pinned in [`sim/pdk.json`](sim/pdk.json), tool versions in
[`sim/toolchain.json`](sim/toolchain.json). Each PDK-dependent runner exits `2`
and refuses to run if the PDK's `SOURCES` stamp differs from the pin. The smoke
flows are fixtures ("smoke fixture, not design") that prove the toolchain runs
on the pinned PDK.

```
ciel enable --pdk-family sky130 f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7   # PDK, once
klt pdk find --pdk sky130A                                                 # confirm resolution
uv venv .venv && uv pip install --python .venv/bin/python numpy==1.26.4 cocotb==2.1.0

# smoke fixtures
python3 sim/smoke/run_smoke.py                       # analog: ngspice, tt/27 C/1.8 V
.venv/bin/python verification/smoke/run_smoke.py     # digital: cocotb + Icarus + klt synthesize

# behavioural modulator model B (numpy only; no EDA tools)
.venv/bin/python -I -m unittest discover -s sim/bmodel -p 'test_*.py'
.venv/bin/python -I sim/bmodel/run.py --params sim/bmodel/ideal.json   # appends a record

# decimation filter
.venv/bin/python verification/decimator/response.py       # spec rows 8-9, analytic; no EDA tools
.venv/bin/python verification/decimator/run_synth.py      # + cocotb RTL sim + klt synthesize
```

Committed records: `sim/smoke/record.json`, `verification/smoke/record.json`,
`sim/bmodel/records/*` (append-only; each `run.py` run adds one) and
`verification/decimator/record.json`. The smoke runners and `run_synth.py` add
`--record` to regenerate theirs. The smoke flows and `run_synth.py` need
`ngspice`, `iverilog`, `yosys` and `klt` on `PATH`; the unit tests and
`response.py` need only Python and numpy.

The T1 item 10 (repo hygiene) attestation is derived, not asserted:

```
uvx --from "klayout-tools==$(cat .github/klt-version)" klt signoff --attest 10 \
    --inventory attest/item10.json --check evidence/item10.json
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).

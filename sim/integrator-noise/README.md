# sim/integrator-noise — first-integrator thermal-noise bench (issue #126)

**Simulated, transistor-level** (ngspice `.noise` on
`design/integrator/integrator.spice` with `design/ota/ota_fd.spice`; not the
behavioural model). Question: what is the in-band input-referred noise of the
first integrator per sampling event, over all 45 DR-002 corners, split into the
sampling-switch kT/C part and the integrate-phase (amplifier) part, and does
each meet its `spec/modulator-adc.md` §5.3 budget?

This is source **T** for model B's `ktc_noise_var` (`sim/bmodel/model.py`: a
per-sampling-event variance in FS², drawn i.i.d. Gaussian and added to
integrator 1's state increment). DR-001 item 2 names "kT/C and amplifier noise
(`.noise` or sampled-noise transient)" as a transistor-level extraction and
rejects hand calculation.

## Bench

`integrator_noise.cir.tmpl` -> `integrator_noise_ktc.cir`,
`integrator_noise_amp.cir` (regenerate with `make_request.py`).

A small-signal `.noise` run needs a **static** clock state, and one corner runs
one analysis with one output. So the two halves of §5.3's thermal share are two
requests over the same 45-point grid — the same shape `sim/integrator-settling`
uses for its `int1`/`int2` pair, and what `settling_common`'s
`grid_complete` / `measurements_present` take a *list* of corner sets for.

| variant | clock state | output | what it measures | referred to |
|---|---|---|---|---|
| `ktc` | phi1, phi1e high | `v(nqp,nqn)` | the four sampling capacitors | integrator input |
| `amp` | phi2 high | `v(vod)` | the OTA plus its phi2 switches | integrator output |

`nqp`/`nqn` are built by four ideal VCVSs into the signed differential sum of
the four sampled capacitor voltages, `(Csi_p + Csr_p) - (Csi_n + Csr_n)`. Its
variance is exactly the quantity §5.3 budgets as `4·kT/Cs`: the input and the
reference sampling phase, both sides, four independent contributions. The
probes are ideal, linear and noiseless, so they neither load nor contribute.

Boundary per DR-005: VCM 0.9 V, VREFP/VREFN 1.5/0.3 V, `ibias` 5 uA, all ideal
**and noiseless** — reference and bias noise is not in these numbers. Load
0.1 pF per side (case B of `design/integrator/SIZING.md`: delaying
integrators, the next stage's `Sin` is off in phi2), i.e. the first
integrator, which is what the issue asks about.

**Bench-only DC stabilization.** In both phases the OTA summing nodes see only
capacitors and gates, so `.op` has no DC path to set them. `Lfp`/`Lfn` =
1e12 H bridge `sump`->`voutp` and `sumn`->`voutn`: a short at DC (the OTA
biases in unity feedback with the outputs at the CMFB common mode) and
6.3e12 ohm at 1 Hz, seven orders above the ~1 Mohm output resistance, so they
are an open everywhere the noise is integrated. The same technique as
`sim/ota-gain`.

`Vinp` carries `AC 1` because ngspice's `noise` command aborts
(`ac input not found`) without an AC value on the named input source. **Only
`onoise` is read**: in the phi2 state `vinp` has no path to the output at all,
so the `inoise` spectrum ngspice refers back to it is meaningless there.

## Measurements (`make_request.py` -> `request_{ktc,amp}.json`)

klt's native noise form (`klayout_tools/sim_noise.py`): `band_hz` for a
band-integrated rms, `at_hz` for a spot density.

- `nz_rms_tot` — rms over the whole swept band, 1 Hz .. 1e11 Hz: the
  **per-sampling-event** rms.
- `nz_rms_bb` (1 Hz .. 20 kHz) and `nz_rms_audio` (20 Hz .. 20 kHz) — the
  baseband share, which reaches the signal band with no aliasing. Two lower
  edges because flicker diverges logarithmically downward: the edge is a
  **choice**, and carrying both makes the sensitivity visible instead of
  hiding it.
- `nz_dens_*` at 20 Hz / 1 kHz / 20 kHz / 1 MHz / 100 MHz — spectrum shape, so
  the record *shows* which part is white and which is flicker-dominated
  instead of asserting it.
- `nz_total_native` (`expr: onoise_total`) and `total_vs_native_rel` —
  ngspice's own integral over the same swept range, and the relative
  disagreement with klt's trapezoid. **Gated `<= 1e-2`** per corner. This is
  both an independent check of the integration and the evidence that the upper
  band edge is far enough out for the integral to have converged. Observed at
  tt/27 C/1.80 V: 1.3e-3 on both variants.

## Units: the two conversions, written out

**Per event -> in band.** A sampled sequence is white across `fs/2`, so the
share of a *white* per-event variance that lands in `BW` is `1/OSR = 1/128`.
That is the link §5.3 assumes and the one model B's i.i.d. draw reproduces:

    inband_white_V2 = var_total_V2 / OSR

The measured spectra are **not** white, so the record also carries the
aliasing-correct link, and this is the one the budget verdict uses:

    inband_V2 = var_baseband_V2 + var_aliased_V2 / OSR

(the baseband share passes straight through and is *not* divided by OSR; only
the share above `BW` folds). For the switches the two agree to about 1 % — the
spectrum is flat from 20 Hz to 1 MHz. For the amplifier they differ by an order
of magnitude, and that difference **is** its flicker content.

**V² -> FS².** One FS is `VREFP - VREFN` = 1.2 V of differential integrator
output, and model B's integrator-1 coefficient is `C1` = Cs/Ci = 0.5, so a
variance referred to the integrator input converts with
`(C1/1.2)² = 0.173611`. Same convention as `sim/integrator-ci`'s `ci_offset`
("one x1 unit is (VREFP−VREFN) of differential output at Cs/Ci").

**Which number to load into model B.** `model_b_equiv_ktc_noise_var_fs2`, not
`var_total_fs2`. It is the *white* per-event variance that reproduces
`inband_V2` through model B's own 1/OSR link (`inband_V2 * OSR`, converted);
model B draws i.i.d. per clock and would otherwise under-count the flicker
share. `amp`'s per-corner `input_referral` is `1/C1` = 2, undoing the one
charge transfer between the measured output and the integrator input.

**Effective sampling capacitance.** A single-pole sampler holds `kT/C` whatever
R is, and the `ktc` output sums four of them, so `cs_eff_F = 4·kT/var_total`
per corner — a direct check on the drawn value. At tt/27 C/1.80 V it comes out
1.137 pF against a drawn 0.9976 pF (`drawn_capacitors` in the record: the
cell's 22.17 x 22.17 um MIM through the PDK's own area/perimeter model, **not**
the 1 pF planning value). The +14 % is the switch and plate parasitics on the
sampled nodes — which is precisely why this bench measures rather than
calculates.

## Budgets (§5.3, unchanged)

| line | budget, in band | compared against |
|---|---|---|
| sampling-switch kT/C share | 4.5e-10 V² | `ktc.inband_V2` |
| total thermal share (switches + amplifier) | 9.0e-10 V² | `ktc + amp` |

Both are reported per corner, pass or fail, and **neither is adjusted**. A
corner that misses is recorded as a miss and filed; resizing the OTA or the
capacitors is out of scope for this issue.

**The flicker caveat, stated plainly.** §5.3 allocates a *thermal* share, and
carries no 1/f allocation at all. The `amp` part measured here is
flicker-dominated across the whole closed-loop band, and ngspice's `.noise`
offers no thermal/flicker split through any klt measurement form
(`2AMLogic/klayout-tools#5553`). So `amp`'s
`inband_V2` is thermal **plus** flicker compared against a thermal-only line:
the comparison is exact for the switches and conservative for the amplifier.
That §5.3 has no 1/f line is itself a finding, not a bench defect.

## Running

    python3 -I sim/integrator-noise/run_noise.py --probe    # 1 corner each, local
    python3 -I sim/integrator-noise/run_noise.py --record   # 2 x 45 corners, batch fleet

The runner refuses a PDK whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2). Each variant is one `klt sim` request (`corners` block, 5 process x
-40/27/125 C x 1.62/1.80/1.98 V, DR-002) submitted to the batch fleet with
`--wait-for-capacity 600`; the job ids are in the record's `remote` and
`batch_receipt`, keyed by variant. It never falls back to a local grid. Both
record-validity gates of `sim/settling_common.py` apply across **both**
variants before anything is written: `grid_complete` (all 45 points in each)
and `measurements_present(key="nz_rms_tot")` (every one of them actually
produced a value, so a dead fleet job cannot become a record). `--record`
refuses to overwrite an existing record (append-only); use
`--record-name record-<label>.json` after a sizing change.
`python3 -I sim/integrator-noise/make_request.py` regenerates both decks and
both requests.

Unit tests (no EDA tools):

    python3 -I -m unittest discover -s sim/integrator-noise -p 'test_*.py'

## Records

- `record.json` — issue #126, first full-grid extraction. Result: the
  **sampling-switch kT/C share passes at all 45 corners** with 4.6 to 7.4 dB
  of margin (worst 1.57e-10 V² at `fs`/1.800 V/125 °C against the 4.5e-10 V²
  line), and the **total thermal share misses at all 45**, by 15.6 to 18.4 dB
  (worst 6.24e-08 V² at `fs`/1.980 V/125 °C against 9.0e-10 V²). The miss is
  the amplifier's flicker noise — 89 to 94 % of its in-band power sits below
  20 kHz, where oversampling does not help. Filed as **#138** (a sizing /
  architecture question plus a missing §5.3 1/f allocation); this bench does
  not fix it, per the issue's scope. `cs_eff_F` lands at 1.108 to 1.285 pF
  across the grid against a drawn 0.9976 pF.

## Limits

Listed in the record's `leaves_out`, and worth repeating:

- **No thermal/flicker split per device.** ngspice's integrated-noise plot does
  carry a per-device, per-mechanism decomposition (158 `1overf` vectors out of
  1818 on this block), but it has no *aggregate* — a mechanism total needs
  every flattened instance name enumerated and summed by hand in the request,
  and `klt sim` has no measurement form for it. Filed under the friction
  protocol as `2AMLogic/klayout-tools#5553`.
- **Both parts are reported as i.i.d. per sampling event.** That over-counts
  the in-band effect of the amplifier's 1/f (consecutive samples of it are
  strongly correlated) and ignores any correlated-double-sampling benefit. A
  correlation-aware treatment is a separate piece of work.
- **The integrate phase's finite duration is not modelled.** The `amp`
  integral runs over the circuit's own noise bandwidth, not truncated to the
  97.66 ns phase.
- No reference or bias noise (DR-005 boundary), no clock-jitter noise (model
  B's `jitter_rms_s`, not from this block), no mismatch (nominal grid, no
  Monte Carlo), no layout parasitics (DR-001 item 4).

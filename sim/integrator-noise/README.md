# sim/integrator-noise — first-integrator thermal-noise bench (issues #126, #140)

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

**Issue #140 added two things** to the issue-#126 bench, without changing
`record.json`: the integrate-phase noise is now also read **where it
accumulates** (the `ampq` variant and the per-corner `transfer` block), and the
in-band noise is split **per device and per mechanism** at one corner
(`device_split`). Both are described below; the results are in
`record-i140.json`.

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
| `ampq` | phi2 high | `v(nqci)` | the same, read across `Ci` — the part that accumulates (#140) | accumulated per-cycle increment |

`nqp`/`nqn` are built by four ideal VCVSs into the signed differential sum of
the four sampled capacitor voltages, `(Csi_p + Csr_p) - (Csi_n + Csr_n)`. Its
variance is exactly the quantity §5.3 budgets as `4·kT/Cs`: the input and the
reference sampling phase, both sides, four independent contributions. The
probes are ideal, linear and noiseless, so they neither load nor contribute.
`nqci` is built the same way, as `(voutp - sump) - (voutn - sumn)`: the
differential voltage across the two integrating capacitors.

`amp` and `ampq` are the **same** static phi2 state read in two places, so a
corner runs both over the same grid and the ratio of the two is a measured
transfer rather than two independent extractions (see "The accumulating
referral" below).

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

## Measurements (`make_request.py` -> `request_{ktc,amp,ampq}.json`)

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
- `nz_rms_trunc1` (1 Hz .. 1 GHz), `nz_rms_trunc2` (1 Hz .. 10 GHz) and
  `trunc_vs_total_rms_rel` (**gated `<= 1e-1`**) — the same integral over
  **truncated** bands, one and two decades below the swept edge, plus
  `nz_dens_top` at 10 GHz for the roll-off slope. This is the upper-edge
  evidence; see the next section.
- `nz_total_native` (`expr: onoise_total`) and `total_vs_native_rel` —
  ngspice's own integral over the same swept range, and the relative
  disagreement with klt's trapezoid. **Gated `<= 1e-2`** per corner. What it
  checks is the *integration scheme and the 20-points/decade grid density*:
  that a trapezoid over this grid reproduces ngspice's own integrator.
  Observed at tt/27 C/1.80 V: 1.3e-3 on both variants. It is **not** evidence
  about the upper band edge — both numbers span the identical sweep, so a
  truncated band would move them together and they would still agree to 1e-3.
  The separate evidence for the edge is below.

## Why the upper band edge is far enough out

This is a **verdict-bearing** property, not a detail: at tt/27 C/1.80 V about
99 % of `ktc.inband_V2` — the number the 4.5e-10 V² budget is compared against
— is the *aliased* share of the full-band integral. A band truncated inside
the circuit's noise bandwidth would under-count the variance and make the
reported margin optimistic. So the record carries measured evidence for it,
per corner, in each part's `upper_edge` block. The test is the direct one —
**move the edge and see whether the integral moves**:

- `var_above_trunc1_frac` and `var_above_trunc2_frac` — the same integral taken
  over bands truncated at 1 GHz and 10 GHz, as `1 - (rms_trunc/rms_tot)²`. That
  *is* the measured share of the full-band variance lying above each truncated
  edge (the input referral cancels, so both are comparable with `var_total_V2`
  directly). Over the 45 corners of `record.json`: **1.9 to 4.7 % lies above
  10 GHz** for `ktc` and 1.3 to 6.6 % for `amp`, down from 3.1 to 23.5 % and
  13.2 to 18.3 % above 1 GHz.
- `per_decade_shrink` — the ratio of the two, i.e. how fast the remaining tail
  shrinks per decade. **0.18 to 0.64** (`ktc`), 0.10 to 0.44 (`amp`).
- `extrapolated_frac_above_F_HI` — that same measured rate carried one decade
  further, past the edge: **0.57 to 1.46 %** (`ktc`), 0.12 to 2.85 % (`amp`).
  Labelled an extrapolation, because it is one.
- `trunc_vs_total_rms_rel` — the 10 GHz truncation as an rms-relative
  difference, **gated `<= 1e-1`** per corner (a reference-validity limit, not a
  spec row). Worst observed over the grid **0.033** (`sf`/1.980 V/−40 °C), a
  factor 3 inside the limit; all 90 corner-runs pass.
- `dens_at_trunc2_V_per_rtHz` against `dens_at_100meg_V_per_rtHz`
  (`rolloff_trunc2_over_100meg`) — the slope that produces all of the above:
  the density falls by a factor 0.015 to 0.037 (`ktc`) and 0.040 to 0.063
  (`amp`), i.e. **−36 to −24 dB**, over the two decades from 100 MHz to 10 GHz.

`summary` carries the worst of each over both variants and all 45 corners, and
closes the loop on the verdict: `extrapolated_tail_margin_impact_db` is what
the *whole* residual tail would be worth on a budget margin if every bit of it
were collected, `10·log10(1 + frac)`. Worst over the grid: **0.12 dB**, against
the 4.58 dB of `ktc` margin at the binding corner. That is the number which
says the upper edge cannot turn a pass into a fail here — and it is reported,
not assumed.

A second, physical check on the same band, for `ktc` only: `cs_eff_F =
4·kT/var_total` lands within switch- and plate-parasitic distance of the drawn
`Cs` on every corner (below). A short integral would under-count the variance
and so report a `cs_eff` *above* the drawn value by far more than parasitics
can explain.

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
per corner — a direct check on the drawn value. Against a drawn 0.9976 pF
(`drawn_capacitors` in the record: the cell's 22.17 x 22.17 um MIM through the
PDK's own area/perimeter model, **not** the 1 pF planning value) it runs
**+11.0 % to +28.8 %** across the 45 corners — 1.137 pF, +14.0 %, at
tt/27 C/1.80 V. It is a spread, not one figure, because the parasitic excess
moves with process and temperature; the record's `method.chosen` quotes the
range and names both binding corners. That excess is the switch and plate
parasitics on the sampled nodes — which is precisely why this bench measures
rather than calculates.

## The accumulating referral (issue #140)

**The question.** `amp` reads `v(vod)` in the static phi2 state and refers it
to the integrator input by `1/C1 = 2`. That is right for noise that is sampled
independently each cycle. For slowly varying (1/f) noise it is not obviously
right: `v(vod)` also carries the summing-node excursion, and the next phi1
reset throws that away. What survives a cycle is the charge left on `Ci`.

**Why `v(nqci)` is the quantity that accumulates.** `Ci` is never reset — it
sits between `sump` and `voutp` in both phases — so the charge on it *is* the
integrator's state, and the output at the end of a phase is that state plus
the summing-node voltage. Take an OTA input-referred noise `Vn` slow compared
with one cycle. At the end of phi1 the `Cs` top plates are at `vcm` and the
summing node is at `vcm + Vn`. In phi2 the top plates join the summing node,
still at `vcm + Vn`, and the bottom plates go to `vcm`. Charge conservation on
the summing node gives a per-cycle state increment of

    ΔV_Ci = (Csi + Csr)/Ci · Vn        (the summing-node parasitic Cp cancels)

while the static `v(vod)` noise gain is `1 + (Csi + Csr + Cp)/Ci`. `Cp`'s
charge does not change across the cycle — the OTA holds the summing node at
its own input offset in *both* phases — so it drops out of the increment but
not out of the static gain. On this sizing `Ci` is drawn equal to
`Csi + Csr`, so the two differ by very close to a factor of 2 in amplitude,
i.e. about 6 dB in power. That is the hand estimate in #140's body; this bench
measures it instead of asserting it.

**How it is measured.** `ampq` is the same clock state, the same deck body, the
same 45-point grid and the **same `1/C1` input referral** as `amp` — only the
probe node differs. So:

- the correction is **where the noise is read**, not a new referral constant.
  `INPUT_REFERRAL["ampq"] == INPUT_REFERRAL["amp"]` on purpose, and a unit test
  pins that: a per-cycle increment refers to the input by the same `C1` the
  signal does, so changing both would double-count;
- the per-corner `transfer` block is the ratio of the two band integrals, in
  which the common referral cancels. It is a **measured** transfer at each of
  the 45 corners, not one corner's value reused — the capacitor ratio, `Cp` and
  the OTA gain all move with corner;
- every integrate-phase noise source appears in both outputs with **its own**
  transfer, so the ratio is the composite the integrator actually accumulates.
  This is the reason not to measure an OTA-only factor and apply it to
  everything: noise entering at a `Cs` bottom plate transfers to `v(nqci)` and
  to `v(vod)` almost equally, while OTA-input noise does not, so a single
  OTA-derived factor would over-correct the switch part.

**Both bands are re-referred.** `transfer.power_ratio_db_by_band` reports the
baseband and the aliased parts separately, because the transfer is *not* the
same in the two: the aliased part extends past the closed-loop bandwidth, where
`v(nqci)` and `v(vod)` decouple. Neither part keeps the old
`1/C1`-at-`v(vod)` treatment — `ampq`'s own spectrum covers the whole swept
band — so #140's fallback (re-refer the baseband only and label the aliased
part as not re-referred) was not needed.

**What refutes it.** `transfer.hand_analysis_residual_db` is the measured
in-band ratio minus the `Csi + Csr`/(`Ci` + `Csi` + `Csr`) prediction with
`Cp` ignored, per corner. `transfer.implied_summing_node_cp_F` inverts the
measured ratio for the `Cp` that would explain it — a derived indicative
number, not an extraction, and quotable in band only because the device split
shows the OTA's own devices carry essentially all the in-band noise there.

**The budget is reported twice, not replaced.** `total_thermal_*` keeps the
pre-#140 static treatment and `total_thermal_accumulated_*` adds the #140 one,
against the **same** §5.3 values. `accumulated_vs_static_db` is the difference
the corrected read makes to each corner's margin.

## The per-device, per-mechanism split (issue #140)

`run_noise.py --devices` — one local `tt/1.800 V/27 C` corner.

ngspice emits a per-device, per-mechanism breakdown of the integrated noise
only when the noise statement carries a `pts_per_summary` argument, and `klt
sim` has no measurement form for those vectors
(`2AMLogic/klayout-tools#5553`). So this one corner is a raw `ngspice -b`,
wrapping the **committed** `integrator_noise_ampq.cir` in the
`.lib`/`.control`/`.end` a raw run needs: same circuit, same probes, same
`deck_sha256` as the grid run, so it is the grid's `tt` corner and not a
second, differently wired bench.

Four blocks are taken — `v(nqci)` and `v(vod)`, each over `1 Hz .. 20 kHz` and
`20 Hz .. 20 kHz` — so the split is directly comparable with the record's
`var_baseband_V2` / `var_audio_band_V2`, and the per-device accumulating/static
ratio is visible device by device.

**The one load-bearing detail.** Those vectors hold each contribution as an
**RMS in volts**, not a variance. The identity that closes is

    Σ_i v_i² == onoise_total²

and `closure_devices_rel` / `closure_mechanisms_rel` report exactly that
residual, gated at `1e-6`; `--devices` and `--record` both **refuse** rather
than record a split that does not close. Summing the vectors as if they were
variances over-counts by about 4e4 on this block, which is why the gate exists
rather than a comment.

`1overf` is flicker; every other mechanism ngspice emits (`id`, `rd`, `rs`,
`rg`, `rb*`) is thermal, and the gate-leakage shot terms (`ig*`) are zero
here. So `thermal_and_shot_V2` is the thermal share §5.3 actually allocates,
and `flicker_V2` is the part it has no line for.

**This block is one corner on purpose.** The 45-corner grid carries the
*transfer* at every corner; only the mechanism attribution is single-corner,
which is what #140's acceptance criterion asks for at minimum. It is an
attribution, not a budget number.

## Budgets (§5.3, unchanged)

| line | budget, in band | compared against |
|---|---|---|
| sampling-switch kT/C share | 4.5e-10 V² | `ktc.inband_V2` |
| total thermal share (switches + amplifier) | 9.0e-10 V² | `ktc + amp` |
| the same line, accumulating treatment (#140) | 9.0e-10 V² | `ktc + ampq` |

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

Issue #140 now **measures** that split, at one corner — see "The per-device,
per-mechanism split" above and `device_split` in `record-i140.json`. The
per-corner numbers across the grid are still thermal plus flicker, because the
split cannot ride on a `klt sim` request. The §5.3 line is still reported
against unchanged; a 1/f allocation is #138 step 2 / #142, not this bench.

## Running

    python3 -I sim/integrator-noise/run_noise.py --probe      # 1 corner each, local
    python3 -I sim/integrator-noise/run_noise.py --devices    # the per-device split, local
    python3 -I sim/integrator-noise/run_noise.py --record \
        --record-name record-i140.json                       # 3 x 45 corners, batch fleet

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

`--record` also runs the local `--devices` corner and **refuses to write a
record without it** (the split is an acceptance criterion of #140, so a record
cannot quietly ship without one). `--devices` on its own prints the split and
exits: no grid, no record. Exit status follows the **accumulating** verdict
after #140; the static one stays in the record beside it.

**Sharding a re-run (`--hosts N`).** The receipt's `job_ceiling` warns on this
grid: its conservative fully-serial bound (`options.timeout_s` 600 s x 45
units + overhead) exceeds the fleet's 3600 s whole-job ceiling, with
`recommended_hosts` 9. The recorded runs finished well
inside it, so they were submitted unsharded — but a re-run whose corner mix is
slower would be killed at the ceiling with **every** unit reported
`batch_job_timeout`, not just the slow one. Pass `--hosts 9` to split the
submission if that is a risk. Sharding is a submission choice, so it changes
neither the request file nor its `sha256`.

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
- `record-i140.json` — issue #140, the same grid plus the `ampq` variant and
  the one-corner device split. `record.json` is untouched and the `ktc` and
  `amp` numbers reproduce it **bit for bit** at all 45 corners, which is also
  the evidence that adding the `nqci` probes left the other two decks
  electrically unchanged.
  - **The hand estimate in #140 is confirmed, not refuted.** The measured
    in-band (baseband) transfer is **−5.71 to −5.65 dB** over the 45 corners,
    against the −6.02 dB that `(Csi+Csr)/(Ci+Csi+Csr)` predicts with `Cp`
    ignored: a residual of **+0.31 to +0.37 dB**, i.e. the estimate was right
    to within a third of a dB everywhere. The spread across 45 corners is
    0.06 dB, because the transfer is set by a capacitor ratio of two MIM
    capacitors drawn on the same layers, which tracks.
  - **The transfer is *not* the same in the two bands**, which is why they are
    reported separately: baseband −5.71 to −5.65 dB, but the aliased part
    **−9.34 to −6.40 dB**, a 2.9 dB spread, because that part extends past the
    closed-loop bandwidth where `v(nqci)` and `v(vod)` decouple.
  - **§5.3 still misses, by less.** The total thermal share misses at 45 of 45
    corners either way, but the miss narrows from 15.6–18.4 dB to
    **9.8–12.7 dB** (worst 1.68e-08 V² at `fs`/1.980 V/125 °C against
    9.0e-10 V²). The switch kT/C share still **passes at all 45**, unchanged
    (bit for bit: 2520 numeric values across the `ktc` and `amp` parts of all
    45 corners, none different from `record.json`).
  - **Where the remaining miss lives, measured under the new treatment.** The
    baseband part alone is 8.06e-09 to 1.56e-08 V² and over the 9.0e-10 V²
    line at **45 of 45** corners; the aliased part alone is 4.57e-10 to
    1.11e-09 V² and over it at **13 of 45**. So the baseband 1/f is the
    binding term — but removing it would still leave 13 corners missing on the
    aliased part alone, and removing the referral error does not close §5.3
    either. **#143 should assume neither is sufficient on its own.** (This
    supersedes the figure the curation carried over from `record.json`, where
    the aliased part was over the line at 45 of 45 under the old
    `1/C1`-at-`v(vod)` referral — the measured aliased transfer is −6.40 to
    −9.34 dB, rather more than the factor of 4 the hand analysis assumed for
    it.)
  - **`Cp` is implied at 150 to 181 fF**, consistent across the grid and
    physically plausible for the summing node.
  - **The flicker/thermal split, at `tt`/1.800 V/27 °C in band:** **99.79 %
    flicker**, 0.21 % thermal and shot. §5.3's thermal line is therefore being
    missed by a part that is almost entirely 1/f, which is the evidence #138
    step 2 / #142 need.
  - **Four devices carry 95.7 % of it**, all inside the OTA (the OTA's own
    devices are 99.996 % of the in-band accumulating noise): the input pair
    `XM1`/`XM2` at 28.1 % each **and the bias current sources `XMN1`/`XMN2`
    at 19.7 % each**. #138's hypothesis that the input pair dominates is
    therefore only **half** right — the pair is 56.3 %, not the whole story.
    The reason is in the geometry the record quotes beside each device:
    `XMN1`/`XMN2` are drawn W 2.0 / L 0.5, a gate area of 1.0 µm² against the
    pair's 8.0 µm², and flicker power goes as `1/(W·L)`. **Resizing the input
    pair alone therefore caps the achievable in-band improvement at about
    3.6 dB**, which is a result #143 needs before it picks a sizing.

## Limits

Listed in the record's `leaves_out`, and worth repeating:

- **No thermal/flicker split per device *across the grid*.** Issue #140 adds
  the split, but from one local corner: `klt sim` still has no measurement form
  for ngspice's per-device, per-mechanism vectors, so the 45-corner requests
  cannot carry it and the per-corner numbers in `corners` remain thermal plus
  flicker. Filed under the friction protocol as
  `2AMLogic/klayout-tools#5553`.
- **The accumulated increments are still i.i.d. per sampling event.** Issue
  #140 removed the part of the over-count that came from referring the
  non-accumulating summing-node excursion as though it accumulated, and that
  correction is measured per corner. What is still left out is the correlation
  *between consecutive accumulated increments*: `ampq`'s increments are
  treated as i.i.d., so the in-band effect of the amplifier's 1/f is still
  over-counted. There is no correlated-double-sampling benefit to claim here —
  this cell's phi1 reset is to `vcm`, not a CDS reset — but a
  correlation-aware treatment of the 1/f remains a separate piece of work.
- **`Cp` is not extracted.** `transfer.implied_summing_node_cp_F` inverts the
  measured in-band amplitude ratio for the summing-node parasitic, which is a
  derived indicative value: the ratio it inverts is the composite over every
  phi2 noise source. It is not quotable for the aliased part, where the phi2
  switches do matter.
- **One `Cp` term is left in, and it makes these numbers conservative.** For
  OTA input-referred noise the true per-cycle increment is
  `(Csi+Csr)/Ci · Vn`, while a *static* read across `Ci` gives
  `(Csi+Csr+Cp)/Ci · Vn` — `Cp`'s charge on `Ci` does not change across a
  cycle, so it leaves the increment but not this measurement. With the implied
  `Cp` that is about **+0.7 dB** of over-count
  (`device_split.ota_input_referred_transfer.inband.`
  `static_across_ci_over_counts_by_db`). It is left in rather than corrected
  out, because correcting it would *improve* the reported margin on the
  strength of a derived number.
- **The large-signal phi1 hold error of #147 is not in this transfer.** The
  transfer is small-signal about the operating point with no large differential
  input, so a large-signal `Sci` hold error does not enter it. #147's `Sci`
  condition (`Vgs = Vdda - vcm`) is worst at low `Vdda` and cold, so **if a
  per-corner transfer looks like an outlier at the 1.620 V/−40 °C corners,
  #147 is the known candidate rather than a new finding.**
- **The integrate phase's finite duration is not modelled.** The `amp` and
  `ampq` integrals run over the circuit's own noise bandwidth, not truncated to
  the 97.66 ns phase. #140 does not change this: `ampq` reads the accumulating
  quantity in a *static* phi2 state, which is the right statistics for noise
  slow compared with one cycle (where the whole flicker question lives) and
  still an over-count for the wideband part, where the finite phase and the
  sample-and-hold at the phi2 fall would shape it.
- No reference or bias noise (DR-005 boundary), no clock-jitter noise (model
  B's `jitter_rms_s`, not from this block), no mismatch (nominal grid, no
  Monte Carlo), no layout parasitics (DR-001 item 4).

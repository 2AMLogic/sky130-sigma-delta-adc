# sim/modulator-tran — short full-modulator transistor-level transient

**Simulated, transistor-level, on an anchor subset. Not an SNDR result and not
a row 2 claim.** This is the short full-modulator transient
[DR-001](../../spec/decisions/DR-001-evidence-split.md) item 2 names as the
cross-check vehicle, run on the seven
[DR-002](../../spec/decisions/DR-002-pvt-corners.md) anchor corners.

It runs `design/modulator/modulator.spice` with `design/ota/ota_fd.spice` and
`design/modulator/comparator/comparator.spice` — exactly the include list
`design/modulator/README.md` "Consuming the netlists" prescribes, and
deliberately *not* the standalone `integrator.spice` / `clkgen.spice`, which
the top-level netlist already defines — against ideal DR-005 boundary sources
(VCM 0.9 V, VREFP/VREFN 1.5/0.3 V, ibias 5 µA), a coherent single tone at
−6 dBFS, and the 5.12 MHz clock.

    python3 -I sim/modulator-tran/make_request.py     # regenerate deck + request
    python3 -I sim/modulator-tran/run_tran.py --probe # 1 local corner, no record
    python3 -I sim/modulator-tran/run_tran.py         # the 7 anchors, batch fleet
    python3 -I sim/modulator-tran/run_tran.py --record  # write record.json + samples/
    python3 -I -m unittest discover -s sim/modulator-tran -p 'test_*.py'

The runner refuses a PDK whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2) and refuses to overwrite an existing record (records are append-only;
use `--record-name`).

## Record length, and why it is this one

**1024 recorded modulator clocks** (200.0 µs) after **64 discarded start-up
clocks**, chosen and written into `make_request.py` *before the first corner
ran*, as DR-001 item 2 requires.

The choice is set by cost, measured on the dispatch host first: about **3.1 s
of ngspice per microsecond of transient** at tt/27 °C/1.80 V with a 1 ns
maximum timestep, i.e. about **0.61 s per modulator clock**. 1088 clocks is
~11 min at tt (the local `--probe` run took 11 min 30 s) and perhaps twice
that at a slow corner, which fits inside the batch fleet's 3600 s whole-job
ceiling with margin. One corner per batch job (`batch.max_units_per_job: 1`)
so each corner gets that budget to itself.

A 1 ns maximum timestep was checked against 0.2 ns on a 2 µs run: the
integrator outputs agreed to five significant figures, for ~30 % less wall
clock and a quarter of the stored timepoints.

### Fleet sharding

A batch job is killed at the fleet's whole-job ceiling (3600 s) with every
unit reported `batch_job_timeout`, and klt's pre-submit check uses the
fully-serial bound `options.timeout_s x units + 120`. Too *many* jobs is the
other failure: each one is an instance the shared Spot quota has to find.

The settings are sized from measured runtime, not guessed:
`max_units_per_job: 3` and `options.timeout_s: 1100` give a 3 420 s bound per
job, inside the ceiling, in **three** jobs for seven anchors.

The first run of this bench used one unit per job, sized before any fleet
runtime was known from this host's ~680 s per corner. Two things came out of
it:

- **The fleet is faster than this host, and varies between instances.** That
  run saw 270–324 s per corner; the run behind the committed record saw
  **441–606 s** (`record.json` carries each corner's `runtime_s`, and
  `summary.slowest_corner_runtime_s` the worst). The 1 100 s budget above is
  still ~1.8x the slowest corner recorded, and the spread is the reason not
  to cut it closer.
- **Seven single-unit jobs is seven instances, and the fleet refused them**
  with `batch_no_capacity` until a shard exhausted its 600 s capacity-wait
  budget and came back `lost_shard`. Three instances is a smaller ask for the
  same work — though it is not a cure: the three-job run lost a shard too,
  and `--resume` recovered it. On a busy fleet, expect to resume.

`run_tran.py` refuses to write a record while a `lost_shard` is outstanding —
a capacity refusal is not a result.

    python3 -I sim/modulator-tran/run_tran.py --resume   # only the lost anchors

`--resume` re-launches only the unfinished units, using the shard map a
previous run left under `.partials/klt-run/` (gitignored).

**Do not regenerate the deck or the request while a run is in flight.** klt
stages the request once at submission and the shard map carries a fingerprint
of what it staged — units, seed, netlist and settings. Re-running
`make_request.py` mid-flight (even for a comment) changes that fingerprint,
and `--resume` then refuses with `resume_fingerprint_mismatch` rather than
resuming against different bytes. That refusal is the right behaviour and it
is the only thing standing between a changed deck and a record that describes
something other than what ran, because **`environment.netlist_sha256` in a klt
report is computed client-side when the report is assembled**: a netlist
edited after submission is hashed there as though it had been simulated.

So the record binds itself three ways rather than trusting that field:

- `deck_sha256` / `request_sha256` over the committed files;
- `batch_request_fingerprint`, the staged request's own fingerprint;
- `klt` and `klt_git_commit` taken **from the report's provenance**, not from
  `klt --version` at record time — this is a shared host that re-provisions
  its tools under running work, so the two genuinely can differ.

## What it measures, and against what

Every measurement below carries `limits` and a `spec_row` tag in the `klt sim`
report, so the report itself says which spec row it grades.

| Measurement | Row | Limit | Where the limit comes from |
|---|---|---|---|
| `p_ana` | 13 | ≤ 1 mW | `spec/modulator-adc.md` row 13 |
| `o1_swing_pp`, `o2_swing_pp` | 11 | ≤ 1.39 V<sub>pp</sub> | `spec/modulator-adc.md` §5.4 |
| `phi1_edges` | 5 | exactly 1024 | the record length itself |
| `bs_edges` | 5 | ≥ 1 and ≤ 1024 | one decision per clock, at most |

**`p_ana`** is the time-weighted mean, over a whole number of clock periods,
of the power delivered by the VDDA source plus the two reference sources. The
5 µA bias current is drawn from `vdda`, so it is already inside the VDDA term.
The `vcm` source is reported as `p_vcm` and is **not** in the row 13 sum.
A second, independent route to the same quantity — `klt sim`'s own integration
of each source's energy over the same window — is recorded beside it, and
`run_tran.py` refuses a record whose two routes disagree by more than 0.1 %.

**Swing and the §5.4 reading.** §5.4 is the only swing figure the ratified
spec gives: the integrator outputs "stay well inside the ≈ 1.39 V<sub>pp</sub>
output swing `sky130-opamp` reports at its worst corner". That sentence does
not say whether 1.39 V<sub>pp</sub> is a differential or a per-node figure. It
is applied here to the **differential** integrator output, which is how
`design/ota/SIZING.md` "Swing vs spec §5.4" reads it (it compares ~2.3
V<sub>pp</sub> *differential* of static headroom against it). No new number is
introduced. The single-ended extremes (`o1p_max`/`o1p_min`, `o2p_max`/`o2p_min`)
are recorded beside the differential swing, **ungraded**, so the other reading
of the sentence and the headroom to the rails both stay visible. If the
differential reading is the wrong one, that is a spec clarification through
`spec/` with a decision record — not something this bench may decide by
loosening its own limit.

The graded swing is the **continuous-time** extreme over the window — what the
amplifier actually has to deliver. The per-clock values in `samples/` are the
*held* states and have a smaller peak-to-peak, because they skip the switching
transients between sample instants. Both are recorded; neither replaces the
other.

**Row 12** (supply 1.62–1.98 V) is covered by the anchor set spanning 1.620,
1.800 and 1.980 V, not by a limit of its own.

**`phi1_edges`** is also a record-admission gate, not just a limit: `phi1`
rises exactly once per modulator clock, so a window that does not contain
exactly 1024 of them is not a record of 1024 modulator clocks, whatever else
it measured.

## What it does **not** claim

- **No SNDR, and no row 2 claim.** An in-band figure needs bins inside the
  20 kHz band of row 1. 1024 modulator clocks give a bin bandwidth of 5 kHz on
  the bitstream and only 8 output samples after decimation by the OSR, so
  neither route resolves the band. Spec §1.2's row 2 claim is a B-model result
  with the DR-001 cross-check; this bench supplies the cross-check's
  transistor-level side as bitstreams and integrator waveforms, not as an
  SNDR. Whether DR-001's "short record" and 3 dB tolerance survive that is the
  cross-check sub-issue's finding, not this one's.
- **No settling, noise, charge-injection or comparator-offset extraction.**
  Those are the single-mechanism benches, on the DR-002 full grid.
- **Nothing post-layout and no Monte Carlo.**
- **It is a subset result.** Seven anchors, stated as a subset of the
  45-point grid everywhere it is reported.

## `samples/` — what the cross-check consumes

One file per anchor, committed, with its sha256 in `record.json`. Each holds,
for every one of the 1024 recorded clocks: the sample instant, the analytic
differential input `u[n]`, the bitstream (`bs_v` in volts and `y` as ±1), and
both integrators' differential outputs `o1d_v`, `o2d_v`. DR-001 item 3 accepts
the model only if "the integrator output waveforms agree", so a bitstream
alone would not be enough.

- **Sample instant**: clock *k*'s falling 50 % crossing of the `clk` source,
  `t = TRISE0 + (k + 0.5)/fs`. That is the end of the phi2 integrate phase and
  a few hundred ps *before* clkgen lowers phi2, so both integrator outputs
  carry the charge that clock transferred and are still driven.
- **Rebuilding `u[n]`**: the input is two `SIN` sources with zero delay and
  zero phase offset from `t = 0`, so
  `u(t) = 0.6014 · sin(2π · 15000 · t)` volts differential, exactly. Divide by
  the 1.2 V differential reference for model B's FS units. The record's
  `input_sequence` block states the tone, amplitude, phase, clock start delay
  and which edge samples the input.
- **Bitstream polarity**: `bs` high means the comparator decided `y = +1`
  (`bs` and `dp` are both buffered from the latch node `q`).
- `record.json` also carries the full bitstream **edge times** per anchor,
  from the `crossings` measurement, as an independent reconstruction path.

**A note for whoever writes the cross-check.** Do not expect sample-by-sample
bit equality between this bitstream and model B's. A single-bit delta-sigma
loop is chaotic: two loops fed the same `u[n]` but differing in initial state
or in any non-ideality diverge within a few clocks and then agree at about
chance. Feeding model B the committed `u_diff_v` from a zero initial state
agrees with the recorded `y` on 52 % of clocks — which says nothing about the
model, because the recorded window starts 64 clocks in. DR-001 item 3 asks
for in-band SNDR agreement and for the integrator output waveforms to agree,
not for matching bits; and the SNDR half of that is not reachable at this
record length (see "What it does not claim"). That tension is the
cross-check's finding to report, and may well be what revisits DR-001's
"short record" and its 3 dB tolerance.

These come back as `.meas` cards inline in the report, not as waveform
artifacts: a 200 µs transient's rawfile is far too large to retrieve for seven
corners, and the batch fleet then needs no artifact retrieval at all.

## Record validity gates

`run_tran.py` writes no record unless **all** of these hold (fixture tests in
`test_run_tran.py` pin each one; no EDA tools needed):

1. all seven anchors returned;
2. every anchor produced every scalar measurement — a fleet job that dies
   still returns one entry per point, so a count gate alone would let an empty
   grid become a "record";
3. every anchor returned a full 1024-clock sample set;
4. `phi1` rose exactly 1024 times in the window at every anchor;
5. the two independent routes to the VDDA power agree.

A corner that **fails a limit** is not one of these: it was simulated, so it is
recorded, and recorded as failing. No limit is loosened to make a corner pass.

## What this bench found

Written here so the bench's own README does not read as if it passed.

- **Row 13 (`P_ana`) passes at every anchor.** Worst 0.580 mW of the 1 mW
  limit, at `ff`/1.980 V/125 °C.
- **Row 5 passes at every anchor.** `phi1` rose exactly 1024 times in every
  record window, and the bitstream toggled 596–624 times.
- **Row 11 fails at every anchor.** Integrator 1's differential swing is
  2.95–3.50 V<sub>pp</sub> against §5.4's ≈ 1.39 V<sub>pp</sub>, and its
  single-ended output reaches within 67 mV of VDDA and 43 mV of ground at
  `tt` — it is railing, not merely swinging wide. The ideal behavioural model
  on the same input sequence predicts 3.06 V<sub>pp</sub>, so the demand is
  the loop's 0.5/0.5 coefficient scaling, not the amplifier. Filed as
  **#148**; fixing it is out of scope for this bench, which records the
  failing corners rather than loosening its limit.

Every corner therefore reports `status: "fail"` and `record.json` has
`"pass": false`. That is the recorded result, not a bench error.

## Known risks

- `#106` reports the input sampling switch about 46 % incomplete at
  ss/1.620 V/−40 °C, which is an anchor. If the modulator misbehaves there,
  that is this bench's finding to record.
- `#106` may regenerate `design/modulator/modulator.spice`. The record names
  the sha256 of every netlist it simulated; a record whose hashes do not match
  the tree is a record of a different netlist.
- The operating point of the assembled modulator is hard (a cross-coupled
  latch is bistable). `.options gmin=1e-9` is in the deck and gmin/source
  stepping warnings are expected; any corner that actually fails to converge
  is reported `error` and refused by gate 2 above.

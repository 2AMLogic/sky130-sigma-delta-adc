# DR-001 corrigendum 01: the cross-check record length, and the in-band SNDR leg

- **Status**: proposed amendment to [DR-001](DR-001-evidence-split.md) item 3;
  it changes one value (the cross-check record length) and states one rule
  (how the long B record is compared with it). Ratified by the usual path:
  two reviews, then the operator. This issue's PR does not ratify it, and
  until ratification DR-001's short-record text stands as written.
- **Date**: 2026-11-17
- **Amends**: DR-001 item 3 (`spec/decisions/DR-001-evidence-split.md`),
  specifically the record length of the short full-modulator transient and
  the sentence "over the same short record". Everything else in DR-001 —
  including the 3 dB tolerance, verbatim — is unchanged.
- **Decided by**: operator ruling (rjwalters, 2026-11-17, attended
  `/fleet:decide` round 20261116-r15, q106), option `a`: "lengthen the
  transistor-level cross-check record until in-band SNDR is computable, and
  keep DR-001's 3 dB gate". Options `b` and `c` (proxy gates as the closing
  leg) are declined by the same ruling.

## Context

DR-001 item 3 accepts model B at a corner only if the in-band SNDR of B and
the transistor-level transient agree within 3 dB over the same record. At
DR-001's committed short length, 1024 recorded clocks, that leg is not
computable: 5 kHz bins make the 20 kHz band of spec row 1 four bins wide,
while the 4-term Blackman-Harris main lobe (± 4 bins) covers all four — the
lobe-summed signal has no in-band noise bins to be compared against
(`sim/bmodel/xcheck-record.json`, `sndr_inband_db.reason`, as of
2026-11-17). Every B SNDR is therefore "uncross-checked" and row 2 stays a
declared gap. DR-001 itself flags the short record and the 3 dB tolerance as
its first-revisit items, and requires the revisit to be a new decision
record; the operator ruling picks the revisit and binds its shape.

## Decision

1. **Long record length: N_T = 4096 recorded clocks** (after the existing
   64 discarded start-up clocks; a 800.0 µs window at the 5.12 MHz clock,
   transient end ~812.7 µs). Per DR-001 item 2's discipline, the length is
   stated before the corner set ran, with its evidence:
   - At N_T the bitstream bins are fs/N_T = **1250 Hz** wide, so the 20 kHz
     band is bins 1..16; the coherent tone at 15 kHz is exactly **bin 12**;
     the 4-term Blackman-Harris main lobe (± 4 bins) covers bins 8..16; and
     **in-band noise bins 1..7 remain**. The lobe-summed signal / in-band
     noise split of spec §1.2 has bins to sum on both sides of the lobe: the
     leg is computable. It is thin (7 bins), and this record says so;
     widening it further is revisited with the post-layout re-run (DR-001
     item 4), not here.
   - **Why 4096 and not more** — measured cost, not preference. The probe
     run of issue #290 (one corner, tt/27 °C/1.80 V, 4160 clocks including
     settling, fleet job `klt-sim-56a43a043984`, posted on the issue before
     the corner set launched) measured **1104.6 s of fleet unit runtime**
     (~0.265 s/clock, ~0.86 GB peak RSS), against 441–606 s per 1088 clocks
     for the committed short run (~0.41–0.56 s/clock). 8192 recorded clocks
     extrapolate to ~3.4–4.6 ks per corner at those rates and 16384 to
     ~6.7–9.2 ks — past the batch fleet's 3600 s whole-job ceiling at every
     measured rate, and one unit's transient runtime is not reducible by
     sharding (sharding divides units per job, never one unit's runtime).
     4096 fits with margin: one corner per batch job (`max_units_per_job:
     1`, `timeout_s: 3300`, serial bound 3300 × 1 + 120 = 3420 s ≤ 3600 s),
     with the slowest anchor extrapolating to ~2.3 ks at the committed
     run's per-clock rates.
   - 4096 is also not the *smallest* useful length: 2^13 = 8192 clocks
     would leave ~23 in-band noise bins but does not fit the ceiling, and
     the next smaller power of two that fits (2048) leaves a single
     in-band noise bin (band bins 1..8, tone bin 6, lobe 2..10). 4096 is
     the longest band-resolving record the fleet can run per corner in one
     job.
2. **Window, tone, amplitude: unchanged from the committed bench.**
   Blackman-Harris 4-term; coherent tone, 15 kHz, bin 12 (12 cycles over
   4096 clocks), −6 dBFS (spec row 11's 0.5·VREF, the amplitude the
   behavioural record was taken at); the same 64 start-up clocks discarded;
   the same T-side per-clock sample grid. The bench is
   `sim/modulator-tran` with `make_request.py --long` /
   `run_tran.py --long` (deck `modulator_tran_long.cir`, request
   `request_long.json`, samples `samples-long/`, record `record-long.json`);
   the committed 1024-clock bench files are untouched — the short record
   remains valid evidence of what it recorded, and `record.json`'s
   deck/request sha256 bindings and the item-5 envelope's
   `xcheck-record.json` pin stay intact.
3. **B-vs-T comparison rule.** Model B is re-run on the T input sequence
   over the same 4096 clocks (the same construction as the committed
   cross-check: `run.py --xcheck` feeds B the committed `u_diff_v`
   unmodified), and both sides are put through the same window and the same
   bin bandwidth. The compared quantity is **in-band SNDR against in-band
   SNDR**: for each side, signal = the tone-lobe sum (bins 8..16), noise =
   the in-band noise bins (1..7), both lobe-summed per §1.2's estimator;
   the gate is |SNDR_B − SNDR_T| ≤ **3 dB, unchanged verbatim**. The
   existing N = 2^16 B records (`sim/bmodel/records/`) are **not**
   re-windowed: they cite this cross-check by corner, and a corner's B
   numbers are reported *cross-checked* only where this leg passes. A leg
   that fails is a model finding, not a relaxation of anything.
4. **The first cross-check record's proxy gates stay reported, not
   gating.** In-band *power* agreement, integrator span agreement and loop
   duty agreement remain in the record as auxiliary diagnostics (the
   operator declined making any of them the closing leg). With the SNDR leg
   computable, the DR-001 legs are: the in-band SNDR gate (this
   corrigendum), integrator span, loop duty.
5. **Corner set: the DR-002 anchor set (7 corners), as the committed
   cross-check record uses.** The operator ruling says "per DR-002 corner";
   this amendment reads that as the anchor set, because DR-002 itself names
   the anchor set for the expensive runs (the full-modulator transient
   among them) and reserves the full 45-point grid for the cheap
   single-mechanism runs. **This reading is the Curator's and Builder's,
   not a verified operator statement**; if the reviewers read "per DR-002
   corner" as the full grid, the amendment's corner-set paragraph is what
   changes — the length arithmetic and comparison rule do not depend on it.
6. **Append-only evidence.** The long T record, the long cross-check
   record, and every SNDR number in them follow DR-001 items 2 and 5: each
   number names source, record length, window, bin bandwidth, amplitude,
   corner and cross-check status; records are written once and never
   overwritten; every number is simulated, nothing measured.

## Alternatives considered

- **16384 recorded clocks** (the scoping proposal): ~55 in-band noise bins
  and a 3.2 ms window, but ~1.9–2.6× the fleet's whole-job ceiling per
  corner at measured per-clock rates — the whole set would report
  `batch_job_timeout` with no data. Not chosen; revisitable if the fleet
  ceiling rises or a slower bench is justified on its own.
- **Keep the 1024-clock record, adopt proxy gates as the closing leg**
  (operator options `b`/`c`): declined by the ruling; the cross-check stays
  SNDR against SNDR.
- **Loosen or re-interpret the 3 dB tolerance**: not proposed; the ruling
  keeps it verbatim, and DR-001 already names tolerance changes as new
  records.

## Spec lines affected

None directly: this amends a decision record (DR-001 item 3), not a row of
`spec/modulator-adc.md`. Row 2's gap statement in the manifest closes
corner-by-corner as the leg passes — that manifest edit is a separate,
later step once this amendment is ratified, and is not part of this
corrigendum.

## Consequences

- The transistor-level bench grows a second, long-record form; the short
  bench stays committed and cited (row 11's report, the T-extraction chain,
  and the existing cross-check record all bind to it).
- Row 2's remaining evidence path is now executable: once this amendment is
  ratified and the leg passes at a corner, that corner's B numbers stop
  being "uncross-checked" and the row 2 claim can cite them.
- #148 (integrator swing) and #138 (integrator-1 thermal noise) still
  invalidate the B parameters when they land; the long runs use whatever
  parameters are current at launch (the committed corner files as of this
  record) and say so, per the sequencing note on the issue.
- Compute follows DR-001 item 6: the corner set runs through `klt sim`'s
  batch backend, one corner per job, `--wait-for-capacity` on the submit.

## Provenance

- Operator ruling: rjwalters, 2026-11-17, issue #290 comment (option `a`;
  options `b`/`c` declined; the "measure one corner first" note).
- Probe: issue #290 builder comment, 2026-11-17 — 1104.6 s wall, unit
  runtime, 1 unit / 1 job (`klt-sim-56a43a043984`), tt/27 °C/1.80 V,
  `phi1_edges` 4096/4096, ~0.86 GB peak RSS; fleet per-clock rates from
  `sim/modulator-tran/record.json` `runtime_s` (441–606 s per 1088 clocks).
- Bin arithmetic re-derived from the bench constants as of this record:
  fs = 5.12 MHz; fs/4096 = 1250 Hz; band edge = 20000/1250 = 16; tone bin =
  15000/1250 = 12; Blackman-Harris 4-term lobe half-width ± 4 (sndr.py
  `LOBE`); in-band noise bins = 16 − 9 = 7.

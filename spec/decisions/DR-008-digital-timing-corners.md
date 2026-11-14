# DR-008: Digital-partition timing corners are the shipped liberty set; the block-boundary I/O budget is the assembled top's

- **Status**: proposed; ratified when the pull request carrying it (issue #131)
  is Judge-approved and merged
- **Date**: 2026-11-14
- **Decided by**: Builder agent, issue #131 (follow-up of #124, T1 item 5 /
  digital)

## Context

[DR-002](DR-002-pvt-corners.md) names 45 PVT points — {tt, ss, ff, sf, fs} ×
{−40, 27, 125 °C} × {1.62, 1.80, 1.98 V} — for **recorded analog results**. It
says corners "must come from what the PDK ships; none may be invented". No
ratified record states a corner set for the **digital** partition, and
`spec/README.md` requires a record "whenever a spec value or approach is set,
changed or scoped".

Two facts force the question. Both were read on 2026-11-14 from the tree this
record lands in.

**1. The standard-cell library cannot express 35 of the 45 points.**
`sky130_fd_sc_hd` in the pinned `sky130A` (built from open_pdks
`f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`, per the installed tree's `SOURCES`)
ships 18 liberty files and no more:

```
ff_100C_1v65  ff_100C_1v95  ff_n40C_1v56  ff_n40C_1v65  ff_n40C_1v76
ff_n40C_1v95  ff_n40C_1v95_ccsnoise
ss_100C_1v40  ss_100C_1v60  ss_n40C_1v28  ss_n40C_1v35  ss_n40C_1v40
ss_n40C_1v44  ss_n40C_1v60  ss_n40C_1v60_ccsnoise  ss_n40C_1v76
tt_025C_1v80  tt_100C_1v80
```

There is no `sf` or `fs` file at all, nothing above 1.95 V, nothing above
100 °C, no `tt` at −40 °C, no `ss` above 1.76 V, and `tt` is at 25 °C rather
than 27 °C. Six of the 18 (`ff_n40C_1v56`, `ss_100C_1v40`,
`ss_n40C_1v{28,35,40,44}`) are below 1.60 V, outside the spec's 1.62–1.98 V
supply range, and are not usable; of the twelve that remain, two
(`ff_n40C_1v95_ccsnoise`, `ss_n40C_1v60_ccsnoise`) are CCS-noise variants of
corners already in the list, leaving **ten distinct usable corners**. `klt sta`
and `klt signoff` grade exactly the corners a run declares, so **no additional
STA run can close this gap**: it is a property of the library, not of the
compute spent on it.

**2. The standalone decimator has no declared I/O timing budget.** Every corner
of `layout/digital/sta-decimator.report.json` reports
`constraint_completeness.status: "incomplete"` with
`unconstrained_endpoints.count: 17` (`dout[15:0]` and `dout_valid`) and
`unclocked_registers: 0`. #124 deliberately declared no
`input_delay_ns` / `output_delay_ns`: no ratified document states what the
decimator's consumer requires, and a fabricated number would be a timing
contract no spec backs.

## Decision

### 1. The digital partition's timing corner set is the ten shipped liberty corners

Recorded digital-timing results (Fmax, setup and hold slack, electrical rules)
are graded on the ten `sky130_fd_sc_hd` liberty corners at or above 1.60 V that
#124 declared, and on no others:

`tt_025C_1v80`, `tt_100C_1v80`, `ss_100C_1v60`, `ss_n40C_1v60`,
`ss_n40C_1v76`, `ff_100C_1v65`, `ff_n40C_1v65`, `ff_n40C_1v76`,
`ff_100C_1v95`, `ff_n40C_1v95`.

This is the closest available cover of the DR-002 grid at or above 1.60 V. Each
is a **stand-in** for a DR-002 point, not that point: the mapping, and the
direction in which each differs, is the table under "Which DR-002 point each
declared corner stands in for" in [`../../layout/README.md`](../../layout/README.md).
That table is the normative stand-in map; this record does not duplicate it.

**This record does not amend DR-002 or §2 of `modulator-adc.md`.** DR-002's 45
points remain the corner set for recorded *analog* results, and its rule that
corners come from what the PDK ships is what this record applies — the device
model library ships five process corners (`tt`, `ss`, `ff`, `sf`, `fs`), the
standard-cell library three (`tt`, `ss`, `ff`).

### 2. The other 35 DR-002 points are a declared, unclosable gap

They are recorded as **not evidenced**, permanently so under the pinned PDK, and
`measurements/characterization.md` reads them that way citing this record. No
verdict moves: T1 item 5 / digital stays met on the ten declared corners only,
and the 45-corner coverage is not claimed anywhere.

The 35 are: all 18 `sf` and `fs` points, and 17 of the 27 `tt`/`ss`/`ff` points
— `tt` at {27/1.62, 27/1.98, −40/1.62, −40/1.80, −40/1.98, 125/1.62,
125/1.98}, `ss` at {27/1.62, 27/1.80, 27/1.98, −40/1.98, 125/1.80, 125/1.98},
and `ff` at {27/1.62, 27/1.80, 27/1.98, 125/1.80} (°C / V).

### 3. The block-boundary I/O timing budget belongs to the assembled top

The standalone decimator report is **register-to-register timing only**, and
that is what it claims. The input and output delay budget is declared where the
consumer becomes real — the assembled ADC top (#122, with #29 and #35) — after
which `layout/digital/sta_request.json` gains
`constraints.input_delay_ns` / `output_delay_ns` (or the per-port
`input_delays` / `output_delays` maps) and the run is repeated. Until then
`constraint_completeness.status: "incomplete"` is the correct and expected
value, not a defect.

## Residual risk, per missing axis

Each entry says what the declared set does **not** bound. The nearest declared
datum is given where one exists; it is a reference point, not a bound.

- **No `sf` or `fs` liberty file (18 points).** Mixed-process skew — fast NMOS
  with slow PMOS, or the reverse — is unmodelled for the digital partition. For
  setup it is covered in effect, because `ss` is slow on *both* device types
  where a mixed corner is slow on only one, so no mixed corner's path delay
  exceeds the `ss` path delay; the declared worst setup slack is 157.898 ns of
  the 195.3125 ns period at `ss_n40C_1v60`, 80.8 % of the period in hand.
  **Hold is not covered by that argument**: hold depends on the *difference*
  between a launch and a capture path, not on both being slow, and a mixed
  corner can make one fast while the other is slow — which neither `ss` nor `ff`
  reproduces. The declared worst hold
  slack is 0.25861 ns at `ff_n40C_1v95`, and nothing bounds how much of that a
  mixed corner consumes.
- **Nothing at 1.98 V; `ff_*_1v95` is 30 mV short, in the optimistic direction
  for hold.** A higher supply makes cells faster, which shrinks hold margin, so
  the 1.98 V hold margin is extrapolated from the 0.25861 ns at
  `ff_n40C_1v95` rather than bounded by any shipped file. This is the single
  most exposed point in the declared set. For setup the same 30 mV is
  pessimistic, so setup at 1.98 V is bounded.
- **Nothing above 100 °C against the 125 °C bound.** At 1.60 V the library is
  *slower cold than hot* — the committed report gives Fmax 26.73 MHz at
  `ss_n40C_1v60` against 31.11 MHz at `ss_100C_1v60` — so at the low-supply end
  the binding setup corner is the −40 °C file that **is** declared, and
  extrapolating to 125 °C from the 100 °C file goes in the faster direction.
  What 125 °C leaves unbounded is therefore not the setup headroom but
  temperature-driven hold degradation and the electrical-rule margins
  (transition and capacitance limits), neither of which any shipped file
  reaches.
- **No `tt` at 27 °C; `tt_025C_1v80` is at 25 °C.** A 2 °C offset on the
  typical corner, the smallest gap in the set, and the only axis where the
  substitution is within the noise of the model's own accuracy.
- **No `ss` above 1.76 V inside the supply range**, so `ss` at 1.80 V and at
  1.98 V are not expressible. `ss` at 1.62 V is graded by a 1.60 V stand-in,
  20 mV low — pessimistic for setup, so that substitution is conservative.
- **No 27 °C point of any process except `tt`.** Room temperature is not graded
  for `ss` or `ff`; both are bracketed by their −40 °C and 100 °C files, which
  is the usual reading, but it is bracketing rather than a graded point.

## Alternatives considered

- **Derive the missing 35 corners (`klt characterize`, or liberty
  interpolation), and declare what the derived files are worth.** Rejected, on
  three grounds. First, `klt characterize` at the pinned 0.8.0 is **combinational
  arcs only** and **one corner per invocation** (`klt characterize --help`,
  "Scope: one corner per invocation, combinational arcs only"). Setup and hold on
  this design are register-to-register, so the sequential arcs that bind the
  result are exactly what it cannot produce — a derived library would be missing
  the numbers the gap is about. Second, 35 corners of the cells a 5 390-instance
  design uses is a large fleet job. Third, and decisively, its product is liberty
  **this repo invented**, which is what DR-002 rules out ("none may be
  invented"); an interpolated 1.98 V file would be the weakest possible evidence
  at the one point where the declared set is most exposed.
- **Amend DR-002's grid so the whole converter uses points the standard-cell
  library can express.** Rejected. DR-002 governs analog results, where the
  device model library *does* ship all five process corners and the supply axis
  is continuous; narrowing the analog grid to suit the digital library would
  throw away evidence that is cheap to obtain, and ratified records are
  superseded, never edited.
- **Leave both limits as README prose, as #124 left them.** Rejected.
  `spec/README.md` requires a record when an approach is scoped, and the prose
  carried no owner: "the 35 uncovered DR-002 points are tracked in #131" turned
  an unclosable gap into an open issue that could never close.
- **Declare an `output_delay_ns` for the decimator now, so
  `constraint_completeness` reads `complete`.** Rejected. No spec row states an
  output timing requirement for `dout` / `dout_valid` — §2's only load line is
  "the decimation filter's input; no off-chip load is specified". A number
  chosen to make a field read `complete` is a contract the spec does not back,
  and it would be graded as evidence.

## Spec lines affected

None. §2 and rows 1–14 of `modulator-adc.md` are unchanged, and DR-002 is
unchanged. This record scopes the *approach* by which the digital partition's
timing is graded; it sets no spec value.

## Consequences

- `measurements/characterization.md` reads the 35 points as a declared gap
  citing this record, not as pending work. Row 6's "Remaining" column names the
  gap rather than an issue that can close it.
- **A declared gap is machine-checkable, not prose.**
  `attestation/item8_envelope.py` gained a third decimator status,
  `declared-gap`, which is accepted only when the row cites an existing
  `spec/decisions/DR-NNN-*.md` and cites no evidence file; the record is bound
  into `attestation/item8-envelope.json` by sha256, so editing this record
  without regenerating the envelope fails CI. A gap may therefore not be
  declared in this repo without a ratified record behind it, and a declared gap
  can never read as evidence. The grammar is covered by
  `attestation/test_item8_envelope.py`.
- Because a declared gap is outside the graded set by this record, it does not
  hold the item-8 envelope at `fail`. That is a deliberate consequence: if
  `declared-gap` were treated as owed work, item 8 could never pass however much
  evidence landed, which would make the envelope's verdict uninformative rather
  than honest.
- Digital-timing results stay met on the ten declared corners only.
  `t1_met_count` does not move (9 before and after), and the item-8 envelope's
  `status` stays `fail` for the reasons it already failed: seven `partial` spec
  rows, rows 13 and 14 `pending`, and the decimator power row pending on #33.
- The decimator's `constraint_completeness: "incomplete"` is an expected value
  for the standalone block. The first run that may legitimately report
  `complete` is the one made under the assembled top's declared I/O budget
  (#122 / #29 / #35).
- **This gap reopens if the PDK pin moves.** If a later `sky130A` ships
  additional liberty files — `sf`/`fs`, anything above 1.95 V or above 100 °C —
  the declared set is re-derived against it and this record superseded. The
  corner names are re-checked at every pin bump, as DR-002 already requires.
- A future record may close the gap by a route this one rejects (vendor-supplied
  liberty at the missing points, or a characterization flow whose output the
  spec accepts as evidence). Closing it is a different and much larger piece of
  work than declaring it.

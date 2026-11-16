# DR-007: integrator coefficient rescale, C1 = C2 = 0.3 (issue #148)

- **Status**: **proposed; NOT ratified, and part of it needs the operator.**
  The coefficient rescale (below) is a design change inside the ratified spec
  and is ratified by the usual Judge-approved merge. The **swing budget** is
  not: no value in `spec/modulator-adc.md` §5.4 can be met (see "Findings"),
  so any budget this record could name is either a reading of §5.4 or a new
  limit, and agents do not relax the ratified spec. The spec is **unchanged**
  by this record. Issue #148 stays open until the operator rules on "Open
  decision for the operator".
- **Date**: 2026-11-16
- **Decided by**: Builder agent, issue #148
- **Evidence**: all **simulated**. Nothing here is measured.

## Context

`sim/modulator-tran/record.json` (issue #125) showed integrator 1's
differential output swinging 2.95–3.50 V<sub>pp</sub> at the seven DR-002
anchors against §5.4's ≈ 1.39 V<sub>pp</sub>, with its single-ended output
within 67 mV of VDDA and 43 mV of ground at `tt`. The cause is the loop's
coefficients, not the amplifier: model B with `C1 = C2 = 0.5` and no swing
limit predicts 3.06–3.28 V<sub>pp</sub> on the same input.

## Findings that force the decision

Model B (ideal parameters, no swing limit), −6 dBFS = spec row 11's
0.5·VREF, 1 048 576 modulator clocks, band [0, 20 000] Hz, `sinc³` by 64,
`sndr.sndr_db`; 1 FS = VREF = 1.2 V differential:

| `C1` | `C2` | int 1 (V<sub>pp</sub>) | int 2 (V<sub>pp</sub>) | SNDR (dB) |
|---|---|---|---|---|
| 0.5 | 0.5 | 3.279 | 2.509 | 85.78 |
| 0.35 | 0.35 | 2.334 | 1.215 | 84.40 |
| **0.3** | **0.3** | **2.113** | **1.030** | **83.26** |
| 0.3 | 0.4 | 2.113 | 1.373 | 83.26 |
| 0.28 | 0.3 | 2.033 | 1.027 | 82.22 |
| 0.25 | 0.5 | 1.942 | 1.713 | 80.12 |

(the 0.25 row is the issue's own sweep; the others re-run here. The 0.5/0.5
row is 0.57 dB under the issue's 86.35 because this run's tone/warm-up
convention differs; the recorded row-2 figure uses the longer record below.)

1. **SNDR depends on `C1` only.** `x2` feeds a `sign()` decision, so scaling
   `C2` leaves the ideal bitstream unchanged (0.3/0.3 and 0.3/0.4 agree to
   the digit). `C2` is therefore a free swing knob (at the price of making
   FS-unit comparator offset and hysteresis look larger against `x2`).
2. **`C1` ≈ 0.25 is a floor set by row 2**: +0.12 dB over 80 dB with every
   non-ideality still to be paid for.
3. **At that floor integrator 1 still swings 1.94 V<sub>pp</sub>**, so no
   coefficient scaling satisfies §5.4's 1.39 V<sub>pp</sub> read as
   differential while meeting row 2. Integrator 2 can (0.3 → 1.03). The
   differential reading of §5.4 is therefore unachievable at the 80 dB
   target, and an agent may not resolve that by choosing a number.

## Decision (coefficients)

**`C1 = C2 = 0.3`**, realised by raising `Ci` from 2.000 to **3.334 pF**
(`cap_mim_m3_1`, 40.64 × 40.64 µm; ratio 1.000/3.334 = 0.29993) with `Cs`
held at 1.000 pF, in the one integrator cell used twice. Moved together in
one change: `design/integrator/integrator.sch`/`.spice`,
`design/modulator/modulator.sch`/`.spice`, `sim/bmodel/model.py` `C1`/`C2`,
`design/integrator/SIZING.md`, `design/modulator/README.md`.

`C1 = 0.3` is chosen as a compromise between swing and the row-2 margin it
leaves, not derived from a ratified budget (there is none). `C2 = C1` rather
than the 0.3/0.4 candidate in the issue: one cell, no schematic split, and
integrator 2 inside even §5.4's 1.39 V<sub>pp</sub> in the model.

### Two paths priced

| | Ci growth (chosen) | Cs reduction (rejected) |
|---|---|---|
| Change | `Ci` 2.000 → 3.334 pF | `Cs` 1.000 → 0.6 pF, `Ci` unchanged |
| Cost | integrating-cap area 987.8 → 1650.8 µm² each, 3 951 → 6 603 µm² for the two cells, **+67 %** (nominal, to be confirmed at layout) | kT/C: §5.3's 4 dB margin at 1 pF falls by 10·log10(1/0.6) = 2.2 dB to about 1.8 dB |
| Why | pays area, which is only a floorplan question (DR-004) | pays the one noise budget no bench has yet priced (#126, #127 open); rejected for that reason |

Floorplan consequence against DR-004: +2 650 µm² of MIM capacitor in the
analog partition; MIM sits over the integrator cell, so the growth is in the
analog block's footprint, not a new partition. Not yet placed.

### Margin over row 2 after the rescale

Ideal model B, new record
`sim/bmodel/records/20261116T231841Z-f8b2fa44.json`: **83.34 dB** peak
(−6 dBFS, 2^16 output samples = 4 194 304 modulator clocks, bin 1.221 Hz,
band [0, 20 kHz], model B, ideal parameters), **+3.34 dB over row 2** (was
86.17 dB, +6.17 dB). The deficit to §5.1's 94.24 dB ceiling widens from 7.98
to 11.32 dB (N = 2^13, pinned in `test_bmodel.py`); #108 still owns why the
ideal loop is below the ceiling at all. **That 3.34 dB is the entire budget
for OTA finite gain, settling, kT/C, charge injection, comparator offset and
jitter** (#126, #127 and siblings). Whether it is enough is **not measured**
and is the central open risk. If the non-idealities do not fit, the cheaper
lever is a larger `C1` (more swing), not a smaller one.

## Transistor-level re-run of the #125 bench

`sim/modulator-tran/record-c0p3.json` (+ `samples-record-c0p3/`), same bench,
same seven DR-002 anchors, 1024 clocks after 64 start-up clocks, batch fleet.
`record.json` and `samples/` are untouched. Graded limits unchanged
(§5.4's 1.39 V<sub>pp</sub>), so **every anchor still reports `fail`**:
that is the recorded result, not a bench error.

| anchor | int 1 was | int 1 now | int 2 was | int 2 now |
|---|---|---|---|---|
| `tt`/1.800/27 | 3.362 | 2.475 | 2.154 | 1.567 |
| `ss`/1.620/125 | 2.950 | 2.297 | 1.756 | 1.545 |
| `ss`/1.620/−40 | 3.056 | 2.275 | 2.001 | 1.384 |
| `ff`/1.980/−40 | 3.500 | 2.530 | 2.256 | 1.605 |
| `ff`/1.980/125 | 3.442 | 2.522 | 2.233 | 1.609 |
| `sf`/1.800/27 | 3.382 | 2.476 | 2.218 | 1.559 |
| `fs`/1.800/27 | 3.278 | 2.401 | 2.087 | 1.589 |

(V<sub>pp</sub> differential, continuous-time extreme.) Worst integrator 1 is
2.53 V<sub>pp</sub>, down 28 % from 3.50, and the output no longer reaches the
rails: at `tt` the single-ended output spans 0.280–1.533 V, 0.267 V from VDDA
and 0.280 V from ground (was 67 mV and 43 mV). Row 13 passes at every anchor
(worst 0.596 mW of 1 mW at `ff`/1.980 V/125 °C, was 0.580 mW), so the larger
`Ci` load did not break power. Row 5 holds (`phi1` 1024 edges everywhere);
the clock generator and supply span are untouched.

**The transistor-level swing is about 20 % above the model's** (2.475 vs
2.113 V<sub>pp</sub> at `tt`), not the 10 % seen at 0.5/0.5 where the circuit
was railing. Why is not diagnosed here. It is exactly what DR-001 item 3's
integrator-waveform cross-check exists to examine, and `sim/bmodel/xcheck.py`
has not been re-run on the new samples (see Consequences).

## Open decision for the operator

§5.4 gives one number, 1.39 V<sub>pp</sub>, and does not say whether it is
per-node or differential. Measurement now bounds the choice:

1. **Differential reading stands**: not achievable with this architecture at
   80 dB (finding 3). Row 11 cannot pass; the spec needs a change. Not
   something an agent may do.
2. **Per-node reading** (1.39 V<sub>pp</sub> per output node): integrator 1
   passes at every anchor. The recorded single-ended spans (`o1p_max -
   o1p_min`, which is a continuous-time extreme on the p side only) are at
   most 1.279 V<sub>pp</sub> (integrator 2: 0.812). That is ungraded in the
   bench and covers one node only. `design/ota/SIZING.md` independently gives
   ~2.3 V<sub>pp</sub> differential static headroom, a one-bias-point hand
   calculation, not a simulated gain-compression result; integrator 1's
   differential swing is above it at 5 of 7 anchors (2.40-2.53) and at it at
   the other two (2.28, 2.30). **A simulated OTA swing / gain-compression
   result is needed before any budget is ratified on that basis.**
3. **Reduce the swing further**: needs a smaller `C1`, which row 2 forbids
   below about 0.25.

The operator is asked to choose between a spec clarification (reading 2,
with a simulated OTA swing figure to back it) and a spec change. Until then
the bench keeps grading 1.39 V<sub>pp</sub> and says `fail`.

Rejected: rescale to 1.39 V<sub>pp</sub> differential (infeasible, above);
raise the OTA's swing (1.8 V supply); change only `model.py` (diverges model
from netlist and breaks the DR-001 cross-check).

## Consequences

- **Stale evidence, not edited** (append-only): `sim/bmodel/xcheck-record.json`,
  `xcheck-sides/`, `corners/` hashes, `item5-model-run.json`,
  `attestation/item8-envelope.json` and the item-9/10 inventories bind
  `model.py`, the netlists or `record.json` by sha256 and describe the
  0.5/0.5 design. They need regenerating by follow-up issues; this record
  does not do it. Earlier row-2 figures (86.17 dB and the corner records)
  describe the old coefficients.
- Settling, charge-injection and noise benches (`sim/integrator-*`,
  `sim/ota-settling`) were run at `Ci` = 2 pF. The larger `Ci` lowers the
  feedback factor; they must be re-run (SIZING.md says so).
- A `klt netlist --check` byte comparison is not possible on this host (no
  `PDK_ROOT`); `design/attest/check_analog_netlists.py` reports both edited
  netlists fresh against their schematics.
- Suspected origin of 0.5/0.5 ("fixed Boser-Wooley coefficients",
  `model.py`) was not traced to a source.

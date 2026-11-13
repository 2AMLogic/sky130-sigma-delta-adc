# sim/integrator-settling — integrator + ota_fd settling bench (issue #53)

**Simulated, transistor-level** (ngspice on `design/integrator/integrator.spice`
with `design/ota/ota_fd.spice`; not the behavioural model). Question: does the
97.66 ns integrate phase (spec row 5) close to 0.01 % (DR-005) for the full
integrator cell, with both sampling caps on the summing node (beta = 0.496,
hand-calc in `design/integrator/SIZING.md`)?

**Answer: for `int1` (case B), yes, after the issue #92 switch fix; for `int2`
(the case-A load bound), no.**

| Record | Cell | `int1` | `int2` | Vdda = 1.620 V |
|---|---|---|---|---|
| `record.json` | as built (#53) | 29/45 | 10/45 | **0/15 both variants** |
| `record-i92.json` | with the #92 switch fix | **45/45** | 13/45 | **15/15 `int1`** |

Both are the 45-point DR-002 grid per variant (90 points each), all simulated
on the batch fleet, nothing measured. The 1.620 V collapse `record.json` shows
was the cell's `vcm`/summing-node switches losing their overdrive at the low
rail, not the OTA -- see "Mechanism at 1.620 V" below. `int2`'s residual is an
open item against the comparator input capacitance, not a passing result; it is
stated in `design/integrator/SIZING.md` and nothing about it relaxes DR-005.

## Bench (`integrator_settling.cir.tmpl` -> `integrator_settling_{int1,int2}.cir`)

The full cell, including switch Ron and the DAC cap on the summing node.
Boundary (DR-005): VCM 0.9 V, VREFP/VREFN 1.5/0.3 V, ibias 5 uA, all ideal.
Stimulus: vin diff +0.6 V and `dn` = 1 (y = -1), the worst-case first-integrator
step: ideal charge transfer `0.5 * (0.6 + 1.2)` = 0.9 V differential
(0.45 V per side, the same step as `sim/ota-settling`).
Phi1/phi1b/phi1e/phi2/dn are behavioural rail-to-rail sources on Vdda with
200 ps edges and no non-overlap generator (clock generation is out of scope).
A bench-only ideal reset (1 ohm, across `Ci`, closed until 31 ns) starts `Ci`
discharged; the cell has no reset. phi2 stays high after its edge at 35 ns; the
tail gives the settled value.

**Stage phasing.** The integrators are delaying (`sim/bmodel`): while integrator
1 integrates (phi2) integrator 2 only samples in phi1, so its `Sin` is off and
integrator 1's output sees only parasitics: **case B** of `SIZING.md`
(236 uS needed). The `int1` variant uses 0.1 pF per side. The `int2` variant
adds 1 pF per side, the **case A** bound (449 uS needed), because the
comparator input and feedback network loading is not defined yet. Both use the
same cell and step; `int2` is a load bound, not a separate circuit.

## Measurements

Same definitions as `sim/ota-settling`, sampled 97.66 ns after the phi2
mid-edge: `err_phase` (**pass <= 1e-4**), `t_1e4/t_1e3/t_1e2`, `slope_pk`,
`t_slew`, `slew_frac`, and the reference-validity gates `end_ripple_rel`
<= 1e-3 and `step_err_vs_ideal` <= 0.05.

## Result (record.json, 2026-11-13)

Jobs `klt-sim-8ea68b4baa34` (int1) and `klt-sim-761cf51b44ee` (int2), AWS batch
fleet, ngspice 47, klt 0.9.2.dev885+ge4c446bd91f2, open_pdks
f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7. Both receipts read `state: failed`:
that is `klt sim` exit code 3, **corners missing their limits**, not a fleet
failure — all 90 points returned measurements.

Worst `err_phase` per process corner (all at 1.620 V / -40 C, the binding
PVT point for both variants):

| Process | int1 pass | int1 worst | int2 pass | int2 worst |
|---|---|---|---|---|
| tt | 6/9 | 0.672 | 2/9 | 0.679 |
| ss | 6/9 | 0.739 | 2/9 | 0.746 |
| ff | 6/9 | 0.551 | 2/9 | 0.562 |
| sf | 6/9 | 0.485 | 4/9 | 0.497 |
| fs | 5/9 | **0.777** | 0/9 | **0.784** |

The grid separates cleanly by **supply**, not by process:

| Vdda | int1 pass | int2 pass |
|---|---|---|
| 1.620 V | 0/15 | 0/15 |
| 1.800 V | 14/15 | 2/15 |
| 1.980 V | 15/15 | 8/15 |

At 1.620 V every corner misses 1e-4, but the failure is not uniform across the
supply corner. At the **8 worst corners per variant** the cell never settles:
`t_1e4` sits at 299-300 ns (the whole transient window) and the `end_ripple_rel`
gate is violated (the output is still moving when the window ends), so
`err_phase` there reads "never settled", not a precise residual. Those 8 are
all five process corners at -40 C, plus tt/ss/fs at 27 C. At 7 of them the
`step_err_vs_ideal` gate is violated too; the exception is tt/27 C, where the
step has reached 0.89 V of the ideal 0.9 V by the end of the window
(`step_err_vs_ideal` 0.011 int1, 0.012 int2, inside the 0.05 gate).
At the **remaining 7** both gates hold, `t_1e4` is 107-257 ns (int1) and
148-273 ns (int2), and `err_phase` is 2.1e-4 to 0.107 (int1) and 2.5e-3 to
0.151 (int2) — a real but bounded residual, not a dead cell. Across all 15,
`err_phase` spans 2.1e-4 to 0.777 (int1) and 2.5e-3 to 0.784 (int2). Among the
37/45 corners per variant where both gates hold at any supply, the worst
`err_phase` is 0.107 (int1) and 0.151 (int2).

## Result (record-i92.json, 2026-11-13) — with the #92 switch fix

Jobs `klt-sim-7c3fda8ee3bb` (int1) and `klt-sim-f11099d8ec3d` (int2), AWS batch
fleet, ngspice 47, klt 0.9.2.dev887+gec7400b7d8e5, open_pdks
f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7. `integrator_netlist_sha256`
`18fc51475f667eea993fbef4e9a3abe7eaa35863ae88f86c25bfb56bc4074d53`;
`ota_netlist_sha256` `7f4724e9631c05760bc98d161100c41b06928b98e0526c027e6a9271d70f7977`,
**byte-identical to `record.json`'s** -- `design/ota/ota_fd` did not change, so
`sim/ota-settling/record-i51-rcm2M-cff100f.json` (45/45) still stands and was
not re-run. Both receipts read `state: failed`, which is `klt sim` exit code 3
(corners missing their limits), not a fleet failure; all 90 points returned
measurements.

**`int1` (0.1 pF, case B): 45/45, every corner inside 1e-4.**

| Vdda | `int1` pass | worst `err_phase`, and where |
|---|---|---|
| 1.620 V | 15/15 | 5.89e-5 at `ss`/-40 C |
| 1.800 V | 15/15 | 4.16e-5 at `sf`/125 C |
| 1.980 V | 15/15 | 3.07e-5 at `ss`/125 C |

The binding corner is `ss`/1.620 V/-40 C at 5.89e-5, a 1.7x margin on the 1e-4
level. `t_1e4` is 52.5-92.5 ns across all 45 corners, i.e. the cell now reaches
the 1e-4 level **inside** the 97.66 ns phase everywhere rather than at 300 ns.
At the nominal tt/1.800 V/27 C corner `err_phase` is 4.56e-6, slightly better
than the 6.4e-6 the as-built cell measured there.

**`int2` (1.1 pF, case-A bound): 13/45 — still failing, and not acceptable.**

| Vdda | `int2` pass | worst `err_phase`, and where |
|---|---|---|
| 1.620 V | 1/15 | 1.42e-3 at `fs`/125 C |
| 1.800 V | 5/15 | 9.34e-4 at `fs`/125 C |
| 1.980 V | 7/15 | 7.74e-4 at `fs`/125 C |

Worst overall 1.42e-3, against 0.784 as built -- a 550x improvement in the
worst residual, and the character of the failure has changed completely: the
`int2` residual is now a bounded settling shortfall spread fairly evenly over
PVT (1.1e-4 to 1.4e-3, worst at 125 C), where before it included eight corners
that did not settle at all. Nominal tt/1.800 V/27 C is 1.06e-4, against 2.28e-4
as built.

**Both validity gates now hold at all 90 points** (`end_ripple_rel` <= 6.5e-6
and 7.3e-6, `step_err_vs_ideal` <= 0.013, against limits of 1e-3 and 0.05),
where `record.json` violated them at 8 corners per variant. So every
`err_phase` in this record is a real residual, not a "never settled" reading.

Whether case A applies at all depends on the comparator input capacitance,
which is still not extracted; 1 pF is a bound, not a measurement. `int2` is
therefore an open item, tracked in `design/integrator/SIZING.md`.

### Mechanism at 1.620 V — the `vcm` / summing-node switches (issue #92)

**Established.** `run_diag.py` -> `diag-i92.json` runs this bench's circuit at
the single binding corner `fs`/1.620 V/-40 C with internal node and device
probes, against both the netlist `record.json` was taken on and the fixed one.
Simulated, one corner, local; not measured.

The twelve `vcm`/summing-node switches (`XSbi_*`, `XSci_*`, `XSti_*`,
`XSbr_*`, `XScr_*`, `XStr_*`) were NMOS-only, gated rail-to-rail on `Vdda`
while passing `vcm` = 0.9 V, so their overdrive is `Vdda - vcm - Vth`. The
probe measures, as built at that corner:

| Quantity | Measured | Meaning |
|---|---|---|
| `Sti` Vgs | 0.713 V | `Vdda - vcm`, and it shrinks with `Vdda` |
| `Sti` Vth | **0.924 V** | 0.9 V source-body bias plus -40 C |
| overdrive | **-0.211 V** | the switch is in subthreshold |
| `Sti` / `Sbi` Id | 111 nA / 116 nA | leakage, not a conducting switch |
| drop across `Sbi` | **+0.281 V** | bottom plate stranded at 1.181 V, not `vcm` |
| `step_dv` | 0.068 V | against an ideal 0.9 V |
| `err_phase` | 0.776 | reproduces the 0.777 in `record.json` |

The other three hypotheses the previous revision of this section left open are
**refuted** by the same probe:

- **Not the OTA's input or output common mode.** The summing nodes sit at
  0.9069 / 0.9079 V and the output common mode at 0.8991 V -- all correct. The
  OTA sees only 0.97 mV of differential input error, so it has nothing to
  drive; the charge never arrives.
- **Not slew limiting.** The tail delivers 67.5 uA and the input pair splits it
  33.8 / 33.6 uA -- balanced, i.e. the OTA is in its linear region throughout.
  A slewing OTA puts the whole tail in one branch (which is exactly what the
  *fixed* run shows at the phi2 edge: 76.3 uA of 76.8 uA in `M1`, then back to
  35.6 / 34.0 uA by mid-phase). The `slew_frac` of 0.82-0.89 this record
  reports at those corners is an artifact of the metric: with `step_dv`
  collapsed to 0.068 V, `slope_pk` is tiny and the "80 % of peak slope" window
  spans most of a nearly flat waveform.
- **Not a PMOS-limited path.** That hypothesis read the process ordering
  (`fs` and `ss` worst, `sf` and `ff` best) as pointing at a slow PMOS, on the
  assumption that sky130's first corner letter is the NMOS. **It is the other
  way round.** In the pinned models (`open_pdks`
  f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7) the second letter is the NMOS:

      grep vth0_diff_0 .../sky130_fd_pr__nfet_01v8__{tt,ff,ss,fs,sf}.corner.spice
      grep -E 'vth0|toxe ' .../sky130_fd_pr__pfet_01v8__{fs,sf}.pm3.spice

  gives NMOS `vth0_diff_0` of fs **+0.0495** > ss +0.0302 > tt -0.0244 >
  ff -0.1007 > sf **-0.1087** V, so `fs` has the *slowest* NMOS and `sf` the
  fastest; the PMOS goes the other way (`fs` 4.01 nm `toxe` and |vth0| 1.048 V
  versus `sf` 4.45 nm and 1.069 V, i.e. `fs` is the *fast* PMOS). The `int1`
  `err_phase` ordering at 1.620 V/-40 C -- fs 0.777 > ss 0.739 > tt 0.672 >
  ff 0.551 > sf 0.485 -- is therefore monotonic in **NMOS** Vth, which is what
  an NMOS switch limit predicts and the opposite of what a PMOS limit would.

**Cross-check that it is the switches and nothing else:** replacing just those
twelve switches with ideal 1 ohm switches, leaving the same `ota_fd`, gives
`err_phase` 9.08e-7 (`fs`), 2.85e-6 (`sf`) and 9.86e-7 (`ss`) at 1.620 V/-40 C,
and 4.29e-7 / 1.43e-6 / 3.08e-6 (`ss` / `fs` / `sf`) at 1.980 V/-40 C. Against
the 0.485-0.777 the as-built cell shows at 1.620 V/-40 C that is five to six
orders of magnitude, and it is 30x to 300x below the 1e-4 criterion -- so the
OTA closes this phase at every one of these corners and the whole failure was
the switch conduction. Bench: `run_variants.py`, results in
`variants-i92.json` (`ideal_*` rows; simulated, one corner each, run locally).

**Fix, and why it is shaped the way it is:** see
`design/integrator/SIZING.md` -> "Why the `vcm` switches need a PMOS half".
In short, each phi2-gated switch gained a low-Vth PMOS half whose gate drive
(`Vsg` = `vcm` = 0.9 V against its gate at `vssa`) does not shrink with `Vdda`,
and the NMOS halves moved to `nfet_01v8_lvt` at identical geometry. The PMOS
halves are small, and `Sci`/`Scr` have none, because their junction
capacitance costs settling at the *high* rail where the NMOS is already strong.

### Versus the hand-calc

Against `SIZING.md` (beta = 0.496, gm 302 uS at the smoke bias point), at the
nominal tt/1.800 V/27 C corner:

| Case | Hand-calc | Measured | Verdict |
|---|---|---|---|
| B (`int1`, 0.1 pF) | 1.1e-5, needs 236 uS | **6.4e-6** | passes 1e-4, as predicted |
| A (`int2`, 1.1 pF) | 1.6e-3, needs 449 uS | **2.3e-4** | misses 1e-4, as predicted |

The hand-calc is confirmed in structure and conservative in magnitude (7x on
case A). The OTA alone passes all 45 corners on its own bench
(`sim/ota-settling/record-i51-rcm2M-cff100f.json`, worst 6.8e-5, same
`ota_fd.spice` sha256 `7f4724e9...` this run used). At 1.800 V and above the
int1-versus-int2 split is what beta = 0.496 loading predicts, and that is
exactly the gap #53 was filed to measure. It does **not** follow that beta
loading explains the 1.620 V failure: the OTA bench drives ideal switches, so
the two benches differ in more than beta (see "Mechanism at 1.620 V" above).

## B-model comparison (`bmodel-threshold.json`)

    python3 -I sim/integrator-settling/bmodel_threshold.py --records

Largest behavioural-model `settling_error` keeping peak SNDR >= 80 dB:
**0.57** (peak 80.06 dB at -6 dBFS; 0.58 gives 79.57 dB and fails), quoted to a
0.01 grid. Record length 2^16 output samples, Blackman-Harris 4-term window,
bin bandwidth 1.2207 Hz, band 0-20 kHz, OSR 128. Behavioural model B,
uncross-checked. Canonical records: `sim/bmodel/records/20261113T094826Z-1e74d78e.json`
(0.57) and `20261113T094837Z-aa4731a8.json` (0.58). The sweep is deterministic:
with every noise parameter zero the result is seed-independent (verified over
seeds 1-5).

**This threshold does not license a 57 % settling error.** `settling_error` is
a *linear* gain factor `(1 - settling_error)` applied equally to both integrator
inputs and constant over the record, so it prices only the signal-independent
part of incomplete settling — a second-order loop at OSR 128 absorbs a uniform
loop-gain deficit very well, which is why the number is so large. The failures
measured here are not a uniform linear deficit of that kind: at 7 of the 8
non-settling corners per variant the charge transfer itself is incomplete
(`step_err_vs_ideal` 0.09 to 0.93), and at fixed 1.620 V `err_phase` varies by
more than three orders of magnitude across PVT — signal- and state-dependent in
a way a constant gain factor cannot represent. Whether the dominant term there
is slew limiting or incomplete switch conduction is **not** established by this
record (above). Comparing the two:

- At **1.800 V and above**, the measured error (1.9e-4 int1, 2.9e-3 int2 worst)
  sits far inside the 0.57 linear budget. This answers the open risk
  `SIZING.md` leaves to the B-model: case A's 1.6e-3 is **not** what limits
  SNDR at nominal supply. Necessary, not sufficient — the distortion term is
  not modelled.
- At **1.620 V** the worst measured error — **0.777** (int1) and **0.784**
  (int2), both at fs/-40 C — exceeds even that loose 0.57 linear budget. The
  rest of the supply corner does not: 5 of the 15 corners per variant are above
  0.57, and 7 sit at or below 0.16 (worst 0.107 int1, 0.151 int2). The
  comparison is in any case not apples-to-apples, since at 7 of the 8
  non-settling corners the charge transfer is incomplete (above), which a constant linear
  gain factor cannot represent. Against DR-005's 1e-4 criterion this is a hard
  failure at **all 15** corners per variant regardless, and that criterion is
  unchanged by the B-model threshold.

## Running

    python3 -I sim/integrator-settling/make_request.py              # regenerate decks + requests
    python3 -I sim/integrator-settling/run_settling.py --probe int1 # 1 corner, local
    python3 -I sim/integrator-settling/run_settling.py --record     # 2 x 45 corners, batch fleet
    python3 -I sim/integrator-settling/run_settling.py --variant int2 --record  # one variant
    python3 -I sim/integrator-settling/run_diag.py                  # 1 corner + node probes, local
    python3 -I sim/integrator-settling/run_diag.py --write          # ... and save diag-i92.json
    python3 -I sim/integrator-settling/run_variants.py              # 10 single-corner variants, local
    python3 -I sim/integrator-settling/run_variants.py --write      # ... and save variants-i92.json

`run_variants.py` is the switch-isolation cross-check behind "Mechanism at
1.620 V" and behind the PMOS-half size bounds in
`design/integrator/SIZING.md`. It runs the same deck, stimulus and timing as
`run_diag.py` -- so its `err_phase` is comparable to that bench and to
`record.json` -- against four netlists: the baseline cell with its twelve `vcm`
switches replaced by **ideal 1 ohm switches** (`ideal`), the baseline unchanged
(`no_pmos_std`), the baseline with those twelve moved to `nfet_01v8_lvt` and
still no PMOS half (`no_pmos_lvt`), and the working-tree cell (`fixed`). The
three baseline variants are transformed out of `--baseline-rev`, so they stay
reproducible after the fix lands. One corner per row, local, simulated; results
in `variants-i92.json`. It refuses to overwrite (append-only; use `--out`).

The switch-level inputs to the same argument -- on-state Ron and off-state
leakage per device -- are a separate bench, `sim/switch-probe/`.

`run_diag.py` is the diagnosis path, not a record path: it runs
`diag_1v62.cir.tmpl` at **one** corner locally (default `fs`/-40 C/1.620 V, the
binding point) with internal node voltages and device operating points saved,
which `--probe` cannot do and could not reach anyway (`--probe` is pinned to
tt/27 C/1.8 V). It runs that corner twice -- against the netlist in the working
tree and against the one at `--baseline-rev` (default `ffbbb3b`, the commit
`record.json` was taken on, pulled with `git show`) -- so the failing cell stays
reproducible after the fix. It builds its `Xint` line from the netlist's own
`.subckt` port list rather than hard-coding it, because `klt netlist` groups
subckt ports by pin type and the two revisions differ in port order (see
"Limits"). `--corner`/`--temp`/`--vdda`/`--load` move it; `--write` refuses to
overwrite.

The runner refuses a PDK whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2), never falls back to a local grid, refuses to write a record unless
all 45 points of both variants returned **and every corner produced an
`err_phase`** (a dead fleet job returns 45 empty points, which the count gate
alone would accept), and refuses to overwrite a record (append-only; use
`--record-name`). Each variant is one `klt sim` request (DR-002 full grid,
5 process x -40/27/125 C x 1.62/1.80/1.98 V) submitted with
`--wait-for-capacity 600`, so a refused launch waits with backoff instead of
failing the run.

`--variant` runs one variant; each completed variant is cached under
`.partials/` (gitignored, keyed to the request and deck sha256) so a capacity
refusal on one variant does not discard the other's 45 corners — re-run the
missing variant and `--record` assembles both. A variant requested in *this*
invocation is never taken from `.partials/`: if its submit fails, the run
refuses with exit 1 and writes no record, so a failed submit can never be
reported as a result. The raw `klt` report, batch receipt and stderr land in
`.artifacts/` (gitignored) *before* the completeness gate, so a failed or
partial grid is still inspectable.

## Limits

Noise, charge injection, clock-generator timing, Monte Carlo, layout parasitics
and the model-versus-transistor cross-check (DR-001) are not covered.

**`phi2b` skew is not simulated (owed).** The PMOS halves are gated by `phi2b`,
an on-cell inverter of `phi2`, so they switch one inverter delay after the NMOS
halves. This bench drives `phi2` with an ideal 0.2 ns ramp and leaves a 5 ns
gap, and it only exercises the phi2 **rising** edge; turn-*off* of `Sti`/`Str`
against the real `clkgen` non-overlap -- where that skew could briefly leave a
half open into the summing node -- is not covered here and is owed to the
clock-generator timing work. Not measured and not bounded by any number in this
file. `int2`'s
1 pF is a bound, not an extracted comparator input capacitance. The B-model
threshold covers the linear part of settling only (above). Nothing here is
measured and nothing relaxes DR-005 or the spec.

**Charge injection is now a live owed item, not a neutral one.** The PMOS
halves issue #92 added raise the channel area of the phi2-gated `vcm`
switches by 1.8x (`Sti`/`Str`) and 5.7x (`Sbi`/`Sbr`). The
common-mode part stays signal-independent, but the mismatch-driven
*differential* part grows as sqrt(W L); that is the price of this fix and it is
charged to the charge-injection extraction, not measured here. Tracked as
issue #102. See `design/integrator/SIZING.md` -> "kT/C and charge injection".

**Port-order drift in the committed netlists.** `klt netlist` (klt
0.9.2.dev885, xschem 3.4.7) orders a subckt's ports by **pin type** --
`iopin`, then `ipin`, then `opin` -- not in the schematic's pin declaration
order, even though `integrator.sch` comments that "Order sets the .subckt
terminal order". So regenerating `design/integrator/integrator.spice` moved
`voutp`/`voutn` from positions 5-6 to the end, and the three decks that
instantiate the cell had to move with it. `design/modulator/modulator.spice`
was already on the type-grouped order, so the two committed netlists had
disagreed since before this issue; `klt netlist --check` exits 3 against the
pre-#92 `integrator.spice` on `main` and no CI job runs that check. This change
regenerates `design/modulator/modulator.spice` as well, so its embedded
`integrator` body now carries the low-Vth switch fix too -- without that, every
assembled-modulator deck (which includes `modulator.spice`, never
`integrator.spice`) would have kept simulating the unfixed cell. A
silently-reordered port list is a tool gap worth filing against klayout-tools:
it can only be caught by an electrical test, and here it showed up as the
summing node sitting at -0.48 V in a diagnosis run. Filed as
klayout-tools#5473 (a narrower follow-up to its closed #4524, whose `--check`
diagnostic is what identified it).

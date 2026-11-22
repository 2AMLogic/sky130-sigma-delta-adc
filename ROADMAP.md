# Roadmap

A second-order, single-bit switched-capacitor delta-sigma ADC with its decimation
filter on sky130, carried to T1 (sim-validated) evidence as graded by `klt signoff`.

Status as of 2026-11-17, `main` @ `0309c08`. Every figure is simulated; none is
measured. The verdict of record is
[`manifests/sky130-sigma-delta-adc.signoff.json`](manifests/sky130-sigma-delta-adc.signoff.json)
and wins over this file. Tracking issue: #3 (its hand-kept checklist is stale).
`WORK_PLAN.md` is the label-generated queue; this file gives the order and why.

## Where it stands

`klt signoff` (pinned klt 0.9.2) grades 22 rows, 11 items by two partitions:
**10 met, 1 not applicable, 11 unmet.**

| T1 item | Analog (modulator) | Digital (decimator) |
|---|---|---|
| 1 Design sources | met: `design/attest/item1-analog-envelope.json` (#116) | met |
| 2 Layout | unmet: `ota_fd` and `integrator` cells committed (#141, #119), no analog envelope yet; #29 | met: `layout/digital/decimator.gds` |
| 3 DRC clean | unmet: #31 | met: `layout/digital/drc-decimator.report.json` (#83) |
| 4 LVS clean | unmet: #32 | met: `layout/digital/lvs-decimator.report.json` (#82) |
| 5 Corner verification | unmet (`check_failed`): envelope fails row 11 (integrator swing, #148) | met at ten liberty corners (#132); 35 DR-002 points uncovered, #131 |
| 6 Monte Carlo | unmet: #34 | not applicable, hash-bound statement (#134) |
| 7 Post-layout | unmet: #35 | unmet: no SDF-annotated run yet |
| 8 Characterization report | unmet (`check_failed`): rows still `partial`/`pending` in `measurements/characterization.md` | same envelope |
| 9 Testbenches shipped | met | met |
| 10 Repo hygiene | met | met |
| 11 Power delivery | unmet: #39 | unmet: #39 |

Evidence on `main` that does not yet move a row:

- Spec ratified, decision records DR-001 to DR-006 (`spec/`). Behavioural model B:
  ideal peak SNDR 86.17 dB (`sim/bmodel/records/`), after the estimator fix of #109.
- Transistor-level schematics and netlists of the OTA, integrator, clock generator
  and top-level modulator (`design/`); the comparator is imported from
  `sky130-comparator` by pinned commit (`reuse.lock.json`, DR-003).
- 45-corner records: OTA settling (`sim/ota-settling/`), integrator settling after
  the low-Vth PMOS switch halves (#93, #99), charge injection (#111), and comparator
  decision time, offset, hysteresis and kickback (#151).
- `ota_fd` generated GDS, DRC-clean on the curated deck, device count matching the
  netlist (`layout/analog/ota_fd/`), built with a klt newer than the CI pin
  (`.github/klt-version`).

## Now (can start today, or already in a pull request)

| What | Done when | Issue | State |
|---|---|---|---|
| Comparator trip staircase that brackets at sf/1.620 V/-40 C | `sim/comparator-decision/record.json` brackets the trip point at that corner, or a decision record says why it is not bracketable and gives the bound instead (the latter: DR-007, one-sided `v_trip` > −1.410 mV; probe `trip-probe-i150.json`) | #150 | PR #199 approved, held on a maintainer merge decision |

## Next (unblocked by a named item above)

- **Item 5, analog**: #125 to #128 landed and #33 closed; the item stays
  `unmet` while the committed envelope fails row 11 (integrator swing, #148)
  and the DR-001 cross-check gap keeps row 2 uncovered. #34 (Monte Carlo) follows.
- **First-integrator noise**: sampled-data referral of 1/f noise (#140, after #126),
  a 1/f line in the spec 5.3 budget by decision record (#142, after #140), then the
  OTA flicker fix and re-run of the OTA-dependent benches (#143). Parent #138: the
  cell misses the 5.3 thermal budget by 16 to 18 dB at all 45 corners.
- **Sampling switches and swing**: remedy for the `Sin` sampling error (#129) and a
  probe of the `Sci` top plate (#147), after #106; integrator swing against spec
  5.4 (#148), after #125.
- **Modulator assembly, item 2 analog** (#29): import the comparator GDS, draw the
  top-level devices, assemble `modulator.gds` per DR-004. After #119 and #121.
- **After #29**: DRC of the analog partition and the top (#31), analog LVS (#32),
  the assembled ADC stream (#122), power delivery (#39), post-layout `klt pex` (#35).
- **Item 11, digital** (#333, carved out of #39): `klt erc` supply evidence for
  `VDDD`/`VSSD` is committed clean (`layout/digital/erc-decimator.report.json`);
  the row turns `met` when the `klt place-and-route` response (#332, for #162)
  is committed and cited beside it (#333 Part B).
- **Decimator electrical rules** (no issue yet; file after #136 so the STA report
  is regenerated once): `layout/README.md` records 660 max-transition and 7
  max-capacitance violations at `ss_n40C_1v60`. Done when the committed STA report
  shows zero at every declared corner, or a decision record accepts them.
- **Item 8**: turns `met` only when rows 1 to 3, 5 and 11 to 14 of
  `measurements/characterization.md` leave `partial`/`pending` (#34, #35).

## Later (each needs its question answered first)

- **Does the transistor-level modulator reach 80 dB?** Model B reaches 86.17 dB
  ideal, and PR #115 puts the corrected ceiling at 88.2 dB at -6 dBFS; the noise
  miss (#138) and the swing finding (#148) both spend that margin.
- **How do `bs` and the clock cross from `VDDA` to `VDDD`?** No schematic holds a
  level shifter or the `VDDD` clock buffer of DR-004; #122 asks for that decision
  record before any assembly.
- **How is digital timing graded at the 35 DR-002 points with no liberty file?**
  `sky130_fd_sc_hd` ships no `sf`/`fs` corner and nothing above 100 C (#131).
- **Which klt pin grades the analog layout?** `ota_fd` was generated with a klt
  newer than the CI pin (`.github/klt-version`); stream and envelopes must be
  regenerated when the pin catches up, before an item-2 analog envelope can be
  cited.

## Blocked and waiting

- **PR #115 (DR-007, spec 5.1 ceiling correction)**: approved, held because merging
  ratifies a decision record; it waits on a maintainer and is stale against `main`.
  Holds #108 and #114 (coherent record length in `run.py`).
- **#121 clock generator cell GDS**: parked on
  [klayout-tools#1962](https://github.com/2AMLogic/klayout-tools/issues/1962):
  `klt gen-compose` cannot wire a multi-unit `mos_array` row into a logic gate. The
  alternative (draw the intra-gate wiring with `klt draw`, under a decision record)
  needs a maintainer decision. This is the one external blocker on #29, and through
  it on analog items 2, 3, 4, 7 and 11.
- **Cleanup proposals awaiting a maintainer ruling**: #96 (remove
  `sim/toolchain.json`), #95, #43; #81 waits on #43, #153 on PR #145.
- **klayout-tools#5550**: the functional-verification report carries no provenance
  block, so the manifest pins no `content_hash` for that citation.

Which open issues are ready for a builder is the label-generated queue in
`WORK_PLAN.md`, regenerated from the forge labels; this file asserts no snapshot
of that state here. The holds above need a human decision, not a label change.

## Not planned

- Voltage reference and bias generation: inputs at the block boundary (DR-005).
- Anti-alias filtering ahead of the sampler beyond what the modulator provides.
- A comparator designed here: it is imported from `sky130-comparator` at a pinned
  commit (DR-003, `reuse.lock.json`).
- Relaxing a ratified spec row to close a gap; changes go by a new decision record.

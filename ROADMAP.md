# Roadmap

A second-order, single-bit switched-capacitor delta-sigma ADC with its decimation
filter on sky130, carried to T1 (sim-validated) evidence as graded by `klt signoff`.

Status as of 2026-11-13, `main` @ `99689a1`. Every figure is simulated; none is
measured. The verdict of record is
[`manifests/sky130-sigma-delta-adc.signoff.json`](manifests/sky130-sigma-delta-adc.signoff.json)
and wins over this file. Tracking issue: #3 (its hand-kept checklist is stale).
`WORK_PLAN.md` is the label-generated queue; this file gives the order and why.

## Where it stands

`klt signoff` (pinned klt 0.8.0) grades 22 rows, 11 items by two partitions:
**9 met, 1 not applicable, 12 unmet.**

| T1 item | Analog (modulator) | Digital (decimator) |
|---|---|---|
| 1 Design sources | met: `design/attest/item1-analog-envelope.json` (#116) | met |
| 2 Layout | unmet: `ota_fd` cell only (#141); #29 | met: `layout/digital/decimator.gds` |
| 3 DRC clean | unmet: #31 | met: `layout/digital/drc-decimator.report.json` (#83) |
| 4 LVS clean | unmet: #32 | unmet: no LVS report yet |
| 5 Corner verification | unmet: #33 (sub-issues #125 to #128) | met at ten liberty corners (#132); 35 DR-002 points uncovered, #131 |
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
  netlist (`layout/analog/ota_fd/`), built with a newer klt than the 0.8.0 CI pin.

`README.md` still says "there is no transistor-level modulator yet"; that is stale
(see Now).

## Now (can start today, or already in a pull request)

| What | Done when | Issue | State |
|---|---|---|---|
| Integrator cell GDS, instantiating `ota_fd` | generated stream under `layout/analog/` with a `--check` regeneration, DRC report and device-count record | #119 | building |
| Short full-modulator transistor-level transient on the DR-002 anchors | bench and record committed with power and swing per anchor | #125 | PR #149, changes requested, CI red |
| OTA DC gain and integrator thermal noise over the 45 corners | record committed as model B parameters | #126 | PR #139 in review |
| `Sin` input-sampling completeness over PVT | record and Ron-vs-input curve committed | #106 | PR #130, changes requested, conflicted |
| Decimator STA with a propagated clock | `sta-decimator.report.json` reads a propagated clock mode; hold verdict includes clock-tree latency | #136 | PR #154 in review |
| Record the digital-timing corner set and the 35-corner gap | spec text or decision record names the declared corners and what is uncovered | #131 | PR #156, changes requested, conflicted |
| Comparator trip staircase that brackets at sf/1.620 V/-40 C | `sim/comparator-decision/record.json` brackets the trip point at that corner | #150 | triage; its cited blocker (PR #151) has merged |
| `ota_fd` MiM plate orientation and README row table | cap-group terminals match the netlist order; regenerated stream passes `--check` | #146 | labelled blocked; its cited blocker (PR #141) has merged |
| Define the manifest `content_hash` for the item-8 envelope | the meaning is written down and the manifest value re-hashes | #155 | triage |
| Decimator LVS, digital only (item 4) | `klt lvs` report on `decimator.gds` against `decimator_pnr.v` reads `status: match`, `power_connectivity` not `mismatch`; manifest cites `4.digital` | none (seed 1) | not filed; split from #32 as #82 was from #31 |
| SDF-annotated decimator re-run, digital only (item 7) | `klt functional-verification` report with `environment.sdf.annotated: true`; manifest cites `7.digital` | none (seed 2) | not filed; split from #35 |
| README status and maturity position | status paragraph matches the verdict of record; item-10 envelope re-attested | none (seed 3) | not filed |

Housekeeping already in pull requests: #152 (PR #157), #105 (PR #145), #103 (PR #133).

## Next (unblocked by a named item above)

- **Item 5, analog (4/4)**: per-corner model B parameters, DR-001 cross-check and
  the item-5 citation: #128, after #125 and #126. Then #33 closes and #34 follows.
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
- **Item 11, digital** (part of #39): `klt erc` supply evidence for `VDDD`/`VSSD`,
  once the digital LVS report carries `power_connectivity.status: match`.
- **Decimator electrical rules** (no issue yet; file after #136 so the STA report
  is regenerated once): `layout/README.md` records 660 max-transition and 7
  max-capacitance violations at `ss_n40C_1v60`. Done when the committed STA report
  shows zero at every declared corner, or a decision record accepts them.
- **Item 8**: turns `met` only when rows 1 to 3, 5, 9 and 11 to 14 of
  `measurements/characterization.md` leave `partial`/`pending` (#33, #34, #35).

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
  newer than the 0.8.0 CI pin; stream and envelopes must be regenerated when the
  pin moves, before an item-2 analog envelope can be cited.

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

No open issue is labelled ready for a builder today: everything open is in
progress, parked, or awaiting curation. The three unfiled Now items can be drawn
without waiting on anything.

## Not planned

- Voltage reference and bias generation: inputs at the block boundary (DR-005).
- Anti-alias filtering ahead of the sampler beyond what the modulator provides.
- A comparator designed here: it is imported from `sky130-comparator` at a pinned
  commit (DR-003, `reuse.lock.json`).
- Relaxing a ratified spec row to close a gap; changes go by a new decision record.

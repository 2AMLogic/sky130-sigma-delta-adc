# Work Log

Chronological record of merged PRs and closed issues, maintained by the Guide role.

### 2026-11-17

- **PR #300**: docs: prune landed rows and stale klt-pin prose from ROADMAP's Now table
- **Issue #297** (closed): ROADMAP.md residual prose drift: Now-table rows for landed work and stale klt 0.8.0 pin mentions
- **PR #295**: docs: add DR-008 corrigendum 03 and re-point the STA-gap citation off closed #131
- **PR #292**: chore(loom): resync installed Loom to v0.19.1306
- **PR #289**: fix(integrator-layout): route sump/sumn as a matched pair, gating 3% symmetry
- **PR #291**: docs: re-point characterization's closed-#33 citations at open owners
- **PR #287**: docs: point GEOMETRIES comment at extract-device-count.json instead of stale counts
- **PR #285**: docs: refresh integrator section of layout/README.md from committed post-#274 artifacts
- **PR #283**: Regenerate the integrator layout for the #147 50-device netlist
- **PR #281**: test: re-derive the tg half-current sum on every committed probe row
- **PR #280**: fix: fail signoff gate when a tracked Python file cannot parse
- **PR #278**: fix: set the tg half-current sum bound to 1e-4 relative, clear of the print floor
- **PR #273**: ci: fail signoff on undefined names via pinned pyflakes
- **Issue #293** (closed): Closed-issue citations outside characterization.md: DR-008 consequence prose, item9-inventory, ROADMAP, and the #131 line-17 citation
- **Issue #284** (closed): The integrator's summing-node routing symmetry dropped from 3% to 9.3% when the #147 field widened, and nothing tracks recovering it
- **Issue #288** (closed): Re-grade characterization rows after #33's closure (curator verdict of record) — unblocks PR #213's cited-issue CI
- **Issue #286** (closed): gen_integrator.py's GEOMETRIES comment still says "44 devices cost 9 klt gen calls" (now 50 / 11)
- **Issue #282** (closed): layout/README.md's integrator section has been stale since #129 and nothing tracks it
- **Issue #279** (closed): switch-probe README overstates what the half-current sum check's tests pin
- **Issue #277** (closed): CI: the signoff pyflakes gate passes green on a Python file that cannot be parsed
- **Issue #275** (closed): switch-probe: the half-current sum refusal aborts a whole sweep at a tolerance that sits on the print-rounding floor
- **Issue #274** (closed): The committed integrator layout is stale against the #147 cell (50 devices vs the 44 it pins) and nothing tracks it
- **Issue #272** (closed): CI: add a pyflakes step — a NameError in a fleet-only runner path reached main and cost a completed batch run
- **Issue #33** (closed): T1 item 5 (corner verification): transistor-level PVT SNDR/power sweep of the modulator, plus decimator STA and klt functional-verification
- **PR #270**: feat(sim): retain the raw modulator-tran klt sim report and cite it for row 11
- **PR #269**: sim: probe the Sci top-plate hold, give Sci/Scr the PMOS half the sweep says they need
- **PR #268**: fix(design): make the Sin input gate a low-Vth pair, sized and graded per DR-010
- **Issue #263** (closed): T1 item 5 analog: retain a citable klt sim report for the modulator transient and cite rows 5, 11, 12, 13
- **Issue #147** (closed): Sci top-plate hold: 98% of the fs/1.620 V/-40 C sampling error at 0.6 V is Sci, not Sin, and Sci has never been probed
- **Issue #129** (closed): Sin pass gate: decide the remedy for the input-sampling error now that the grid exists (54.3% unsampled at ss/1.620 V/-40 C, and level-dependent)
- **PR #267**: docs: record the klt-pin reopen trigger's re-read at the 0.9.2 pin
- **PR #262**: refactor: share the --check CLI driver between the cell generators via layout_common.run_cli
- **PR #261**: docs: correct Router by_net comment; shared finish_trunks tags every cell's met2 trunks
- **PR #259**: fix: register manifests and sim/modulator-tran tool-free steps in check-ci.sh CHECKS
- **PR #255**: refactor: delegate runners' shas/load_partial/save_partial to settling_common
- **PR #247**: ci: collapse signoff.yml's two overlapping layout/analog test steps into one
- **Issue #258** (closed): Share the --check CLI driver between gen_integrator.py and gen_ota_fd.py: two ~145-line main() copies
- **Issue #253** (closed): Finish settling_common consolidation: drop hand-rolled shas/partial/sha256 copies in 4 runners
- **Issue #250** (closed): Record the DR-008 klt-pin re-read at the 0.9.2 pin (corrigendum 01's reopen trigger, fired by #244)
- **Issue #246** (closed): check-ci drift guard fails on main: manifests and sim/modulator-tran tool-free steps are not registered in CHECKS
- **Issue #239** (closed): layout_common.Router: by_net comment says the OTA cell's dict stays empty, but the shared finish_trunks tags every trunk
- **Issue #211** (closed): signoff.yml's two layout/analog unittest steps overlap: the DRC-guard step's test_*.py pattern already runs test_layout_common.py

### 2026-11-16

- **PR #256**: fix: fold SPICE continuation lines before parsing extracted X-devices
- **PR #244**: feat: per-corner model-B evidence and DR-001 cross-check for item 5 analog
- **PR #220**: chore(loom): resync installed Loom to v0.19.1302
- **Issue #204** (closed): parse_extract_devices silently drops an X-line whose model token sits on a SPICE continuation line
- **Issue #203** (closed): check-ci drift guard fails on main: the analog-generator test step (44e8cee) is not registered in CHECKS
- **Issue #128** (closed): T1 item 5 (analog 4/4): per-corner model B parameters, DR-001 cross-check on the anchors, and the item-5 analog citation
- **PR #249**: docs: add DR-008 corrigendum 01 — klt-pin scope of the characterize ground
- **PR #245**: fix(test): pin ota_fd merge counts to parser-independent check.expected
- **PR #130**: sim: extract Sin input-sampling completeness over PVT and its Ron-vs-input curve
- **Issue #227** (closed): DR-008's `klt characterize` rejection ground is pinned to klt 0.8.0 and goes stale at the next klt pin bump
- **Issue #210** (closed): test_layout_common.py mis-attributes check.found as a parser-independent source (it is parse_extract_devices' own output)
- **Issue #106** (closed): Input sampling switch Sin is ~46% incomplete near vcm at ss/1.620 V/-40 C
- **PR #242**: fix: regenerate item9 attest under the klt pin and document the rule
- **PR #156**: spec: record the digital-timing corner set and declare the 35-corner gap
- **Issue #223** (closed): item9-envelope provenance.klt_version now names an unpinned klt dev build; .github/klt-version pins 0.8.0
- **Issue #131** (closed): Decimator STA: 35 of the 45 DR-002 corners have no liberty file, and the block-boundary I/O timing budget is undeclared
- **PR #240**: fix: report a non-object manifest as a violation, not a traceback
- **PR #238**: refactor: unify connect_met1, finish_trunks and add_shape into the shared Router base
- **PR #235**: fix: treat a non-object cited JSON file as provenance-less in content-hash check
- **PR #149**: feat(sim): short full-modulator transient bench on the DR-002 anchor set
- **Issue #237** (closed): check_content_hashes.py: a non-object manifest top level crashes check_manifest with a traceback
- **Issue #234** (closed): check_content_hashes.py: a cited JSON file whose top level is not an object crashes provenance_input_hash
- **Issue #201** (closed): gen_ota_fd/gen_integrator: two of the seven kept Router overrides differ only by a default budget and a one-sided message, and finish_trunks disagrees on a zero-height trunk
- **Issue #125** (closed): T1 item 5 (analog 1/4): short full-modulator transistor-level transient on the DR-002 anchor set, with power and swing limits
- **PR #222**: fix: enforce both directions of the manifest content_hash iff invariant
- **Issue #215** (closed): check_content_hashes.py enforces only half the documented content_hash "if and only if" invariant
- **Issue #216** (closed): Merge pipeline stalled: strict required-status-checks policy blocks every behind PR and nothing updates them
- **Issue #224** (closed): ngspice_version() has no committed test for its no-argument path, the one three probe runners use
- **Issue #225** (closed): Move duplicated assert_drc_clean into layout_common: two byte-identical copies in the analog generators
- **Issue #146** (closed): ota_fd layout: MiM plate orientation differs from the netlist's terminal order for one cap group; README row table quotes ring extents
- **Issue #153** (closed): Two more ngspice-version lookups could reach settling_common.ngspice_version() (log-first variant)
- **Issue #155** (closed): Manifest content_hash for item8-envelope.json is stale, and the field's meaning is undefined for a generic envelope
- **Issue #163** (closed): README status and maturity position are stale: state what the verdict of record says, and re-attest item 10
- **Issue #182** (closed): Share the Rect/Anchor/Router classes copy-pasted between gen_ota_fd.py and gen_integrator.py
- **Issue #186** (closed): Pin klayout in the --check uvx resolution: the gate degrades to CANNOT VERIFY on the next klayout release
- **Issue #190** (closed): comparator-decision: pass_criterion prose claims a +/-3.5 mV span requirement that bracketed() does not enforce
- **Issue #191** (closed): layout/analog/layout_common.py has no CI-executed test: the parsers behind both cells' device-count evidence are never run by signoff.yml
- **Issue #192** (closed): sim/ota-settling/request.json is intentionally stale: record-pinned; regeneration drifts by capacity_wait_s
- **Issue #198** (closed): DR-006's Consequences bullet is stale: it says record.json predates the gap line, but the committed record carries it
- **Issue #212** (closed): Share the unmeasured/corner_set/call test helpers: three near-identical copies in sim/ test benches
- **Issue #226** (closed): layout_common's router/DRC-spacing core has no CI-executed test: #191 closed the gap for the parsers only
- **PR #231**: test: pin ngspice_version()'s no-argument path in NgspiceVersion
- **PR #229**: refactor: dedupe assert_drc_clean into layout_common
- **PR #177**: fix(manifest): drop the unverifiable item-8 content_hash pins and gate the pin invariant
- **PR #180**: docs: README status matches the verdict of record; item-10 envelope re-attested
- **PR #195**: comparator-decision: state the trip gate as implemented in pass_criterion
- **PR #197**: refactor(layout): share the Rect/Anchor/Router core via layout_common
- **PR #205**: test: CI-execute layout_common's extracted-netlist parsers with captured klt fixtures
- **PR #206**: docs(spec): corrigendum for DR-006's stale record.json Consequences bullet
- **PR #207**: ota_fd: emit row extents from place_rows, requote the README table, record the cap-plate LVS probe
- **PR #208**: refactor(sim): fold the log-first ngspice version lookup into settling_common.ngspice_version()
- **PR #214**: test(sim): share one unmeasured/corner_set/call fixture harness across the benches
- **PR #217**: test: guard every committed record's request_sha256 pin from orphaning
- **PR #219**: fix: pin the klayout axis in the --check gates' uvx resolution
- **PR #228**: test: pin layout_common's Rect/Router geometry core with 26 unit tests

### 2026-11-15

- **PR #193**: refactor(sim): share one measurement-dict helper across the six benches
- **Issue #185** (closed): Share the measurement-dict helper e(): six identical copies in sim/*/make_request.py
- **PR #181**: refactor: share the .partials/ sha staleness gate in settling_common.py
- **Issue #174** (closed): Consolidate the triplicated .partials/ staleness gate into settling_common.py
- **PR #200**: test: dedupe the by-path module loader into runner_test_common.load_runner
- **Issue #165** (closed): Two by-path runner loaders remain in sim/ after #152: test_settling_common.py and comparator-decision/test_run_decision.py
- **PR #189**: fix(layout): abort the analog generator flows on a non-clean klt drc verdict
- **Issue #164** (closed): gen_integrator.py records klt drc but never asserts it, so a regeneration can emit a DRC-dirty stream with exit 0
- **PR #196**: docs: grade characterization row 9 evidenced per DR-006, drop stale #18 citation
- **Issue #170** (closed): characterization.md row 9 still cites #18 as pending, but #18 closed completed and DR-006 ratified the reading
- **PR #188**: feat(layout): klt lvs the routed decimator against its as-built netlist and grade 4.digital met
- **Issue #161** (closed): T1 item 4, digital only: klt lvs the routed decimator against its as-built netlist and cite it for 4.digital
- **PR #184**: fix: evaluate gen --check at the klt build recorded in the cell's own provenance
- **Issue #172** (closed): gen_ota_fd.py --check cannot pass: the committed ota_fd.gds no longer reproduces under a newer klt
- **PR #179**: refactor: share the layout/analog generator plumbing in one layout_common module
- **Issue #176** (closed): Share the plumbing copy-pasted between gen_ota_fd.py and gen_integrator.py: four identical helpers, and two extract parsers that have already drifted
- **PR #178**: fix: one column-reservation site; route summaries report reserved met2 columns
- **Issue #168** (closed): gen_ota_fd.py: one column-reservation site, and a met2_columns that does not count met2 columns (117 vs 105)
- **PR #167**: fix(pnr): refuse on the PDK stamp klt actually records, and test it
- **Issue #158** (closed): run_pnr.py's PDK-pin refusal can never fire: it reads a top-level `pdk.version` that klt reports do not have
- **PR #160**: docs: roadmap as of 2026-11-13
- **PR #154**: evidence(sta): grade the decimator with a propagated clock, not an ideal one
- **Issue #136** (closed): Decimator STA: cite the propagated-clock run so the hold verdict includes clock-tree latency
- **PR #145**: refactor(sim): share the SPICE joiner, figure-of-merit block, deck fill and baseline read across the issue #92 probe runners
- **Issue #105** (closed): Share the pasted helpers in the issue #92 probe runners: three copies of the SPICE line joiner, two of the figure-of-merit block

### 2026-11-14

- **PR #173**: refactor(layout): drop the never-called mcon spacing guard and the wrong DELIVERABLES tuple
- **Issue #166** (closed): Remove the never-called mcon/met2 spacing guard and the wrong DELIVERABLES tuple from gen_ota_fd.py
- **PR #171**: sim: measure the integrate-phase noise where it accumulates, and split it per device
- **Issue #140** (closed): First-integrator amplifier noise: sampled-data-correct referral of 1/f noise and a per-device flicker/thermal split (sim/integrator-noise)
- **PR #159**: feat(layout): generate the SC integrator cell GDS with the OTA instantiated
- **Issue #119** (closed): Analog layout 2/3: generated GDS of the SC integrator cell with its capacitors and switches
- **PR #157**: test(sim): share one klt-sim runner harness across the two benches
- **Issue #152** (closed): Share the two klt-sim runner test harnesses: RunnerCase and the issue #94 admission test class are copied per bench
- **PR #151**: sim: measure the comparator's decision time, offset, hysteresis and kickback over the DR-002 grid
- **Issue #127** (closed): T1 item 5 (analog 3/4): comparator decision time, systematic offset and hysteresis in the modulator over the 45-corner grid
- **PR #139**: feat(sim): extract OTA DC gain and integrator thermal noise over the 45-corner grid
- **Issue #126** (closed): T1 item 5 (analog 2/4): OTA DC gain and integrator thermal noise over the 45-corner grid, as model B parameters
- **PR #134**: feat(signoff): bind a not_applicable record to T1 item 6 (digital)
- **Issue #123** (closed): T1 item 6 (digital partition): hash-bound not_applicable statement for decimator spec rows 6-10
- **PR #133**: chore: drop never-matched build ignores, ignore the cocotb runners' scratch
- **Issue #103** (closed): Prune .gitignore rules that match nothing, and ignore the build scratch the cocotb runners actually leave

### 2026-11-13

- **PR #144**: ci: fetch full history so the pre-#92 fixture comparison runs
- **Issue #120** (closed): Make the pre-#92 fixture check run in CI: it is skipped on every run because the checkout is shallow
- **PR #141**: feat(layout): generate the ota_fd OTA cell GDS from the netlist
- **Issue #118** (closed): Analog layout 1/3: generated GDS of the fully-differential OTA cell (ota_fd)
- **PR #135**: feat(ci): run the tool-free signoff checks in the local check:ci gate
- **Issue #104** (closed): Make npm test run the tool-free tests CI already runs: check:ci parses two JSON files and runs no tests
- **PR #132**: feat(verification): grade decimator timing at ten liberty corners and cite item 5 digital
- **Issue #124** (closed): T1 item 5 (digital): klt sta on the routed decimator across the sky130_fd_sc_hd corners, plus a klt functional-verification report
- **Issue #27** (closed): T1 item 1 (design sources, analog partition): xschem schematic and derived netlist of the 2nd-order switched-capacitor modulator
- **PR #116**: feat(attest): attest the analog design sources for T1 item 1
- **Issue #42** (closed): T1 item 1 (analog 4/4): attestation inventory, manifest evidence, regenerated verdict
- **PR #112**: feat(bmodel): stamp a code_sha256 map in every B-model evidence writer
- **Issue #110** (closed): B-model records stamp a dirty base commit, not the code that produced the number
- **PR #111**: feat(sim): extract the integrator charge-injection residual and correct the sqrt(W L) argument
- **Issue #102** (closed): Extract integrator charge injection after the #92 PMOS switch halves
- **PR #109**: fix(bmodel): drop the ENBW factor from sndr_db and regenerate the B evidence
- **Issue #107** (closed): B-model SNDR estimator reads 3.0 dB high: sndr_db applies an ENBW factor to a lobe-summed signal
- **PR #100**: refactor(attest): move item-10 inventory and envelope under attestation/
- **Issue #91** (closed): Fold attest/ and evidence/ into attestation/: three directory conventions for one kind of file
- **PR #99**: fix(integrator): give the vcm switches a low-Vth PMOS half so the cell settles at 1.620 V
- **Issue #92** (closed): Integrator cell does not settle at Vdda=1.62 V (0/15 corners, both load variants): diagnose, then fix the OTA or the switches
- **PR #98**: test(sim): refuse a settling record built on a failed submit, and cover the record-validity gates
- **Issue #94** (closed): Settling runner: fixture test for measurements_present(), and surface a failed submit that fell back to a cached partial
- **PR #93**: feat(sim): record 45-corner integrator settling over PVT and extract the B-model settling budget
- **Issue #53** (closed): Settling of the SC integrator with ota_fd over PVT (OTA gm margin at beta 0.50)
- **PR #89**: docs: record klt netlist --check result for vendored comparator
- **Issue #60** (closed): Close klt netlist --check for vendored comparator.sch (needs xschem >= 3.4.5)

### 2026-11-12

- **PR #87**: Bump Repo Skills 0.25.10 -> 0.26.1

### 2026-11-07

- **PR #84**: Bump Repo Skills 0.25.1 -> 0.25.10

### 2026-11-06

- **PR #83**: feat(layout): klt drc the routed decimator and grade 3.digital met
- **Issue #82** (closed): T1 item 3, digital only: klt drc the routed decimator GDS and cite it for 3.digital

### 2026-11-01

- **PR #78**: fix: refresh item-9 attestation envelope for updated response.py hash
- **Issue #77** (closed): main red: item-9 attestation drifted (response.py hash stale after DR-006)
- **PR #75**: test(decimator): end-to-end B-bitstream check and re-recorded row 9 floor
- **Issue #74** (closed): DR-006 follow-ups: record the 75 dB 'row 9 elsewhere' line durably; row 9 evidence column claims B evidence that does not exist
- **PR #23**: docs(spec): grade decimation stopband (row 9): 90 dB in alias bands, 75 dB floor elsewhere, DR-006
- **Issue #18** (closed): Spec owner: confirm row 9 stopband reading (alias bands vs every frequency fout-BW..fs/2)
- **PR #72**: Bump Repo Skills 0.24.7 -> 0.25.1

### 2026-10-28

- **PR #68**: feat(measurements): characterization report with item-8 envelope and CI re-check
- **Issue #67** (closed): T1 item 8 (characterization report): per-row characterization report with decimator Fmax/area/power and a klt signoff --attest 8 envelope

### 2026-10-27

- **PR #65**: feat(layout): reproducible routed GDS and item-2 envelope for the decimator
- **Issue #30** (closed): T1 item 2 (layout, digital partition): place-and-route of the decimator on VDDD/VSSD, committed routed GDS
- **PR #63**: refactor: share klt sim runner and request builder across settling benches
- **Issue #57** (closed): Consolidate duplicated klt-sim runner logic in sim/*-settling
- **PR #59**: feat(design): add clkgen, vendored comparator and top-level modulator schematic
- **Issue #41** (closed): T1 item 1 (analog 3/4): clock phases, pinned comparator import, top-level modulator schematic
- **PR #46**: feat: attest digital T1 item 1 with committed synthesized decimator netlist
- **Issue #28** (closed): T1 item 1 (design sources, digital partition): commit the decimator gate-level netlist and attest the RTL + netlist inventory
- **PR #58**: feat(design): linear resistive CMFB sense and doubled tail/branch currents close OTA step settling at 45 corners
- **Issue #51** (closed): OTA: CMFB sense and branch currents fail the 45-corner step-settling record
- **PR #56**: feat(sim): add integrator+ota_fd settling bench and 45-corner runner
- **PR #52**: feat(sim): OTA step-settling bench with failing 45-corner record
- **PR #47**: feat: attest T1 item 9 testbench inventory with klt signoff --attest
- **PR #54**: feat(design): add fully-differential SC integrator with 1-bit feedback DAC
- **Issue #48** (closed): Follow-on from PR #45: OTA slew-rate risk (~10 V/us vs 0.45 V per-side worst-case step)
- **Issue #36** (closed): T1 item 9 (testbenches shipped): testbench inventory over the smoke, model B, decimator and modulator benches, attested with klt signoff --attest 9
- **Issue #40** (closed): T1 item 1 (analog 2/4): SC integrator and 1-bit feedback DAC, schematic and netlist
- **PR #45**: feat(design): add fully-differential folded-cascode OTA with CMFB
- **PR #44**: feat: attest T1 item 10 repo hygiene with klt 0.8.0 and refresh README
- **Issue #38** (closed): T1 item 1 (analog 1/4): fully-differential OTA with CMFB, schematic and netlist
- **Issue #37** (closed): T1 item 10 (repo hygiene): README status and full reproduction, hygiene inventory attested with klt signoff --attest 10

### 2026-10-24

- **Issue #20** (closed): Remove digital smoke fixture verification/smoke: superseded by decimator runner

### 2026-10-23

- **PR #19**: feat(sim): behavioural second-order delta-sigma model B with SNDR records
- **PR #17**: feat(rtl): CIC4 + 41-tap FIR decimation filter with cycle model, cocotb tests and synthesis record
- **Issue #15** (closed): Behavioural modulator model (B): discrete-time 2nd-order 1-bit loop with T-parameter inputs and a §1.2-conformant SNDR report
- **Issue #16** (closed): Decimation filter RTL: CIC3 + FIR to 80 kSps, 16-bit output, bit-exact against a fixed-point model with cocotb

### 2026-10-21

- **PR #13**: fix: make npm check scripts validate manifest JSON instead of always passing
- **PR #10**: Bump Repo Skills 0.24.3 -> 0.24.7
- **Issue #12** (closed): Replace vacuous always-pass package.json check scripts

### 2026-10-20

- **PR #6**: ci: grade T1 state with klt signoff and commit the verdict of record
- **Issue #5** (closed): T1 item 10: add CI and a klt signoff block manifest as the verdict of record

### 2026-10-17

- **PR #8**: feat: pin sky130 PDK and tools, add analog and digital smoke runs
- **PR #7**: docs(spec): ratify sky130 delta-sigma ADC target spec and decision records
- **PR #1**: chore(loom): Install Loom 0.19.1181
- **Issue #4** (closed): Pin the sky130 PDK and both simulation flows, and commit analog and digital smoke runs (T1 item 9 groundwork)
- **Issue #2** (closed): Draft and ratify the target spec

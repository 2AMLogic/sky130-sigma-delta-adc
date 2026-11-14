# layout

## Digital partition: `layout/digital/`

Routed GDS of the decimation filter (`decimator`), produced by `klt place-and-route`
(OpenROAD floorplan, placement, CTS, global and detailed route) from the committed
gate-level netlist `rtl/netlist/decimator_synth.v`. Not hand-edited.

| File | Role |
|---|---|
| `pnr_request.json` | the P&R request: cell library, floorplan, PDN, clock |
| `run_pnr.py` | driver; `python3 layout/digital/run_pnr.py` regenerates, `--check` compares |
| `decimator.gds` | routed layout (T1 item 2, digital); hash-pinned by `design/attest/item2-digital-envelope.json` |
| `decimator.def`, `decimator_pnr.v` | routed DEF and as-built netlist (CTS buffers included): the LVS reference for #32 |
| `sta_request.json` | the multi-corner `klt sta` request on the routed DEF |
| `sta-decimator.report.json` | the committed STA report (T1 item 5, digital, with `verification/decimator/fv-decimator.report.json`) |

Recorded choices (`pnr_request.json`):

- **Supplies**: PDN on `VDDD`/`VSSD` (sky130hd preset: met1 follow-pins, met4/met5 straps) with
  tap cells; separate from `VDDA`/`VSSA` per DR-004. 1625 tap cells; the tool's own
  power-delivery audit reads `complete`.
- **Die / core**: 360.22 x 360.22 um die (129,758 um^2), core 121,877 um^2, 40 % utilization
  target (42.4 % achieved), 5 um core margin. DR-004 gives no coordinates and the analog
  floorplan (#29) has not landed, so this is a standalone block outline; placing it opposite
  the first integrator is left to the assembly step.
- **Clock**: `clk`, 195.3125 ns (fs = 5.12 MHz, spec row 5). Timing is graded by the STA below.

Reproducibility: two independent runs of the driver (same pinned PDK, OpenROAD
`26Q3-1510-g6cb3f2b704` container, seed 1) gave a byte-identical GDS, DEF and netlist. The
flow takes about 30 minutes (detailed routing dominates), so it is not in CI; CI checks the
envelope and the graded verdict. The driver runs `klt` from the repo root because the
containerised `openroad` mounts only the working directory.

DRC: `klt drc` (klt 0.8.0, `sky130` deck, content hash
`sha256:ba0f97887e3d231aec8b54f1f52f2941ded0228f0234b6759712bcaca0e942e6`) on
`decimator.gds`, top `decimator`, is `clean` (0 violations); report
`digital/drc-decimator.report.json`, reproduce with `digital/run_drc.sh --check`
(about 3.5 minutes). This is the klt curated deck, not the foundry-complete deck. Quoted from
the report's `coverage` block: `deck_scope` is cap2m, capm, ct, difftap, li, licon, m1-m5,
npc, nsdm, nwell, poly, psdm, rpm, urpm, via, via2-via4, x. `layers_in_stream_without_rules`
(drawn, no rule): 64/5, 64/16, 64/59, 67/5, 67/16, 68/5, 68/16, 70/5, 70/16, 72/5, 72/16,
81/4, 81/23, 83/44, 122/16, 235/4, 236/0. `rules_skipped` (48, all no-applicable-geometry
angle/ongrid/width rules on layers absent from this stream, e.g. capm, dnwell, hvi, lvtn,
pad, vpp): see the report. The run resolved klayout 0.30.13 against the 0.30.12 klt was
tested with, so counts like `rules_skipped` may differ on 0.30.12; the verdict is unaffected.
Analog-partition and assembled-top DRC stay with #31.

What the router reports: 0 unrouted nets, detailed-route DRC
count converged to 0, 0 antenna violations. The report also lists max-transition (2053) and
max-capacitance (43) violations against the library limits, concentrated in the slow corners
(`ss_*`, 1.28-1.76 V); these are not addressed here. The router's own in-flow corner sweep
spans corners down to 1.28 V, below the spec's 1.62 V supply bound; the STA below declares
only corners at or above 1.60 V and sees those electrical violations at one corner
(`ss_n40C_1v60`).

## Multi-corner STA (T1 item 5, digital)

`klt sta` (pinned klt 0.8.0, OpenROAD `26Q3-1510-g6cb3f2b704`) on the committed
`digital/decimator.def` — `geometry_source: "routed"`, clock `clk` at 195.3125 ns,
`constraints.propagated_clock: true` — with
`pdk.corners` naming ten corners, so one fixed geometry is characterized at all ten in a
single request. (`klt place-and-route` re-run per corner would give ten *different*
placements and routings, which is not a characterization of this layout.) Request
`digital/sta_request.json`, report `digital/sta-decimator.report.json`. Reproduce with:

```sh
# from the repo root; takes about half a minute. Pinned klt, not the host klt,
# and an explicit --pdk-root: both reach the committed report's own provenance
# (`provenance.klt_version`, `pdk.source: "--pdk-root flag"`).
uvx --from "klayout-tools==$(cat .github/klt-version)" klt sta \
  layout/digital/sta_request.json --pdk sky130A \
  --pdk-root "$(klt pdk find --pdk sky130A --format json | jq -r .root)" \
  --format json > layout/digital/sta-decimator.report.json
```

A re-run reproduces every timing number exactly, but **not** the file byte-for-byte:
each corner's `engine_log.invocation_id` is a fresh UUID, and `engine_log.script_sha256`
covers a generated TCL that embeds the checkout's absolute `read_def` path. Compare with
`jq -S 'del(.corners[].engine_log)'` on both sides, not `diff`.

**Result**: every one of the ten corners is `timing_status: "constrained"` with
non-negative setup and hold slack and zero setup/hold violations. Worst setup slack
157.838 ns of the 195.3125 ns period at `ss_n40C_1v60` (Fmax 26.69 MHz); worst hold slack
0.2698 ns at `ff_n40C_1v95`; best Fmax 109.79 MHz at `ff_n40C_1v95`. The clock is 5.12 MHz,
so the slowest declared corner leaves a 5.2x frequency margin.

These supersede the ideal-clock figures this report carried before #136 (worst setup
157.898 ns at `ss_n40C_1v60`, Fmax 26.73 MHz; worst hold 0.2586 ns at `ff_n40C_1v95`; best
Fmax 110.05 MHz), kept here so the replaced result stays readable. Propagating the clock
costs setup (insertion delay lands on the launch edge) and *earns* hold (it lands on the
capture edge too): worst setup fell 0.060 ns and worst hold rose 0.0112 ns. Both signs are
what a real clock tree does, and neither moves the verdict.

**Which DR-002 point each declared corner stands in for.** Spec §2 (DR-002) asks for 45
points: {tt, ss, ff, sf, fs} x {-40, 27, 125 C} x {1.62, 1.80, 1.98 V}. `sky130_fd_sc_hd`
ships 18 liberty files and none of them is at a DR-002 point exactly, so the declared set is
the closest available cover at or above 1.60 V:

| Declared liberty corner | DR-002 point it stands in for | How it differs |
|---|---|---|
| `tt_025C_1v80` | tt / 27 C / 1.80 V | 25 C, not 27 C |
| `tt_100C_1v80` | tt / 125 C / 1.80 V | 100 C, not 125 C (optimistic for setup) |
| `ss_100C_1v60` | ss / 125 C / 1.62 V | 100 C and 1.60 V (20 mV low: pessimistic for setup) |
| `ss_n40C_1v60` | ss / -40 C / 1.62 V | 1.60 V, 20 mV low (pessimistic for setup) |
| `ss_n40C_1v76` | ss / -40 C / 1.80 V | 1.76 V, 40 mV low (pessimistic for setup) |
| `ff_100C_1v65` | ff / 125 C / 1.62 V | 100 C; 1.65 V, 30 mV high |
| `ff_n40C_1v65` | ff / -40 C / 1.62 V | 1.65 V, 30 mV high |
| `ff_n40C_1v76` | ff / -40 C / 1.80 V | 1.76 V, 40 mV low |
| `ff_100C_1v95` | ff / 125 C / 1.98 V | 100 C; 1.95 V, 30 mV low (optimistic for hold) |
| `ff_n40C_1v95` | ff / -40 C / 1.98 V | 1.95 V, 30 mV low (optimistic for hold) |

**What the library cannot cover, and so this report does not claim.** There is no `sf` or
`fs` liberty file at all — 18 of the 45 points, uncovered outright. Of the 27 remaining
`tt`/`ss`/`ff` points, ten have the nearest-available stand-in above and 17 do not: the
library ships no file above 100 C (against the 125 C bound), none at 27 C, none at exactly
1.98 V, no `tt` file at -40 C, and no `ss` file above 1.76 V. The liberty files below
1.60 V (`ss_100C_1v40`, `ss_n40C_1v{28,35,40,44}`, `ff_n40C_1v56`) are
outside the spec's 1.62-1.98 V supply range and are deliberately **not** declared. `klt
signoff` grades exactly the corners a run declares, so **item 5 / digital is met on these
ten corners only — this is not 45-corner coverage.** The 35 uncovered DR-002 points are
tracked in #131.

**Other limits of this report, stated rather than implied.**

- **No SPEF.** Routed-DEF timing with no extracted wire parasitics
  (`spef_path: null`, `power_basis.parasitics: "estimate_only"`). Parasitic-annotated
  timing is #35.
- **Propagated clock.** `clock_mode: "propagated"` — the session issues
  `set_propagated_clock [get_clocks clk]`, so the DEF's own clock tree carries insertion
  delay into both the launch and the capture edge of every check. The
  `clock_propagation` evidence block per corner reports the worst network latency actually
  reached: 0.3204 ns at `ff_n40C_1v95` up to 0.9745 ns at `ss_n40C_1v60`, i.e. up to 0.5 %
  of the 195.3125 ns period. Its `clock_sinks` count (2-3) is **not** the size of the tree:
  `report_clock_latency` prints only the min- and max-latency sinks, and `clock_sinks_sample`
  is a diagnostic sample. The latency is computed from the routed DEF's own interconnect
  with no SPEF, so it is an estimate of insertion delay, not an extracted one. The separate
  aggregate `clock_skew_ns` metric is unchanged at ~0.013 ns by propagation.
- **Register-to-register only.** Every corner reports
  `constraint_completeness.status: "incomplete"` with 17 unconstrained endpoints
  (`dout[15:0]`, `dout_valid`) and 0 unclocked registers. No block-boundary input/output
  delay budget is declared, because no ratified document states one; inventing one would be
  a timing contract no spec backs. Tracked in #131.
- **`fmax_mhz` is extrapolated**, `1/(T - WNS)`, not a bisected search.
- **Electrical rules.** `ss_n40C_1v60` reports 660 max-transition and 7 max-capacitance
  violations against the liberty limits (every other declared corner reports 0). These are
  electrical-rule violations, not slack violations: they do not enter the item-5 timing
  verdict and are not addressed here.

## Functional verification (T1 item 5, digital)

The second half of the item-5 digital citation is `klt functional-verification` over the
same cocotb suite CI already runs, against `rtl/decimator.v` + `rtl/decimator_coef.v`:
request `../verification/decimator/fv_request.json`, report
`../verification/decimator/fv-decimator.report.json` — `status: "pass"`, 8 tests, 0 failed,
0 skipped, Icarus 13.0, cocotb 2.1.0, `random_seed` pinned to 1. It is a pre-layout,
zero-delay RTL regression (`environment.sdf: null`); SDF-annotated gate-level
re-simulation is #35. Reproduce with:

```sh
klt functional-verification verification/decimator/fv_request.json \
  -o /tmp/klt-fv-decimator --format json \
  > verification/decimator/fv-decimator.report.json
```

`-o` is load-bearing for the committed artifact: the pinned klt writes the scratch log
paths into `environment.results_xml`/`test_log`/`build_log` as **absolute** paths, so
without it the report would carry the producing checkout's own directory. The same report
carries no `provenance` block at all, which is why the manifest pins a `content_hash` for
the STA citation (the routed DEF's own hash) but none for this one. Both gaps are filed
upstream as 2AMLogic/klayout-tools#5550.

The whole-chain response check (`verification/decimator/response.py`, spec rows 8-9) is
**not** part of the item-5 citation: it stays gated by
`verification/decimator/run_synth.py` and by its own CI step in
`.github/workflows/signoff.yml`.

## Analog partition: `layout/analog/`

Generated GDS of the modulator's analog cells, one directory per cell. #29 assembles
them; until it lands these are standalone cells with no shared floorplan, no top-level
supply plan and no inter-cell abutment.

| Cell | Directory | Status |
|---|---|---|
| `ota_fd` — fully-differential folded-cascode OTA | `analog/ota_fd/` | generated, DRC `clean`, device count matches the netlist (#118) |
| `integrator` — switched-capacitor integrator + 1-bit feedback DAC | `analog/integrator/` | generated, DRC `clean`, device count matches the netlist per model including the low-Vth split (#119) |
| clock generator | — | not started |

### `ota_fd` (#118)

`analog/ota_fd/ota_fd.gds`, top cell `ota_fd`, **352.58 x 144.16 um**
(50,828 um^2). Produced by `analog/ota_fd/gen_ota_fd.py` from
`design/ota/ota_fd.spice`: one `klt gen` call per device group (`diff_pair`
cross-quads for the matched pairs, `mos_array` for the single devices,
`res_array`/`cap_array` for the passives), two `guard_ring` body-tie rings, the
script's own floorplan and met1/met2 router, merged by `klt gen-compose` used as
a placer only. Nothing hand-drawn.

- **Reproducing**: `python3 layout/analog/ota_fd/gen_ota_fd.py --check` regenerates
  into a temp dir and **byte-compares** against the committed stream (it passes; two
  consecutive runs reproduce it exactly). Both the regeneration and the comparison are
  **local-only** — CI installs the pinned klt but no PDK, and every `klt gen`/`drc`/
  `extract` call needs a resolved `sky130A`. CI checks the committed envelopes instead,
  as it does for the digital partition.
- **Build that produced it**: klt `0.9.2.dev964+g02db14ecf46b`, klayout `0.30.13`,
  `sky130A` / open_pdks `f6eeac7` (the `sim/pdk.json` pin). **Not** the klt `0.8.0` CI
  pin — byte-reproducibility is an assertion about that klt build, so the stream and its
  envelopes must be regenerated in the same PR when the pin moves.
- **DRC**: `klt drc` (sky130 curated deck, content hash `sha256:36027b82…`, `released:
  false`) on `ota_fd.gds` is `clean` — **0 violations**, so no rule names to quote;
  report `analog/ota_fd/drc.report.json`. `layers_in_stream_without_rules`: `66/13`
  (resistor-ID marker), `68/5` (`met1.pin` port labels); `rules_skipped`: 53. This is a
  different deck build from the one the digital partition quotes above, and it is **not**
  a DRC-clean signoff claim — that stays with #31.
- **Device count**: `klt extract` gives 29 merged devices (14 `nfet_01v8`, 9
  `pfet_01v8`, 3 `cap_mim_m3_1`, 1 `res_high_po`, 2 `res_xhigh_po`), matching the
  netlist's 29 `X` lines; `analog/ota_fd/extract-device-count.json` records both the
  merged and the `mult`-expanded raw counts and names which was compared.
- **Pins and body ties**: all eight `.subckt` ports (`vdda vssa inp inn outp outn vcm
  ibias`) are labelled on `met1.pin` and come back out of `klt extract` as named pins;
  every nFET bulk extracts to `vssa` and every pFET bulk to `vdda` through the two tap
  rings.
- LVS (#32), parasitic extraction (#35) and power-delivery checks (#39) are not claimed.

Full floorplan, per-pair matching rationale, routing discipline and the klayout-tools
gaps hit along the way: `analog/ota_fd/README.md`.

### `integrator` (#119)

`analog/integrator/integrator.gds`, top cell `integrator`, **493.67 x 313.32 um**
(154,677 um^2, 3183 flattened polygons). Produced by
`analog/integrator/gen_integrator.py` from `design/integrator/integrator.spice`:
one `klt gen` call per distinct device geometry (9 of them cover all 44 netlist
devices, one block per device — nothing folded into a shared array), ten
`guard_ring` body-tie rings, the script's own floorplan and met1/met2 router,
merged by `klt gen-compose` used as a placer only. **The OTA is instantiated,
not redrawn**: a `blocks[].cell` entry naming the committed
`analog/ota_fd/ota_fd.gds`. Nothing hand-drawn.

- **Reproducing**: `python3 layout/analog/integrator/gen_integrator.py --check`
  regenerates into a temp dir and **byte-compares** against the committed stream
  (it passes; consecutive runs reproduce the 269,580-byte stream exactly).
  Local-only, for the same reason as `ota_fd` — CI installs the pinned klt but
  no PDK.
- **Pinned inputs**: the generator asserts the sha256 of **both**
  `analog/ota_fd/ota_fd.gds` (`27ace056…eeefe976`) and
  `design/integrator/integrator.spice` (`18fc5147…4074d53`) before generating,
  and aborts if either moved. That is what makes the stream detectably stale if
  #143 resizes the OTA or #129/#147 resize a switch drawn here.
- **Build that produced it**: klt `0.9.2.dev1022+g2a9c52b27ce7`, klayout
  `0.30.13`, `sky130A` / open_pdks `f6eeac7`. A **later** build than the one that
  produced `ota_fd.gds` (`dev964`); `blocks[].cell` does not regenerate the OTA,
  so the OTA half of the stream is build-independent.
- **DRC**: `klt drc` (sky130 curated deck) on `integrator.gds` is `clean` — **0
  violations**, covering the OTA instance too; report
  `analog/integrator/drc.report.json`. `layers_in_stream_without_rules`: `66/13`
  (resistor-ID marker, from the OTA), `68/5` (`met1.pin`); `rules_skipped`: 51.
  The 20 `lvtn` markers are checked (`lvtn.angle.1`, `lvtn.ongrid.1`). **Not** a
  DRC-clean signoff claim — that stays with #31.
- **Device count**: `klt extract` over the stream, minus `klt extract` over
  `ota_fd.gds` alone in the same run, gives this cell's own **44 devices by
  netlist model**: 9 `nfet_01v8`, 12 `nfet_01v8_lvt`, 9 `pfet_01v8`, 8
  `pfet_01v8_lvt`, 6 `cap_mim_m3_1`, plus the OTA's 29 through its instance.
  **The low-Vth split is confirmed by extraction**, contrary to the premise
  #119's acceptance criterion was weakened on; `extract-device-count.json`
  records both that result and the flavour-blind 21/17/6 the criterion asked
  for, and explains the difference from the earlier probe.
- **Pins and body ties**: the sixteen `.subckt` ports are labelled on `met1.pin`
  and come back out of `klt extract`; `outp`/`outn` share a pin with the OTA's
  own `outp`/`outn` labels, which is how the OTA's outputs are shown to be the
  nets `Ci_p`/`Ci_n` sit on. 42 distinct device-terminal nets, the 29 this cell
  declares plus the OTA's 21 less the 8 they share. Every nFET bulk extracts to
  `vssa` and every pFET bulk to `vdda` through the ten tap rings.
- **Mirror symmetry**: the cell has a horizontal axis at y = 143.43 um and each
  capacitor group (`Csi`, `Csr`, `Ci`) is a true mirror pair about it, asserted
  from the placed geometry on every run. The amplifier-side plate of all six is
  bound to the MiM top plate, which is `design/integrator/SIZING.md:72-74`'s "to
  be confirmed in layout" step — though extraction cannot read a plate binding
  back, and whether `c0` is physically the top plate stays #146's question.
- **Summing nodes**: `sump` 130.5 um, `sumn` 134.5 um of drawn wire, the
  shortest nets in the cell that connect more than three anchors, symmetric to
  3 %. Nothing is shielded, so all four met1 clock adjacencies (0.18–0.32 um,
  all against `phi2`) and all fifteen met1/met2 clock crossings are listed in
  `analog/integrator/route-summary.json` and in the cell's README.
- LVS (#32), parasitic extraction (#35) and power-delivery checks (#39) are not
  claimed.

Full floorplan, plate-binding rationale, the OTA pin-access scheme, and the
klayout-tools gaps hit along the way (#5607, #5608, #5609):
`analog/integrator/README.md`.

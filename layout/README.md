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

Recorded choices (`pnr_request.json`):

- **Supplies**: PDN on `VDDD`/`VSSD` (sky130hd preset: met1 follow-pins, met4/met5 straps) with
  tap cells; separate from `VDDA`/`VSSA` per DR-004. 1625 tap cells; the tool's own
  power-delivery audit reads `complete`.
- **Die / core**: 360.22 x 360.22 um die (129,758 um^2), core 121,877 um^2, 40 % utilization
  target (42.4 % achieved), 5 um core margin. DR-004 gives no coordinates and the analog
  floorplan (#29) has not landed, so this is a standalone block outline; placing it opposite
  the first integrator is left to the assembly step.
- **Clock**: `clk`, 195.3125 ns (fs = 5.12 MHz, spec row 5). Timing closure is #33's concern.

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
(`ss_*`, 1.28-1.76 V); these are not addressed here and no timing number is claimed.

## Analog partition

Empty until #29 lands. See the repo README for scope.

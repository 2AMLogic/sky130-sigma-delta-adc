# `integrator` — generated analog layout

Generated GDS of the switched-capacitor integrator with its 1-bit feedback DAC
(`design/integrator/integrator.sch`, netlist `design/integrator/integrator.spice`,
sizing trace `design/integrator/SIZING.md`). Second of the three cell layouts
the analog partition (#29) assembles; it **instantiates** the OTA cell #118
built (`layout/analog/ota_fd/ota_fd.gds`) rather than redrawing it. The
modulator uses this cell twice (`xi1`, `xi2` in
`design/modulator/modulator.spice`).

| File | Role |
|---|---|
| `gen_integrator.py` | the only source of the stream: `python3 layout/analog/integrator/gen_integrator.py` regenerates, `--check` compares |
| `integrator.gds` | the generated stream, top cell `integrator` |
| `extract-device-count.json` | `klt extract` device count vs the netlist, plus the extracted pin list and net count |
| `drc.report.json` | `klt drc` (sky130 deck) over the committed stream |
| `route-summary.json` | capacitor symmetry, summing-node evidence, per-block origins and orientations, per-net anchors, reserved met2 columns, met1 spine tracks, every `lvtn` marker |

Nothing here is hand-drawn or GUI-edited. Every polygon comes from one of three
places: a `klt gen` call (one per distinct device geometry), the committed
`ota_fd.gds` placed as an instance, or this script's own floorplan and router,
written through `klt draw` and merged by `klt gen-compose` used as a **placer
only** (`placement.strategy: "explicit"`, no `routing` block) — the same split
the sibling `analog/ota_fd/gen_ota_fd.py` documents.

Cell outline **494.57 x 313.32 um** (154,961 um^2), 4259 flattened polygons,
289,704 bytes (`klt stats`; 3965 polygons / 269,844 bytes before #147 added
the `Sci`/`Scr` PMOS halves and the `phi1eb` inverter pair). The OTA instance is 352.58 x 144.16 um of that, so the
integrator's own device field and routing channel account for roughly the left
141 um. The cell's bbox starts at x = **-1.67 um**, not 0: the router's met2
column grid extends two pitches past the leftmost block (the westmost guard
ring, whose own bbox starts at x = 1.58 um), and four trunks take the columns at
x = -1.5, -1.0, -0.5 and 0.0. #29 places this cell by its bbox, so the negative
origin is a datum to read, not a problem to fix here.

## The two pinned inputs

This cell's geometry is only valid against the exact OTA and netlist it was
floorplanned around, so the generator asserts both hashes before it generates
anything and aborts with a "the geometry here is stale" message if either moved:

| Input | sha256 |
|---|---|
| `layout/analog/ota_fd/ota_fd.gds` (124,534 bytes) | `27ace056b255428e05c0fd6293dd08239fe97ba67379f6a330c30a94eeefe976` |
| `design/integrator/integrator.spice` | `6857c4ca5422d9736e6e18a898ab873a7fab9cc1bc89e3e395abe55ab66e1c9d` |

Same `ota_netlist_sha256` / `integrator_netlist_sha256` convention the `sim/`
records already use, and both are repeated in `extract-device-count.json`. This
is what makes the stream **detectably** stale rather than silently stale if
#143 resizes the OTA for flicker noise, or #129/#147 resize a switch that lives
in this cell.

## Reproducing it

```sh
python3 layout/analog/integrator/gen_integrator.py            # regenerate + verify + emit
python3 layout/analog/integrator/gen_integrator.py --check    # regenerate into a temp dir,
                                                              # byte-compare, write nothing
```

**`--check` is a byte-level comparison** of the regenerated GDS against the
committed `integrator.gds`, not a `klt diff` geometry comparison. That is a
stronger assertion and it holds: consecutive runs on this host reproduced the
committed 289,704-byte stream exactly. The script has no randomness and no
dict-ordering dependence (every iteration order is sorted or table-driven).

**Both checks are local-only; CI does not run them.** `.github/workflows/signoff.yml`
installs the pinned klt (`.github/klt-version`, currently `0.8.0`) but installs
**no PDK**, and every `klt gen` / `klt drc` / `klt extract` / `klt gen-compose`
call here needs a resolved `sky130A`. CI checks the committed envelopes instead,
exactly as it does for `ota_fd` and for the digital partition.

**Which build produced the stream** (`extract-device-count.json` → `tool`):

| | |
|---|---|
| klt | `0.9.3.dev256+g59096013d161` (`klayout-tools @ git+https://github.com/2AMLogic/klayout-tools@59096013d161e35fffbda0958887b13887cf3fe5`) |
| klayout | `0.30.13` |
| PDK | `sky130A`, open_pdks `f6eeac7` (the `sim/pdk.json` pin), resolved from `~/.ciel` |

This is **not** the klt CI pin (`0.8.0`), and it is a later build than the one
that produced `ota_fd.gds` (`0.9.2.dev964`). Byte-reproducibility is an
assertion about *this* klt build: a generator change upstream moves geometry, so
`--check` asserts the build recorded in this cell's own evidence, not whatever
`klt` is on PATH. The pin is read back from `drc.report.json` → `provenance`
(`klt_version` / `klt_git_commit` / `klt_reinstall_spec` / `klayout_version`):

The klayout axis is part of the pin: `provenance.klt_reinstall_spec` pins
**klayout-tools** only (upstream declares `klayout>=0.30`, a floor), so the
klayout a fresh resolution installs can drift, and the committed bytes were
written by the klayout recorded beside them. `--check` therefore compares the
running/resolved `klayout_version` against the recorded one and refuses
(exit 2) on a difference — a byte difference is only ever called a geometry
regression when **both** axes match the recording.

- **Host klt matches the recorded commit** — its klayout must equal the
  recorded one too; then the regenerated GDS is byte-compared against
  `integrator.gds` directly. A difference is a generator or geometry
  regression: exit 1, `FAIL`.
- **Host klt differs** — `--check` re-runs the flow under the recorded build
  via `uvx --from "<provenance.klt_reinstall_spec>" --with "klayout==<recorded>" klt`
  (both axes pinned) and byte-compares that output, so the gate stays meaningful
  across host toolchain upgrades. The resolution probe also verifies the
  resolved build's klayout equals the recorded one; the invocation itself
  carries the klayout pin, so a mismatch there means the pin was not honoured
  (stale cache, or the recorded release unavailable on this platform) — it
  names both versions, prints a diagnostic command, and exits 2. A byte
  difference is still exit 1 / `FAIL` (geometry), never blamed on the
  toolchain.
- **The gate cannot run** — `drc.report.json`/`provenance` missing or
  unreadable, `uvx` unavailable, the recorded build failing to resolve, or a
  klayout mismatch on either branch — is exit 2, `CANNOT VERIFY`, naming the
  reason and the exact `uvx` command a human can run. It never reports a
  pass. If `klt version --format json` omits `git_commit`, the direct branch
  degrades to the uvx branch (identity is re-derived there) rather than
  failing.

When the recorded pin moves (a deliberate klt upgrade), re-run the generator
and commit the refreshed stream and envelopes in the same PR — the new
`provenance` becomes the pin `--check` asserts against.
`gen_compose`'s `blocks[].cell` path does **not**
re-generate the OTA, so the OTA half of the stream is whatever `ota_fd.gds`
holds, independent of the klt build used here.

## Device groups

One `klt gen` call per distinct geometry; several netlist devices share a
report, so 50 devices cost 11 `klt gen` calls (plus 10 `guard_ring` calls). Every
netlist device is drawn as its own block — no device is folded into a shared
array — so the drawn device count equals the netlist's line for line.

| Netlist devices | Geometry | Generator | Drawn as |
|---|---|---|---|
| `Sin_*_n` (2) | `nl4` | `mos_array` | W=4, L=0.15, 1 finger, `nfet` **+ `lvtn` marker** (the #129 low-Vth fix) |
| `Sr_*_n`, `Mra_*_n`, `Mrb_*_n` (6) | `n4` | `mos_array` | W=4, L=0.15, 1 finger, `nfet` |
| `Sin_*_p` (2) | `pl8` | `mos_array` | W=8, L=0.35, 1 finger, `pfet` **+ `lvtn` marker** (the #129 low-Vth fix; the lvt PMOS model has no bin below L=0.35) |
| `Sr_*_p`, `Mra_*_p`, `Mrb_*_p` (6) | `p8` | `mos_array` | W=8, L=0.15, 1 finger, `pfet` |
| `Sbi_*`, `Sbr_*`, `Sci_*`, `Scr_*`, `Sti_*`, `Str_*` (12) | `nl12` | `mos_array` | W=12, L=0.15, `nfet` **+ `lvtn` marker** |
| `Sbi_*_p`, `Sbr_*_p` (4) | `pl24` | `mos_array` | W=24, L=0.35, `pfet` **+ `lvtn` marker** |
| `Sti_*_p`, `Str_*_p` (4) | `pl4` | `mos_array` | W=4, L=0.35, `pfet` **+ `lvtn` marker** |
| `Sci_*_p`, `Scr_*_p` (4) | `pl4` | `mos_array` | W=4, L=0.35, 1 finger, `pfet` **+ `lvtn` marker** (the #147 PMOS halves, at the Sti precedent size — same geometry entry as `Sti_*_p`/`Str_*_p`) |
| `Iphi1eb_n`, `Iphi2b_n` (`mult=4`) | `inv_n` | `mos_array` | W=2, L=0.15, **4 fingers** |
| `Iphi1eb_p`, `Iphi2b_p` (`mult=4`) | `inv_p` | `mos_array` | W=4, L=0.15, **4 fingers** |
| `Csi_*`, `Csr_*` (4) | `cap1p` | `cap_array` | one 22.17 x 22.17 um MiM unit |
| `Ci_*` (2) | `cap2p` | `cap_array` | one 31.43 x 31.43 um MiM unit |

`dummy=0` on every `mos_array`, as in the sibling cell. The only devices the
netlist gives a `mult` are the four inverter halves (`phi2b` and the #147
`phi1eb` pair), drawn as 4 fingers each of
the netlist's own W — so the drawn total width equals the schematic's, and the
four units merge back to one device in the count (below).

**No unit-capacitor decomposition.** `Ci` is one 2 pF `cap_mim_m3_1`, not two
1 pF units in parallel, because splitting it is a schematic change (device
count, netlist regeneration, item-1 envelope refresh) that #119 rules out. If
#34's mismatch result asks for a ratio-matched unit array, that is a separate
issue against `design/`, not a layout-only change.

### The `lvtn` markers are drawn by this script, not by `klt gen`

`klt gen mos_array`'s `voltage_flavor` resolves **no** marker on the sky130
family for any low-Vth name — it accepts `hvi`, `native` and `nvt`, and reports
`drc_hints.voltage_flavor_mark_present: false` with "no marker was drawn" for
anything else. So the 28 `_lvt` devices get their `lvtn` (125/44) rectangle
from this script: one per device, the placed block's own bbox grown by 0.38 um,
emitted in the same `klt draw` document as the routing. The generator then
asserts that no marker reaches a device the netlist declares standard-Vth, and
`route-summary.json` → `lvtn_markers` records all 28 rectangles.

Filed as a tool gap: **2AMLogic/klayout-tools#5607**.

The markers are not decorative. `klt drc` checks `lvtn.angle.1` and
`lvtn.ongrid.1` on them (both pass), and `klt extract` reads them — see the
device count below.

## Mirror symmetry and the capacitors

The cell has a horizontal mirror axis at **y = 143.43 um**. The p-side device
rows sit above it and the n-side rows are the same geometries at the mirrored
`gen-compose` orientation, placed so that each row is the reflection of its
partner. The OTA is placed so that its own `inn`/`inp` labels — which are
`sump`/`sumn` — straddle that axis.

Each of the three capacitor groups is therefore a **true mirror pair about the
cell's axis**, not merely a matched pair placed somewhere convenient. The
generator reads this back off the placed geometry and refuses to emit a stream
where it does not hold (`route-summary.json` → `capacitors`):

| Group | Plate | p-side block | n-side block | Mirror check |
|---|---|---|---|---|
| `Csi` | 22.17 x 22.17 um | `csi_p`, `rotate_180`, y 184.97–209.06 | `csi_n`, `mirror_x`, y 77.80–101.89 | same x; 41.54 um either side of the axis |
| `Csr` | 22.17 x 22.17 um | `csr_p`, `rotate_180`, y 184.97–209.06 | `csr_n`, `mirror_x`, y 77.80–101.89 | same x; 41.54 um either side |
| `Ci` | 31.43 x 31.43 um | `ci_p`, `rotate_180`, y 184.97–218.32 | `ci_n`, `mirror_x`, y 68.54–101.89 | same x; 41.54 um either side |

This is **mirror symmetry, not common centroid**. DR-004 item 3 asks for
common-centroid capacitor arrays, and #119's criterion allows either; a
common-centroid A-B-B-A arrangement of a two-element group needs each
capacitor split into two series/parallel halves, which is the unit
decomposition the issue rules out. Mirror symmetry is what a two-element group
can have without changing the netlist, and it is what is drawn.

### Plate binding: the amplifier side is on the MiM top plate, uniformly

All six capacitors bind the **netlist's first terminal to the `cap_array` `_TOP`
port**, which the generator reports on met4 (71/20) over the capm plate:

| Capacitor | Netlist | Top plate (met4) | Bottom plate (met3) |
|---|---|---|---|
| `Csi_p` / `Csi_n` | `XCsi_p tpi_p bpi_p` | `tpi_p` / `tpi_n` | `bpi_p` / `bpi_n` |
| `Csr_p` / `Csr_n` | `XCsr_p tpr_p bpr_p` | `tpr_p` / `tpr_n` | `bpr_p` / `bpr_n` |
| `Ci_p` / `Ci_n` | `XCi_p sump voutp` | `sump` / `sumn` | `voutp` / `voutn` |

In every case the first terminal is the amplifier/summing-node side (`tp*`
reaches `sump`/`sumn` through `Sti`/`Str`; `Ci`'s first terminal **is** the
summing node), which is `design/integrator/SIZING.md:72-74`'s "the
amplifier-side plate of each capacitor is drawn on the MIM top plate (`c0`) to
keep the substrate parasitic off the summing node (**to be confirmed in
layout**)". **This cell is that confirmation step**, and the binding is uniform
across all six — the inconsistency #146 found between `ota_fd`'s two cap groups
does not repeat here.

Two honest caveats:

- **`klt extract` cannot read the binding back.** It normalises a two-terminal
  device and names the plates `a`/`b`, so the extracted netlist says nothing
  about which metal a net landed on. The binding is asserted by the generator's
  layer choice and recorded in `route-summary.json`; it is not independently
  confirmed by extraction. Same blind spot #146 hit.
- **Whether `c0` is physically the top plate in the sky130 model is #146's open
  question, not this cell's.** If #146 concludes `c0` is the bottom plate, what
  changes is `SIZING.md:72` — the intent — and this cell is regenerated with the
  binding flipped. The binding here follows the documented intent and the
  netlist's terminal order, which agree.

## Floorplan

Five half-rows per side, listed from the mirror axis outward, plus two rows for
the single-ended `phi2b` and `phi1eb` inverters and the OTA instance to the
east.

| |y - axis| (um) | Row | Blocks | Ring |
|---|---|---|---|
| 3.0 – 16.1 | `swn` | `Sti`, `Str` (nFET low-Vth, W=12) | `ptap_swn_p`/`_n` |
| 26.1 – 31.5 | `swp` | `Sti_p`, `Str_p` (pFET low-Vth, W=4) | `ntap_swp_p`/`_n` |
| 41.5 – 74.9 | `cap` | `Csr`, `Csi`, `Ci` (left to right) | — |
| 85.9 – 99.0 | `nfet` | `Mra_n`, `Mrb_n`, `Sin_n`, `Sr_n`, `Sbi`, `Sbr`, `Sci`, `Scr` | `ptap_p`/`_n` |
| 112.0 – 137.4 | `pfet` | `Mra_p`, `Mrb_p`, `Sin_p`, `Sr_p`, `Sbi_p`, `Sbr_p`, `Sci_p`, `Scr_p` | `ntap_p`/`_n` |
| p side only, beyond `pfet` | `inv_n`, `inv_p` | `Iphi1eb_n`, `Iphi2b_n` / `Iphi1eb_p`, `Iphi2b_p` | `ptap_inv`, `ntap_inv` |

**The first two rows exist to keep the summing node short.** Every device on
`sump`/`sumn` — the four `Sti`/`Str` switch halves per side and the integrating
capacitor's top plate — is in the three rows nearest the axis, and the two
switch rows are **right-aligned** against the device field's eastern edge, which
is the edge the OTA sits beyond. Before that restructuring the switch halves
were distributed by flavour across the whole field and the two summing nodes
routed 240.1 / 244.0 um; afterwards they route 130.5 / 134.5 um (120.7 / 133.1
in the current, post-#147 field).

**Body ties.** Ten `klt gen guard_ring` blocks, one per (flavour, row): an
`add_well=false` p+ tap ring in the p-substrate around each nFET row, tied to
`vssa`, and an `add_well=true` n+ tap ring inside an n-well around each pFET
row, tied to `vdda`. These are not an assertion — `klt extract` resolves every
one of this cell's nFET bulks to `vssa` and every pFET bulk to `vdda` in the
committed stream, which it could not do without a contacted tie.

Inter-block gaps are 14 um, far wider than any DRC minimum. That is a routing
constraint, not a matching one: the router gives every met2 trunk its own global
x column on a 0.5 um grid, so the field has to be wide enough to hold one column
per anchor. 186 columns are reserved (trunks plus riser keep-outs).

## How the OTA is reached

The OTA is a `blocks[].cell` entry — an existing cell in an existing stream,
placed, never regenerated. Its eight ports are recovered from the `met1.pin`
(68/5) labels #118 drew, through `cell.ports_from_labels`, with an `access`
landing search that finds, for each, a point on that net where a via1+via2
ladder up to met3 clears the OTA's own geometry.

That matters because **the OTA cell has no boundary pins**: all eight labels sit
in its interior, within x 3–36 um and y 74–131 um of its own origin, in the
middle of a cell whose met1 and met2 are dense across its full 352 um width. The
escape works only because the OTA draws **no met3 above y = 61.82 um** in its
own frame, and every landing is above that. So each port's route is: the
validated ladder at the landing point, then a met3 run due west at the landing's
own y, out over the OTA and past its western edge, then a via2/via1 stack back
down to met2/met1 on a column this cell owns. The eight landings are 2.4 um
apart in y at the closest, against a 0.9 um met3 pitch, so the eight runs cannot
collide; the columns are assigned west-to-east in descending landing y, so a
column never lies under a higher landing's own run.

The instance origin is (139.62, 40.80); the landings below are in the composed
frame, listed in the order the escape columns are assigned (descending y):

| OTA port | Integrator net | Landing x, y (um) |
|---|---|---|
| `vdda` | `vdda` | 142.97, 170.85 |
| `inn` | `sump` | 146.47, 148.20 |
| `outp` | `voutp` | 154.97, 141.70 |
| `inp` | `sumn` | 146.27, 138.65 |
| `outn` | `voutn` | 158.77, 132.65 |
| `vssa` | `vssa` | 143.47, 130.25 |
| `vcm` | `vcm` | 175.94, 118.55 |
| `ibias` | `ibias` | 144.47, 115.05 |

(`route-summary.json` → `ota` carries these, the instance origin, and
`gen-compose`'s own `source_digest` of the stream it read.)

**No met1 or met2 of this cell's is ever placed over the OTA instance** — the
router's x window stops a pitch short of it, and the eight escape columns are
carved out of the last few pitches of that window. Only met3 crosses, where the
OTA has none.

Two klayout-tools gaps were hit here and filed:

- **2AMLogic/klayout-tools#5608** — the `access` landing search checks the
  via-drop pads against *other* nets but not against the port net's **own**
  shapes, so a pad wider than the run it lands on protrudes and leaves a
  sub-minimum notch against the macro's other metal. klt's own pad sizes
  (met1/met2 0.42 um) did exactly that on `outn`: `met1.space.1` +
  `met2.space.1`, a 0.13 um gap. This script draws the deck minimum instead
  (met1 0.34, met2 0.38, met3 0.49), which clears it.
- **2AMLogic/klayout-tools#5609** — `derived_ports[].label_um` and `.landing`
  come back in the *source* cell's frame while `bbox_um` and `ports[]` come back
  in the composed frame, with nothing marking the difference. This script runs
  the probe at the origin and translates itself.

A third gap, the missing low-Vth generator flavour, is
**2AMLogic/klayout-tools#5607** (above).

## Routing discipline

Three planes, the same split the sibling cell uses:

- **In-block straps (met1).** A `klt gen` block exposes each unit's S/D/G
  separately, so the router first collapses each block to one anchor per net:
  pads of a net sharing a pad row are tied by one horizontal met1 strap with an
  mcon on each pad, on its own track of a 0.5 um ladder inside the pads.
- **met1 horizontal, met2 vertical.** Every horizontal run and every short jog
  onto a pad is met1; met2 carries per-anchor vertical trunks and nothing else.
- **One global x column per trunk.** Columns sit on a 0.5 um grid and a trunk
  owns its column outright, so two met2 runs can never come within a pitch of
  each other and no met2–met2 spacing search is needed. 186 columns are
  reserved (trunks plus riser keep-outs).
- **met3/met4 risers.** `cap_array` reports its bottom plate on met3 and its top
  plate on met4, so each capacitor terminal gets a same-layer run out of the
  block and a via stack down to met2. The eight OTA escapes use met3 as above.

Nets are routed in a fixed order with `sump` and `sumn` **first**, so they take
the shortest columns and tracks the floorplan allows and every other net routes
around them.

## Verification

The DRC verdict, the device counts, the pins and the net count below are
re-asserted by the script on every run; a failure aborts before anything is
emitted. The `coverage`-block disclosure numbers are recorded evidence, not
re-asserted: they shift with the klt deck build.

### DRC

`klt drc --deck sky130` over the committed `integrator.gds`, top cell
`integrator`, is **`clean`: 0 violations**, so there are no rule names to quote
(`drc.report.json`). Disclosure from the report's `coverage` block:
`layers_in_stream_without_rules` (drawn, no rule) is `66/13` (the resistor-ID
marker, which comes in with the OTA instance) and `68/5` (`met1.pin`, the port
labels); `rules_skipped` is 51, all no-applicable-geometry angle/ongrid/width
rules on layers absent from this stream. The 28 `lvtn` rectangles **are**
checked (`lvtn.angle.1`, `lvtn.ongrid.1`).

This is klt's curated deck, **not** the foundry-complete deck, and not the same
deck build `layout/README.md` quotes for the digital partition (klt `0.8.0`).
**This is not a DRC-clean signoff claim** — that is #31's, against the deck and
klt build #31 chooses. Note the run covers the OTA instance too, so this is also
a re-confirmation that `ota_fd.gds` is clean in context.

### Device count — including the low-Vth split

`klt extract` over the committed stream, **minus** `klt extract` over the
committed `ota_fd.gds` on its own in the same run (the extractor flattens
through the placed instance, so the OTA's devices appear in both and cancel).
The difference is this cell's own devices:

| Netlist model | Netlist | Extracted |
|---|---|---|
| `sky130_fd_pr__nfet_01v8` | 8 | **8** |
| `sky130_fd_pr__nfet_01v8_lvt` | 14 | **14** |
| `sky130_fd_pr__pfet_01v8` | 8 | **8** |
| `sky130_fd_pr__pfet_01v8_lvt` | 14 | **14** |
| `sky130_fd_pr__cap_mim_m3_1` | 6 | **6** |
| total | 50 | **50** |

matching `design/integrator/integrator.spice`'s 50 primitive `X` lines exactly,
plus the OTA's own 29 devices through its instance.

**This is stronger than #119's acceptance criterion, and the criterion's premise
turned out to be wrong.** The issue weakened the check to a flavour-blind
21 `nfet` / 17 `pfet` / 6 `cap_mim` total, on the strength of a curator probe
that found `klt extract --deck sky130` reporting an `lvtn` marker as
recognition-only and classifying marked and unmarked arrays identically. On this
cell's geometry it does not: the extracted netlist names
`sky130_fd_pr__nfet_01v8_lvt` and `sky130_fd_pr__pfet_01v8_lvt` and gets all
twenty-eight right (14 nfet + 14 pfet; #129 moved the `Sin` halves, #147 added
the `Sci`/`Scr` PMOS halves). The likely difference is the marker's extent —
2AMLogic/klayout-tools#5301 records that the sky130 deck decides flavour by
channel overlap and mis-classifies a marker that ends inside a shared
source/drain diffusion, and the probe used a two-column array while every marker
here covers one whole single-finger device plus a 0.38 um enclosure.
`extract-device-count.json` records **both** results: the per-model counts under
`found_own_devices`, with `lvt_split_confirmed_by_extraction: true`, and the
criterion as written under `flavour_blind_check` (22 / 22 / 6, also passing).
No regression report was filed upstream against the closed
klayout-tools#5283/#5301, because the behaviour those describe did not reproduce
here.

Counts are **merged** first — devices sharing a model and all terminals, after
normalising the terminals a device is symmetric in — which is what an LVS
combine-parallel-devices pass does, and what makes each 4-finger inverter half
count once. `raw_counts` records the unmerged figures beside them (64
`nfet_01v8` and 45 `pfet_01v8` across the whole stream, OTA included), so the
merge is visible rather than silent.

### Pins

The sixteen `.subckt` ports are labelled on `met1.pin` (68/5). `klt extract`
returns **eighteen pins carrying twenty label texts**:

- the sixteen this cell drew, and
- four more — `inp`, `inn`, `outp`, `outn` — which are the **OTA cell's own**
  `met1.pin` labels, carried in through the instance.

`outp` and `outn` come back **sharing a pin** with this cell's `voutp`/`voutn`
(`* pin outp,voutp`), which is the evidence that the OTA's outputs really are
the nets the integrating capacitors sit on. `inp` and `inn` stand alone, on
`sumn`/`sump`, which this cell does not export. The generator asserts that exact
grouping; a label that landed on metal its net does not own would break it.

### Net count

The extracted netlist has **43** distinct device-terminal nets: this cell's 30
schematic nets plus the OTA's 21, less the 8 they share. A terminal the router
left dangling still extracts, as an extra node on an otherwise correct device,
so the device count alone cannot see it; this count can.

### Summing nodes (`sump`, `sumn`)

`route-summary.json` → `summing_nodes` records the whole of the following.

**Drawn lengths: `sump` 120.695 um, `sumn` 133.075 um** — a 9.3 % difference.
Both are shorter than every other multi-anchor net in the cell. The full ranking
is `ibias` (16.2, one anchor — it has no device in this cell and only reaches
the OTA), `vinp` (38.6), `vinn` (40.6), then **`sump` and `sumn`**, then
`voutn` (143.0) and everything else up to `vcm` (1954.7). So the claim that
holds, and the one the generator can support, is: *the two summing nodes are the
shortest nets in the cell that connect more than three anchors.* The asymmetry
between them grew from 3 % (pre-#147) to 9.3 % when the field widened: the two
rows the extra `Sci`/`Scr` PMOS halves joined are left-aligned, so the pfet row
became the widest row and the whole field grew 0.9 um east — and `sump`, routed
first, kept more of the short-column advantage than `sumn`. The asymmetry is
the router's greedy column and track choice, not a floorplan asymmetry: the
capacitor and switch placements are exact mirrors (above), and the OTA's
`inn`/`inp` are equidistant from the axis by construction.

**Clock proximity is disclosed, not shielded.** Nothing in this cell is
shielded, so every place a clock run comes within 1.0 um of a summing-node run
on the same layer, or crosses one on a different layer, is listed here and in
the committed summary. `phi1eb` — the #147 local complement that gates the
`Sci`/`Scr` PMOS halves — is a clock net like the others and is disclosed the
same way:

*Beside* — two met1 adjacencies, both against `phi1eb`:

| Summing net | Clock | Layer | Gap |
|---|---|---|---|
| `sump` | `phi1eb` | met1 | 0.160 um |
| `sump` | `phi1eb` | met1 | 0.160 um |

*Over* — nineteen orthogonal met1/met2 crossings (16 of 0.1156 um^2 — a 0.34 x
0.34 um overlap — one of 0.0986 and two of 0.0782): `sump`/`sumn` against
`phi2` (8), `phi1eb` (5), `phi2b` (4) and `phi1e` (2).

`phi2` is the phase that closes `Sti`/`Str` onto the summing node, so a `phi2`
coupling injects while the summing node is already connected to the amplifier
rather than during the hold — which is the less damaging of the two cases, but
it is not nothing, and no number here says how much charge it is. `phi1eb`
couples to `sump` while the top plate is being driven to `vcm` through the
`Sci`/`Scr` half it gates, i.e. during the reset, not the hold. **Quantifying
any of it is parasitic extraction's job (#35), not this cell's**; what this
cell owes is the list, and the list is above.

## What this cell does *not* claim

- A **DRC-clean signoff** verdict: #31, against the deck and klt build it
  chooses. The 0-violation run above is this issue's evidence that the geometry
  is sane, not a tier claim.
- An **LVS match**: #32. The extracted netlist does correspond device-for-device
  (including flavour) and net-for-net to `design/integrator/integrator.spice`,
  but no `klt lvs` compare was run and no reference-vs-layout envelope is
  committed.
- **Parasitic extraction** (#35) — including any statement about how much the
  clock crossings listed above actually couple — and **power-delivery
  checks** (#39).
- That `c0` is the sky130 model's physical top plate: #146.
- Any **simulated or measured** result. Nothing here was simulated; no number on
  this page comes from ngspice.

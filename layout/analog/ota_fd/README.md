# `ota_fd` — generated analog layout

Generated GDS of the fully-differential folded-cascode OTA
(`design/ota/ota_fd.sch`, netlist `design/ota/ota_fd.spice`, sizing trace
`design/ota/SIZING.md`). First of the three cell layouts the analog partition
(#29) assembles; the integrator (#119) instantiates this cell.

| File | Role |
|---|---|
| `gen_ota_fd.py` | the only source of the stream: `python3 layout/analog/ota_fd/gen_ota_fd.py` regenerates, `--check` compares |
| `ota_fd.gds` | the generated stream, top cell `ota_fd` |
| `extract-device-count.json` | `klt extract` device count vs the netlist, plus the extracted pin list and net count |
| `drc.report.json` | `klt drc` (sky130 deck) over the committed stream |
| `route-summary.json` | where every net was routed: per-block origins, per-net anchors, met2 columns, met1 spine tracks |

Nothing here is hand-drawn or GUI-edited. Every polygon comes either from a
`klt gen` call (one per device group) or from this script's own floorplan and
router, written through `klt draw` and merged by `klt gen-compose` used as a
**placer only** (`placement.strategy: "explicit"`, no `routing` block) — the
same split the pinned sibling `2AMLogic/sky130-comparator`
(`a0767fa5a4bedc9128a7e95b8b512075536522c8`, `layout/gen_comparator.py`) uses
and documents.

Cell outline **352.58 x 144.16 um** (50,828 um^2), 1877 flattened polygons.
The width is set by `Rcm1`/`Rcm2`: each is a single 350 um `res_xhigh_po_0p35`
body in the schematic, and `klt gen res_array`'s `rows` folds the *number* of
units, not one unit's length, so a single 350 um body cannot be serpentined.
Splitting `Rcm` into series units would be a schematic change, which this
issue rules out (`design/` + netlist regeneration + an item-1 envelope
refresh), so the body is drawn straight and the cell is as wide as it is.
Filed as a tool gap: 2AMLogic/klayout-tools#5555.

## Reproducing it

```sh
python3 layout/analog/ota_fd/gen_ota_fd.py            # regenerate + verify + emit
python3 layout/analog/ota_fd/gen_ota_fd.py --check    # regenerate into a temp dir,
                                                      # byte-compare, write nothing
```

**`--check` is a byte-level comparison** of the regenerated GDS against the
committed `ota_fd.gds`, not a `klt diff` geometry comparison. That is a
stronger assertion and it holds: two consecutive runs on this host reproduced
the committed 124,534-byte stream exactly. The script has no randomness and no
dict-ordering dependence (every iteration order is sorted or table-driven).

**Both checks are local-only; CI does not run them.** `.github/workflows/signoff.yml`
installs the pinned klt (`.github/klt-version`, currently `0.8.0`) but installs
**no PDK**, and every `klt gen` / `klt drc` / `klt extract` call here needs a
resolved `sky130A`. CI checks the committed envelopes instead, exactly as it
does for the digital partition.

**Which build produced the stream** (`extract-device-count.json` → `tool`):

| | |
|---|---|
| klt | `0.9.2.dev964+g02db14ecf46b` (`klayout-tools @ git+https://github.com/2AMLogic/klayout-tools@02db14ecf46b`) |
| klayout | `0.30.13` |
| PDK | `sky130A`, open_pdks `f6eeac7` (the `sim/pdk.json` pin), resolved from `~/.ciel` |

This is **not** the klt CI pins (`0.8.0`). Byte-reproducibility is an assertion
about *this* klt build: a generator change upstream moves geometry, so
`--check` on a different klt will fail even though the design did not change.
Re-run the generator and commit the refreshed stream and envelopes in the same
PR when the pin moves.

## Device groups

One `klt gen` call per matched group or single device. A netlist device with
`mult=M` is drawn as `splits=M` interleaved unit instances at the netlist's own
`W`, so the drawn total width equals the schematic's.

| Netlist devices | Block | Generator | Drawn as |
|---|---|---|---|
| `M1`, `M2` | `inpair` | `diff_pair` | `splits=2`, W=8 per unit (schematic W=16, `mult=1`) |
| `MT` | `mtail` | `mos_array` | `fingers=16`, W=2 (schematic `mult=16`) |
| `MP1`, `MP2` | `ptop` | `diff_pair` | `splits=8`, W=10 (`mult=8`) |
| `MPC1`, `MPC2` | `pcasc` | `diff_pair` | `splits=4`, W=10 (`mult=4`) |
| `MNC1`, `MNC2` | `ncasc` | `diff_pair` | `splits=2`, W=7 (`mult=2`) |
| `MN1`, `MN2` | `nsink` | `diff_pair` | `splits=8`, W=2 (`mult=8`) |
| `MCS`, `MCR` | `cmfbin` | `diff_pair` | `splits=2`, W=2 (`mult=2`) |
| `MCPS`, `MCPR` | `cmfbld` | `diff_pair` | `splits=2`, W=2.5 per unit (schematic W=5, `mult=1`) |
| `MCT` | `mct` | `mos_array` | `fingers=2` (`mult=2`) |
| `MB1`, `MBN1`, `MBN2` | `mb1`, `mbn1`, `mbn2` | `mos_array` | one W=2 unit each |
| `MBCN` | `mbcn` | `mos_array` | one W=0.42, L=1.0 unit |
| `MBP1`, `MBP2` | `mbp1`, `mbp2` | `mos_array` | one W=5 unit each |
| `MBCP` | `mbcp` | `mos_array` | one W=0.42, L=0.6 unit |
| `Rcm1`, `Rcm2` | `rcm` | `res_array` | `flavor=xhigh`, 350 x 0.35 um, `num=2`, `rows=2` |
| `Rz` | `rz` | `res_array` | `flavor=high`, 4.5 x 0.35 um |
| `Cff1`, `Cff2` | `cff` | `cap_array` | two 7.07 x 7.07 um MiM units |
| `Ccm` | `ccm` | `cap_array` | one 44.2 x 44.2 um MiM unit |

`dummy=0` on every `mos_array`/`res_array`. klt's dummy elements do **not**
extract as devices (probed: a `dummy=1` `mos_array` and a `dummy=1` `res_array`
each extract exactly their real units), so they would not have broken the
device count — see the matched-pairs table below for why they are omitted
anyway.

### Two groups are drawn at half the schematic's `W`

`inpair` (`M1`/`M2`, W=16, `mult=1`) and `cmfbld` (`MCPS`/`MCPR`, W=5,
`mult=1`) are the two matched pairs the schematic declares as single devices.
`diff_pair` only interleaves `splits >= 2`, so getting a cross-quad for them
means drawing two half-width units per device: W=8 x2 and W=2.5 x2. Total
drawn width equals the schematic's and the device count is unchanged (the two
units merge, below), but the *per-device* `W` in the layout is half the
netlist's. This is the same trade the pinned sibling's input pair makes
(schematic W=13 drawn as 2 x W=6.5). It is recorded here because **#32's LVS
will see it** as a property difference unless its request compares total width
rather than per-device `W`.

## Matched pairs and how each was drawn

`design/ota/SIZING.md` never uses the word "matched", so the groups below are
the list the curator read off the netlist connectivity and the sizing table
(issue #118 body, "Curator pass").

| Pair | Drawn |
|---|---|
| `M1`/`M2` (input pair) | **Common-centroid cross-quad**, `diff_pair splits=2`: two W=8 units per device interleaved over two rows, the top row in mirrored column order. This is the offset-critical pair |
| `MP1`/`MP2` (folded-cascode top sources) | **Common-centroid cross-quad**, `splits=8`: eight W=10 units per device, 16 columns, mirrored top row |
| `MPC1`/`MPC2` (pFET cascodes) | **Common-centroid cross-quad**, `splits=4` |
| `MNC1`/`MNC2` (nFET cascodes) | **Common-centroid cross-quad**, `splits=2` |
| `MN1`/`MN2` (bottom sinks) | **Common-centroid cross-quad**, `splits=8`, `mirror=true` (current-mirror labels) |
| `MCS`/`MCR` (CM sense pair) | **Common-centroid cross-quad**, `splits=2` |
| `MCPS`/`MCPR` (CMFB load mirror) | **Common-centroid cross-quad**, `splits=2`, `mirror=true`, at half `W` (above) |
| `Rcm1`/`Rcm2` (CM sense resistors) | **Adjacent identical bodies, no dummies** — see below |
| `Cff1`/`Cff2` (CM-loop feedforward caps) | **Adjacent identical units** in one `cap_array`, 1.5 um apart, same plate size and orientation, no dummies — `cap_array` draws no dummy units |
| `ibias` mirror family (`MB1`, `MT`, `MBN1`, `MBN2`, `MCT`, and `MN1`/`MN2` above) | **Unit-matched and abutted, not interdigitated** — see below |

**`Rcm1`/`Rcm2`: not common-centroid, and no dummies.** Common-centroid for a
two-element resistor pair needs each body split into two series halves
(A-B-B-A), which is a schematic change this issue rules out. That leaves
dummies as the AC's other option, and they are declined: `res_array dummy=1`
adds one dummy body per row, which at 350 um per body doubles the strip from
351 um to 703 um and so doubles the whole cell's width — and with `rows=2` the
dummies land at the *outer* ends of the boustrophedon rows, not between the two
real bodies, so they do not shield the one environment asymmetry that matters.
What is drawn instead: the two bodies are the two folded rows of one
`res_array` — same drawn length, same drawn width, same flavour, 2.6 um apart,
sharing one local environment. The residual mismatch moves the *sensed* common
mode, not the differential signal (`design/ota/SIZING.md`, "CM sense made
linear"), so this is the pair in the list that needs matching least.

**The `ibias` mirror family: unit-matched, not interdigitated.** Every leg is
built from the same W=2/L=0.5 unit: `MT` as a 16-finger `mos_array` (16 units
on one shared diffusion — the tightest unit-to-unit match available),
`MN1`/`MN2` as the cross-quad `nsink` above, `MCT` as 2 fingers, and `MB1`,
`MBN1`, `MBN2` as single units placed in one row, `MB1` (the reference)
leftmost. They are **not** interdigitated with each other. Reason: these are
the 5 uA-class bias legs, where a mirror-ratio error shifts a bias current by a
few percent and is absorbed by the settling margin already recorded
(`sim/ota-settling/record-i51-rcm2M-cff100f.json`, 45/45 corners), whereas
interdigitating five different devices into one array means routing 63
independently-exposed unit terminals through the same channel the signal path
uses. The two legs whose *matching to each other* actually sets the output
balance — `MN1`/`MN2` — are cross-quad.

## Body ties

Two `klt gen guard_ring` blocks, one per device flavour:

- `ptapring` — `add_well=false`: a p+ tap ring (`tap` + `psdm` + `licon` + `li1`)
  in the p-substrate around both nFET rows, 74.95 x 41.37 um, tied to **`vssa`**.
- `ntapring` — `add_well=true`: an n+ tap ring (`tap` + `nsdm`) inside a solid
  `nwell` box over its whole extent around the pFET row, 54.32 x 28.18 um, tied
  to **`vdda`**. The ring's own well merges each pFET block's local well into
  one.

These are not an assertion: `klt extract` resolves **every** nFET's bulk
terminal to `vssa` and every pFET's to `vdda` in the committed stream
(`_gen/ota_fd.extract.spice`), which it could not do without a contacted tie.

## Floorplan and routing

Five rows, bottom to top, each separated by a routing channel:

| y (um) | Row | Blocks |
|---|---|---|
| 0 - 5 | passives | `rcm` (the 351 um CM-sense strip) |
| 14 - 60 | MiM caps | `ccm`, `cff`, `rz` |
| 69 - 110 | nFET bias (inside `ptapring`) | `mb1`, `mbn1`, `mbn2`, `mbcn`, `mct`, `cmfbin`, `mtail`, `nsink` |
| 89 - 108 | nFET signal (inside `ptapring`) | `inpair`, `ncasc` |
| 116 - 144 | pFET (inside `ntapring`) | `ptop`, `pcasc`, `cmfbld`, `mbp1`, `mbp2`, `mbcp` |

Routing discipline, two layers plus a MiM riser:

- **In-block straps (met1).** A `klt gen` block exposes every unit
  sub-instance's S/D/G separately — a `splits=8` `diff_pair` reports 48 ports —
  so the router first collapses each block to one anchor per net: the pads of a
  net that share a pad row are tied by one horizontal met1 strap with an mcon
  on each pad, on its own track of a 0.5 um ladder inside the pads so several
  nets can share one row. The strap is spanned by pad **x**, never by port
  name: `diff_pair` numbers its top row in mirrored column order, so name
  order silently leaves that row's outermost sub-instance unstrapped (it did,
  until the device count caught it). Filed as a tool gap:
  2AMLogic/klayout-tools#5557.
- **met1 horizontal, met2 vertical.** Every horizontal run and every short jog
  onto a pad is met1; met2 carries per-anchor vertical trunks and nothing else.
- **One global x column per trunk.** Columns sit on a 0.5 um grid and a trunk
  owns its column outright, so two met2 runs can never come within a pitch of
  each other and no met2-met2 spacing search is needed. 117 columns are in use.
- **MiM risers.** `cap_array` reports its bottom plate on met3 and its top
  plate on met4, so each capacitor terminal gets a same-layer run out of the
  block followed by a via3/via2 stack down to met2. Filed as a tool gap:
  2AMLogic/klayout-tools#5556.

`route-summary.json` records every block origin, every net's anchors with the
met2 column and y each landed on, and every met1 spine track.

## Verification

All four numbers below are regenerated by the script and re-asserted on every
run; a failure aborts before anything is emitted.

**DRC** — `klt drc --deck sky130` over the committed `ota_fd.gds`, top cell
`ota_fd`, is **`clean`: 0 violations**, so there are no rule names to quote
(`drc.report.json`). Disclosure from the report's `coverage` block: `deck_scope`
is cap2m, capm, ct, difftap, li, licon, m1-m5, npc, nsdm, nwell, poly, psdm,
rpm, urpm, via, via2-via4, x. `layers_in_stream_without_rules` (drawn, no
rule): `66/13` (the resistor-ID marker `res_array` draws) and `68/5`
(`met1.pin`, the port labels). `rules_skipped`: 53, all no-applicable-geometry
angle/ongrid/width rules on layers absent from this stream. This is klt's
curated deck (`sha256:36027b82…`, `released: false`), **not** the
foundry-complete deck, and not the same deck build `layout/README.md` quotes
for the digital partition (klt `0.8.0`). **This is not a DRC-clean signoff
claim** — that is #31's, against the deck and klt build #31 chooses.

**Device count** — `klt extract` over the committed stream gives **29 merged
devices: 14 `nfet_01v8`, 9 `pfet_01v8`, 3 `cap_mim_m3_1`, 1 `res_high_po`,
2 `res_xhigh_po`**, matching `design/ota/ota_fd.spice`'s 29 `X` lines exactly
(`extract-device-count.json`). The count is derived from the extracted
netlist, never from the generator's parameters.

Two bases are recorded, because the netlist's `mult=` makes "device count"
ambiguous:

- `raw_counts` — one entry per drawn unit device: 50 `nfet_01v8`, 31
  `pfet_01v8`, 3 MiM, 3 poly resistors. This is the `mult`-expanded unit count
  (48 nFET / 29 pFET in the netlist) **plus** the two half-`W` splits described
  above (`inpair` +2 nFET, `cmfbld` +2 pFET).
- `merged_counts` — devices sharing a model and all terminals merged, after
  normalising the terminals a device is symmetric in (a MOSFET's source and
  drain alternate finger by finger, so a 16-finger device would otherwise count
  as two). This mirrors an LVS combine-parallel-devices pass, and it is the
  basis compared against the 29 instance lines.

**Pins** — the eight `.subckt` ports `vdda vssa inp inn outp outn vcm ibias`
are labelled on `met1.pin` (68/5) and all eight come back out of `klt extract`
as named pins (`extracted_pins`). The supply labels are on the schematic's own
names `vdda`/`vssa` (DR-004 item 1), not `VDD`/`GND`.

**Net count** — the extracted netlist has **21** distinct device-terminal nets,
the same 21 the schematic has. A terminal the router left dangling still
extracts, as an extra node on an otherwise correct device, so the device count
alone cannot see it; this count can, and it caught two real routing defects
during development.

## What this cell does *not* claim

- A **DRC-clean signoff** verdict: #31, against the deck and klt build it
  chooses. The 0-violation run above is this issue's evidence that the geometry
  is sane, not a tier claim.
- An **LVS match**: #32. The extracted netlist does correspond device-for-device
  and net-for-net to `design/ota/ota_fd.spice`, but no `klt lvs` compare was run
  and no reference-vs-layout envelope is committed, and #32 will have to decide
  how to treat the two half-`W` groups above.
- **Parasitic extraction** (#35) and **power-delivery checks** (#39).
- Any **simulated or measured** result. Nothing here was simulated; no number on
  this page comes from ngspice.

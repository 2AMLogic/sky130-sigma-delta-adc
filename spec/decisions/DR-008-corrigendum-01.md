# DR-008 corrigendum 01: the `klt characterize` rejection's first ground is pinned to klt 0.8.0

- **Status**: factual corrigendum to DR-008; corrects the scope of one
  rejection ground and adds a reopen trigger DR-008 lacks. It is **not** a
  spec change: it sets no value, changes no limit, and re-decides nothing.
  DR-008's `## Decision` section is unchanged and remains in force, and the
  rejection it documents still stands.
- **Date**: 2026-11-16
- **Corrects**: the first ground of the `klt characterize` alternative in
  DR-008's `## Alternatives considered`
  (`spec/decisions/DR-008-digital-timing-corners.md`), and supplements
  DR-008's `## Consequences` with a klt-pin reopen trigger. DR-008 is left
  byte-identical to its ratified version — this record is read beside it,
  not into it. DR-008 is bound into `attestation/item8-envelope.json` by
  sha256 precisely so it stays that way; no envelope regeneration is needed
  here, and this corrigendum is not an envelope-cited file.

## What is corrected

The first ground of DR-008's rejection of "derive the missing 35 corners
(`klt characterize`, or liberty interpolation)" reads:

> First, `klt characterize` at the pinned 0.8.0 is **combinational arcs
> only** and **one corner per invocation** (`klt characterize --help`,
> "Scope: one corner per invocation, combinational arcs only"). Setup and
> hold on this design are register-to-register, so the sequential arcs that
> bind the result are exactly what it cannot produce — a derived library
> would be missing the numbers the gap is about.

That claim is accurate **at the pin this repo records in
`.github/klt-version`** (`0.8.0` as of this corrigendum). Re-verified
2026-11-16 in a throwaway environment: `uvx --from "klayout-tools==0.8.0"
klt characterize --help` prints exactly the Scope line DR-008 quotes:

> Scope: one corner per invocation, combinational arcs only.

It is **scoped to that pin, and no longer true at klt 0.9.x**. Observed
2026-11-16 on the host tool (`klt --version` → `klt
0.9.3.dev181+g2f281f0d605c`), `klt characterize --help` reports:

> Scope: one corner per invocation; every combinational timing arc, plus --
> for a cell declaring `cell.clock_pin` (edge-triggered) or
> `cell.enable_pin` (level-sensitive latch) -- clock-to-output and
> enable-to-output arcs (issues #4755, #5521), a latch's transparent
> data-to-output arcs, and setup/hold constraint arcs for each pin in
> `cell.constrained_pins` (issue #4756).

So the sequential arcs DR-008 said `klt characterize` "cannot produce" —
the register-to-register setup/hold constraint arcs the rejection ground
turned on — are emitted at klt 0.9.x. For completeness, the same `--help`
still lists what 0.9.x does **not** emit: recovery/removal arcs, async
set/reset arcs, the `ff`/`latch` state groups, latch time borrowing,
min-pulse-width. The one-corner-per-invocation clause of the ground still
holds at 0.9.x.

## What is unchanged

- **The rejection stands.** Its third ground is decisive and untouched by
  any of this: a derived library is liberty **this repo invented**, which
  DR-002 rules out ("none may be invented"). An interpolated or
  characterized 1.98 V file would still be the weakest possible evidence at
  the one point where DR-008's declared set is most exposed. The second
  ground (fleet cost: 35 corners of the cells a 5 390-instance design uses
  is a large fleet job) is likewise unchanged.
- DR-008's `## Decision` — the ten shipped `sky130_fd_sc_hd` liberty
  corners, the other 35 DR-002 points as a declared, unclosable gap, and
  the block-boundary I/O budget at the assembled top — stands exactly as
  ratified. This corrigendum does not reopen, restate or amend it.
- DR-008's `## Consequences` bullet that binds the record into
  `attestation/item8-envelope.json` by sha256 continues to operate as
  written: the record is byte-identical, so the envelope's CI check passes
  without regeneration.

## Reopen trigger (supplements DR-008 `## Consequences`)

DR-008 carries a reopen trigger for a **PDK** pin bump ("This gap reopens
if the PDK pin moves") but none for a **klt** pin bump, so nothing in the
record would prompt a re-read when `.github/klt-version` moves. Added here,
parallel to the PDK trigger:

**A change to `.github/klt-version` requires re-reading the first ground of
the `klt characterize` rejection** and recording, in a corrigendum or a
superseding record, either that it still stands at the new pin (quoting the
new pin's `klt characterize --help` Scope line) or what the new pin changes
about it. The record carrying the re-read cites the klt version observed and
the date. The staleness this trigger guards against is not hypothetical: it
was observed pre-emptively at klt 0.9.x, as quoted above, while this repo's
pin was still 0.8.0. This corrigendum is itself the first record in that
series: it re-read the ground at klt 0.9.x and finds the combinational-arcs
clause no longer holds there, while the rejection itself still stands on the
third ground.

## Provenance

- Verified against `origin/main` @ `22c56af`, 2026-11-16, by Builder on
  issue #227: `.github/klt-version` reads `0.8.0`; `uvx --from
  "klayout-tools==0.8.0" klt characterize --help` prints the Scope line
  DR-008 quotes; the host klt prints the 0.9.x Scope line quoted above;
  `python3 -I attestation/item8_envelope.py --check` passes with DR-008
  byte-identical and no envelope regeneration.
- Discovered during Judge evaluation of PR #156; tracked as issue #227.

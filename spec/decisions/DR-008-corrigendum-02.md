# DR-008 corrigendum 02: the `klt characterize` rejection's first ground still stands at the 0.9.2 pin

- **Status**: factual corrigendum to DR-008; records the klt-pin reopen
  trigger's re-read at the new pin. It is **not** a spec change: it sets
  no value, changes no limit, and re-decides nothing. DR-008's
  `## Decision` section is unchanged and remains in force, and the
  rejection it documents still stands.
- **Date**: 2026-11-17
- **Discharges**: the reopen trigger that DR-008 corrigendum 01
  (`spec/decisions/DR-008-corrigendum-01.md`) appended to DR-008's
  `## Consequences`. DR-008 itself is left byte-identical to its ratified
  version — it is bound into `attestation/item8-envelope.json` by sha256
  precisely so it stays that way; no envelope regeneration is needed
  here, and this corrigendum is not an envelope-cited file.

## The trigger fired

Corrigendum 01's trigger requires a re-read of the first ground of the
`klt characterize` rejection whenever `.github/klt-version` changes,
recorded with the klt version observed and the date. The pin moved
`0.8.0` → `0.9.2` (PR #244, closing #128; pin bump `125b6bc`, merged
2026-11-16), so the trigger's exact condition is met and this record is
its discharge.

## The re-read

Re-read 2026-11-17 at **klt 0.9.2** — the released version the pin now
records, run in a throwaway environment (`uvx --from
"klayout-tools==0.9.2" klt characterize --help`; `klt --version` →
`klt 0.9.2`). The Scope line is:

> Scope: one corner per invocation, combinational arcs only.

That is verbatim the Scope line DR-008 quotes at `0.8.0`. **DR-008's
first ground still stands at the `0.9.2` pin**: at this pin
`klt characterize` is still combinational arcs only and one corner per
invocation, the sequential register-to-register setup/hold arcs that
bind this design's result are still exactly what it cannot produce, and
nothing about DR-008's rejection or `## Decision` moves. The other two
grounds are independent of the klt pin anyway — the second (fleet cost
of 35 corners) is unchanged, and the third (a derived library is
liberty this repo invented, which DR-002 rules out) is not a function
of the tool version at all.

## What this settles about corrigendum 01

Corrigendum 01's "no longer true at klt 0.9.x" was measured on the host
dev build (`klt 0.9.3.dev181+g2f281f0d605c`), not on a 0.9.x **release**
— a distinction it did not have to draw, because no release pin had been
taken yet. This re-read settles it: the expanded sequential-arc Scope is
a `0.9.3.dev*` observation, and released `0.9.2` still prints the
`0.8.0` Scope line. Corrigendum 01's wording is narrowed to the dev
build it was measured on accordingly; nothing it observed is deleted.

The trigger remains armed for the next pin change, exactly as
corrigendum 01 wrote it.

## Provenance

- Verified against `origin/main` @ `d4c966e`, 2026-11-17, by Builder on
  issue #250: `.github/klt-version` reads `0.9.2`; `uvx --from
  "klayout-tools==0.9.2" klt characterize --help` prints the Scope line
  quoted above; `python3 -I attestation/item8_envelope.py --check`
  passes with DR-008 byte-identical and no envelope regeneration.
- Precedent: DR-008 corrigendum 01 itself (issue #227, PR #249),
  including its "filed rather than blocking" handling — the trigger
  names no same-PR requirement.
- Discovered during Judge evaluation of PR #244; tracked as issue #250.

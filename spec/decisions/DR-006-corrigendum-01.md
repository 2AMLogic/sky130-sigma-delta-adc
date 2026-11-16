# DR-006 corrigendum 01: the committed record.json postdates the gap line

- **Status**: factual corrigendum to DR-006; corrects one stale Consequences
  bullet. It is **not** a spec change: it sets no value, changes no limit,
  and re-decides nothing. DR-006's `## Decision` section is unchanged and
  remains in force.
- **Date**: 2026-11-15
- **Corrects**: the second bullet of DR-006's `## Consequences`
  (`spec/decisions/DR-006-decimation-stopband-reading.md`), which is left
  byte-identical to its ratified version — this record is read beside it,
  not into it.

## What is corrected

DR-006's Consequences states:

> `verification/decimator/record.json` was recorded before the gap line
> existed and is left as recorded (append-only evidence); regenerate it at
> the next RTL or filter change. The gap figure is reproducible by running
> `response.py` on the committed coefficients.

The first sentence of that bullet is stale. It described the tree as of
2026-10-25, when DR-006 was last revised (`fea12a2`), and the gap-grading
line of `response.py` did indeed not yet exist in the committed record then.

The record has since been regenerated at `e425415` (2026-11-01, "test(decimator):
add B-bitstream end-to-end check; re-record response lines with row 9 floor"),
after the last revision of DR-006. The committed `record.json` now carries
**both** ratified grading lines, both `PASS`, exactly as printed by the
record's `response` field:

```
row 8 passband 0-20 kHz: peak-to-peak 0.0401 dB (limit 0.1) PASS
row 9 alias bands k*80k +/-20k to fs/2: worst attenuation 93.91 dB at 300.00 kHz (limit 90.0) PASS
row 9 elsewhere, 60 kHz..fs/2 outside the alias bands: worst attenuation 79.20 dB at 284.50 kHz (limit 75.0) PASS
```

The gap line is therefore recorded evidence, not something a reader must
re-derive by hand.

## What is unchanged

- DR-006's `## Decision` section stands exactly as ratified: alias bands at
  "attenuation of at least 90 dB", elsewhere (the gaps) at "attenuation of
  at least **75 dB**". This corrigendum does not reopen, restate or amend it.
- The last sentence of the corrected bullet still holds: the gap figure is
  reproducible by running `response.py` on the committed coefficients.
  Re-verified 2026-11-15 at `273b70e`: `cd verification/decimator &&
  python3 response.py` exits 0 and prints the three `response` strings above
  identically.
- `record.json` remains append-only evidence; it is current for its RTL and
  is regenerated at the next RTL or filter change, as the (still-valid part
  of the) corrected bullet instructs.
- The remaining three Consequences bullets of DR-006 are unaffected.

## Provenance

- Verified against `origin/main` @ `273b70e`, 2026-11-15, by Builder on
  issue #198: the bullet reads as quoted above; `git log` on
  `verification/decimator/record.json` gives `e425415` (2026-11-01) and on
  DR-006 gives `fea12a2` (2026-10-25); the committed record's `response`
  strings and a fresh `response.py` run agree byte-for-byte.
- Discovered during code evaluation of PR #196; tracked as issue #198.

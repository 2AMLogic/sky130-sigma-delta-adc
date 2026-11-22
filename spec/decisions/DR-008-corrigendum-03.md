# DR-008 corrigendum 03: the decimator power row's owner is #35, not #33

- **Status**: factual corrigendum to DR-008; supersedes the owner citation
  in one `## Consequences` bullet. It is **not** a spec change: it sets
  no value, changes no limit, and re-decides nothing. DR-008's
  `## Decision` section is unchanged and remains in force — the
  ten declared corners stay the digital partition's corner set, the other
  35 DR-002 points stay a declared unclosable gap, and the block-boundary
  I/O budget stays the assembled top's. DR-008 itself is left
  byte-identical to its ratified version — it is bound into
  `attestation/item8-envelope.json` by sha256 precisely so it stays that
  way; this corrigendum is not an envelope-cited file, so it causes no
  envelope regeneration.
- **Date**: 2026-11-17
- **Supersedes**: the citation in the Consequences bullet of DR-008
  (`spec/decisions/DR-008-digital-timing-corners.md`) that ends "… and
  the decimator power row pending on #33." The row's owner is **#35**.

## What drifted

DR-008 was decided on issue #131, whose parent tracker #33 ("T1 item 5:
transistor-level PVT SNDR/power sweep of the modulator, plus decimator
STA and klt functional-verification") owned the bench work at ratification
time, so the Consequences bullet named #33 as what the decimator power row
waited on. #33 closed 2026-11-17 on a Curator verdict of record (item 5
analog `unmet`, digital `met`), and the remaining power work was left to
#35 ("T1 item 7: post-layout verification"), which is open.

`measurements/characterization.md` already records the post-#33 ownership
in the three places the power row lives:

- spec row 13 ("P_ana <= 1 mW, P_dig reported"): "P_dig and post-layout
  power: pending (#35)";
- spec row 14 ("DRC + LVS clean, post-layout"): post-layout pending (#35);
- the decimator table's "Power at each of the 45 corners" row:
  "pending (#35)".

The graded envelope already agrees with the report: the
`pending_issues` its grammar collects are #31, #32, #35, #138 and #148 —
#33 is not among them, and no gate reads the prose bullet. What drifted is
DR-008's prose citation alone; the envelope verdict the bullet describes
(stays `fail` while power is pending) is unchanged, because #35 is open.

## What this settles

The decimator power row's owner is #35, exactly as
`measurements/characterization.md` says in rows 13, 14 and the 45-corner
power row. Nothing is edited inside DR-008, no envelope is regenerated for
this corrigendum, and DR-008's sha256 binding is unchanged (verified
below).

## Provenance

- Verified against `origin/main` @ `c1f3159`, 2026-11-17, by Builder on
  issue #293: DR-008's Consequences bullet still ends "row pending on
  #33."; #33 is CLOSED (2026-11-17T03:00:52Z), #35 is OPEN;
  `sha256sum spec/decisions/DR-008-digital-timing-corners.md` =
  `9fe14c8771e8d077bc477ca63832ca995a5ce635e891779f2c7ced387a5acd2d`,
  identical on `origin/main` and on the tree this corrigendum lands in;
  `python3 -I attestation/item8_envelope.py --check` and
  `--verify-issues` pass. (The envelope is regenerated in the same change
  for the `characterization.md` line-18 citation re-point, not for this
  file.)
- Precedent: DR-008 corrigendum 01 (issue #227, PR #249) and corrigendum
  02 (issue #250) — factual corrections are recorded beside the record,
  never in it.

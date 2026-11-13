# comparator — provenance

The quantizer comparator is **adopted by pinned reference, not redrawn**
(DR-003, `spec/decisions/DR-003-sibling-reuse.md`).

| Field | Value |
|---|---|
| Repo | `2AMLogic/sky130-comparator` |
| Commit | `a0767fa5a4bedc9128a7e95b8b512075536522c8` (2026-10-17T21:28:41Z), equal to the `reuse.lock.json` `imports[block=comparator].commit` pin |
| How fetched | `gh api repos/2AMLogic/sky130-comparator/contents/<path>?ref=<commit>`, content written byte-for-byte |
| Schematic | `design/comparator.sch` at the commit -> `comparator.sch` here (sha256 `bbcf7430218b6a6999f2b4a654978a59859f5815951d18820b81bf37ae76a69b`) |
| Netlist | `sim/comparator-decision/testbench/comparator_core.spice` at the commit -> `comparator_core.spice` here (sha256 `e83be11dee6279b1a97a81c7cc27764147f15dabbac7f13df5134b75ad835ab4`). The sibling's own `design/netlist.sh` derives it from the schematic; it has no `.sym` and no committed `.subckt` |

Files in this directory:

- `comparator.sch`, `comparator_core.spice` — vendored, **never edited here**.
  A bump is a new pin in `reuse.lock.json`, a record, and a re-fetch.
- `wrap_comparator.sh` -> `comparator.spice` — the only local derivation: the
  flat device lines under a `.subckt comparator vdda vssa clk vinp vinn outp outn`,
  with the global nets `VDD`/`GND` renamed to the ports `vdda`/`vssa` so the
  comparator sits on the analog rails (DR-004) rather than ngspice node 0. No
  device line is otherwise changed. `wrap_comparator.sh --check` gates drift.
- `comparator.sym` — a `type=primitive` symbol written here (port list only),
  so the modulator schematic can instantiate the block and the modulator
  netlist does not redefine it; `comparator.spice` is `.include`d separately,
  as `design/ota/ota_fd.spice` is.

## What is and is not checked

- `wrap_comparator.sh --check` (exit 0): `comparator.spice` matches its inputs.
- **`klt netlist --check` on `comparator.sch`: run 2026-11-13, rc=3 (diff
  found), device lines identical.** Host xschem 3.4.7 (`XSCHEM V3.4.7`), klt
  `0.9.2.dev885+ge4c446bd91f2`. The earlier note that the check "cannot pass"
  (xschem 3.4.4 did not evaluate the schematic's `expr()` parameters and `klt
  netlist` refused, exit 1) no longer applies: on 3.4.7 the check runs. It
  still returns rc=3 because `--check` is byte-level, and the vendored
  `comparator_core.spice` is the sibling's committed output with its own hand
  header comment block (lines 1-68) and none of the wrapper lines xschem emits
  (`** sch_path:`, `**.subckt`, `**.ends`, `.end`). Those header/footer lines
  are the only differences. Device lines (the `X...` lines and their `+`
  continuations) were compared after regenerating to a scratch path without
  `--check`:

  ```
  klt netlist design/modulator/comparator/comparator.sch -o /tmp/cmp_regen.spice --rcfile design/xschemrc
  diff <(grep -E '^(X|\+)' design/modulator/comparator/comparator_core.spice) \
       <(grep -E '^(X|\+)' /tmp/cmp_regen.spice)
  ```

  The `diff` output is empty. This is a simulated-netlist equivalence of
  device lines, not a byte-level `--check` pass. Neither vendored file was
  edited (sha256 values above unchanged).

## Checks DR-003 still owes (not done here)

Decision time against the 97.7 ns half-period at the DR-002 corners, and
kickback against the integrator amplifier input. Neither is claimed.

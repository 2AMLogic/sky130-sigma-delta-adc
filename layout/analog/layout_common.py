"""layout/analog/layout_common.py -- plumbing shared by the layout/analog
generators.

`gen_ota_fd.py` and `gen_integrator.py` grew paste-copies of the flow
scaffolding: `nm`/`snap`/`run`/`emit`, the klt build pin, and the extracted
netlist parsers.  The copies had already drifted -- the two extract parsers
picked an X-line's model token with two different predicates, so the two
cells' device-count evidence (`extract-device-count.json`) was not guaranteed
to be computed the same way (issue #176).  One module, imported by both, is
the fix, and the generated-layout flow (#121 clkgen, #122 the assembled top)
imports it instead of pasting a third copy.

Import pattern: each generator inserts its parent directory on `sys.path`
(the `sim/` benches do the same for `settling_common`), so
`python3 layout/analog/<cell>/gen_<cell>.py` works from any working
directory, including under `python3 -I`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

# --- units and PDK pin (mirrors sim/pdk.json) ---------------------------------
DBU = 1000
GRID_UM = 0.005          # manufacturing grid (*.ongrid.1)
PDK_VARIANT = "sky130A"
PDK_ROOT_DEFAULT = "~/.ciel"


def nm(value_um: float) -> int:
    return int(round(value_um * DBU))


def snap(value_um: float) -> float:
    """Round onto the PDK manufacturing grid (*.ongrid.1)."""
    return round(round(value_um / GRID_UM) * GRID_UM, 6)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True):
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed (rc={result.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def emit(out_dir: Path, cell_dir: Path, top_cell: str) -> None:
    """Copy a flow scratch directory's deliverables into the cell directory."""
    shutil.copyfile(out_dir / f"{top_cell}.gds", cell_dir / f"{top_cell}.gds")
    for name in ("extract-device-count.json", "drc.report.json"):
        shutil.copyfile(out_dir / name, cell_dir / name)
    shutil.copyfile(out_dir / "route.summary.json", cell_dir / "route-summary.json")


def klt_pin(klt_cmd: list[str]) -> dict:
    """The exact klt build, recorded with the evidence.

    The stream is byte-reproducible at *this* build: a generator change
    upstream moves geometry, so `--check` is an assertion about one klt, and
    the reader has to be told which one.
    """
    r = run([*klt_cmd, "version", "--format", "json"], check=False)
    try:
        d = json.loads(r.stdout)
    except Exception:
        return {"klt": "unknown"}
    return {
        "klt": d.get("version"),
        "git_commit": d.get("git_commit"),
        "reinstall_spec": d.get("reinstall_spec"),
        "klayout": d.get("klayout_version"),
    }


class PinError(RuntimeError):
    """`--check` cannot name the klt build it must assert against."""


def recorded_pin(cell_dir: Path) -> dict:
    """The klt pin recorded in this cell's committed DRC evidence.

    `--check` asserts byte-reproducibility of the stream at one klt build
    *and* one klayout version (the stream writer is klayout's); both are
    read back from `drc.report.json` -> `provenance`
    (`klt_version` / `klt_git_commit` / `klt_reinstall_spec` /
    `klayout_version`) instead of being taken on faith from whatever `klt`
    is on PATH.  A missing or unreadable pin is a hard error: a gate that
    cannot name the build it asserts against must never pass.
    """
    path = cell_dir / "drc.report.json"
    if not path.exists():
        raise PinError(f"{path} does not exist -- no recorded klt pin")
    try:
        prov = json.loads(path.read_text()).get("provenance") or {}
    except Exception as exc:
        raise PinError(f"{path} is unreadable: {exc}") from exc
    missing = [k for k in ("klt_version", "klt_git_commit",
                           "klt_reinstall_spec", "klayout_version")
               if not prov.get(k)]
    if missing:
        raise PinError(f"{path}: provenance lacks {', '.join(missing)}")
    return {"klt": prov["klt_version"],
            "git_commit": prov["klt_git_commit"],
            "reinstall_spec": prov["klt_reinstall_spec"],
            "klayout": prov["klayout_version"]}


# --- extracted-netlist parsing ------------------------------------------------
def _symmetric_terminals(terminals: tuple[str, ...]) -> tuple[str, ...]:
    """Normalise a device's terminal order over the terminals it is symmetric in.

    A MOSFET's source and drain are interchangeable, and a multi-finger device
    extracts with them alternating finger by finger (half the fingers come out
    D-G-S-B, half S-G-D-B).  Without this they look like two different
    devices and never combine, so a `fingers=16` tail current source would
    count as two.  Resistors and capacitors are symmetric in both terminals.
    """
    if len(terminals) == 4:          # D G S B
        d, g, src, b = terminals
        lo, hi = sorted((d, src))
        return (lo, g, hi, b)
    if len(terminals) == 3:          # A B bulk (res)
        a, b, bulk = terminals
        lo, hi = sorted((a, b))
        return (lo, hi, bulk)
    return tuple(sorted(terminals))  # 2-terminal (cap)


def _is_model_token(t: str) -> bool:
    """Does this X-line token name the extracted device's model?

    `klt extract` writes the sky130 models as `sky130_fd_pr__<name>`, and can
    emit the bare short names (`nfet`, `pfet`) for subckt-wrapped devices, so
    both forms are accepted.  This is one shared predicate on purpose: the two
    cell generators used to carry two different ones (`"sky130_fd_pr__" in t`
    vs the prefix-or-bare test), which is drift with no behavioural difference
    on the netlists they produce today but no guarantee for the next one.
    """
    return t.startswith("sky130_fd_pr__") or t in ("nfet", "pfet")


def parse_extract_devices(netlist_text: str) -> tuple[Counter, Counter]:
    """Count extracted devices by model, merging parallel same-net devices.

    One drawn transistor is one line, so a ``splits=8`` leg appears as eight
    W=10 devices where the schematic declares one ``mult=8`` device, and a
    16-finger ``mos_array`` appears as 16.  Counting therefore merges devices
    sharing a model and all terminals -- what an LVS "combine parallel
    devices" pass does -- and reports the raw counts beside the merged ones so
    the merge is visible rather than silent.
    """
    raw: Counter = Counter()
    groups: set[tuple[str, tuple[str, ...]]] = set()
    for line in netlist_text.splitlines():
        tok = line.split()
        if not tok or not tok[0].startswith("X"):
            continue
        model = next((t for t in tok if _is_model_token(t)), None)
        if model is None:
            continue
        terminals = tuple(tok[1:tok.index(model)])
        raw[model] += 1
        groups.add((model, _symmetric_terminals(terminals)))
    combined: Counter = Counter()
    for model, _terminals in groups:
        combined[model] += 1
    return raw, combined


def extract_nets(netlist_text: str) -> list[str]:
    """Every distinct net name appearing on an extracted device terminal."""
    nets: set[str] = set()
    for line in netlist_text.splitlines():
        tok = line.split()
        if not tok or not tok[0].startswith("X"):
            continue
        model = next((t for t in tok if _is_model_token(t)), None)
        if model is None:
            continue
        nets.update(tok[1:tok.index(model)])
    return sorted(nets)

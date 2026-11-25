#!/usr/bin/env python3
"""Materialize the SDF gate-level fv request with PDK-resolved cell models.

`klt functional-verification` compiles the PDK's behavioural standard-cell
models ahead of the gate netlist. Naming those model files in the committed
request's `sources` needs a path that climbs out of the repository
(`../../../../.ciel/...`), which resolves only when the checkout sits at
exactly the right depth -- in a `.loom/worktrees/issue-N` worktree it points
at a path that does not exist (issue #360). The committed request therefore
keeps its `sources` repo-relative, and this helper injects the two model
files resolved from the pinned install at run time, the same way the other
PDK-consuming runners do (`settling_common.require_pinned_pdk`, shared with
the smoke and decimator runners since issue #376: `klt pdk find --pdk
<variant> --format json`, `--pdk-root` override):

    python3 verification/decimator/resolve_fv_sdf.py [--pdk-root ROOT] \
        | klt functional-verification - -o <outdir> --format json

The pinned klt (0.9.2) resolves a stdin request's relative paths against the
cwd, not the request file's directory, so the helper re-anchors every
relative path at the committed request's own directory and emits it
absolute -- the materialized request runs from any cwd and any checkout.
`testbench.search_path` is pinned to the request's directory for the same
reason. Exit 2 (REFUSE on stderr) when the install's SOURCES stamp differs
from the sim/pdk.json pin, the cell models are missing, or a committed
source or SDF file escapes the checkout or does not exist. stdout is the
request JSON only; the resolution note goes to stderr.
"""
import argparse, json, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
REQUEST = HERE / "fv_sdf_request.json"
sys.path.insert(0, str(REPO / "sim"))
from settling_common import require_pinned_pdk  # noqa: E402


def refuse(msg):
    print(f"REFUSE: {msg}", file=sys.stderr)
    return 2


def anchored(entry):
    """Resolve a request path against the request's own directory."""
    p = pathlib.Path(entry).expanduser()
    return (p if p.is_absolute() else HERE / p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    a = ap.parse_args()
    pin = json.load(open(REPO / "sim/pdk.json"))
    assert re.fullmatch(r"[0-9a-f]{40}", pin["open_pdks_revision"]), "pin is not a 40-hex SHA"
    root, stamp = require_pinned_pdk(pin, a.pdk_root)

    lib = pin["standard_cell_library"]
    verilog = root / "libs.ref" / lib / "verilog"
    models = []
    if (verilog / "primitives.v").is_file():
        models.append(verilog / "primitives.v")
    if not (verilog / f"{lib}.v").is_file():
        return refuse(f"{lib} verilog cell models not found under {verilog}")
    models.append(verilog / f"{lib}.v")

    req = json.load(open(REQUEST))
    resolved = []
    for entry in req["sources"]:
        p = anchored(entry)
        if not p.is_file():
            return refuse(f"request source not found: {entry} ({p})")
        if not p.resolve().is_relative_to(REPO.resolve()):
            return refuse(f"request source escapes the checkout: {entry} "
                          f"({p.resolve()}); PDK files are injected at run time, "
                          f"not named in the committed request")
        resolved.append(str(p.resolve()))
    req["sources"] = resolved + [str(m) for m in models]

    req["testbench"]["search_path"] = str(HERE)

    sdf = req.get("options", {}).get("sdf")
    if sdf and "file" in sdf:
        f = anchored(sdf["file"])
        if not f.is_file():
            return refuse(f"SDF file not found: {sdf['file']} ({f})")
        if not f.resolve().is_relative_to(REPO.resolve()):
            return refuse(f"SDF file escapes the checkout: {sdf['file']} ({f.resolve()})")
        sdf["file"] = str(f.resolve())

    print(f"note: {lib} cell models from {verilog} (sources stamp '{stamp}')",
          file=sys.stderr)
    print(json.dumps(req, indent=2))
    return 0


sys.exit(main())

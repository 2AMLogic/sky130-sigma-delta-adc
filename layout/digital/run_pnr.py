#!/usr/bin/env python3
"""Digital-partition place-and-route: rtl/netlist/decimator_synth.v -> routed GDS.

    python3 layout/digital/run_pnr.py [--pdk-root ROOT] [--check]

Runs `klt place-and-route` on layout/digital/pnr_request.json against the pinned PDK
(sim/pdk.json) and copies the routed GDS, DEF and as-built netlist next to the request.
--check leaves the committed files alone and exits 3 if the fresh GDS differs from the
committed one (raw bytes), else 0. The flow takes tens of minutes (detailed routing).
A non-check run also commits the klt response envelope itself as
pnr-decimator.response.json (issue #333): the power block item 11 cites, with the
producing checkout's absolute paths rewritten to repo-relative. --check never writes
the response (timing fields make it non-reproducible; the GDS is the byte-for-byte
receipt).
Exit 2 = the PDK klt recorded in the report (provenance.pdk.version) is absent or
differs from the sim/pdk.json pin; 1 = flow failed.
"""
import argparse, hashlib, json, pathlib, shutil, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = {"gds_path": "decimator.gds", "def_path": "decimator.def", "verilog_path": "decimator_pnr.v"}
RESPONSE = "pnr-decimator.response.json"


def scrub_paths(value, root):
    """Rewrite the producing checkout's absolute paths out of a JSON value.

    `klt` names its artifacts relative to the request's repo, but other
    fields (an engine command line, a --pdk-root) can carry the producing
    checkout's absolute path. The committed response must be free of them
    (issue #333 step 5): `<root>/` becomes repo-relative and a bare
    `<root>` becomes `.`, recursively; every other value passes through
    unchanged.
    """
    if isinstance(value, str):
        return value.replace(root + "/", "").replace(root, ".")
    if isinstance(value, list):
        return [scrub_paths(v, root) for v in value]
    if isinstance(value, dict):
        return {k: scrub_paths(v, root) for k, v in value.items()}
    return value


def report_pdk_stamp(rep):
    """The PDK stamp `klt` recorded in a report, or None when it recorded none.

    `klt` writes it at `provenance.pdk.version` -- the variant's SOURCES file
    verbatim, the same string the thirteen tree-reading runners compare against
    `sim/pdk.json`'s `sources_stamp` (sim/smoke/run_smoke.py:34). A klt report
    has no top-level `pdk` key, and `provenance.pdk` is null on a check that
    resolved no PDK install (layout/digital/drc-decimator.report.json), so both
    levels are read defensively -- but never defaulted to the pin: an absent
    stamp is an unverified PDK, not a pass.
    """
    return ((rep.get("provenance") or {}).get("pdk") or {}).get("version")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--check", action="store_true", help="compare, do not overwrite")
    a = ap.parse_args()
    pin = json.load(open(REPO / "sim/pdk.json"))
    cmd = ["klt", "place-and-route", str((HERE / "pnr_request.json").relative_to(REPO)),
           "--pdk", pin["variant"], "--format", "json"]
    if a.pdk_root:
        cmd += ["--pdk-root", a.pdk_root]
    # cwd = repo root: a containerised openroad only mounts $PWD, and the netlist is under rtl/
    o = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    if o.returncode:
        print(o.stdout + o.stderr, file=sys.stderr)
        return 1
    rep = json.loads(o.stdout)
    stamp = report_pdk_stamp(rep)
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: report PDK is '{stamp}', pinned '{pin['sources_stamp']}'", file=sys.stderr)
        return 2
    drift = False
    for key, name in OUT.items():
        v = rep[key]
        src = pathlib.Path(v["path"] if isinstance(v, dict) else v)
        src = src if src.is_absolute() else REPO / src
        dst = HERE / name
        h = hashlib.sha256(src.read_bytes()).hexdigest()
        have = hashlib.sha256(dst.read_bytes()).hexdigest() if dst.exists() else None
        print(f"{name}: fresh {h}{'' if have is None else ' (committed matches)' if have == h else ' (committed DIFFERS)'}")
        if a.check:
            drift |= key == "gds_path" and have != h
        else:
            shutil.copyfile(src, dst)
    if not a.check:
        (HERE / RESPONSE).write_text(json.dumps(scrub_paths(rep, str(REPO)), indent=1) + "\n")
        print(f"{RESPONSE}: written (producing checkout's absolute paths removed)")
    return 3 if drift else 0


if __name__ == "__main__":
    sys.exit(main())

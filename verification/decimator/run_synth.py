#!/usr/bin/env python3
"""Decimator verification runner: response check, cocotb RTL sim, klt synthesize, record.

    .venv/bin/python verification/decimator/run_synth.py [--pdk-root ROOT] [--record]
                                                         [--rtl-dir DIR] [--no-synth]

Exit 0 only if response.py passes, every cocotb test passes, and synthesis ran.
Exit 2 if the PDK tree differs from the pin in sim/pdk.json (as the smoke runner).
--rtl-dir builds from a scratch copy of the RTL (negative controls); --no-synth skips
the synthesis step. --record overwrites record.json.
"""
import argparse, hashlib, json, pathlib, re, shutil, subprocess, sys
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import model as m  # noqa: E402


def resolve_root(variant, pdk_root):
    if pdk_root:
        return pathlib.Path(pdk_root).expanduser()
    out = subprocess.run(["klt", "pdk", "find", "--pdk", variant, "--format", "json"],
                         capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"REFUSE: klt pdk find failed: {out.stderr.strip()}")
    return pathlib.Path(json.loads(out.stdout)["root"])


def ver(cmd, pat):
    o = subprocess.run(cmd, capture_output=True, text=True)
    mt = re.search(pat, o.stdout + o.stderr)
    return mt.group(0) if mt else "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--record", action="store_true", help="overwrite record.json")
    ap.add_argument("--rtl-dir", help="directory holding decimator.v and decimator_coef.v (default: repo rtl/)")
    ap.add_argument("--no-synth", action="store_true")
    a = ap.parse_args()
    pin = json.load(open(REPO / "sim/pdk.json"))
    assert re.fullmatch(r"[0-9a-f]{40}", pin["open_pdks_revision"]), "pin is not a 40-hex SHA"
    root_all = resolve_root(pin["variant"], a.pdk_root)
    src = root_all / pin["variant"] / "SOURCES"
    stamp = src.read_text().strip() if src.exists() else "<missing SOURCES>"
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root_all / pin['variant']} is '{stamp}', pinned '{pin['sources_stamp']}'",
              file=sys.stderr)
        return 2
    rtl = pathlib.Path(a.rtl_dir).resolve() if a.rtl_dir else REPO / "rtl"
    files = [rtl / "decimator.v", rtl / "decimator_coef.v"]

    # 1. whole-chain response (analytic, from the quantized coefficients in rtl/)
    r = subprocess.run([sys.executable, str(HERE / "response.py")], capture_output=True, text=True, cwd=HERE)
    print(r.stdout, end="")
    if r.returncode:
        print(r.stderr, file=sys.stderr)
        print("response.py FAILED", file=sys.stderr)
        return 1
    response_lines = [ln for ln in r.stdout.splitlines() if ln.startswith(("row 8", "row 9", "grid"))]

    # 2. cocotb + Icarus
    import cocotb
    from cocotb_tools.runner import get_runner
    build = HERE / "build"
    shutil.rmtree(build, ignore_errors=True)
    run = get_runner("icarus")
    run.build(sources=files, hdl_toplevel="decimator", build_dir=build, always=True,
              build_args=["-g2012"])
    res = run.test(hdl_toplevel="decimator", test_module="test_decimator", build_dir=build,
                   test_dir=HERE, results_xml=build / "results.xml")
    cases = list(ET.parse(res).getroot().iter("testcase"))
    failed = [c.get("name") for c in cases if c.find("failure") is not None or c.find("error") is not None]
    if not cases or failed:
        print(f"cocotb FAILED: {failed or 'no testcases ran'}", file=sys.stderr)
        return 1
    print(f"cocotb: {len(cases)} tests passed")
    if a.no_synth:
        shutil.rmtree(build, ignore_errors=True)
        return 0

    # 3. klt synthesize against the pinned PDK
    req = json.load(open(HERE / "synth_request.json"))
    if a.rtl_dir:
        req["sources"] = [str(f) for f in files]
        req_path = build / "synth_request.json"
        json.dump(req, open(req_path, "w"))
    else:
        req_path = HERE / "synth_request.json"
    o = subprocess.run(["klt", "synthesize", str(req_path), "--pdk", pin["variant"],
                        "--pdk-root", str(root_all), "--format", "json"], capture_output=True, text=True)
    if o.returncode:
        print(o.stdout + o.stderr, file=sys.stderr)
        return 1
    s = json.loads(o.stdout)
    rec = {
        "result_kind": "simulated RTL (cocotb/Icarus) + synthesized (Yosys via klt), no timing; not measured",
        "design": "rtl/decimator.v + rtl/decimator_coef.v",
        "rtl_sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
        "pdk_sources_stamp": stamp,
        "cell_library": "sky130_fd_sc_hd", "corner": "tt_025C_1v80",
        "tools": {"cocotb": cocotb.__version__, "icarus": ver(["iverilog", "-V"], r"Icarus Verilog version [\d.]+"),
                  "yosys": s.get("engine_version"), "klt": ver(["klt", "--version"], r"klt \S+")},
        "cocotb": {"testcases": len(cases), "failed": 0},
        "response": response_lines,
        "synth": {"instance_count": s["instance_count"], "area_um2": s["area_um2"],
                  "instance_counts_by_type": s["instance_counts_by_type"],
                  "netlist_sha256": s["netlist_sha256"]},
    }
    print(json.dumps(rec, indent=2))
    if a.record:
        (HERE / "record.json").write_text(json.dumps(rec, indent=2) + "\n")
    shutil.rmtree(build, ignore_errors=True)
    return 0


sys.exit(main())

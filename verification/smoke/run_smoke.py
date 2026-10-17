#!/usr/bin/env python3
"""Digital smoke runner (smoke fixture, not design). See README.md."""
import argparse, json, pathlib, re, shutil, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]


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
    m = re.search(pat, o.stdout + o.stderr)
    return m.group(0) if m else "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--record", action="store_true", help="overwrite record.json")
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

    # 1. cocotb + Icarus
    import cocotb
    from cocotb_tools.runner import get_runner
    build = REPO / "verification/smoke/build"
    r = get_runner("icarus")
    r.build(sources=[HERE / "smoke_acc1.v"], hdl_toplevel="smoke_acc1", build_dir=build, always=True)
    res = r.test(hdl_toplevel="smoke_acc1", test_module="test_smoke_acc1", build_dir=build,
                 test_dir=HERE, results_xml=build / "results.xml")
    import xml.etree.ElementTree as ET
    cases = list(ET.parse(res).getroot().iter("testcase"))
    failed = [c for c in cases if c.find("failure") is not None or c.find("error") is not None]
    if not cases or failed:
        print("cocotb test FAILED", file=sys.stderr)
        return 1

    # 2. klt synthesize against the pinned PDK
    o = subprocess.run(["klt", "synthesize", str(HERE / "synth_request.json"), "--pdk", pin["variant"],
                        "--pdk-root", str(root_all), "--format", "json"], capture_output=True, text=True)
    if o.returncode:
        print(o.stdout + o.stderr, file=sys.stderr)
        return 1
    s = json.loads(o.stdout)
    rec = {
        "fixture": "smoke fixture, not design",
        "result_kind": "simulated RTL (cocotb/Icarus) + synthesized (Yosys via klt), no timing",
        "pdk_sources_stamp": stamp,
        "cell_library": "sky130_fd_sc_hd", "corner": "tt_025C_1v80",
        "tools": {"cocotb": cocotb.__version__, "icarus": ver(["iverilog", "-V"], r"Icarus Verilog version [\d.]+"),
                  "yosys": s.get("engine_version"), "klt": ver(["klt", "--version"], r"klt \S+")},
        "cocotb": {"testcases": len(cases), "failed": 0},
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

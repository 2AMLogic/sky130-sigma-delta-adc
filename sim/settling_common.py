"""Shared helpers for the settling benches (ota-settling, integrator-settling).

Toolchain only: submits a `klt sim` request, parses the report into per-corner
measurements, summarizes it, and builds the common DR-002 request. Each bench
keeps its own fixture, measurements and record metadata.
"""
import hashlib, json, pathlib, subprocess, sys

GRID_POINTS = 45  # DR-002 full grid: 5 process x 3 T x 3 Vdda
KEYS = ("vod_pre", "vod_end", "step_dv", "vod_phase", "err_phase", "t_1e4", "t_1e3", "t_1e2",
        "slope_pk", "t_slew", "slew_frac", "end_ripple_rel", "step_err_vs_ideal")


def sha256(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def pdk_stamp(variant, pdk_root):
    if pdk_root:
        root = pathlib.Path(pdk_root).expanduser()
    else:
        out = subprocess.run(["klt", "pdk", "find", "--pdk", variant, "--format", "json"],
                             capture_output=True, text=True)
        if out.returncode:
            sys.exit(f"REFUSE: klt pdk find failed: {out.stderr.strip()}")
        root = pathlib.Path(json.loads(out.stdout)["root"])
    src = root / variant / "SOURCES"
    return root, (src.read_text().strip() if src.exists() else "<missing SOURCES>")


def request(deck, measurements, t_end, timeout_s, poll_timeout_s):
    return {
        "netlist": deck,
        "engine": "ngspice",
        "backend": "batch",
        "models": {"pdk": "sky130A", "lib": "libs.tech/ngspice/sky130.lib.spice"},
        "corners": {
            "process": ["tt", "ss", "ff", "sf", "fs"],
            "supply_v": {"vdda": [1.62, 1.80, 1.98]},
            "temperature_c": [-40, 27, 125],
        },
        "analysis": {"kind": "tran", "args": f"10p {t_end:.6g} 0 0.1n"},
        "measurements": measurements,
        "options": {"timeout_s": timeout_s, "keep_artifacts": False},
        "batch": {"poll_timeout_s": poll_timeout_s},
    }


def run_klt(request_path, probe, tmpdir, tag, probe_path):
    """Run `klt sim` on request_path; with probe, on one local tt/27C/1.8V corner.

    Returns (report, corners) or None (details on stderr) if no usable report.
    """
    request_path = pathlib.Path(request_path)
    cmd = ["klt", "sim", str(request_path), "--format", "json", "-o", str(tmpdir / f"out-{tag}")]
    if probe:
        req = json.load(open(request_path))
        req["corners"] = {"process": ["tt"], "supply_v": {"vdda": [1.8]}, "temperature_c": [27]}
        req["backend"] = "local"
        probe_path = pathlib.Path(probe_path)
        probe_path.write_text(json.dumps(req))
        cmd[2] = str(probe_path)
        cmd += ["--backend", "local"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if probe:
        probe_path.unlink()
    try:
        rep = json.loads(r.stdout)
        rep["corners"]
    except (ValueError, KeyError):
        print(r.stdout[-2000:] + r.stderr[-2000:], file=sys.stderr)
        return None
    corners = {}
    for c in rep["corners"]:
        m = {x["name"]: x.get("value") for x in c["measurements"]}
        corners[c["corner_id"]] = {"status": c["status"], **{k: m.get(k) for k in KEYS},
                                   "diagnostics": [d["code"] for d in c.get("diagnostics", [])]}
    return rep, corners


def summarize(corners):
    ok = [k for k, v in corners.items() if v["status"] == "pass"]
    worst = sorted((v["err_phase"], k) for k, v in corners.items() if v["err_phase"] is not None)[-1:]
    return {"corner_count": len(corners), "pass": len(ok), "fail": len(corners) - len(ok),
            "worst_err_phase": worst[0] if worst else None}


def grid_complete(corners_list):
    """True if every corner set holds the full DR-002 grid; else print REFUSE."""
    if any(len(c) != GRID_POINTS for c in corners_list):
        print(f"REFUSE: not all {GRID_POINTS} grid points returned; no record written", file=sys.stderr)
        return False
    return True

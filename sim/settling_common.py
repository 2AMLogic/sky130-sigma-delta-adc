"""Shared helpers for the settling benches (ota-settling, integrator-settling).

Toolchain only: submits a `klt sim` request, parses the report into per-corner
measurements, summarizes it, and builds the common DR-002 request. Each bench
keeps its own fixture, measurements and record metadata.
"""
import hashlib, json, pathlib, shutil, subprocess, sys

GRID_POINTS = 45  # DR-002 full grid: 5 process x 3 T x 3 Vdda
KEYS = ("vod_pre", "vod_end", "step_dv", "vod_phase", "err_phase", "t_1e4", "t_1e3", "t_1e2",
        "slope_pk", "t_slew", "slew_frac", "end_ripple_rel", "step_err_vs_ideal")

# Every batch submit waits for fleet capacity with backoff instead of failing
# the step on `batch_no_capacity`: the spot quota is shared, so a burst is
# refused routinely. Host rule; overrides the request's `batch.capacity_wait_s`.
CAPACITY_WAIT_S = 600


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
        "batch": {"poll_timeout_s": poll_timeout_s, "capacity_wait_s": CAPACITY_WAIT_S},
    }


def _find_receipt(outdir):
    """The batch receipt `klt sim` leaves beside the per-corner artifacts, if any."""
    for p in sorted(pathlib.Path(outdir).rglob("batch-receipt.json")):
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return None
    return None


def run_klt(request_path, probe, tmpdir, tag, probe_path, *,
            capacity_wait_s=CAPACITY_WAIT_S, artifacts_dir=None):
    """Run `klt sim` on request_path; with probe, on one local tt/27C/1.8V corner.

    Batch submits always pass --wait-for-capacity, so a refused launch waits
    with backoff instead of failing the run (host rule). The raw report and the
    batch receipt are copied into artifacts_dir (when given) *before* any
    completeness gate, so a partial or failed grid is still inspectable.

    Returns (report, corners) or None (details on stderr) if no usable report.
    """
    request_path = pathlib.Path(request_path)
    outdir = pathlib.Path(tmpdir) / f"out-{tag}"
    report_out = pathlib.Path(tmpdir) / f"report-{tag}.json"
    cmd = ["klt", "sim", str(request_path), "--format", "json",
           "-o", str(outdir), "--report-out", str(report_out)]
    if probe:
        req = json.load(open(request_path))
        req["corners"] = {"process": ["tt"], "supply_v": {"vdda": [1.8]}, "temperature_c": [27]}
        req["backend"] = "local"
        probe_path = pathlib.Path(probe_path)
        probe_path.write_text(json.dumps(req))
        cmd[2] = str(probe_path)
        cmd += ["--backend", "local"]
    else:
        cmd += ["--wait-for-capacity", str(capacity_wait_s)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if probe:
        probe_path.unlink()
    receipt = _find_receipt(outdir)
    if artifacts_dir:
        artifacts_dir = pathlib.Path(artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        if report_out.exists():
            shutil.copy2(report_out, artifacts_dir / report_out.name)
        if receipt is not None:
            (artifacts_dir / f"receipt-{tag}.json").write_text(json.dumps(receipt, indent=2) + "\n")
        (artifacts_dir / f"klt-{tag}.stderr.txt").write_text(r.stderr[-20000:])
    try:
        rep = json.loads(r.stdout)
        rep["corners"]
    except (ValueError, KeyError):
        print(r.stdout[-2000:] + r.stderr[-2000:], file=sys.stderr)
        return None
    if receipt is not None:
        rep.setdefault("batch_receipt", receipt)
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


def measurements_present(corners_list):
    """True if every corner actually produced an `err_phase`; else print REFUSE.

    A fleet job that dies (`batch_job_failed`) still returns one entry per grid
    point, so the count gate alone passes and an empty grid becomes a "record".
    A corner that merely misses the limit still measures a value, so requiring
    a non-null `err_phase` everywhere separates "simulated and failing" from
    "never simulated".
    """
    bad = [(i, k, v["diagnostics"]) for i, c in enumerate(corners_list)
           for k, v in sorted(c.items()) if v["err_phase"] is None]
    if bad:
        codes = sorted({d for _, _, ds in bad for d in ds}) or ["<none>"]
        print(f"REFUSE: {len(bad)} corner(s) returned no err_phase (diagnostics: {', '.join(codes)}); "
              "nothing was simulated there, so no record is written", file=sys.stderr)
        return False
    return True

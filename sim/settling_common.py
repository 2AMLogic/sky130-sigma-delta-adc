"""Shared `klt sim` plumbing for the transistor-level benches.

Used by ota-settling, integrator-settling and integrator-ci. Toolchain only:
submits a `klt sim` request, parses the report into per-corner measurements,
summarizes it, and builds the common DR-002 request. Each bench keeps its own
fixture, measurements and record metadata.

The measurement-key list and the admission sentinel are per bench: the
settling benches' defaults (`KEYS`, `err_phase`) are the historical ones, and
`run_klt`/`summarize`/`measurements_present` take `keys=`/`key=` overrides for
a bench that measures something else (issue #102).

`join_continuations` and `ngspice_version` are here for the same reason: they
are toolchain, not bench content, and the local single-corner probe runners
(`integrator-settling/run_diag.py`, `integrator-settling/run_variants.py`,
`switch-probe/run_probe.py`, `integrator-ci/run_ci.py`) each need them.
"""
import hashlib, json, pathlib, re, shutil, subprocess, sys

GRID_POINTS = 45  # DR-002 full grid: 5 process x 3 T x 3 Vdda

# DR-002 anchor set, for the runs the full grid is too expensive for (the short
# full-modulator transient, Monte Carlo): 7 points, (process, Vdda, T_degC).
ANCHOR_POINTS = (
    ("tt", 1.80, 27),
    ("ss", 1.62, 125),
    ("ss", 1.62, -40),
    ("ff", 1.98, -40),
    ("ff", 1.98, 125),
    ("sf", 1.80, 27),
    ("fs", 1.80, 27),
)
ANCHOR_SUBSET_NOTE = ("DR-002 anchor set (7 points), a declared subset of the full "
                      "45-point grid, as DR-002 allows for Monte Carlo")

KEYS = ("vod_pre", "vod_end", "step_dv", "vod_phase", "err_phase", "t_1e4", "t_1e3", "t_1e2",
        "slope_pk", "t_slew", "slew_frac", "end_ripple_rel", "step_err_vs_ideal")

# Every batch submit waits for fleet capacity with backoff instead of failing
# the step on `batch_no_capacity`: the spot quota is shared, so a burst is
# refused routinely. Host rule; overrides the request's `batch.capacity_wait_s`.
CAPACITY_WAIT_S = 600


def sha256(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def join_continuations(text):
    """Fold SPICE `+` continuation lines into the logical line they continue.

    Returns the logical lines in file order; each folded `+` contributes its
    text with the `+` stripped and a single space in front. A `+` line with
    nothing before it has no line to fold into, so it is kept as it stands.

    Shared because every runner that reads a netlist as text needs it before
    it can match an instance line: `klt netlist` wraps long device lines, so a
    plain `splitlines()` splits W/L off the instance that declares them.
    """
    out, cur = [], None
    for ln in text.splitlines():
        if ln.startswith("+") and cur is not None:
            cur += " " + ln[1:].strip()
        else:
            if cur is not None:
                out.append(cur)
            cur = ln
    if cur is not None:
        out.append(cur)
    return out


def ngspice_version():
    """Return e.g. 'ngspice-47', or 'unknown'.

    `ngspice -v` line 1 is the banner's '******' rule, not the version, so
    match the version token anywhere in the output (same convention as
    sim/smoke/run_smoke.py and sim/ota-op-smoke/run_op.py).
    """
    m = re.search(r"ngspice-\d+",
                  subprocess.run(["ngspice", "-v"], capture_output=True, text=True).stdout)
    return m.group(0) if m else "unknown"


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


def anchor_units(process_map=None):
    """`corners.units` for the DR-002 anchor set (an explicit point list).

    `process_map` renames the process sections, e.g. {"tt": "tt_mm", ...} to
    select sky130's per-instance-mismatch `.lib` sections for a Monte Carlo
    run. `corners.units` is executed as given with no crossing, so the 7
    anchors stay 7 points instead of a 45-point grid minus 38 excludes.
    """
    m = process_map or {}
    return [{"process": m.get(p, p), "supply_v": {"vdda": v}, "temperature_c": t}
            for p, v, t in ANCHOR_POINTS]


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
            capacity_wait_s=CAPACITY_WAIT_S, artifacts_dir=None, keys=KEYS,
            hosts=None):
    """Run `klt sim` on request_path; with probe, on one local tt/27C/1.8V corner.

    Batch submits always pass --wait-for-capacity, so a refused launch waits
    with backoff instead of failing the run (host rule). The raw report and the
    batch receipt are copied into artifacts_dir (when given) *before* any
    completeness gate, so a partial or failed grid is still inspectable.

    `keys` selects which measurements are carried into the per-corner dict
    (default: the settling benches' KEYS).

    `hosts` shards the expanded unit list across that many fleet instances
    (`--hosts`). The fleet kills a job that is still running at its whole-job
    ceiling and reports every unit `batch_job_timeout`, so a request whose unit
    count makes one job's wall clock approach that ceiling has to be split;
    sharding is a submission choice, not a property of the request, so it never
    changes the request file or its sha256.

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
        req.pop("monte_carlo", None)   # one local corner, no sampling
        req["backend"] = "local"
        probe_path = pathlib.Path(probe_path)
        probe_path.write_text(json.dumps(req))
        cmd[2] = str(probe_path)
        cmd += ["--backend", "local"]
    else:
        cmd += ["--wait-for-capacity", str(capacity_wait_s)]
        if hosts:
            cmd += ["--hosts", str(hosts)]
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
        entry = {"status": c["status"], **{k: m.get(k) for k in keys},
                 "diagnostics": [d["code"] for d in c.get("diagnostics", [])]}
        if c.get("monte_carlo"):       # this corner is a Monte Carlo sample
            entry["monte_carlo"] = c["monte_carlo"]
        corners[c["corner_id"]] = entry
    return rep, corners


def summarize(corners, key="err_phase"):
    ok = [k for k, v in corners.items() if v["status"] == "pass"]
    worst = sorted((abs(v[key]), k) for k, v in corners.items() if v.get(key) is not None)[-1:]
    return {"corner_count": len(corners), "pass": len(ok), "fail": len(corners) - len(ok),
            f"worst_{key}": worst[0] if worst else None}


def grid_complete(corners_list, expected=GRID_POINTS):
    """True if every corner set holds `expected` points; else print REFUSE."""
    if any(len(c) != expected for c in corners_list):
        got = ", ".join(str(len(c)) for c in corners_list)
        print(f"REFUSE: not all {expected} grid points returned (got {got}); "
              "no record written", file=sys.stderr)
        return False
    return True


def measurements_present(corners_list, key="err_phase"):
    """True if every corner actually produced a `key` value; else print REFUSE.

    A fleet job that dies (`batch_job_failed`) still returns one entry per grid
    point, so the count gate alone passes and an empty grid becomes a "record".
    A corner that merely misses the limit still measures a value, so requiring
    a non-null `err_phase` everywhere separates "simulated and failing" from
    "never simulated".
    """
    bad = [(i, k, v["diagnostics"]) for i, c in enumerate(corners_list)
           for k, v in sorted(c.items()) if v.get(key) is None]
    if bad:
        codes = sorted({d for _, _, ds in bad for d in ds}) or ["<none>"]
        print(f"REFUSE: {len(bad)} corner(s) returned no {key} (diagnostics: {', '.join(codes)}); "
              "nothing was simulated there, so no record is written", file=sys.stderr)
        return False
    return True

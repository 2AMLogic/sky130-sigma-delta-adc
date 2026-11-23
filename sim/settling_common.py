"""Shared `klt sim` plumbing for the transistor-level benches.

Used by ota-settling, integrator-settling, integrator-ci, ota-gain,
integrator-noise, comparator-decision and modulator-tran; the local runners
ota-op-smoke, integrator-load-check and modulator-load-check import only
`require_pinned_pdk` (issue #81), the PDK-pin gate every runner owes before
it may touch the PDK. Toolchain only:
submits a `klt sim` request, parses the report into per-corner measurements,
summarizes it, and builds the common DR-002 request. The `.partials/` cache
(`shas`/`load_partial`/`save_partial`) is a record-admission gate like the
other two (`grid_complete`/`measurements_present`), so it lives here too: a
partial produced by a different request or deck must never reach a record.
The settling benches share their measurement expressions, not just their
names: `settling_measurements()` builds both benches' 14-entry list from
per-bench timing and limit constants (the 2026-11-23 operator ruling on
issue #95, reversing the per-bench choice this paragraph used to record),
so `err_phase`, `t_1e4` and `t_slew` mean the same thing in both. Everything
else stays per bench: each keeps its own fixture, constants and limits,
record metadata, and the non-settling benches their own measurements.

The multi-variant loop over that cache (`submit_variant`, `run_variant_set`,
`run_probe`, `refuse_missing_variants`, `refuse_from_partials_conflicts`)
is shared the same way (issue #354, continuing #57/#174/#253): the four
multi-variant runners (integrator-settling, comparator-decision,
integrator-ci, integrator-sampling) pass their own request/probe/tag/partial
spellings and their own `run_klt`/`HERE`/`PARTIALS`/`ARTIFACTS` in as hooks,
so the loop is written once while each bench keeps its filenames, its
refusal-wording history and its test seams.

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


def shas(request_path, deck_path):
    """The two-key sha dict stamped into a result and re-checked on reload."""
    return {"request_sha256": sha256(request_path),
            "deck_sha256": sha256(deck_path)}


def load_partial(path, expected_shas):
    """The cached partial at `path`, if it matches `expected_shas`, else None.

    A record-admission gate beside `grid_complete`/`measurements_present`: a
    partial produced by a different request or deck is silently stale
    evidence, so a sha mismatch (or an unparseable file) is dropped with a
    NOTE on stderr, never returned.
    """
    p = pathlib.Path(path)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except ValueError:
        return None
    if {k: d.get(k) for k in expected_shas} != expected_shas:
        print(f"NOTE: ignoring stale .partials/{p.name} (request or deck changed since it ran)",
              file=sys.stderr)
        return None
    return d


def save_partial(path, result):
    p = pathlib.Path(path)
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(result, indent=2) + "\n")


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


def ngspice_version(log=None):
    """Return e.g. 'ngspice-47', or 'unknown'.

    `ngspice -v` line 1 is the banner's '******' rule, not the version, so
    match the version token anywhere in the output. With `log`, prefer a
    version token already captured in a run log over a fresh `ngspice -v`.
    """
    m = re.search(r"ngspice-\d+", log) if log else None
    if m is None:
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


def require_pinned_pdk(pin, pdk_root):
    """`pdk_stamp` plus the sim/pdk.json pin check every local runner owes.

    The lookup and the SOURCES-stamp comparison the non-attested local
    runners (ota-op-smoke, integrator-load-check, modulator-load-check) each
    hand-copied before issue #81: resolve the PDK root (`pdk_root`, else
    `klt pdk find` via `pdk_stamp`), read `<root>/<variant>/SOURCES`, and on
    a mismatch with `pin["sources_stamp"]` print the historical `REFUSE:`
    line to stderr and exit 2. Returns the `<root>/<variant>` path. The
    lookup failure path (exit with `REFUSE: klt pdk find failed: …`) stays
    in `pdk_stamp`, unchanged.
    """
    variant = pin["variant"]
    root, stamp = pdk_stamp(variant, pdk_root)
    root = root / variant
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'",
              file=sys.stderr)
        sys.exit(2)
    return root


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


def measurement(name, expr, unit=None, limits=None):
    """One entry of a request's `measurements` list.

    Hoisted from the six benches' identical local `e()` (issue #185); callers
    import it aliased as `e` so their measurement lists keep their spelling.
    """
    m = {"name": name, "expr": expr}
    if unit:
        m["unit"] = unit
    if limits:
        m["limits"] = limits
    return m


def settling_measurements(t_step, t_sample, t_end, t_slew0, ideal_dv,
                          err_max, ripple_max, ideal_tol):
    """The settling benches' 14-entry measurement list (issue #95).

    One definition of err_phase / t_1e4 / t_slew for ota-settling and
    integrator-settling (the 2026-11-23 operator ruling): the integrator
    result is read against the OTA one (#92), which only holds while the
    expressions mean the same thing in both benches. The per-bench timing
    constants, slew-mask start and limits stay arguments.

    The formatting matches the integrator bench's historical f-strings, so
    `request_int1.json` / `request_int2.json` rebuild byte-identically; the
    OTA bench's committed request keeps its hand-written `3.3e-9` slew start
    (`{t_slew0:.6g}` prints `3.3e-09`) and is not regenerated (issue #192).
    """
    # `lt`/`gt`: bare < > are shell redirections in ngspice's control language.
    slewmask = f"(abs(deriv(v(vod))) ge 0.8*slope_pk)*(time gt {t_slew0:.6g})"
    return [
        measurement("vod_pre", "v(vod)[0]", "V"),
        measurement("vod_end", "v(vod)[length(v(vod))-1]", "V"),
        measurement("step_dv", "vod_end - vod_pre", "V"),
        measurement("k_phase", f"mean(time lt {t_sample:.6g})*length(time)"),
        measurement("vod_phase", f"v(vod)[k_phase-1] + ({t_sample:.6g}-time[k_phase-1])/(time[k_phase]-time[k_phase-1])"
                     "*(v(vod)[k_phase]-v(vod)[k_phase-1])", "V"),
        measurement("err_phase", "abs(vod_phase - vod_end)/abs(step_dv)", None, {"max": err_max}),
        measurement("t_1e4", f"vecmax((abs(v(vod)-vod_end) gt 1e-4*abs(step_dv))*time) - {t_step:.6g}", "s"),
        measurement("t_1e3", f"vecmax((abs(v(vod)-vod_end) gt 1e-3*abs(step_dv))*time) - {t_step:.6g}", "s"),
        measurement("t_1e2", f"vecmax((abs(v(vod)-vod_end) gt 1e-2*abs(step_dv))*time) - {t_step:.6g}", "s"),
        measurement("slope_pk", f"vecmax(abs(deriv(v(vod)))*(time gt {t_slew0:.6g}))", "V/s"),
        measurement("t_slew", f"vecmax({slewmask}*time) - vecmin({slewmask}*time + 1*(1-{slewmask}))", "s"),
        measurement("slew_frac", "t_slew/t_1e4"),
        measurement("end_ripple_rel", f"(vecmax(v(vod)*(time gt {t_end - 20e-9:.6g}) - 10*(time le {t_end - 20e-9:.6g}))"
                     f" - vecmin(v(vod)*(time gt {t_end - 20e-9:.6g}) + 10*(time le {t_end - 20e-9:.6g})))"
                     "/abs(step_dv)", None, {"max": ripple_max}),
        measurement("step_err_vs_ideal", f"abs(abs(step_dv) - {ideal_dv})/{ideal_dv}", None, {"max": ideal_tol}),
    ]


def request(deck, measurements, t_end=None, timeout_s=None, poll_timeout_s=None, *,
            analysis=None, options=None):
    """The common DR-002 full-grid batch request for `deck`.

    Exactly one of `t_end` (a transient, the historical form: the analysis is
    `tran 10p <t_end> 0 0.1n`) or `analysis` (a ready-made analysis object, for
    a bench that measures something a transient cannot reach -- the `ac` gain
    bench and the `noise` bench of issue #126) must be given. With `t_end` the
    result is byte-identical to the pre-#126 form, so the settling benches'
    committed requests and their sha256 do not move.

    `options` adds keys to the `options` block (e.g. `ngspice_init`);
    `timeout_s` and `keep_artifacts` stay under this function's control.
    """
    if (t_end is None) == (analysis is None):
        raise ValueError("request() takes exactly one of t_end (a transient) or analysis")
    if timeout_s is None or poll_timeout_s is None:
        raise ValueError("request() needs timeout_s and poll_timeout_s")
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
        "analysis": analysis if analysis is not None
        else {"kind": "tran", "args": f"10p {t_end:.6g} 0 0.1n"},
        "measurements": measurements,
        "options": {**(options or {}), "timeout_s": timeout_s, "keep_artifacts": False},
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
            hosts=None, outdir=None, resume=False):
    """Run `klt sim` on request_path; with probe, on one local tt/27C/1.8V corner.

    Batch submits always pass --wait-for-capacity, so a refused launch waits
    with backoff instead of failing the run (host rule). The raw report and the
    batch receipt are copied into artifacts_dir (when given) *before* any
    completeness gate, so a partial or failed grid is still inspectable.

    `keys` selects which measurements are carried into the per-corner dict
    (default: the settling benches' KEYS).

    `outdir` overrides the per-run scratch directory (default: a fresh one
    under `tmpdir`). A stable one is what makes `resume` possible: `klt sim`
    keeps its shard map and checkpoint there. `resume` passes `--resume`, so
    a re-run launches only the units a previous run left unrun -- the fleet
    loses shards to capacity refusals and Spot reclaims routinely, and
    without this the only way to finish such a grid is to pay for all of it
    again. `resume` without a matching `outdir` from an earlier run is an
    error `klt sim` reports; this helper does not second-guess it.

    `hosts` shards the expanded unit list across that many fleet instances
    (`--hosts`). The fleet kills a job that is still running at its whole-job
    ceiling and reports every unit `batch_job_timeout`, so a request whose unit
    count makes one job's wall clock approach that ceiling has to be split;
    sharding is a submission choice, not a property of the request, so it never
    changes the request file or its sha256.

    Returns (report, corners) or None (details on stderr) if no usable report.
    """
    request_path = pathlib.Path(request_path)
    outdir = pathlib.Path(outdir) if outdir else pathlib.Path(tmpdir) / f"out-{tag}"
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
        if resume:
            cmd += ["--resume"]
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


# ------------------------------------------------- the variant-set loop ----
#
# The multi-variant runners (integrator-settling, comparator-decision,
# integrator-ci, integrator-sampling) share one loop shape: a `want` set of
# variants the record needs, a `run` subset asked for this invocation, reuse
# of a cached partial for the rest, and the issue #94 rule -- a variant whose
# submit fails is refused, never backfilled from .partials/. It lived as four
# hand-copied blocks (already drifting: --from-partials vs --probe ordering,
# missing-partial wording, temp-dir cleanup) until issue #354 folded it here.
# Everything per-bench stays a hook, so each bench keeps its spelling and the
# shared test harness keeps patching RUNNER.run_klt / HERE / PARTIALS /
# ARTIFACTS on the runner module.


def submit_variant(run_klt_fn, request_path, tmp, tag, probe_path, *,
                   variant=None, probe=False, artifacts_dir=None,
                   summarize_fn, shas, env_fields=None, status_line=False,
                   **run_klt_kw):
    """One variant's `klt sim` submission, assembled into its result dict.

    Returns the result dict (`summary`/`corners`/`pass`/`ngspice`/
    `engine_host`/`remote`, any `env_fields(e)`, then `shas`), or None after
    the issue #94 refusal line if `run_klt_fn` returned no usable report: a
    failed submit is never a result, and never a reason to fall back to a
    local grid or to .partials/.

    `tag` names the run_klt artifacts (`.artifacts/klt-{tag}.stderr.txt`);
    `variant` (default `tag`) is the label the loop prints and the value
    `summarize_fn(variant, corners)` sees. `status_line` prints the summary
    with the report status merged in, the settling benches' shape.
    `env_fields` derives extra result fields from the report's environment
    block (the charge-injection bench's `monte_carlo_env`).
    """
    v = tag if variant is None else variant
    res = run_klt_fn(request_path, probe, tmp, tag, probe_path,
                     artifacts_dir=None if probe else artifacts_dir, **run_klt_kw)
    if res is None:
        print(f"{tag}: no usable report (see .artifacts/klt-{tag}.stderr.txt); "
              "not falling back to a local grid or to .partials/", file=sys.stderr)
        return None
    rep, corners = res
    e = rep.get("environment", {})
    summary = summarize_fn(v, corners)
    result = {"summary": summary, "corners": corners,
              "pass": rep.get("status") == "pass",
              "ngspice": e.get("engine_version", "unknown"),
              "engine_host": e.get("engine_host"), "remote": e.get("remote"),
              **(env_fields(e) if env_fields else {}), **shas}
    line = {"status": rep.get("status"), **summary} if status_line else summary
    print(v, json.dumps(line, indent=2))
    return result


def run_probe(variant, tmp, *, run_klt_fn, artifacts_dir, request_fn,
              probe_request_fn, tag_fn, summarize_fn, shas_fn,
              env_fields=None, status_line=False, **run_klt_kw):
    """One local tt/27C/1.8V corner of one variant; None means refuse (exit 1).

    The single-variant `--probe` shape every runner shares: submit locally,
    refuse with the probe's own exit-1 line if nothing came back, else hand
    the result dict to the caller (which prints its corners). No partial is
    written for a probe.
    """
    res = submit_variant(run_klt_fn, request_fn(variant), tmp, tag_fn(variant),
                         probe_request_fn(variant), variant=variant, probe=True,
                         summarize_fn=summarize_fn, shas=shas_fn(variant),
                         env_fields=env_fields, status_line=status_line,
                         **run_klt_kw)
    if res is None:
        print(f"REFUSE: no result for the {variant} probe; nothing printed.",
              file=sys.stderr)
        return None
    return res


def run_variant_set(want, run, tmp, *, run_klt_fn, artifacts_dir, request_fn,
                    probe_request_fn, tag_fn, partial_fn, shas_fn, summarize_fn,
                    reuse_label_fn=None, submit_kwargs_fn=None, usable_fn=None,
                    env_fields=None, status_line=False):
    """The want-vs-run loop: reuse a partial, submit fresh, cache. -> results.

    For every variant in `want` that this invocation did not ask for (not in
    `run`), a sha-matching cached partial is reused. Every variant in `run`
    is submitted fresh, and its result is cached under `partial_fn(v)` --
    unless `usable_fn(v, corners)` says it could not stand in a record on its
    own (a lost-shard grid: legitimate to report, illegitimate to cache over
    a good partial). A failed submit prints the issue #94 refusal line and
    leaves the variant missing; `refuse_missing_variants` turns that into
    the exit-1 refusal.

    The hooks are the per-bench spellings: `request_fn`/`probe_request_fn`/
    `tag_fn` name the request, probe request and run_klt tag for a variant;
    `partial_fn` the cache path; `reuse_label_fn` (default: the partial's
    filename) the reuse line's label; `shas_fn` the hash gate;
    `summarize_fn(variant, corners)` the summary; and `submit_kwargs_fn(v)`
    any extra run_klt kwargs (keys, capacity_wait_s, hosts, outdir, resume).
    """
    results = {}
    for v in want:
        if v not in run:
            saved = load_partial(partial_fn(v), shas_fn(v))
            if saved:
                label = partial_fn(v).name if reuse_label_fn is None else reuse_label_fn(v)
                print(f"{v}: reusing {label} ({saved['summary']})")
                results[v] = saved
            continue
        res = submit_variant(
            run_klt_fn, request_fn(v), tmp, tag_fn(v), probe_request_fn(v),
            variant=v, artifacts_dir=artifacts_dir, summarize_fn=summarize_fn,
            shas=shas_fn(v), env_fields=env_fields, status_line=status_line,
            **(submit_kwargs_fn(v) if submit_kwargs_fn else {}))
        if res is None:
            continue
        results[v] = res
        if usable_fn is None or usable_fn(v, res["corners"]):
            save_partial(partial_fn(v), res)
        else:
            print(f"{v}: not cached in .partials/ -- this result cannot stand "
                  "in a record on its own; re-run this variant", file=sys.stderr)
    return results


def refuse_missing_variants(want, results, from_partials=False):
    """The shared missing-variant refusal; True refuses (caller exits 1)."""
    missing = [v for v in want if v not in results]
    if not missing:
        return False
    how = "no cached partial for" if from_partials else "no result for"
    print(f"REFUSE: {how} {', '.join(missing)}; no record written. "
          f"Re-run with --variant {missing[0]} when the fleet has capacity.", file=sys.stderr)
    return True


def refuse_from_partials_conflicts(**flags):
    """Refuse --from-partials combined with flags that would mean something.

    `flags` maps a flag name (without dashes) to whether it was given; any
    given flag prints the exit-2 refusal and returns True. --from-partials
    submits nothing, so --probe/--variant/--resume cannot change what it
    does -- and a runner that dispatched on --probe first would silently
    launch a local simulation instead of refusing, the drift issue #354
    closed.
    """
    bad = [f"--{name}" for name, given in flags.items() if given]
    if not bad:
        return False
    print(f"REFUSE: --from-partials submits nothing, so {', '.join(bad)} "
          "has no meaning with it", file=sys.stderr)
    return True

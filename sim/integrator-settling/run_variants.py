#!/usr/bin/env python3
"""Issue #92 switch-isolation cross-check: what the cell does with other switches.

Single-corner transient probes, run locally, that answer "is it really the
switches?" and "how small can the PMOS halves get?". Simulated (ngspice,
transistor-level design/integrator + design/ota/ota_fd); not measured, not a
record, not a performance claim. The 45-corner evidence is record*.json.

Four variants, all on the same deck, stimulus and timing as run_diag.py, so
every err_phase here is comparable to that bench and to record.json:

  ideal         the as-built cell with its twelve vcm switches replaced by
                ideal 1 ohm switches, same ota_fd. If the OTA were the limit,
                this would still fail.
  no_pmos_std   the as-built cell unchanged: plain nfet_01v8 halves, no PMOS
                half anywhere.
  no_pmos_lvt   the as-built cell with the twelve halves moved to
                nfet_01v8_lvt and still no PMOS half -- isolates what the
                low-Vth swap costs on its own.
  fixed         the working-tree cell (low-Vth NMOS + W 24 / W 4 PMOS halves).

`ideal`, `no_pmos_std` and `no_pmos_lvt` are built by transforming the baseline
netlist pulled out of git, so they stay reproducible after the fix lands.

    python3 -I sim/integrator-settling/run_variants.py           # print
    python3 -I sim/integrator-settling/run_variants.py --write   # save
"""
import argparse, json, pathlib, re, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from settling_common import pdk_stamp
import run_diag

T_END, T_SAMPLE = run_diag.T_END, run_diag.T_SAMPLE

# The twelve vcm switches: the phi2-gated transfer/bottom-plate pair and the
# phi1e-gated top-plate reset, on both sides. Their PMOS halves (added by the
# fix) carry a further `_p` suffix, which the trailing space here excludes.
VCM_SW = re.compile(r"^XS(bi|ci|ti|br|cr|tr)_(p|n) ", re.M)

# (key, variant, corner, temp, vdda) -- one row = one transient
POINTS = [
    # Is it the switches? Idealize only them, at the three worst 1.620 V skews.
    ("ideal_fs_1v62", "ideal", "fs", -40, 1.620),
    ("ideal_sf_1v62", "ideal", "sf", -40, 1.620),
    ("ideal_ss_1v62", "ideal", "ss", -40, 1.620),
    # ... and at the high rail, where the as-built cell already passes.
    ("ideal_fs_1v98", "ideal", "fs", -40, 1.980),
    ("ideal_sf_1v98", "ideal", "sf", -40, 1.980),
    ("ideal_ss_1v98", "ideal", "ss", -40, 1.980),
    # How small can the halves get? Bounds at the hot corner that wants them small.
    ("ideal_sf_1v80_125c", "ideal", "sf", 125, 1.800),
    ("no_pmos_std_sf_1v80_125c", "no_pmos_std", "sf", 125, 1.800),
    ("no_pmos_lvt_sf_1v80_125c", "no_pmos_lvt", "sf", 125, 1.800),
    ("fixed_sf_1v80_125c", "fixed", "sf", 125, 1.800),
]


def join_continuations(txt):
    out, cur = [], None
    for ln in txt.splitlines():
        if ln.startswith("+") and cur is not None:
            cur += " " + ln[1:].strip()
        else:
            if cur is not None:
                out.append(cur)
            cur = ln
    if cur is not None:
        out.append(cur)
    return out


def transform(baseline, fixed, variant):
    """Build a variant netlist. Returns (bytes, note)."""
    if variant == "fixed":
        return fixed, "working-tree netlist, unmodified"
    lines = join_continuations(baseline.decode())
    n = sum(1 for l in lines if VCM_SW.match(l))
    if n != 12:
        sys.exit(f"REFUSE: expected 12 vcm switches in the baseline netlist, found {n}")
    if b"pfet_01v8_lvt" in baseline:
        sys.exit("REFUSE: the baseline netlist already has PMOS halves; "
                 "the no-PMOS variants assume it does not")
    out = []
    for l in lines:
        m = VCM_SW.match(l)
        if not m:
            out.append(l)
            continue
        if variant == "ideal":
            # XS<name> <drain> <gate> <source> <bulk> <model> ... ->
            # S<name> <drain> <source> <gate> <bulk> swideal   (1 ohm closed)
            f = l.split()
            out.append(f"S{m.group(0)[2:].strip()} {f[1]} {f[3]} {f[2]} {f[4]} swideal")
        elif variant == "no_pmos_lvt":
            out.append(l.replace("sky130_fd_pr__nfet_01v8 ", "sky130_fd_pr__nfet_01v8_lvt "))
        elif variant == "no_pmos_std":
            out.append(l)
        else:
            sys.exit(f"REFUSE: unknown variant '{variant}'")
    if variant == "ideal":
        i = next(k for k, l in enumerate(out) if l.lower().startswith(".ends"))
        out.insert(i, ".model swideal sw vt=0.5 vh=0.1 ron=1 roff=1e15")
    notes = {"ideal": "baseline netlist, twelve vcm switches replaced by ideal 1 ohm switches",
             "no_pmos_std": "baseline netlist, unmodified (plain nfet_01v8, no PMOS halves)",
             "no_pmos_lvt": "baseline netlist, twelve vcm switches moved to nfet_01v8_lvt, "
                            "still no PMOS halves"}
    return ("\n".join(out) + "\n").encode(), notes[variant]


def probes_min():
    """Only the figures of merit record.json reports -- no device probes.

    run_diag.py's probe block names switch devices by their internal MOS
    instance, which the `ideal` variant does not have; these four scalars are
    defined exactly as there, so the numbers stay comparable.
    """
    return "\n".join([
        ".control", "option gmin=1e-9",
        "save v(vod) v(voutp) v(voutn)",
        f"tran 10p {T_END:.6g} 0 0.1n",
        "let vod_pre = v(vod)[0]",
        "let vod_end = v(vod)[length(v(vod))-1]",
        "let step_dv = vod_end - vod_pre",
        f"meas tran vod_phase find v(vod) at={T_SAMPLE:.6g}",
        "let err_phase = abs(vod_phase - vod_end)/abs(step_dv)",
        "let step_err_vs_ideal = abs(abs(step_dv) - 0.9)/0.9",
        f"let end_ripple_rel = (vecmax(v(vod)*(time gt {T_END-20e-9:.6g})"
        f" - 10*(time le {T_END-20e-9:.6g}))"
        f" - vecmin(v(vod)*(time gt {T_END-20e-9:.6g}) + 10*(time le {T_END-20e-9:.6g})))"
        "/abs(step_dv)",
        "print vod_pre vod_end step_dv vod_phase err_phase step_err_vs_ideal end_ripple_rel",
        ".endc"])


def run(key, netlist_bytes, corner, temp, vdda, ng, pdk_lib, tmp):
    net = tmp / f"integrator-{key}.spice"
    net.write_bytes(netlist_bytes)
    deck = ((HERE / "diag_1v62.cir.tmpl").read_text()
            .replace("{{PDK_LIB}}", f'"{pdk_lib}"').replace("{{CORNER}}", corner)
            .replace("{{TEMP}}", str(temp)).replace("{{VDDA}}", str(vdda))
            .replace("{{LOAD}}", "0.1p")
            .replace("{{OTA}}", f'"{REPO / "design/ota/ota_fd.spice"}"')
            .replace("{{NETLIST}}", f'"{net}"')
            .replace("{{XINT}}", run_diag.xint_line(netlist_bytes))
            .replace("{{PROBES}}", probes_min()))
    d = tmp / f"deck-{key}.cir"
    d.write_text(deck)
    r = subprocess.run(["ngspice", "-b", str(d)], capture_output=True, text=True, cwd=ng)
    log = r.stdout + r.stderr
    vals = {k: float(x) for k, x in
            re.findall(r"^([a-z0-9_]+)\s*=\s*([-+0-9.eE]+)\s*$", log, re.M)}
    wanted = ("err_phase", "step_dv", "step_err_vs_ideal", "end_ripple_rel")
    if r.returncode or any(k not in vals for k in wanted):
        print(log[-3000:], file=sys.stderr)
        sys.exit(f"REFUSE: ngspice did not produce the scalars for '{key}'")
    return {k: vals[k] for k in ("vod_pre", "vod_end", "step_dv", "vod_phase",
                                 "err_phase", "step_err_vs_ideal", "end_ripple_rel")
            if k in vals}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdk-root", default=None)
    ap.add_argument("--baseline-rev", default=run_diag.BASELINE_REV)
    ap.add_argument("--out", default="variants-i92.json")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    pin = json.load(open(REPO / "sim/pdk.json"))
    root, stamp = pdk_stamp(pin["variant"], a.pdk_root)
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'", file=sys.stderr)
        return 2
    out = HERE / a.out
    if a.write and out.exists():
        print(f"REFUSE: {out.name} exists; results are append-only (use --out)", file=sys.stderr)
        return 2
    ng = root / pin["variant"] / "libs.tech/ngspice"
    pdk_lib = ng / "sky130.lib.spice"

    fixed = (REPO / "design/integrator/integrator.spice").read_bytes()
    base = subprocess.run(["git", "show", f"{a.baseline_rev}:design/integrator/integrator.spice"],
                          cwd=REPO, capture_output=True)
    if base.returncode:
        print(f"REFUSE: cannot read the baseline netlist at {a.baseline_rev}: "
              f"{base.stderr.decode()[-300:]}", file=sys.stderr)
        return 2

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="integrator-variants-"))
    nets = {}
    for v in ("ideal", "no_pmos_std", "no_pmos_lvt", "fixed"):
        nb, note = transform(base.stdout, fixed, v)
        nets[v] = (nb, note)

    res = {
        "fixture": "Integrator settling with substituted switches: switch-isolation "
                   "cross-check and PMOS-half size bounds (issue #92)",
        "result_kind": "simulated (ngspice, transistor-level netlists of design/integrator + "
                       "design/ota/ota_fd); one corner per row, run locally; not measured, "
                       "not a record, not a performance claim",
        "purpose": "show the 1.620 V failure is switch conduction and not the OTA, and bound "
                   "how small the PMOS halves can get",
        "pass_criterion": "err_phase <= 1e-4 (DR-005), same definition as record.json",
        "deck": "diag_1v62.cir.tmpl (same stimulus and timing as run_diag.py)",
        "pdk_sources_stamp": stamp,
        "pdk_pin": {"file": "sim/pdk.json", "open_pdks_revision": pin["open_pdks_revision"]},
        "ngspice": run_diag._ngspice_version(),
        "deck_sha256": run_diag.sha256_bytes((HERE / "diag_1v62.cir.tmpl").read_bytes()),
        "ota_netlist_sha256": run_diag.sha256_bytes((REPO / "design/ota/ota_fd.spice").read_bytes()),
        "baseline_rev": a.baseline_rev,
        "variants": {v: {"note": note, "netlist_sha256": run_diag.sha256_bytes(nb)}
                     for v, (nb, note) in nets.items()},
        "points": {},
    }
    for key, variant, corner, temp, vdda in POINTS:
        vals = run(key, nets[variant][0], corner, temp, vdda, ng, pdk_lib, tmp)
        res["points"][key] = {"variant": variant, "corner": corner, "temperature_c": temp,
                              "vdda_V": vdda, "values": vals}
        print(f"  {key:28s} err_phase = {vals['err_phase']:.4g}", file=sys.stderr)

    txt = json.dumps(res, indent=2) + "\n"
    if a.write:
        out.write_text(txt)
        print(f"wrote {out.name}")
    else:
        print(txt)
        print("re-run with --write to save", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

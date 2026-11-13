#!/usr/bin/env python3
"""Issue #92 single-corner diagnosis of the Vdda = 1.620 V non-settling.

Runs diag_1v62.cir.tmpl at ONE corner (default fs / -40 C / 1.620 V, the binding
PVT point of record.json), locally, against two netlists:

  as_built  the integrator as it was when record.json was taken (pulled out of
            git at --baseline-rev, so the failing cell stays reproducible after
            the fix lands)
  fixed     the integrator netlist in the working tree

and writes diag-i92.json. Simulated, one corner, local -- not a record and not
a performance claim. The 45-corner evidence is record*.json; see README.md.
"""
import argparse, hashlib, json, pathlib, re, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from settling_common import pdk_stamp

BASELINE_REV = "ffbbb3b"   # merge of PR #93: the netlists record.json was taken on

# Scalars pulled out of the transient. `lt`/`gt`: bare < > are shell
# redirections in ngspice's control language.
T_STEP, T_PHASE, T_END = 35.0e-9, 97.66e-9, 335e-9
T_SAMPLE = T_STEP + T_PHASE
T_MID = 100e-9      # inside the integrate phase
T_EDGE = 40e-9      # just after the phi2 edge, where a slewing OTA would show


def probes(nsw, psw):
    """The .control block: the record's own figures of merit, plus node evidence.

    nsw/psw are the internal device names of one NMOS switch and its PMOS half
    (None when the netlist has no PMOS half).
    """
    sti = f"@m.xint.xsti_p.{nsw}"
    sbi = f"@m.xint.xsbi_p.{nsw}"
    str_ = f"@m.xint.xstr_p.{nsw}"
    sbr = f"@m.xint.xsbr_p.{nsw}"
    ota = "@m.xint.xota"
    save = [sti, sbi, str_, sbr,
            f"{ota}.xmt.msky130_fd_pr__nfet_01v8[id]",
            f"{ota}.xm1.msky130_fd_pr__nfet_01v8[id]",
            f"{ota}.xm2.msky130_fd_pr__nfet_01v8[id]"]
    saves = " ".join(f"{d}[vth] {d}[id]" for d in (sti, sbi, str_, sbr))
    if psw:
        saves += f" @m.xint.xsti_p_p.{psw}[id] @m.xint.xsbi_p_p.{psw}[id]"
    L = [".control", "option gmin=1e-9",
         "save v(vod) v(voutp) v(voutn) v(vcm) v(phi2) v(phi1e)",
         "+ v(xint.sump) v(xint.sumn) v(xint.tpi_p) v(xint.bpi_p) v(xint.tpr_p) v(xint.bpr_p)",
         f"+ {saves}",
         f"+ {ota}.xmt.msky130_fd_pr__nfet_01v8[id] {ota}.xm1.msky130_fd_pr__nfet_01v8[id]",
         f"+ {ota}.xm2.msky130_fd_pr__nfet_01v8[id]",
         f"tran 10p {T_END:.6g} 0 0.1n",
         # --- the same figures of merit record.json reports ---
         "let vod_pre = v(vod)[0]",
         "let vod_end = v(vod)[length(v(vod))-1]",
         "let step_dv = vod_end - vod_pre",
         f"meas tran vod_phase find v(vod) at={T_SAMPLE:.6g}",
         "let err_phase = abs(vod_phase - vod_end)/abs(step_dv)",
         "let step_err_vs_ideal = abs(abs(step_dv) - 0.9)/0.9",
         f"let end_ripple_rel = (vecmax(v(vod)*(time gt {T_END-20e-9:.6g}) - 10*(time le {T_END-20e-9:.6g}))"
         f" - vecmin(v(vod)*(time gt {T_END-20e-9:.6g}) + 10*(time le {T_END-20e-9:.6g})))/abs(step_dv)",
         "print vod_pre vod_end step_dv vod_phase err_phase step_err_vs_ideal end_ripple_rel",
         # --- switch evidence, mid-integrate ---
         "let vgs_sti = v(phi2) - v(xint.sump)",
         "let vgs_sbi = v(phi2) - v(vcm)",
         "let drop_sti = v(xint.tpi_p) - v(xint.sump)",
         "let drop_sbi = v(xint.bpi_p) - v(vcm)",
         "let drop_str = v(xint.tpr_p) - v(xint.sump)",
         "let drop_sbr = v(xint.bpr_p) - v(vcm)",
         "let vocm = (v(voutp)+v(voutn))/2",
         "let vsum_diff = v(xint.sump) - v(xint.sumn)"]
    for nm, ex in (("vgs_sti", "vgs_sti"), ("vgs_sbi", "vgs_sbi"),
                   ("vth_sti", f"{sti}[vth]"), ("vth_sbi", f"{sbi}[vth]"),
                   ("vth_str", f"{str_}[vth]"), ("vth_sbr", f"{sbr}[vth]"),
                   ("id_sti", f"{sti}[id]"), ("id_sbi", f"{sbi}[id]"),
                   ("id_str", f"{str_}[id]"), ("id_sbr", f"{sbr}[id]"),
                   ("drop_sti", "drop_sti"), ("drop_sbi", "drop_sbi"),
                   ("drop_str", "drop_str"), ("drop_sbr", "drop_sbr"),
                   ("sump", "v(xint.sump)"), ("sumn", "v(xint.sumn)"),
                   ("vsum_diff", "vsum_diff"), ("vocm", "vocm"),
                   ("voutp", "v(voutp)"), ("voutn", "v(voutn)"),
                   ("tpi_p", "v(xint.tpi_p)"), ("bpi_p", "v(xint.bpi_p)")):
        L.append(f"let x_{nm} = {ex}")
        L.append(f"meas tran m_{nm} find x_{nm} at={T_MID:.6g}")
    if psw:
        for nm, d in (("idp_sti", f"@m.xint.xsti_p_p.{psw}"), ("idp_sbi", f"@m.xint.xsbi_p_p.{psw}")):
            L.append(f"let x_{nm} = {d}[id]")
            L.append(f"meas tran m_{nm} find x_{nm} at={T_MID:.6g}")
    # --- sampling-phase evidence (phi1e still closed at 20 ns) ---
    for nm, ex in (("tpi_smp", "v(xint.tpi_p)"), ("bpi_smp", "v(xint.bpi_p)")):
        L.append(f"let y_{nm} = {ex}")
        L.append(f"meas tran m_{nm} find y_{nm} at=20n")
    # --- OTA branch currents: a slewing OTA puts the whole tail in one branch ---
    for nm, ex in (("i_tail", f"{ota}.xmt.msky130_fd_pr__nfet_01v8[id]"),
                   ("i_m1", f"{ota}.xm1.msky130_fd_pr__nfet_01v8[id]"),
                   ("i_m2", f"{ota}.xm2.msky130_fd_pr__nfet_01v8[id]")):
        L.append(f"let z_{nm} = {ex}")
        L.append(f"meas tran m_{nm}_edge find z_{nm} at={T_EDGE:.6g}")
        L.append(f"meas tran m_{nm}_mid find z_{nm} at={T_MID:.6g}")
    L.append(".endc")
    return "\n".join(L)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def xint_line(netlist_bytes):
    """Build `Xint ...` from the netlist's own .subckt port order.

    `klt netlist` groups subckt ports by pin type, so the committed port order
    changed with the issue #92 regeneration (voutp/voutn moved to the end). The
    diagnosis has to run the pre-fix netlist too, so the instance line is
    derived rather than hard-coded. Every port maps to the bench net of the same
    name except vssa, which is the bench ground.
    """
    txt = netlist_bytes.decode()
    lines, cur = [], None
    for ln in txt.splitlines():
        if ln.startswith("+") and cur is not None:
            cur += " " + ln[1:].strip()
        else:
            if cur is not None:
                lines.append(cur)
            cur = ln
    if cur is not None:
        lines.append(cur)
    decl = next((l for l in lines if l.lower().startswith(".subckt integrator")), None)
    if decl is None:
        sys.exit("REFUSE: no '.subckt integrator' line in the netlist")
    ports = decl.split()[2:]
    expected = {"vdda", "vssa", "vinp", "vinn", "voutp", "voutn", "vrefp", "vrefn",
                "vcm", "ibias", "phi1", "phi1b", "phi1e", "phi2", "dp", "dn"}
    if set(ports) != expected:
        sys.exit(f"REFUSE: unexpected integrator port set {sorted(ports)}")
    nets = ["0" if p == "vssa" else p for p in ports]
    return "Xint " + " ".join(nets) + " integrator"


def run(tag, netlist_bytes, corner, temp, vdda, load, ng, pdk_lib, tmp):
    nsw = ("msky130_fd_pr__nfet_01v8_lvt" if b"nfet_01v8_lvt" in netlist_bytes
           else "msky130_fd_pr__nfet_01v8")
    psw = "msky130_fd_pr__pfet_01v8_lvt" if b"pfet_01v8_lvt" in netlist_bytes else None
    net = tmp / f"integrator-{tag}.spice"
    net.write_bytes(netlist_bytes)
    deck = ((HERE / "diag_1v62.cir.tmpl").read_text()
            .replace("{{PDK_LIB}}", f'"{pdk_lib}"').replace("{{CORNER}}", corner)
            .replace("{{TEMP}}", str(temp)).replace("{{VDDA}}", str(vdda))
            .replace("{{LOAD}}", load)
            .replace("{{OTA}}", f'"{REPO / "design/ota/ota_fd.spice"}"')
            .replace("{{NETLIST}}", f'"{net}"')
            .replace("{{XINT}}", xint_line(netlist_bytes))
            .replace("{{PROBES}}", probes(nsw, psw)))
    d = tmp / f"deck-{tag}.cir"
    d.write_text(deck)
    r = subprocess.run(["ngspice", "-b", str(d)], capture_output=True, text=True, cwd=ng)
    log = r.stdout + r.stderr
    vals = {k: float(x) for k, x in
            re.findall(r"^(?:m_)?([a-z0-9_]+)\s*=\s*([-+0-9.eE]+)\s*$", log, re.M)}
    wanted = ("err_phase", "step_dv", "step_err_vs_ideal", "end_ripple_rel")
    if r.returncode or any(k not in vals for k in wanted):
        print(log[-3000:], file=sys.stderr)
        sys.exit(f"REFUSE: ngspice did not produce the diagnosis scalars for '{tag}'")
    return {"netlist_sha256": sha256_bytes(netlist_bytes),
            "switch_nmos_model": nsw.removeprefix("m"),
            "switch_pmos_half": psw.removeprefix("m") if psw else None,
            "values": vals}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--corner", default="fs")
    ap.add_argument("--temp", type=float, default=-40)
    ap.add_argument("--vdda", type=float, default=1.62)
    ap.add_argument("--load", default="0.1p", help="per-side output load (int1 = 0.1p)")
    ap.add_argument("--baseline-rev", default=BASELINE_REV)
    ap.add_argument("--out", default="diag-i92.json")
    ap.add_argument("--write", action="store_true",
                    help="write the result file (refuses to overwrite: append-only)")
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

    cur = (REPO / "design/integrator/integrator.spice").read_bytes()
    base = subprocess.run(["git", "show", f"{a.baseline_rev}:design/integrator/integrator.spice"],
                          cwd=REPO, capture_output=True)
    if base.returncode:
        print(f"REFUSE: cannot read the baseline netlist at {a.baseline_rev}: "
              f"{base.stderr.decode()[-300:]}", file=sys.stderr)
        return 2

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="integrator-diag-"))
    res = {
        "fixture": "Integrator settling bench, ONE corner, with internal node and device probes (issue #92)",
        "result_kind": "simulated (ngspice, transistor-level netlists of design/integrator + "
                       "design/ota/ota_fd); one corner, run locally; not measured, not a record",
        "purpose": "name the mechanism behind the 0/15 Vdda = 1.620 V failures in record.json",
        "corner": {"process": a.corner, "temperature_c": a.temp, "vdda_V": a.vdda,
                   "load_per_side": a.load, "variant_equivalent": "int1" if a.load == "0.1p" else a.load},
        "conditions": {"vcm_V": 0.9, "vrefp_V": 1.5, "vrefn_V": 0.3, "vin_diff_V": 0.6, "dn": 1,
                       "phase_ns": 97.66, "sampled_at_ns": 132.66,
                       "probe_times_ns": {"edge": 40, "mid_integrate": 100, "mid_sample": 20}},
        "pass_criterion": "err_phase <= 1e-4 (DR-005), same definition as record.json",
        "pdk_sources_stamp": stamp,
        "pdk_pin": {"file": "sim/pdk.json", "open_pdks_revision": pin["open_pdks_revision"]},
        "ngspice": subprocess.run(["ngspice", "-v"], capture_output=True, text=True
                                  ).stdout.splitlines()[0] if True else None,
        "deck_sha256": sha256_bytes((HERE / "diag_1v62.cir.tmpl").read_bytes()),
        "ota_netlist_sha256": sha256_bytes((REPO / "design/ota/ota_fd.spice").read_bytes()),
        "baseline_rev": a.baseline_rev,
        "runs": {},
    }
    res["runs"]["as_built"] = run("as-built", base.stdout, a.corner, a.temp, a.vdda, a.load,
                                  ng, pdk_lib, tmp)
    res["runs"]["fixed"] = run("fixed", cur, a.corner, a.temp, a.vdda, a.load, ng, pdk_lib, tmp)
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

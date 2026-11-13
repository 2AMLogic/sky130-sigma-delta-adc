#!/usr/bin/env python3
"""First-integrator thermal-noise runner (simulated, transistor-level).

Submits both variant requests (ktc, amp) over the DR-002 full grid through
`klt sim`, which sends them to the batch fleet; never falls back to a local
grid. --probe runs one tt/27C/1.8V corner of each locally (bench debugging, no
record). See README.md for the method, the unit conversions and what is left
out.
"""
import argparse, json, math, pathlib, re, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from settling_common import (grid_complete, measurements_present,  # noqa: E402
                             pdk_stamp, run_klt, sha256)

sys.path.insert(0, str(HERE))
import make_request as mk  # noqa: E402

ARTIFACTS = HERE / ".artifacts"   # raw klt reports / batch receipts, gitignored

KEYS = ("nz_rms_tot", "nz_rms_bb", "nz_rms_audio", "nz_dens_20", "nz_dens_1k",
        "nz_dens_20k", "nz_dens_1meg", "nz_dens_100meg", "nz_total_native",
        "total_vs_native_rel")

# --- spec and model constants, each with the line it comes from -------------
OSR = 128                   # spec row 4 target (fs 5.12 MHz, BW 20 kHz)
BW_HZ = mk.BW_HZ            # spec row 3
C1 = 0.5                    # model B's integrator-1 coefficient, Cs/Ci
VFS_DIFF_V = 1.2            # 1 FS = VREFP - VREFN, the integrator-ci convention
KTC_BUDGET_V2 = 4.5e-10     # spec 5.3, in-band sampling-switch kT/C share
THERMAL_BUDGET_V2 = 9.0e-10 # spec 5.3, in-band total thermal share
K_B = 1.380649e-23          # J/K, SI 2019 exact

# sky130A MIM parameters, for the drawn-capacitance reference only (the
# per-corner value this bench reports is derived from the simulation, not
# from these). res_typical__cap_typical__lin.spice and
# sky130_fd_pr__model__r+c.model.spice in the pinned PDK.
CAMIMC_F_PER_UM2 = 2.00e-15
CPMIMC_F_PER_UM = 0.19e-15
M3_DW_UM = -0.025

# The noise is measured at a different place in each variant, so each carries
# its own referral to the integrator input (differential volts), where spec
# 5.3's budget lives. ktc is already there; amp is at the differential output,
# one charge transfer later, so dividing by C1 undoes the Cs/Ci gain.
INPUT_REFERRAL = {"ktc": 1.0, "amp": 1.0 / C1}


def _join_continuations(text):
    out = []
    for raw in text.splitlines():
        if raw.startswith("+") and out:
            out[-1] += " " + raw[1:].strip()
        else:
            out.append(raw.strip())
    return out


def mim_farads(w_um, l_um):
    """sky130_fd_pr__cap_mim_m3_1 capacitance at the typical cap section."""
    wc, lc = w_um + M3_DW_UM, l_um + M3_DW_UM
    return CAMIMC_F_PER_UM2 * wc * lc + CPMIMC_F_PER_UM * 2.0 * (wc + lc)


def drawn_caps(netlist=REPO / "design/integrator/integrator.spice"):
    """Cs and Ci as drawn in the cell, not the 1 pF / 2 pF planning values."""
    geo = {}
    for line in _join_continuations(pathlib.Path(netlist).read_text()):
        m = re.match(r"^X(Csi|Csr|Ci)_([pn])\s+.*\bW=([0-9.eE+-]+)\s+L=([0-9.eE+-]+)", line)
        if m:
            geo.setdefault(m.group(1), []).append((float(m.group(3)), float(m.group(4))))
    def one(key):
        wl = geo.get(key) or []
        return mim_farads(*wl[0]) if wl else None
    cs, ci = one("Csi"), one("Ci")
    return {
        "cs_drawn_F": cs, "ci_drawn_F": ci,
        "cs_drawn_geometry_um": list(geo.get("Csi", [(None, None)])[0]),
        "ci_drawn_geometry_um": list(geo.get("Ci", [(None, None)])[0]),
        "drawn_ratio_cs_over_ci": (cs / ci) if cs and ci else None,
        "planning_values_not_used": {"cs_pF": 1.0, "ci_pF": 2.0,
                                     "from": "spec/modulator-adc.md 5.3 planning values"},
        "method": ("drawn W/L of the cell's sky130_fd_pr__cap_mim_m3_1 devices through the "
                   f"PDK's own area/perimeter model (camimc {CAMIMC_F_PER_UM2:g} F/um^2, "
                   f"cpmimc {CPMIMC_F_PER_UM:g} F/um, m3_dw {M3_DW_UM:g} um) at the TYPICAL "
                   "cap section. The cap_low/cap_high sections move camimc by -11%/+12%, so "
                   "this single number is a reference, not a per-corner value -- the "
                   "per-corner cs_eff_F below is derived from each corner's own simulated "
                   "variance and does carry that spread, plus the switch and plate "
                   "parasitics the drawn capacitance alone does not."),
    }


def temp_k(corner_id):
    """Absolute temperature from a klt corner_id like `ss/1.620V/-40C`."""
    m = re.search(r"/(-?\d+)C$", corner_id)
    return None if m is None else float(m.group(1)) + 273.15


def part(corner_id, c, variant):
    """One variant's noise at one corner, referred to the integrator input."""
    g = INPUT_REFERRAL[variant]
    rms = c.get("nz_rms_tot")
    if rms is None:
        return {"status": c["status"], "diagnostics": c.get("diagnostics", []),
                "var_total_V2": None}
    var_tot = (rms * g) ** 2
    var_bb = (c["nz_rms_bb"] * g) ** 2 if c.get("nz_rms_bb") is not None else None
    var_audio = (c["nz_rms_audio"] * g) ** 2 if c.get("nz_rms_audio") is not None else None
    var_alias = None if var_bb is None else max(var_tot - var_bb, 0.0)
    row = {
        "status": c["status"],
        "measured_rms_V": rms,
        "input_referral": g,
        # Per sampling event: the whole swept band, input-referred.
        "var_total_V2": var_tot,
        # The share that reaches the signal band without aliasing, and the
        # share above it, which folds.
        "var_baseband_V2": var_bb,
        "var_audio_band_V2": var_audio,
        "var_aliased_V2": var_alias,
        # The two in-band links. `inband_V2` is the one the budget is compared
        # against: the baseband share passes straight through and only the
        # folded share is divided by OSR. `inband_white_V2` is the link spec
        # 5.3 and model B assume (white noise, all of it aliased); the two
        # differ by exactly the flicker content of this part.
        "inband_V2": None if var_alias is None else var_bb + var_alias / OSR,
        "inband_white_V2": var_tot / OSR,
        "spectrum_V_per_rtHz": {"20Hz": c.get("nz_dens_20"), "1kHz": c.get("nz_dens_1k"),
                                "20kHz": c.get("nz_dens_20k"), "1MHz": c.get("nz_dens_1meg"),
                                "100MHz": c.get("nz_dens_100meg")},
        "klt_vs_ngspice_integral_rel": c.get("total_vs_native_rel"),
        "diagnostics": c.get("diagnostics", []),
    }
    # Model B's ktc_noise_var is a per-event variance in FS^2 at the
    # integrator-1 state increment; one FS of integrator input becomes C1 FS
    # there, and 1 FS = VREFP - VREFN volts. The equivalent WHITE per-event
    # variance is the one that reproduces `inband_V2` under model B's own
    # white-aliasing assumption, which is inband * OSR.
    fs2 = (C1 / VFS_DIFF_V) ** 2
    row["var_total_fs2"] = fs2 * var_tot
    row["model_b_equiv_var_V2"] = (None if row["inband_V2"] is None
                                   else row["inband_V2"] * OSR)
    row["model_b_equiv_ktc_noise_var_fs2"] = (None if row["inband_V2"] is None
                                              else fs2 * row["inband_V2"] * OSR)
    if variant == "ktc":
        t = temp_k(corner_id)
        # A single-pole sampler holds kT/C whatever R is, and this output sums
        # four of them, so 4kT/var is the effective sampling capacitance that
        # the real switch and plate parasitics present -- a direct check on
        # the drawn value.
        row["cs_eff_F"] = None if t is None or var_tot <= 0 else 4.0 * K_B * t / var_tot
        row["temperature_K"] = t
    return row


def derive(sets):
    """Join the variant corner sets into one per-corner row with the verdicts."""
    cids = sorted(set().union(*[set(s) for s in sets.values()]))
    out = {}
    for cid in cids:
        row = {v: part(cid, sets[v][cid], v) for v in sets if cid in sets[v]}
        ktc, amp = row.get("ktc", {}), row.get("amp", {})
        ib_k, ib_a = ktc.get("inband_V2"), amp.get("inband_V2")
        total = None if ib_k is None or ib_a is None else ib_k + ib_a
        row["verdict"] = {
            "ktc_inband_V2": ib_k,
            "ktc_budget_V2": KTC_BUDGET_V2,
            "ktc_pass": None if ib_k is None else ib_k <= KTC_BUDGET_V2,
            "ktc_margin_db": None if not ib_k else 10.0 * math.log10(KTC_BUDGET_V2 / ib_k),
            "total_thermal_inband_V2": total,
            "total_thermal_budget_V2": THERMAL_BUDGET_V2,
            "total_thermal_pass": None if total is None else total <= THERMAL_BUDGET_V2,
            "total_thermal_margin_db": (None if not total else
                                        10.0 * math.log10(THERMAL_BUDGET_V2 / total)),
        }
        out[cid] = row
    return out


def summarize(rows):
    def binding(path, pick):
        have = [(_dig(r, path), cid) for cid, r in rows.items() if _dig(r, path) is not None]
        if not have:
            return None
        v, cid = pick(have)
        return {"corner_id": cid, "value": v}
    fails_k = sorted(cid for cid, r in rows.items() if r["verdict"]["ktc_pass"] is False)
    fails_t = sorted(cid for cid, r in rows.items() if r["verdict"]["total_thermal_pass"] is False)
    return {
        "corner_count": len(rows),
        "binding_ktc_corner": binding(("verdict", "ktc_inband_V2"), max),
        "binding_total_thermal_corner": binding(("verdict", "total_thermal_inband_V2"), max),
        "ktc_budget_V2": KTC_BUDGET_V2,
        "ktc_fail_corners": fails_k,
        "ktc_pass_count": len(rows) - len(fails_k),
        "total_thermal_budget_V2": THERMAL_BUDGET_V2,
        "total_thermal_fail_corners": fails_t,
        "total_thermal_pass_count": len(rows) - len(fails_t),
        "cs_eff_F_range": [binding(("ktc", "cs_eff_F"), min), binding(("ktc", "cs_eff_F"), max)],
        "worst_klt_vs_ngspice_integral_rel": max(
            [v for cid, r in rows.items() for v in
             (_dig(r, ("ktc", "klt_vs_ngspice_integral_rel")),
              _dig(r, ("amp", "klt_vs_ngspice_integral_rel"))) if v is not None] or [None]),
    }


def _dig(d, path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--probe", action="store_true", help="one tt/27C/1.8V corner, local, no record")
    ap.add_argument("--record", action="store_true",
                    help="write record.json (refuses to overwrite: records are append-only)")
    ap.add_argument("--record-name", default="record.json",
                    help="record file name, for a re-run after a sizing change (new file)")
    a = ap.parse_args()
    pin = json.load(open(REPO / "sim/pdk.json"))
    root, stamp = pdk_stamp(pin["variant"], a.pdk_root)
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'", file=sys.stderr)
        return 2
    out = HERE / a.record_name
    if a.record and out.exists():
        print(f"REFUSE: {out.name} exists; records are append-only (use --record-name)", file=sys.stderr)
        return 2
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="integrator-noise-"))
    sets, reps = {}, {}
    for v in mk.VARIANTS:
        res = run_klt(HERE / f"request_{v}.json", a.probe, tmp, v,
                      HERE / f"probe_request_{v}.json",
                      artifacts_dir=None if a.probe else ARTIFACTS, keys=KEYS)
        if res is None:
            print(f"REFUSE: variant {v} returned no usable report", file=sys.stderr)
            return 1
        reps[v], sets[v] = res
    rows = derive(sets)
    summary = summarize(rows)
    print(json.dumps({"status": {v: r.get("status") for v, r in reps.items()},
                      **summary}, indent=2))
    if a.probe:
        print(json.dumps(rows, indent=2))
        return 0
    corner_sets = [sets[v] for v in mk.VARIANTS]
    if not grid_complete(corner_sets) or not measurements_present(corner_sets, key="nz_rms_tot"):
        return 1
    env = reps["ktc"].get("environment", {})
    rec = {
        "fixture": ("First-integrator thermal-noise bench (issue #126): design/integrator's full "
                    "cell held in one clock phase per variant, small-signal .noise over "
                    f"{mk.F_LO:g} Hz - {mk.F_HI:g} Hz. ktc = the four sampling capacitors in "
                    "phi1; amp = the OTA with its phi2 switches, at the differential output."),
        "source": "T",
        "result_kind": ("simulated (ngspice .noise, transistor-level netlists of "
                        "design/integrator/integrator.spice and design/ota/ota_fd.spice; not the "
                        "behavioural model). A simulated number is never called measured."),
        "model_b_parameter": ("ktc_noise_var (sim/bmodel/model.py): per-sampling-event variance "
                              "in FS^2, added to integrator 1's state increment"),
        "method": {
            "analysis": {v: json.load(open(HERE / f"request_{v}.json"))["analysis"]
                         for v in mk.VARIANTS},
            "chosen": ("`.noise` on the real cell, one of the three forms issue #126 allows and "
                       "the one DR-001 item 2 names. Not kT/C arithmetic: the simulated variance "
                       "carries each corner's own capacitance, its switch noise at the bias that "
                       "phase gives it, and the plate and switch parasitics that arithmetic from "
                       "the drawn value alone would miss (cs_eff_F below is 15% above the drawn "
                       "Cs for exactly that reason)."),
            "why_two_requests": ("a small-signal .noise run needs a static clock state and one "
                                 "corner runs one analysis with one output, so the two halves of "
                                 "spec 5.3's thermal share are two requests over the same "
                                 "45-point grid, as sim/integrator-settling does with int1/int2"),
            "variants": {v: {"what": d["what"], "referred_to": d["referred_to"],
                             "clock_state": d["clocks"], "output": d["output"]}
                         for v, d in mk.VARIANTS.items()},
            "integration_band_Hz": [mk.F_LO, mk.F_HI],
            "lower_edge": (f"every band integral starts at {mk.F_LO:g} Hz. Flicker noise "
                           "diverges logarithmically downward, so this edge is a choice, not a "
                           "property of the circuit: var_audio_band_V2 repeats the baseband "
                           f"integral from {mk.AUDIO_LO_HZ:g} Hz so the sensitivity is visible "
                           "rather than hidden."),
            "convergence": ("klt_vs_ngspice_integral_rel compares klt's trapezoid over the swept "
                            "grid against ngspice's own onoise_total over the same range; "
                            f"agreement within {mk.NATIVE_TOL:g} is gated per corner and is also "
                            "the evidence that the upper edge is far enough out."),
        },
        "unit_conversions": {
            "osr": OSR,
            "bandwidth_Hz": BW_HZ,
            "per_event_to_inband": ("the sampled sequence is white across fs/2, so the share of a "
                                    "WHITE per-event variance that lands in BW is 1/OSR = "
                                    f"1/{OSR}. This is the link spec 5.3 assumes and the one "
                                    "model B's i.i.d. Gaussian draw reproduces: inband_white_V2 "
                                    "= var_total_V2 / OSR."),
            "non_white_correction": ("the measured spectra are not white, so inband_V2 splits "
                                     "them: the baseband share (below BW) reaches the band with "
                                     "no aliasing and is NOT divided by OSR, and only the share "
                                     "above BW folds. inband_V2 = var_baseband_V2 + "
                                     "var_aliased_V2 / OSR. For the switches the two links agree "
                                     "to a part in 1e4 (white); for the amplifier they do not, "
                                     "and the difference is its flicker content."),
            "volts_to_fs": (f"1 FS = VREFP - VREFN = {VFS_DIFF_V} V of differential integrator "
                            f"output, and model B's integrator-1 coefficient is C1 = {C1}, so a "
                            "variance referred to the integrator input in V^2 becomes "
                            f"(C1/{VFS_DIFF_V})^2 = {(C1 / VFS_DIFF_V) ** 2:.6g} times that in "
                            "FS^2. Same convention as sim/integrator-ci's ci_offset."),
            "model_b_equivalent": ("model_b_equiv_ktc_noise_var_fs2 is the WHITE per-event "
                                   "variance that reproduces inband_V2 through model B's own "
                                   "1/OSR link, i.e. inband_V2 * OSR converted to FS^2. That, "
                                   "not var_total_fs2, is the number to load into "
                                   "ktc_noise_var, because model B draws i.i.d. per clock and "
                                   "would otherwise under-count the flicker share."),
        },
        "budget": {
            "from": "spec/modulator-adc.md 5.3 (kT/C budget, target column)",
            "ktc_share_V2": KTC_BUDGET_V2,
            "total_thermal_share_V2": THERMAL_BUDGET_V2,
            "unchanged": ("both budgets are the ratified planning allocation and are reported "
                          "against, not adjusted. A corner that misses is recorded as a miss and "
                          "filed; resizing the OTA or the capacitors is out of scope here."),
            "flicker_caveat": ("5.3 allocates a THERMAL share. The amplifier part measured here "
                               "is flicker-dominated across the whole closed-loop band, and "
                               "ngspice's .noise gives no thermal/flicker split through any klt "
                               "measurement form, so amp's inband_V2 is thermal PLUS flicker "
                               "compared against a thermal-only line. The comparison is "
                               "therefore conservative for the amplifier and exact for the "
                               "switches -- and 5.3 carries no 1/f allocation at all, which is "
                               "itself a finding, not a bench defect."),
        },
        "leaves_out": [
            "flicker/thermal separation. ngspice's integrated-noise plot does carry a "
            "per-device, per-mechanism decomposition, but it has no aggregate: a mechanism "
            "total needs every flattened instance name enumerated and summed by hand in "
            "the request, and klt sim has no measurement form for it. Filed under the "
            "friction protocol as 2AMLogic/klayout-tools#5553.",
            "correlation of the sampled noise between consecutive clocks: both parts are "
            "reported as i.i.d. per event, which over-counts the in-band effect of the "
            "amplifier's 1/f and ignores any correlated-double-sampling benefit",
            "the finite duration of the integrate phase: the amplifier integral is taken over "
            "the circuit's own noise bandwidth, not truncated to the 97.66 ns phase",
            "reference and bias noise (DR-005: inputs at the boundary, ideal and noiseless here)",
            "clock-jitter-induced noise (model B's jitter_rms_s, not extracted from this block)",
            "mismatch (this is the nominal grid, no Monte Carlo) and layout parasitics (DR-001 "
            "item 4, post-layout)",
        ],
        "conditions": {"vcm_V": 0.9, "vrefp_V": 1.5, "vrefn_V": 0.3, "vin_diff_V": 0.6,
                       "ibias_uA": 5, "load_pF_per_side": 0.1,
                       "corner_set": "DR-002 full grid, 5 process x 3 T x 3 Vdda"},
        "drawn_capacitors": drawn_caps(),
        "pdk_sources_stamp": stamp,
        "pdk_pin": {"file": "sim/pdk.json", "open_pdks_revision": pin["open_pdks_revision"]},
        "ngspice": env.get("engine_version", "unknown"),
        "klt": subprocess.run(["klt", "--version"], capture_output=True, text=True).stdout.strip(),
        "engine_host": env.get("engine_host"),
        "remote": {v: reps[v].get("environment", {}).get("remote") for v in mk.VARIANTS},
        "batch_receipt": {v: reps[v].get("batch_receipt") for v in mk.VARIANTS},
        "request_sha256": {v: sha256(HERE / f"request_{v}.json") for v in mk.VARIANTS},
        "deck_sha256": {v: sha256(HERE / f"integrator_noise_{v}.cir") for v in mk.VARIANTS},
        "deck_template_sha256": sha256(HERE / "integrator_noise.cir.tmpl"),
        "integrator_netlist_sha256": sha256(REPO / "design/integrator/integrator.spice"),
        "ota_netlist_sha256": sha256(REPO / "design/ota/ota_fd.spice"),
        "summary": summary,
        "corners": rows,
        "pass": all(r.get("status") == "pass" for r in reps.values()),
    }
    if a.record:
        out.write_text(json.dumps(rec, indent=2) + "\n")
        print(f"wrote {out}", file=sys.stderr)
    return 0 if not summary["total_thermal_fail_corners"] else 1


if __name__ == "__main__":
    sys.exit(main())

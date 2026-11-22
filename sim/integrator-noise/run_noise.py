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
        "nz_dens_20k", "nz_dens_1meg", "nz_dens_100meg", "nz_dens_top",
        "nz_rms_trunc1", "nz_rms_trunc2", "trunc_vs_total_rms_rel",
        "nz_total_native", "total_vs_native_rel")

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

# The two separate convergence claims this bench makes, kept here (and pinned
# by test_run_noise.py) because they are easy to conflate and a verdict depends
# on the second one: 99% of ktc's inband_V2 is the aliased share of the
# FULL-BAND integral, so a truncated band would make the budget margin
# optimistic.
CONVERGENCE = {
    "integration_scheme": (
        "klt_vs_ngspice_integral_rel compares klt's trapezoid against ngspice's own "
        f"onoise_total over the same swept range, gated <= {mk.NATIVE_TOL:g} per corner. "
        "What it shows: that the 20-points/decade grid resolves the spectrum well "
        "enough for a trapezoid to reproduce ngspice's own integrator. What it does "
        "NOT show: anything about the upper band edge -- both numbers span the "
        "identical sweep, so truncating the band would move them together and they "
        "would still agree. It is not cited as upper-edge evidence."),
    "upper_edge": (
        f"the per-corner evidence that F_HI = {mk.F_HI:g} Hz is far enough out is in "
        "`upper_edge` below, and it is the direct test: the SAME integral over bands "
        f"truncated at {mk.F_TRUNC[0]:g} Hz and {mk.F_TRUNC[1]:g} Hz. An integral with "
        "content left above its edge moves when the edge moves, so "
        "1 - (rms_trunc/rms_tot)^2 is the measured share of the full-band variance "
        "lying above each truncated edge, and the ratio of the two is the per-decade "
        "shrink rate. extrapolated_frac_above_F_HI carries that same rate one decade "
        f"further, past {mk.F_HI:g} Hz. trunc_vs_total_rms_rel gates the "
        f"{mk.F_TRUNC[1]:g} Hz one at {mk.TRUNC_TOL:g} per corner (a "
        "reference-validity limit, not a spec row). The density roll-off beside it "
        f"({mk.F_DENS_TOP:g} Hz against 100 MHz) is the slope that produces this. "
        "summary.extrapolated_tail_margin_impact_db closes the loop on why this "
        "matters: it is what the whole residual tail would be worth on a budget "
        "margin, 10*log10(1 + frac), against the dB of margin the verdicts report."),
    "closure": (
        "independently, for ktc: cs_eff_F = 4kT/var_total_V2 lands within switch- and "
        "plate-parasitic distance of the drawn Cs on every corner (see "
        "summary.cs_eff_F_range and method.chosen). A short integral would under-count "
        "the variance and so report a cs_eff ABOVE the drawn value by far more than "
        "parasitics can explain, so this is a second, physical check on the same band."),
}

# The noise is measured at a different place in each variant, so each carries
# its own referral to the integrator input (differential volts), where spec
# 5.3's budget lives. ktc is already there; amp is at the differential output,
# one charge transfer later, so dividing by C1 undoes the Cs/Ci gain.
#
# `ampq` carries the SAME 1/C1, and that is the point of issue #140 rather than
# an oversight. One FS of integrator input produces a per-cycle output
# increment of C1 FS, so dividing an increment by C1 refers it to the input --
# the identical referral `amp` uses. What #140 corrects is not the referral but
# WHERE the noise is read: `amp` reads v(vod), whose noise includes the
# summing-node excursion that the next phi1 reset discards, while `ampq` reads
# the voltage across Ci, which is the increment that actually accumulates. The
# correction is therefore measured, per corner, as the ratio of the two band
# integrals (`transfer` below), not asserted as a referral constant.
INPUT_REFERRAL = {"ktc": 1.0, "amp": 1.0 / C1, "ampq": 1.0 / C1}

# --- per-device decomposition (--devices), one local corner -----------------
# ngspice emits a per-device, per-mechanism breakdown of the integrated noise
# only when the noise statement carries a `pts_per_summary` argument, and `klt
# sim` has no measurement form for it (2AMLogic/klayout-tools#5553), so this
# one corner is a raw `ngspice -b`. The vectors are named
# `onoise_total.m.<flat.instance.path>.m<model>[.<mechanism>]` and hold the
# device's contribution as an RMS in VOLTS, not a variance: the identity that
# closes is sum(v_i^2) == onoise_total^2, which DEV_CLOSURE_TOL gates below.
# Summing the vectors as if they were variances is wrong by ~4e4 on this block
# and is exactly the mistake the closure gate exists to catch.
DEV_MECHANISMS = ("1overf", "id", "igb", "igd", "igs", "rbdb", "rbpb", "rbpd",
                  "rbps", "rbsb", "rd", "rg", "rs")
DEV_FLICKER = "1overf"
DEV_CLOSURE_TOL = 1e-6      # sum(v_i^2)/onoise_total^2 - 1, both groupings
DEV_PTS_PER_SUMMARY = 1000000   # > the point count, so exactly one summary
DEV_COVERAGE = 0.90         # the share the named device list must reach


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


def device_geometry(netlists=("design/ota/ota_fd.spice",
                             "design/integrator/integrator.spice")):
    """Drawn W/L and model per instance name, read from the design netlists.

    So the device split names devices a reader can act on: flicker power goes
    as 1/(W*L), so the drawn geometry beside each named instance is what says
    WHY it dominates, and it is read from the netlist rather than asserted.
    Keyed by the lower-cased instance name, which is how ngspice flattens it.
    """
    geo = {}
    for rel in netlists:
        for line in _join_continuations((REPO / rel).read_text()):
            m = re.match(r"^X(\S+)\s+.*?\b(sky130_fd_pr__\S+?)\s+"
                         r"L=([0-9.eE+-]+)\s+W=([0-9.eE+-]+)", line)
            if m:
                # Keyed as ngspice flattens it: the leading X included, lower
                # case, so `xint.xota.xm1` -> `xm1` finds XM1.
                geo[f"X{m.group(1)}".lower()] = {"design_instance": f"X{m.group(1)}",
                                                 "model": m.group(2),
                                                 "L_um": float(m.group(3)),
                                                 "W_um": float(m.group(4)),
                                                 "netlist": rel}
    return geo


def name_devices(named, geo):
    """Attach the drawn geometry to each named instance, where it is known.

    `instance` stays the ngspice flat path (so the number is traceable to the
    run) and the design-side name and geometry are added beside it.
    """
    for d in named:
        g = geo.get(d["instance"].split(".")[-1])
        if g:
            d.update(g)
            d["wl_um2"] = g["W_um"] * g["L_um"]
    return named


def temp_k(corner_id):
    """Absolute temperature from a klt corner_id like `ss/1.620V/-40C`."""
    m = re.search(r"/(-?\d+)C$", corner_id)
    return None if m is None else float(m.group(1)) + 273.15


def upper_edge(c, g, var_tot):
    """Measured evidence that the band integral converged below F_HI.

    The truncated-band integrals are the direct test: an integral that still
    has content above its edge moves when the edge moves, so
    1 - (rms_trunc/rms_tot)^2 is the share of the full-band variance above each
    truncated edge. The input referral `g` cancels in every ratio here, which
    is why the shares are comparable with var_total_V2 directly.
    """
    rms = c.get("nz_rms_tot")

    def frac_above(key):
        """Share of the full-band variance above that truncated edge."""
        t = c.get(key)
        return None if t is None or not rms else max(1.0 - (t / rms) ** 2, 0.0)

    f1, f2 = frac_above("nz_rms_trunc1"), frac_above("nz_rms_trunc2")
    # Same geometric shrink one decade further: an estimate of the tail left
    # above F_HI, labelled as an extrapolation rather than a measurement.
    shrink = None if not f1 or f2 is None else f2 / f1
    d_top, d_100m = c.get("nz_dens_top"), c.get("nz_dens_100meg")
    return {
        "truncated_edges_Hz": list(mk.F_TRUNC),
        "var_above_trunc1_frac": f1,
        "var_above_trunc2_frac": f2,
        "per_decade_shrink": shrink,
        "extrapolated_frac_above_F_HI": (None if shrink is None or f2 is None
                                         else f2 * shrink),
        "trunc_vs_total_rms_rel": c.get("trunc_vs_total_rms_rel"),
        "trunc_vs_total_rms_rel_limit": mk.TRUNC_TOL,
        "dens_at_trunc2_V_per_rtHz": d_top,
        "dens_at_100meg_V_per_rtHz": d_100m,
        "rolloff_trunc2_over_100meg": (None if not d_top or not d_100m else d_top / d_100m),
        "what_it_shows": CONVERGENCE["upper_edge"],
    }


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
    row["spectrum_V_per_rtHz"][f"{mk.F_DENS_TOP:g}Hz"] = c.get("nz_dens_top")
    row["upper_edge"] = upper_edge(c, g, var_tot)
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


def _db(x):
    return None if not x or x <= 0 else 10.0 * math.log10(x)


def implied_summing_node_cp_F(ratio_v, caps):
    """The summing-node parasitic the measured in-band amplitude ratio implies.

    For noise referred to the OTA input, the static phi2 output gain is
    1 + (Cs_tot+Cp)/Ci and the part across Ci is (Cs_tot+Cp)/Ci, so the
    amplitude ratio across-Ci / at-vod is r = (Cs_tot+Cp)/(Ci+Cs_tot+Cp).
    Inverting: Cp = (r*Ci - (1-r)*Cs_tot) / (1-r).

    Derived, not measured, and only indicative: the ratio it inverts is the
    composite over every phi2 noise source, not the OTA alone. It is quotable
    in band precisely because the device split shows the OTA's own devices
    carry essentially all of the in-band noise there; it is NOT quotable for
    the aliased part, where the switches matter.
    """
    cs, ci = (caps or {}).get("cs_drawn_F"), (caps or {}).get("ci_drawn_F")
    if not cs or not ci or ratio_v is None or not 0.0 < ratio_v < 1.0:
        return None
    return (ratio_v * ci - (1.0 - ratio_v) * 2.0 * cs) / (1.0 - ratio_v)


def transfer(amp, ampq, caps=None):
    """The measured static -> accumulating transfer at one corner.

    `amp` and `ampq` are the SAME static phi2 state read in two places, so
    every noise source of the integrate phase appears in both, each with its
    own transfer to each output. The ratio below is therefore the composite
    the integrator actually accumulates -- not an OTA-only factor applied
    indiscriminately -- and the common 1/C1 input referral cancels in it.

    Measured per corner and per band, because the transfer depends on the
    capacitor ratio, Cp and the OTA gain, all of which move with corner.
    """
    def ratio(key):
        a, q = amp.get(key), ampq.get(key)
        return None if a is None or q is None or a <= 0 else q / a
    bands = {k: ratio(v) for k, v in (
        ("total", "var_total_V2"), ("baseband", "var_baseband_V2"),
        ("audio_band", "var_audio_band_V2"), ("aliased", "var_aliased_V2"),
        ("inband", "inband_V2"))}
    r_bb = bands["baseband"]
    cs, ci = (caps or {}).get("cs_drawn_F"), (caps or {}).get("ci_drawn_F")
    # The hand analysis of issue #140: Cs_tot/(Ci+Cs_tot) in amplitude, with the
    # summing-node parasitic ignored. Carried here so each corner either
    # confirms or refutes it against a measured number.
    hand_v = None if not cs or not ci else (2.0 * cs) / (ci + 2.0 * cs)
    return {
        "power_ratio_by_band": bands,
        "power_ratio_db_by_band": {k: _db(v) for k, v in bands.items()},
        "amplitude_ratio_baseband": None if r_bb is None else math.sqrt(r_bb),
        "hand_analysis_amplitude_ratio": hand_v,
        "hand_analysis_power_ratio_db": None if hand_v is None else _db(hand_v ** 2),
        "hand_analysis_residual_db": (
            None if hand_v is None or r_bb is None
            else _db(r_bb) - _db(hand_v ** 2)),
        "implied_summing_node_cp_F": implied_summing_node_cp_F(
            None if r_bb is None else math.sqrt(r_bb), caps),
        "what_it_is": (
            "measured ratio of the ampq band integral (across Ci, the part that "
            "accumulates) to the amp band integral (at v(vod), which also carries "
            "the non-accumulating summing-node excursion), at THIS corner. Both are "
            "the same static phi2 state and the same 1/C1 input referral, so the "
            "ratio is the transfer issue #140 asks for, with every integrate-phase "
            "noise source carrying its own transfer rather than one OTA factor "
            "applied to all of them. hand_analysis_* is the unsimulated estimate "
            "from the issue body, reported beside it so this corner confirms or "
            "refutes it."),
    }


def derive(sets, caps=None):
    """Join the variant corner sets into one per-corner row with the verdicts."""
    cids = sorted(set().union(*[set(s) for s in sets.values()]))
    out = {}
    for cid in cids:
        row = {v: part(cid, sets[v][cid], v) for v in sets if cid in sets[v]}
        ktc, amp, ampq = row.get("ktc", {}), row.get("amp", {}), row.get("ampq", {})
        ib_k, ib_a, ib_q = (ktc.get("inband_V2"), amp.get("inband_V2"),
                            ampq.get("inband_V2"))
        total = None if ib_k is None or ib_a is None else ib_k + ib_a
        total_q = None if ib_k is None or ib_q is None else ib_k + ib_q
        if amp and ampq:
            row["transfer"] = transfer(amp, ampq, caps)
        fs2 = (C1 / VFS_DIFF_V) ** 2
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
            # --- issue #140: the same budget against the accumulating part ---
            # The budget is NOT adjusted; only the amplifier term is measured
            # where it accumulates instead of at v(vod).
            "total_thermal_inband_accumulated_V2": total_q,
            "total_thermal_accumulated_pass": (None if total_q is None
                                               else total_q <= THERMAL_BUDGET_V2),
            "total_thermal_accumulated_margin_db": (
                None if not total_q else 10.0 * math.log10(THERMAL_BUDGET_V2 / total_q)),
            "accumulated_vs_static_db": (None if not total or not total_q
                                         else _db(total_q / total)),
            # The number to load into model B's ktc_noise_var: switches plus the
            # accumulating amplifier term, as a WHITE per-event variance in FS^2.
            "model_b_equiv_ktc_noise_var_fs2_static": (
                None if total is None else fs2 * total * OSR),
            "model_b_equiv_ktc_noise_var_fs2_accumulated": (
                None if total_q is None else fs2 * total_q * OSR),
        }
        out[cid] = row
    return out


VARIANT_ORDER = ("ktc", "amp", "ampq")


def summarize(rows):
    def worst(path):
        return max([v for r in rows.values() for v in
                    [_dig(r, (x,) + path) for x in VARIANT_ORDER]
                    if v is not None] or [None])
    worst_tail = worst(("upper_edge", "extrapolated_frac_above_F_HI"))

    def binding(path, pick):
        have = [(_dig(r, path), cid) for cid, r in rows.items() if _dig(r, path) is not None]
        if not have:
            return None
        v, cid = pick(have)
        return {"corner_id": cid, "value": v}
    def fails(key):
        return sorted(cid for cid, r in rows.items() if r["verdict"].get(key) is False)

    def span(path):
        """[min, max] of a per-corner value, each with its corner id."""
        return [binding(path, min), binding(path, max)]
    fails_k, fails_t = fails("ktc_pass"), fails("total_thermal_pass")
    fails_q = fails("total_thermal_accumulated_pass")
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
        # --- issue #140: the accumulating treatment, same budget ------------
        "binding_total_thermal_accumulated_corner": binding(
            ("verdict", "total_thermal_inband_accumulated_V2"), max),
        "total_thermal_accumulated_fail_corners": fails_q,
        "total_thermal_accumulated_pass_count": len(rows) - len(fails_q),
        "total_thermal_accumulated_margin_db_range": span(
            ("verdict", "total_thermal_accumulated_margin_db")),
        "accumulated_vs_static_db_range": span(("verdict", "accumulated_vs_static_db")),
        # The measured transfer itself, over the grid: the headline #140 result.
        "transfer_baseband_db_range": span(("transfer", "power_ratio_db_by_band", "baseband")),
        "transfer_aliased_db_range": span(("transfer", "power_ratio_db_by_band", "aliased")),
        "transfer_inband_db_range": span(("transfer", "power_ratio_db_by_band", "inband")),
        "transfer_hand_analysis_residual_db_range": span(
            ("transfer", "hand_analysis_residual_db")),
        "implied_summing_node_cp_F_range": span(("transfer", "implied_summing_node_cp_F")),
        "cs_eff_F_range": [binding(("ktc", "cs_eff_F"), min), binding(("ktc", "cs_eff_F"), max)],
        "worst_klt_vs_ngspice_integral_rel": worst(("klt_vs_ngspice_integral_rel",)),
        "worst_trunc_vs_total_rms_rel": worst(("upper_edge", "trunc_vs_total_rms_rel")),
        # Upper-edge convergence, worst over both variants and all corners: the
        # largest measured share of a part's variance lying above the truncated
        # edge one decade below F_HI, and the largest extrapolated share above
        # F_HI itself.
        "worst_var_above_trunc2_frac": worst(("upper_edge", "var_above_trunc2_frac")),
        "worst_extrapolated_frac_above_F_HI": worst_tail,
        # What that residual tail would be worth on a budget margin, if every
        # bit of it were collected: 10*log10(1 + frac). This is the number that
        # says whether the upper edge can change a verdict.
        "extrapolated_tail_margin_impact_db": (
            None if worst_tail is None else 10.0 * math.log10(1.0 + worst_tail)),
    }


def cs_eff_spread(summary, caps):
    """The measured cs_eff range as a percentage over the drawn Cs.

    A 45-corner spread, not a point value: the parasitic excess moves with
    process and temperature, so quoting one corner's figure would misstate it.
    """
    drawn = (caps or {}).get("cs_drawn_F")
    lo, hi = (summary.get("cs_eff_F_range") or [None, None])[:2]
    if not drawn or not lo or not hi:
        return ("cs_eff_F below is the per-corner effective sampling capacitance the "
                "simulation implies, against the drawn Cs")
    def pct(e):
        return 100.0 * (e["value"] / drawn - 1.0)
    return ("cs_eff_F below runs {:+.1f}% ({}) to {:+.1f}% ({}) against the drawn Cs of "
            "{:.5g} F, a 45-corner spread rather than one figure").format(
                pct(lo), lo["corner_id"], pct(hi), hi["corner_id"], drawn)


# --- per-device / per-mechanism decomposition -------------------------------
# AC 3 of issue #140. The bands are the two in-band integrals the record
# already carries, so the split is directly comparable with var_baseband_V2 /
# var_audio_band_V2; both outputs are taken so the per-device transfer ratio
# (accumulating vs static) is visible device by device, not only in aggregate.
DEV_BLOCKS = (("inband_nqci", "v(nqci)", mk.F_LO, mk.BW_HZ),
              ("inband_vod", "v(vod)", mk.F_LO, mk.BW_HZ),
              ("audio_nqci", "v(nqci)", mk.AUDIO_LO_HZ, mk.BW_HZ),
              ("audio_vod", "v(vod)", mk.AUDIO_LO_HZ, mk.BW_HZ))


def device_deck(pdk_root, process="tt"):
    """The raw-ngspice wrapper around the committed ampq deck.

    Built at run time and never committed: it is the one place this bench needs
    `.lib`/`.control`/`.end` of its own, because `klt sim` owns those in every
    other path and has no measurement form for the per-device vectors
    (2AMLogic/klayout-tools#5553). The circuit is the committed
    `integrator_noise_ampq.cir` verbatim -- same body, same probes, same
    sha256 as the grid run -- so this corner is the grid's tt corner and not a
    second, differently-wired bench.
    """
    lib = pathlib.Path(pdk_root) / "sky130A/libs.tech/ngspice/sky130.lib.spice"
    out = ["* generated by run_noise.py --devices; not committed. See README.md.",
           f'.lib "{lib}" {process}',
           f'.include "{HERE / "integrator_noise_ampq.cir"}"',
           ".control", "set numdgt=12", "set width=250", "op"]
    for tag, node, lo, hi in DEV_BLOCKS:
        out += [f"noise {node} Vinp dec {mk.PTS_PER_DECADE} {lo:g} {hi:g} "
                f"{DEV_PTS_PER_SUMMARY}",
                f"echo @@BLOCK {tag}",
                # `print all` acts on the current plot, which after a noise
                # command is the integrated-noise plot. No setplot: a second
                # analysis makes a second pair of plots, and a literal
                # `setplot noise2` would re-select the FIRST one.
                "print all"]
    out += [".endc", ".end", ""]
    return "\n".join(out)


def parse_device_print(text):
    """Parse `print all` blocks into per-device and per-mechanism variances.

    The vectors hold an RMS in volts, so each is squared before summing; the
    closure check in device_split() is what proves that reading is right.
    """
    blocks, cur = {}, None
    for raw in text.splitlines():
        ln = raw.strip()
        if ln.startswith("@@BLOCK "):
            cur = blocks.setdefault(ln.split()[1],
                                    {"total_V2": None, "devices": {}, "mechanisms": {}})
            continue
        m = re.match(r"^onoise_total(\S*)\s*=\s*([-\d.eE+]+)\s*$", ln)
        if m is None or cur is None:
            continue
        suffix, v2 = m.group(1), float(m.group(2)) ** 2
        if not suffix:
            cur["total_V2"] = v2
            continue
        parts = suffix.lstrip(".").split(".")
        if parts[-1] in DEV_MECHANISMS:
            key = parts[-1]
            cur["mechanisms"][key] = cur["mechanisms"].get(key, 0.0) + v2
        else:
            # `m.<flat.instance.path>.m<model>` -> the instance path alone.
            inst = ".".join(parts[1:-1]) if len(parts) > 2 else ".".join(parts)
            cur["devices"][inst] = cur["devices"].get(inst, 0.0) + v2
    return blocks


def device_block(b):
    """One parsed block as the record carries it, with its closure gate."""
    tot, dev, mech = b["total_V2"], b["devices"], b["mechanisms"]
    sd, sm = sum(dev.values()), sum(mech.values())
    flick = mech.get(DEV_FLICKER, 0.0)
    ranked = sorted(dev.items(), key=lambda kv: -kv[1])
    named, cum = [], 0.0
    for inst, v in ranked:
        if cum >= DEV_COVERAGE * sd:
            break
        cum += v
        named.append({"instance": inst, "var_V2": v, "share": v / sd if sd else None})
    return {
        "total_V2": tot,
        "closure_devices_rel": None if not tot else sd / tot - 1.0,
        "closure_mechanisms_rel": None if not tot else sm / tot - 1.0,
        "closure_tol": DEV_CLOSURE_TOL,
        "flicker_V2": flick,
        "thermal_and_shot_V2": sm - flick,
        "flicker_share": flick / sm if sm else None,
        "thermal_and_shot_share": (sm - flick) / sm if sm else None,
        "by_mechanism_V2": dict(sorted(mech.items(), key=lambda kv: -kv[1])),
        "devices_to_coverage": name_devices(named, device_geometry()),
        "devices_to_coverage_share": cum / sd if sd else None,
        "coverage_target": DEV_COVERAGE,
        "device_count": len(dev),
    }


def device_split(pdk_root, corner="tt/1.800V/27C"):
    """Run the local per-device corner and return the record section, or None."""
    deck = pathlib.Path(tempfile.mkdtemp(prefix="integrator-noise-dev-")) / "devices.cir"
    deck.write_text(device_deck(pdk_root))
    # cwd = HERE so the committed deck's own `../../design/...` includes resolve.
    r = subprocess.run(["ngspice", "-b", str(deck)], capture_output=True, text=True,
                       cwd=str(HERE))
    blocks = parse_device_print(r.stdout)
    if not blocks or any(b["total_V2"] is None for b in blocks.values()):
        print("REFUSE: --devices produced no usable per-device breakdown\n"
              + (r.stdout[-2000:] + r.stderr[-2000:]), file=sys.stderr)
        return None
    out = {tag: device_block(blocks[tag]) for tag, *_ in DEV_BLOCKS if tag in blocks}
    bad = sorted(tag for tag, b in out.items()
                 if b["closure_devices_rel"] is None
                 or abs(b["closure_devices_rel"]) > DEV_CLOSURE_TOL
                 or abs(b["closure_mechanisms_rel"]) > DEV_CLOSURE_TOL)
    if bad:
        print(f"REFUSE: per-device closure failed for {', '.join(bad)}: the summed "
              "per-device variances do not reproduce onoise_total^2, so the "
              "decomposition is not trustworthy and no split is recorded",
              file=sys.stderr)
        return None
    # The per-device accumulating/static ratio, for the devices named in band.
    ratios = []
    nq, vo = out.get("inband_nqci", {}), out.get("inband_vod", {})
    vod_dev = {d["instance"]: d["var_V2"] for d in vo.get("devices_to_coverage", [])}
    for d in nq.get("devices_to_coverage", []):
        a = vod_dev.get(d["instance"])
        if a:
            ratios.append({"instance": d["instance"], "power_ratio": d["var_V2"] / a,
                           "power_ratio_db": _db(d["var_V2"] / a)})
    # AC 1 of issue #140 names the transfer from OTA INPUT-REFERRED noise
    # specifically, so it is reported on its own as well as in the composite:
    # restricted to the OTA's own devices, where the switch part -- which has a
    # different transfer to each output -- cannot dilute it.
    ota = {}
    for band in ("inband", "audio"):
        def ota_var(tag):
            d = (blocks.get(tag) or {}).get("devices") or {}
            return sum(v for k, v in d.items() if ".xota." in f".{k}.")
        q, v = ota_var(f"{band}_nqci"), ota_var(f"{band}_vod")
        tot_q = (blocks.get(f"{band}_nqci") or {}).get("total_V2")
        # `or 0.0`, not a .get default: drawn_caps() yields an explicit None
        # if the netlist parse finds no Csi, and 2.0 * None raises.
        cs_tot = 2.0 * ((drawn_caps() or {}).get("cs_drawn_F") or 0.0)
        cp = implied_summing_node_cp_F(math.sqrt(q / v) if v else None, drawn_caps())
        ota[band] = {
            "ota_var_nqci_V2": q,
            "ota_var_vod_V2": v,
            "ota_share_of_total_nqci": (q / tot_q) if tot_q else None,
            "power_ratio": (q / v) if v else None,
            "power_ratio_db": _db(q / v) if v else None,
            "amplitude_ratio": math.sqrt(q / v) if v else None,
            "implied_summing_node_cp_F": cp,
            # The one residual bias of the static across-Ci read, stated rather
            # than buried: for OTA-input noise the TRUE per-cycle increment is
            # Cs_tot/Ci * Vn, while a static read across Ci gives
            # (Cs_tot+Cp)/Ci * Vn. So this read OVER-states the accumulating
            # part by (1 + Cp/Cs_tot) in amplitude -- the recorded ampq numbers
            # are conservative by this much, never optimistic.
            "static_across_ci_over_counts_by_db": (
                None if cp is None or not cs_tot else _db((1.0 + cp / cs_tot) ** 2)),
            "over_count_note": (
                "the static across-Ci read includes Cp's share of the charge on Ci, "
                "which does NOT change across a cycle (the OTA holds the summing node "
                "at its own input offset in both phases), so it drops out of the true "
                "per-cycle increment but not out of this measurement. Derived from the "
                "implied Cp, so indicative, and it makes the recorded accumulating "
                "numbers conservative, not optimistic."),
        }
    return {
        "corner_id": corner,
        "source": "T",
        "ota_input_referred_transfer": ota,
        "ota_input_referred_transfer_note": (
            "AC 1 of issue #140: the transfer from OTA input-referred noise to the "
            "accumulated per-cycle increment, isolated from the composite by summing "
            "only the OTA's own devices at each output. The composite the record "
            "actually applies per corner is corners[*].transfer; this block is what "
            "says how much of that composite is the OTA transfer and how much is the "
            "switches', and it is the one that the issue's hand analysis predicts."),
        "result_kind": ("simulated (one local ngspice corner, transistor-level; a raw "
                        "`ngspice -b` because klt sim has no measurement form for the "
                        "per-device vectors). A simulated number is never called measured."),
        "method": ("ngspice emits a per-device, per-mechanism breakdown of the integrated "
                   "noise only when the noise statement carries a pts_per_summary "
                   f"argument ({DEV_PTS_PER_SUMMARY}, above the point count, so one "
                   "summary). The vectors hold each contribution as an RMS in VOLTS, so "
                   "they are squared before summing; closure_* below is the proof of that "
                   "reading -- the summed per-device and per-mechanism variances must "
                   f"reproduce onoise_total^2 to {DEV_CLOSURE_TOL:g}, and the run refuses "
                   "to record a split that does not. Summing the vectors as if they were "
                   "variances over-counts by about 4e4 on this block."),
        "deck": ("the committed integrator_noise_ampq.cir verbatim, wrapped at run time "
                 "in the .lib/.control/.end a raw ngspice run needs; same circuit, same "
                 "probes and same deck_sha256 as the grid run"),
        "one_corner_only": ("the DR-002 anchor tt/1.800 V/27 C, which is what AC 3 of "
                            "issue #140 asks for at minimum. The 45-corner grid carries "
                            "the TRANSFER at every corner; only this decomposition is "
                            "single-corner, and it is a mechanism attribution, not a "
                            "budget number."),
        "mechanism_note": ("`1overf` is flicker; every other mechanism (id, rd, rs, rg, "
                           "rb*) is thermal, and ig* is gate-leakage shot noise, zero on "
                           "this block. So thermal_and_shot_V2 is the thermal share spec "
                           "5.3 actually allocates."),
        "blocks": out,
        "accumulating_vs_static_power_ratio_db_by_device": ratios,
        "friction": "2AMLogic/klayout-tools#5553 (no klt measurement form for this)",
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
    ap.add_argument("--devices", action="store_true",
                    help="print the per-device / per-mechanism in-band split from one "
                         "local tt/1.800V/27C corner and exit (no grid, no record). "
                         "--record computes the same section and refuses without it.")
    ap.add_argument("--record", action="store_true",
                    help="write record.json (refuses to overwrite: records are append-only)")
    ap.add_argument("--record-name", default="record.json",
                    help="record file name, for a re-run after a sizing change (new file)")
    ap.add_argument("--hosts", type=int, metavar="N",
                    help="shard the submission across N fleet instances "
                         "(klt sim --hosts). The fleet kills a job still running "
                         "at its whole-job ceiling and reports every unit "
                         "batch_job_timeout, and this grid's conservative serial "
                         "bound exceeds that ceiling (the receipt's job_ceiling "
                         "warns, with a recommended_hosts), so pass this if a "
                         "re-run's corners are slower than the ones recorded. "
                         "Sharding is a submission choice: it does not change the "
                         "request file or its sha256.")
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
    caps = drawn_caps()
    if a.devices:
        dev = device_split(root)
        if dev is None:
            return 1
        print(json.dumps(dev, indent=2))
        return 0
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="integrator-noise-"))
    sets, reps = {}, {}
    for v in mk.VARIANTS:
        res = run_klt(HERE / f"request_{v}.json", a.probe, tmp, v,
                      HERE / f"probe_request_{v}.json",
                      artifacts_dir=None if a.probe else ARTIFACTS, keys=KEYS,
                      hosts=None if a.probe else a.hosts)
        if res is None:
            print(f"REFUSE: variant {v} returned no usable report", file=sys.stderr)
            return 1
        reps[v], sets[v] = res
    rows = derive(sets, caps)
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
    cs_spread = cs_eff_spread(summary, caps)
    # AC 3 of issue #140: the record must carry the flicker/thermal and
    # per-device split, so a record is not written without it.
    devices = device_split(root)
    if devices is None:
        print("REFUSE: no per-device split, so no record is written", file=sys.stderr)
        return 1
    rec = {
        "fixture": ("First-integrator thermal-noise bench (issue #126): design/integrator's full "
                    "cell held in one clock phase per variant, small-signal .noise over "
                    f"{mk.F_LO:g} Hz - {mk.F_HI:g} Hz. ktc = the four sampling capacitors in "
                    "phi1; amp = the OTA with its phi2 switches, at the differential output; "
                    "ampq = the same integrate phase read across Ci, i.e. the part that "
                    "accumulates (issue #140), plus a one-corner per-device split."),
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
                       f"the drawn value alone would miss ({cs_spread}, for exactly that "
                       "reason)."),
            "why_three_requests": ("a small-signal .noise run needs a static clock state and "
                                   "one corner runs one analysis with one output, so the two "
                                   "halves of spec 5.3's thermal share are two requests over "
                                   "the same 45-point grid (as sim/integrator-settling does "
                                   "with int1/int2), and issue #140's accumulating read of the "
                                   "integrate phase is a third over that same grid"),
            "accumulating_vs_static": (
                "issue #140. `amp` reads v(vod) in the static phi2 state and refers it to the "
                "integrator input by 1/C1. That is right for noise that is sampled "
                "independently each cycle, but v(vod) also carries the summing-node excursion, "
                "which the next phi1 reset discards: what accumulates is the charge left on Ci. "
                "`ampq` is the SAME state and the SAME 1/C1 referral read across Ci instead, so "
                "it measures the per-cycle output increment directly, and the per-corner ratio "
                "of the two band integrals (corners[*].transfer) is the transfer #140 asks for "
                "-- measured, at every corner, with every integrate-phase noise source carrying "
                "its own transfer rather than one OTA-derived factor applied to all of them. "
                "Why this is the accumulating quantity: with the summing node at vcm+Vn in phi2 "
                "and the Cs top plates reset to vcm in phi1, charge conservation on the summing "
                "node gives a per-cycle state increment of (Csi+Csr)/Ci * Vn, independent of "
                "the summing-node parasitic Cp, while the static v(vod) noise gain is "
                "1 + (Csi+Csr+Cp)/Ci. The ratio is therefore about 1/2 in amplitude on this "
                "sizing, where Ci is drawn equal to Csi+Csr. BOTH the baseband and the aliased "
                "part are re-referred this way, so neither keeps the old 1/C1-at-v(vod) "
                "treatment -- see corners[*].transfer.power_ratio_db_by_band, which reports "
                "them separately because the transfer is not the same in the two bands."),
            "variants": {v: {"what": d["what"], "referred_to": d["referred_to"],
                             "clock_state": d["clocks"], "output": d["output"]}
                         for v, d in mk.VARIANTS.items()},
            "integration_band_Hz": [mk.F_LO, mk.F_HI],
            "lower_edge": (f"every band integral starts at {mk.F_LO:g} Hz. Flicker noise "
                           "diverges logarithmically downward, so this edge is a choice, not a "
                           "property of the circuit: var_audio_band_V2 repeats the baseband "
                           f"integral from {mk.AUDIO_LO_HZ:g} Hz so the sensitivity is visible "
                           "rather than hidden."),
            # Two separate claims, each with the evidence that actually bears on
            # it. Conflating them would matter: 99% of ktc's inband_V2 is the
            # aliased share of the full-band integral, so the budget verdict
            # rests on the upper edge, not on the integration scheme.
            "convergence": CONVERGENCE,
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
            "flicker_caveat": ("5.3 allocates a THERMAL share, and the per-corner amplifier "
                               "numbers here are thermal PLUS flicker, so the comparison is "
                               "conservative for the amplifier and exact for the switches. "
                               "issue #140 now MEASURES that split, at one corner: see "
                               "device_split.blocks.inband_nqci.flicker_share, which is the "
                               "fraction of the accumulating in-band amplifier noise that is "
                               "1/f rather than thermal. The thermal-only part is "
                               "thermal_and_shot_V2. 5.3 still carries no 1/f allocation at "
                               "all, which remains a finding (#138 step 2 / #142), not a bench "
                               "defect -- this bench reports against the ratified line "
                               "unchanged and does not relax it."),
            "reported_twice": ("both budgets are reported against the pre-#140 static "
                               "treatment (total_thermal_*) AND the #140 accumulating one "
                               "(total_thermal_accumulated_*), with the SAME budget values, so "
                               "the effect of the corrected referral on the verdict is visible "
                               "rather than substituted silently."),
        },
        "leaves_out": [
            "flicker/thermal separation ACROSS THE GRID. issue #140 adds the split, but "
            "from one local corner (device_split, tt/1.800V/27C): klt sim still has no "
            "measurement form for ngspice's per-device, per-mechanism vectors, so the "
            "45-corner requests cannot carry it. Filed under the friction protocol as "
            "2AMLogic/klayout-tools#5553; the per-corner numbers in `corners` are "
            "therefore still thermal PLUS flicker.",
            "correlation of the sampled noise between consecutive clocks, BEYOND the "
            "accumulating referral. issue #140 removes the part of the over-count that "
            "came from referring the non-accumulating summing-node excursion as if it "
            "accumulated (see method.accumulating_vs_static), and that correction is "
            "measured per corner. What is still left out is the correlation BETWEEN "
            "consecutive accumulated increments: ampq's increments are still treated as "
            "i.i.d. per event, so the in-band effect of the amplifier's 1/f is still "
            "over-counted, and any correlated-double-sampling benefit is still ignored. "
            "This bench's phi1 reset is to vcm, not a CDS reset, so there is no CDS "
            "benefit to claim here.",
            "the summing-node parasitic Cp is not measured. transfer."
            "implied_summing_node_cp_F inverts the measured in-band amplitude ratio for "
            "it, which is a derived indicative value, not an extraction: the ratio it "
            "inverts is the composite over every phi2 noise source, and it is quotable "
            "in band only because the device split shows the OTA's own devices carry "
            "essentially all of the in-band noise there. It is not quotable for the "
            "aliased part, where the phi2 switches do matter.",
            "the last Cp term of the accumulating read, which makes these numbers "
            "CONSERVATIVE rather than optimistic. For OTA input-referred noise the true "
            "per-cycle increment is (Csi+Csr)/Ci * Vn, while a STATIC read across Ci "
            "gives (Csi+Csr+Cp)/Ci * Vn: Cp's charge on Ci does not change across a "
            "cycle, so it leaves the increment but not this measurement. The size of "
            "that residual is reported as device_split.ota_input_referred_transfer."
            "inband.static_across_ci_over_counts_by_db, derived from the implied Cp. "
            "Removing it would IMPROVE the reported margin, so it is left in rather "
            "than corrected out on a derived number.",
            "the large-signal phi1 hold error of issue #147. The transfer measured here "
            "is small-signal about the operating point with no large differential input, "
            "so a large-signal Sci hold error does not enter it. #147's Sci condition "
            "(Vgs = Vdda - vcm) is worst at low Vdda and cold, so if a per-corner "
            "transfer looks like an outlier at the 1.620 V/-40 C corners, #147 is the "
            "known candidate rather than a new finding.",
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
        "drawn_capacitors": caps,
        "device_split": devices,
        "issue": ("#140: sampled-data-correct referral of the integrate-phase noise "
                  "(the `ampq` variant and corners[*].transfer) and a per-device "
                  "flicker/thermal split (device_split). Extends the issue #126 bench; "
                  "record.json is untouched."),
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
    # The accumulating treatment is this bench's verdict after issue #140; the
    # static one stays in the record beside it, reported against the same
    # budget, but it is not what the exit status asserts.
    return 0 if not summary["total_thermal_accumulated_fail_corners"] else 1


if __name__ == "__main__":
    sys.exit(main())

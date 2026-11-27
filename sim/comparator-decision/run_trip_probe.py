#!/usr/bin/env python3
"""Issue #150 single-corner diagnosis of the unbracketed trip corner.

Runs the committed `trip` deck at ONE corner (default sf / -40 C / 1.620 V,
the corner `record.json` names in `corners_without_a_bracketed_trip`),
locally, and captures the per-clock evidence the 45-corner run does not
keep: the held v(o1d), v(o2d), dd and cmpd at every clock of the staircase,
the flip grading re-derived exactly as `make_request.trip_measurements()`
defines it, and a cross-check against `record.json`'s own numbers at the
corner. What the record leaves unestablished -- which side of the swept
window the trip lies on, and whether the staircase itself is well-formed
there -- is answered by the per-clock table, not by inference.

Simulated, one corner, local -- not a record and not a performance claim.
The 45-corner evidence is record.json; see README.md and
spec/decisions/DR-007-comparator-trip-bracketing.md.

Run: python3 run_trip_probe.py --write
"""
import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import make_request as MR  # noqa: E402
from settling_common import ngspice_version, pdk_stamp  # noqa: E402

DECK = HERE / "comparator_decision_trip.cir"
OUT_DEFAULT = "trip-probe-i150.json"
CLOCKS = range(MR.TRIP_LAST_CLK + 1)          # 0 .. 23, the whole staircase

# The bench's own grading windows (make_request.trip_measurements), so the
# probe's flip rows are the same measurement the record grades, not a second
# opinion of it.
W_LEAD = MR.W_LEAD
UP_A, UP_B = MR.tedge(MR.TRIP_UP_FIRST) - W_LEAD, MR.tedge(MR.TRIP_UP_LAST + 1) - W_LEAD
DN_A, DN_B = UP_B, MR.tedge(MR.TRIP_DN_LAST + 1) - W_LEAD
UP_SENT, DN_SENT = MR.tedge(MR.TRIP_UP_LAST), MR.tedge(MR.TRIP_DN_LAST)
DIAGNOSTIC_PATTERNS = ("singular matrix", "nonconvergence", "Timestep too small")

# Cross-host reproduction tolerance for the record cross-check: the committed
# grid ran on the batch fleet, the probe runs here; same engine major version,
# so agreement to a part in 1e6 of a millivolt-scale number is the honest bar.
MATCH_RTOL = 1e-6


def win(a, b):
    return f"(time ge {a:.9g})*(time le {b:.9g})"


def held(sig, a, b):
    w = win(a, b)
    return f"mean({sig}*({w}))/mean({w})"


def control_block(t_end):
    """Save the decision-path nodes and derive one held value per clock.

    Window and formula per clock are exactly the bench's `held()` on W_HOLD,
    so a held probe value is directly comparable with the record's numbers.
    """
    L = [".control",
         "set numdgt=12",
         "set measureprec=12",
         "save v(o2d) v(o1d) v(dd) v(cmpd) v(vdda)",
         f"tran 0.05n {t_end:.9g} 0 5n"]
    names = []
    for k in CLOCKS:
        a, b = MR.tedge(k) + MR.W_HOLD[0], MR.tedge(k) + MR.W_HOLD[1]
        for tag, sig in (("o1d", "v(o1d)"), ("o2d", "v(o2d)"),
                         ("dd", "v(dd)"), ("cmpd", "v(cmpd)")):
            L.append(f"let {tag}_{k} = {held(sig, a, b)}")
            names.append(f"{tag}_{k}")
    # the bench's own flip grading, verbatim definitions
    for tag, (a, b), sent in (("up", (UP_A, UP_B), UP_SENT),
                              ("dn", (DN_A, DN_B), DN_SENT)):
        m = (f"({win(a, b)})*(v(dd) ge 0.5*v(vdda))") if tag == "up" \
            else (f"({win(a, b)})*(v(dd) le -0.5*v(vdda))")
        L += [f"let m_{tag} = {m}",
              f"let flip_{tag} = vecmax(m_{tag})",
              f"let tflip_{tag} = vecmin(time*m_{tag} + {sent:.9g}*(1-m_{tag}))",
              f"let k_{tag} = floor((tflip_{tag} - {MR.T0:.9g})/{MR.TCLK:.9g})"]
        names += [f"flip_{tag}", f"tflip_{tag}", f"k_{tag}"]
    for n in names:                       # one scalar per print: full precision
        L.append(f"print {n}")
    L.append(".endc")
    return "\n".join(L)


def build_deck(corner, temp, vdda, t_end, pdk_lib):
    """The committed trip deck at one corner, plus the standalone plumbing.

    klt sim owns .lib/.control/.end for the grid run; this adds them back for
    a bare ngspice, sets the corner, and substitutes Vdda. Anything else
    staying byte-identical to the committed deck is the point: the probe then
    runs exactly the deck record.json was taken on.
    """
    body = DECK.read_text()
    marker = "Vdda vdda 0 1.8"
    if body.count(marker) != 1:
        sys.exit(f"REFUSE: expected exactly one '{marker}' in {DECK.name}")
    body = body.replace(marker, f"Vdda vdda 0 {vdda:.9g}")
    lib = f'.lib "{pdk_lib}" {corner}\n.temp {temp:.6g}\n'
    return lib + body + "\n" + control_block(t_end) + "\n.end\n"


def run(deck_path, ng_dir):
    r = subprocess.run(["ngspice", "-b", str(deck_path)],
                       capture_output=True, text=True, cwd=HERE)
    log = r.stdout + r.stderr
    vals = {}
    for k, x in re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-+0-9.eE]+)\s*$", log, re.M):
        vals[k] = float(x)
    missing = [n for n in ("o2d_4", "o2d_12", "dd_4", "cmpd_4", "flip_up", "k_dn")
               if n not in vals]
    if r.returncode or missing:
        print(log[-4000:], file=sys.stderr)
        sys.exit(f"REFUSE: ngspice did not produce the probe scalars "
                 f"(missing: {', '.join(missing) or 'none'}, rc={r.returncode})")
    return vals, log


def netlist_hashes():
    names = ("design/modulator/modulator.spice",
             "design/modulator/comparator/comparator.spice",
             "design/modulator/comparator/comparator_core.spice",
             "design/ota/ota_fd.spice")
    return {n: hashlib.sha256((REPO / n).read_bytes()).hexdigest() for n in names}


def per_clock_table(vals, vdda):
    """One row per clock: measured held values beside the designed schedule."""
    _card, sched = MR.trip_input_pwl()
    designed_seen = {n: (sched[n - 1][3] if n >= 1 else 0.0) for n in CLOCKS}
    rows = []
    for k in CLOCKS:
        dd, cmpd = vals[f"dd_{k}"], vals[f"cmpd_{k}"]
        rows.append({
            "clock": k,
            "t_edge_s": MR.tedge(k),
            "designed_o1d_V": sched[k][2],
            "designed_o2d_seen_V": designed_seen[k],
            "o1d_held_V": vals[f"o1d_{k}"],
            "o2d_held_V": vals[f"o2d_{k}"],
            "dd_held_V": dd,
            "cmpd_held_V": cmpd,
            "decision_y": 1 if dd >= 0.5 * vdda else (-1 if dd <= -0.5 * vdda else 0),
            "comparator_resolved_y": 1 if cmpd >= 0.5 * vdda
                                     else (-1 if cmpd <= -0.5 * vdda else 0),
        })
    return rows


def probe_answers(rows, vals):
    """What the record could not say, read off the per-clock table.

    Data, not interpretation: every field here is a restatement of rows or
    flip values above. Which side of the window the trip lies on follows from
    `threshold_above_every_presented_value`: no graded clock presented a
    non-negative differential and no resolution to y = +1 happened anywhere.
    """
    up = [r for r in rows if MR.TRIP_UP_FIRST <= r["clock"] <= MR.TRIP_UP_LAST]
    dn = [r for r in rows if MR.TRIP_DN_FIRST <= r["clock"] <= MR.TRIP_DN_LAST]
    steps_dn = [dn[i + 1]["o2d_held_V"] - dn[i]["o2d_held_V"]
                for i in range(len(dn) - 1)]
    dd_high_up = [r["clock"] for r in up if r["decision_y"] == 1]
    cmpd_high = [r["clock"] for r in rows if r["comparator_resolved_y"] == 1]
    o1d_err = [r["o1d_held_V"] - r["designed_o1d_V"] for r in rows]
    return {
        "staircase_foot_V": up[0]["o2d_held_V"],
        "staircase_top_V": up[-1]["o2d_held_V"],
        "between_sweeps_V": rows[MR.TRIP_UP_LAST + 1]["o2d_held_V"],
        "dn_foot_V": dn[0]["o2d_held_V"],
        "dn_top_V": dn[-1]["o2d_held_V"],
        "decision_at_foot_y": up[0]["decision_y"],
        "dd_high_clocks_up_sweep": dd_high_up,
        "cmpd_high_clocks_any": cmpd_high,   # y=+1 resolutions anywhere in the run
        "threshold_above_every_presented_value":
            not cmpd_high and all(r["o2d_held_V"] < 0.0 for r in up),
        "max_o2d_presented_V": max(r["o2d_held_V"] for r in up),
        "falling_half_steps_V": steps_dn,
        "falling_half_monotonic_down": all(s < 0.0 for s in steps_dn),
        "falling_half_span_V": dn[-1]["o2d_held_V"] - dn[0]["o2d_held_V"],
        "o1d_held_minus_designed_V": o1d_err,
    }


def cross_check(rows, vals, record):
    """The probe against record.json's own numbers at this corner.

    The record values marked (table) are re-derived from the probe's
    per-clock table with the bench's own window arithmetic; the rest are the
    probe's ngspice-computed grading rows. `match` is relative, except exact
    for the 0/1 flags.
    """
    cid = "sf/1.620V/-40C"
    tr = record["variants"]["trip"]["corners"][cid]
    held = {r["clock"]: r["o2d_held_V"] for r in rows}
    k_up, k_dn = int(vals["k_up"]), int(vals["k_dn"])

    def t_held(k):
        return held.get(k)

    table = {
        "v_trip_up": t_held(k_up),
        "v_trip_dn": t_held(k_dn),
        "v_prev_up": t_held(k_up - 1),
        "v_prev_dn": t_held(k_dn - 1),
        "step_up": None if None in (t_held(k_up), t_held(k_up - 1))
                   else t_held(k_up) - t_held(k_up - 1),
        "step_dn": None if None in (t_held(k_dn), t_held(k_dn - 1))
                   else t_held(k_dn) - t_held(k_dn - 1),
        "span_up": None if None in (t_held(MR.TRIP_UP_LAST), t_held(MR.TRIP_UP_FIRST))
                   else t_held(MR.TRIP_UP_LAST) - t_held(MR.TRIP_UP_FIRST),
        "span_dn": None if None in (t_held(MR.TRIP_DN_LAST), t_held(MR.TRIP_DN_FIRST))
                   else t_held(MR.TRIP_DN_LAST) - t_held(MR.TRIP_DN_FIRST),
    }
    direct = {k: vals[k] for k in ("flip_up", "flip_dn", "tflip_up", "tflip_dn",
                                   "k_up", "k_dn")}
    out = {}
    for k, rv in tr.items():
        if k not in table and k not in direct:
            continue
        pv = direct.get(k, table.get(k))
        if pv is None or rv is None:
            ok, delta = False, None
        else:
            delta = pv - rv
            ok = (pv == rv) if k in ("flip_up", "flip_dn", "k_up", "k_dn") \
                else abs(delta) <= MATCH_RTOL * max(abs(rv), 1e-15)
        out[k] = {"record": rv, "probe": pv, "delta": delta, "match": ok,
                  "via": "grading" if k in direct else "per_clock_table"}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--corner", default="sf")
    ap.add_argument("--temp", type=float, default=-40)
    ap.add_argument("--vdda", type=float, default=1.62)
    ap.add_argument("--t-end", type=float, default=None,
                    help="override the transient length (debug smoke only; "
                         "the committed evidence uses the bench's own T_END)")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--write", action="store_true",
                    help="write the result file (refuses to overwrite: append-only)")
    a = ap.parse_args()

    pin = json.load(open(REPO / "sim/pdk.json"))
    root, stamp = pdk_stamp(pin["variant"], a.pdk_root)
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'",
              file=sys.stderr)
        return 2
    out = HERE / a.out
    if a.write and out.exists():
        print(f"REFUSE: {out.name} exists; results are append-only (use --out)",
              file=sys.stderr)
        return 2
    ng = root / pin["variant"] / "libs.tech/ngspice"
    t_end = a.t_end if a.t_end is not None else MR.T_END["trip"]
    cid = f"{a.corner}/{a.vdda:.3f}V/{a.temp:.0f}C"

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="trip-probe-"))
    deck = tmp / f"trip-probe-{a.corner}.cir"
    deck.write_text(build_deck(a.corner, a.temp, a.vdda, t_end, ng / "sky130.lib.spice"))
    vals, log = run(deck, ng)

    record = json.loads((HERE / "record.json").read_text())
    rows = per_clock_table(vals, a.vdda)
    res = {
        "fixture": ("Comparator decision trip bench, ONE corner, with per-clock "
                    "waveform evidence (issue #150)"),
        "result_kind": ("simulated (ngspice, the committed trip deck's own "
                        "netlists: design/modulator + design/ota/ota_fd + the "
                        "vendored comparator); one corner, run locally; not "
                        "measured, not a record"),
        "purpose": ("settle, by measurement, which side of the swept window the "
                    "trip lies on at the corner record.json names in "
                    "corners_without_a_bracketed_trip, and whether the staircase "
                    "there is well-formed (per-clock o1d/o2d/dd/cmpd)"),
        "corner": {"process": a.corner, "temperature_C": a.temp, "vdda_V": a.vdda,
                   "corner_id": cid},
        "conditions": {"vcm_V": 0.9, "vrefp_V": 0.9, "vrefn_V": 0.9,
                       "fs_Hz": MR.FS_HZ, "t_end_s": t_end,
                       "hold_window_after_edge_ns": [MR.W_HOLD[0] * 1e9,
                                                     MR.W_HOLD[1] * 1e9],
                       "graded_clocks": {"up": [MR.TRIP_UP_FIRST, MR.TRIP_UP_LAST],
                                         "dn": [MR.TRIP_DN_FIRST, MR.TRIP_DN_LAST]}},
        "pass_criterion": ("none: a diagnostic probe. The only gate is the "
                           "cross_check below -- the probe must reproduce "
                           "record.json's own numbers at this corner."),
        "pdk_sources_stamp": stamp,
        "pdk_pin": {"file": "sim/pdk.json",
                    "open_pdks_revision": pin["open_pdks_revision"]},
        "ngspice": ngspice_version(),
        "deck_sha256": hashlib.sha256(DECK.read_bytes()).hexdigest(),
        "netlist_sha256": netlist_hashes(),
        "diagnostics_seen": [p for p in DIAGNOSTIC_PATTERNS if p.lower() in log.lower()],
        "per_clock": rows,
        "probe_answers": probe_answers(rows, vals),
        "cross_check": cross_check(rows, vals, record),
    }
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

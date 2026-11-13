#!/usr/bin/env python3
"""OTA open-loop DC-gain runner (simulated, transistor-level). See README.md.

Default: submit request.json (45-point DR-002 grid) through `klt sim`, which
sends it to the batch fleet; never falls back to a local grid.
--probe: one tt/27C/1.8V corner, run locally (bench debugging, no record).
"""
import argparse, json, math, pathlib, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from settling_common import (grid_complete, measurements_present,  # noqa: E402
                             pdk_stamp, run_klt, sha256)

sys.path.insert(0, str(HERE))
import make_request as mk  # noqa: E402

ARTIFACTS = HERE / ".artifacts"   # raw klt report / batch receipt, gitignored

KEYS = ("vid_mag", "a0_lo", "a0_min", "a0_max", "a0_flat_rel", "acm_max", "acm_rel")

# The comparison column: the finite-gain leak of sim/integrator-ci's post_dac
# variant over the same 45 points. Its own README calls it a cross-check and
# not a DC-gain extraction -- the slow/cold outliers are contaminated by the
# incomplete input sampling of #106 -- so it is carried for comparison only
# and a disagreement there is reported, never reconciled.
CI_RECORD = REPO / "sim/integrator-ci/record.json"


def db(a):
    """Linear V/V -> dB, or None."""
    return None if a is None or a <= 0 else 20.0 * math.log10(a)


def ci_comparison(path=CI_RECORD):
    """{corner_id: implied_dc_gain_db} from the integrator-ci record, or {}."""
    try:
        per = json.loads(pathlib.Path(path).read_text())["derived"]["dac_crosscheck"]["per_corner"]
    except (OSError, ValueError, KeyError):
        return {}
    return {cid: row.get("implied_dc_gain_db") for cid, row in per.items()
            if row.get("implied_dc_gain_db") is not None}


def derive(corners, ci=None):
    """Per-corner gain rows: V/V, dB, the validity gates, the comparison column."""
    ci = {} if ci is None else ci
    out = {}
    for cid, c in sorted(corners.items()):
        a0 = c.get("a0_lo")
        row = {"status": c["status"], "dc_gain_v_per_v": a0, "dc_gain_db": db(a0),
               "a0_band_min_v_per_v": c.get("a0_min"), "a0_band_max_v_per_v": c.get("a0_max"),
               "band_flatness_rel": c.get("a0_flat_rel"), "vid_mag_V": c.get("vid_mag"),
               "cm_conversion_rel": c.get("acm_rel"),
               "diagnostics": c.get("diagnostics", [])}
        ref = ci.get(cid)
        row["integrator_ci_implied_db"] = ref
        row["integrator_ci_delta_db"] = (None if ref is None or row["dc_gain_db"] is None
                                         else row["dc_gain_db"] - ref)
        out[cid] = row
    return out


def binding(rows):
    """The lowest-gain corner: (corner_id, V/V, dB). None if nothing measured."""
    have = [(r["dc_gain_v_per_v"], cid) for cid, r in rows.items()
            if r["dc_gain_v_per_v"] is not None]
    if not have:
        return None
    a0, cid = min(have)
    return {"corner_id": cid, "dc_gain_v_per_v": a0, "dc_gain_db": db(a0)}


def summarize(rows):
    gains = [r["dc_gain_v_per_v"] for r in rows.values() if r["dc_gain_v_per_v"] is not None]
    deltas = [abs(r["integrator_ci_delta_db"]) for r in rows.values()
              if r.get("integrator_ci_delta_db") is not None]
    flat = [r["band_flatness_rel"] for r in rows.values() if r["band_flatness_rel"] is not None]
    return {
        "corner_count": len(rows),
        "pass": sum(1 for r in rows.values() if r["status"] == "pass"),
        "fail": sum(1 for r in rows.values() if r["status"] != "pass"),
        "binding_corner": binding(rows),
        "dc_gain_db_range": [db(min(gains)), db(max(gains))] if gains else None,
        "worst_band_flatness_rel": max(flat) if flat else None,
        "worst_integrator_ci_delta_db": max(deltas) if deltas else None,
    }


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
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ota-gain-"))
    res = run_klt(HERE / "request.json", a.probe, tmp, "gain",
                  HERE / "probe_request_gain.json",
                  artifacts_dir=None if a.probe else ARTIFACTS, keys=KEYS)
    if res is None:
        return 1
    rep, corners = res
    rows = derive(corners, ci_comparison())
    summary = summarize(rows)
    print(json.dumps({"status": rep.get("status"), **summary}, indent=2))
    if a.probe:
        print(json.dumps(rows, indent=2))
        return 0
    # Both record-validity gates, on `a0_lo`: 45 points returned, and every
    # one of them actually produced a gain (a dead fleet job returns an entry
    # per point with no values, which the count gate alone would accept).
    if not grid_complete([corners]) or not measurements_present([corners], key="a0_lo"):
        return 1
    env = rep.get("environment", {})
    rec = {
        "fixture": ("OTA open-loop DC-gain bench (issue #126): design/ota/ota_fd at the bias it "
                    "has in the integrator's integrate phase (inputs at VCM = 0.9 V, outputs at "
                    "the CMFB common mode, ibias 5 uA), differential gain read at the bottom of "
                    "an ac sweep with the feedback loop open at ac and closed at dc"),
        "source": "T",
        "result_kind": ("simulated (ngspice, transistor-level netlist of design/ota/ota_fd; not "
                        "the behavioural model). A simulated number is never called measured."),
        "model_b_parameter": "dc_gain (sim/bmodel/model.py), integrator amplifier DC gain A in V/V",
        "method": {
            "analysis": json.load(open(HERE / "request.json"))["analysis"],
            "why_ac_not_dc": ("the open-loop operating point of a fully differential OTA is not "
                              "stable, so there is no dc sweep to read; DR-001 item 2 names an ac "
                              "response as the finite-gain method"),
            "dc_asymptote": (f"reported at {mk.F_LO:g} Hz, the bottom of the sweep; the "
                             f"{mk.F_LO:g}-{mk.F_HI:g} Hz band is gated flat to "
                             f"{mk.FLAT_MAX:g} relative per corner, which is what makes the "
                             "reading a dc gain and not a band value"),
            "loop_opening": ("bench-only 1e12 H inductors carry the dc feedback (a short at dc, "
                             "6.3e12 ohm at 1 Hz against the ~1 Mohm output resistance) and 1 F "
                             "capacitors carry the ac drive (open at dc, 0.16 ohm at 1 Hz)"),
            "load": ("1.8 pF per side, CL,eff inside the integrator per design/ota/SIZING.md. "
                     "The dc gain does not depend on it; it is for comparability only."),
            "leaves_out": ("gain-bandwidth, phase margin and the CMFB loop response (the "
                           "settling bench and design/ota/SIZING.md own those); mismatch (this "
                           "is the nominal grid, no Monte Carlo); and layout parasitics (DR-001 "
                           "item 4, post-layout)"),
        },
        "no_spec_budget": ("spec/modulator-adc.md has no ratified DC-gain row: 5.3 budgets noise, "
                           "not gain, so this record reports the per-corner value and its binding "
                           "corner and makes no pass/fail against the spec. `pass` below is the "
                           "reference-validity verdict of the three gates in make_request.py "
                           "(drive magnitude, band flatness, common-mode rejection), not a spec "
                           "verdict. design/ota/SIZING.md: whether ~55 dB is enough against the "
                           "80 dB target is a T-tier check, not decided there; issue #128 consumes "
                           "these values into model B and answers it."),
        "conditions": {"vcm_V": 0.9, "ibias_uA": 5, "load_pF_per_side": 1.8,
                       "ac_drive_V_differential": 1.0,
                       "corner_set": "DR-002 full grid, 5 process x 3 T x 3 Vdda"},
        "pdk_sources_stamp": stamp,
        "pdk_pin": {"file": "sim/pdk.json", "open_pdks_revision": pin["open_pdks_revision"]},
        "ngspice": env.get("engine_version", "unknown"),
        "klt": subprocess.run(["klt", "--version"], capture_output=True, text=True).stdout.strip(),
        "engine_host": env.get("engine_host"),
        "remote": env.get("remote"),
        "batch_receipt": rep.get("batch_receipt"),
        "request_sha256": sha256(HERE / "request.json"),
        "deck_sha256": sha256(HERE / "ota_gain.cir"),
        "ota_netlist_sha256": sha256(REPO / "design/ota/ota_fd.spice"),
        "comparison_column": {
            "from": "sim/integrator-ci/record.json derived.dac_crosscheck.per_corner",
            "caveat": ("the finite-gain leak of the post_dac variant, which that bench's README "
                       "calls a cross-check and not a DC-gain extraction; its slow/cold outliers "
                       "are contaminated by the incomplete input sampling of #106. A disagreement "
                       "there is expected and is reported, not reconciled."),
        },
        "summary": summary,
        "corners": rows,
        "pass": rep.get("status") == "pass",
    }
    if a.record:
        out.write_text(json.dumps(rec, indent=2) + "\n")
        print(f"wrote {out}", file=sys.stderr)
    return 0 if rec["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

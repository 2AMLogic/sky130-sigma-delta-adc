#!/usr/bin/env python3
"""Modulator netlist load check (not a performance claim). See README.md."""
import json, pathlib, re, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
MIN_GAP_S = 0.3e-9  # a non-overlap gap must exceed this at tt; corner margins are owed to the T-tier work


def main():
    pin = json.load(open(REPO / "sim/pdk.json"))
    out = subprocess.run(["klt", "pdk", "find", "--pdk", pin["variant"], "--format", "json"],
                         capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"REFUSE: klt pdk find failed: {out.stderr.strip()}")
    root = pathlib.Path(json.loads(out.stdout)["root"]) / pin["variant"]
    src = root / "SOURCES"
    stamp = src.read_text().strip() if src.exists() else "<missing SOURCES>"
    if stamp != pin["sources_stamp"]:
        print(f"REFUSE: PDK at {root} is '{stamp}', pinned '{pin['sources_stamp']}'", file=sys.stderr)
        return 2
    ng = root / "libs.tech/ngspice"
    deck = ((HERE / "modulator_load.cir").read_text()
            .replace("{{PDK_LIB}}", f'"{ng / "sky130.lib.spice"}"')
            .replace("{{OTA}}", f'"{REPO / "design/ota/ota_fd.spice"}"')
            .replace("{{COMPARATOR}}", f'"{REPO / "design/modulator/comparator/comparator.spice"}"')
            .replace("{{NETLIST}}", f'"{REPO / "design/modulator/modulator.spice"}"'))
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td) / "deck.cir"
        d.write_text(deck)
        r = subprocess.run(["ngspice", "-b", str(d)], capture_output=True, text=True, cwd=ng)
    log = r.stdout + r.stderr
    v = {}
    for line in log.splitlines():
        k, eq, x = line.partition("=")
        parts = x.split()
        if eq and k.strip().isidentifier() and len(parts) == 1:
            try:
                v[k.strip()] = float(parts[0])
            except ValueError:
                pass
    need = ["overlap_phi1_phi2", "overlap_phi1e_phi2", "t_phi2_fall", "t_phi1e_rise", "t_phi1_rise",
            "t_phi1e_fall", "t_phi1_fall", "t_phi2_rise", "bs_max", "bs_min"]
    unresolved = re.search(r"unknown subckt|Could not find|no such", log, re.I)
    if r.returncode or unresolved or any(k not in v for k in need):
        print(log[-3000:], file=sys.stderr)
        return 1
    gaps = {"phi2_fall_to_phi1e_rise": v["t_phi1e_rise"] - v["t_phi2_fall"],
            "phi2_fall_to_phi1_rise": v["t_phi1_rise"] - v["t_phi2_fall"],
            "phi1_fall_to_phi2_rise": v["t_phi2_rise"] - v["t_phi1_fall"]}
    checks = {
        "netlist_loads_no_unresolved_subckt": True,
        "no_phi1_phi2_overlap": v["overlap_phi1_phi2"] == 0,
        "no_phi1e_phi2_overlap": v["overlap_phi1e_phi2"] == 0,
        "gaps_exceed_min": all(g > MIN_GAP_S for g in gaps.values()),
        "phi1e_falls_before_phi1": v["t_phi1e_fall"] < v["t_phi1_fall"],
        "bitstream_reaches_both_rails": v["bs_max"] > 1.6 and v["bs_min"] < 0.2,
    }
    ok = all(checks.values())
    print(json.dumps({"gaps_s": gaps, "phi1_minus_phi1e_fall_s": v["t_phi1_fall"] - v["t_phi1e_fall"],
                      "checks": checks, "pass": ok}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Regenerate the two deck/request pairs (ktc, amp). See README.md."""
import json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from settling_common import request

# Swept band. F_LO is the lower edge of every band integral, so it is also the
# lower edge of the flicker integral, which diverges logarithmically -- the
# record states it and carries the 20 Hz variant beside it so the sensitivity
# is visible. F_HI is above every pole in the circuit: the sampling-branch RC
# corner is a few hundred MHz and the closed-loop bandwidth tens of MHz.
#
# The per-corner evidence that F_HI is far enough out is the same integral
# taken over bands truncated one and two decades below it (`nz_rms_trunc*`,
# gated): a band with content left above its edge moves when the edge moves,
# so the measured shares above 1e9 and 1e10 Hz, and the shrink rate between
# them, are what show the integral has converged. It is NOT
# `total_vs_native_rel` below -- that compares two integrals of the *same*
# swept range, so a band truncated anywhere would move both together and they
# would still agree. That gate checks the integration scheme and the grid
# density, which is a different claim.
F_LO = 1.0
F_HI = 1e11
# The two truncated upper edges of the convergence sequence, one and two
# decades below F_HI, plus the spot density at the first of them.
F_TRUNC = (1e9, 1e10)
F_DENS_TOP = F_TRUNC[-1]
PTS_PER_DECADE = 20
BW_HZ = 2.0e4          # spec row 3 signal bandwidth, 20 kHz
AUDIO_LO_HZ = 20.0     # the 20 Hz variant of the baseband integral

NATIVE_TOL = 1e-2      # reference-validity gate (not a spec row), see README.md
# Upper-edge reference-validity gate (not a spec row): the rms over the band
# truncated one decade below F_HI must agree with the full-band rms to this.
# On rms, so in variance the top decade is bounded by about twice it.
TRUNC_TOL = 1e-1

# The two phases. A small-signal `.noise` run needs a static clock state, and
# one corner runs one analysis with one output, so the two parts of the thermal
# budget are two requests over the same 45-point grid (settling_common's
# grid_complete/measurements_present take a list of corner sets for exactly
# this). sim/integrator-settling does the same with its int1/int2 pair.
VARIANTS = {
    "ktc": {
        "clocks": {"PHI1": "1", "PHI1B": "0", "PHI1E": "1", "PHI2": "0"},
        "note": "phi1 sampling state",
        # The signed differential sum of the four sampled capacitor voltages.
        # Its variance is the spec 5.3 quantity 4*kT/Cs: the input and the
        # reference sampling phase, both sides, four independent contributions.
        "output": "v(nqp,nqn)",
        "what": ("switch kT/C: the sampled voltage on the four input- and "
                 "reference-branch sampling capacitors, differentially summed"),
        "referred_to": "integrator input",
    },
    "amp": {
        "clocks": {"PHI1": "0", "PHI1B": "1", "PHI1E": "0", "PHI2": "1"},
        "note": "phi2 integrate state",
        "output": "v(vod)",
        "what": ("integrate phase: the OTA together with the phi2 switches that "
                 "are in its loop -- spec 5.3's thermal share is 'sampling "
                 "switches and amplifier', and the phi2 switches belong to the "
                 "amplifier half of that split"),
        "referred_to": "integrator differential output",
    },
}


def e(name, expr, unit=None, limits=None):
    m = {"name": name, "expr": expr}
    if unit:
        m["unit"] = unit
    if limits:
        m["limits"] = limits
    return m


def n(name, quantity="onoise", at_hz=None, band_hz=None, unit=None, limits=None):
    """A klt native noise measurement (klayout_tools/sim_noise.py)."""
    body = {"quantity": quantity}
    body["at_hz" if at_hz is not None else "band_hz"] = at_hz if at_hz is not None else band_hz
    m = {"name": name, "noise": body}
    if unit:
        m["unit"] = unit
    if limits:
        m["limits"] = limits
    return m


# Only `onoise` is read: see the deck comment on Vinp's AC value.
MEASUREMENTS = [
    # The per-sampling-event rms: the whole swept band.
    n("nz_rms_tot", band_hz=[F_LO, F_HI], unit="V"),
    # The baseband share, which reaches the signal band with no aliasing. Two
    # lower edges, so the record shows how much of it is sub-audio flicker.
    n("nz_rms_bb", band_hz=[F_LO, BW_HZ], unit="V"),
    n("nz_rms_audio", band_hz=[AUDIO_LO_HZ, BW_HZ], unit="V"),
    # Spectrum shape, so the record shows whether the part is white (the
    # switches) or flicker-dominated (the amplifier) rather than asserting it.
    n("nz_dens_20", at_hz=20.0),
    n("nz_dens_1k", at_hz=1e3),
    n("nz_dens_20k", at_hz=BW_HZ),
    n("nz_dens_1meg", at_hz=1e6),
    n("nz_dens_100meg", at_hz=1e8),
    # --- upper-edge convergence, measured three ways -----------------------
    # The same integral over bands TRUNCATED one and two decades below F_HI.
    # This is the direct test: a band that still has content above its edge
    # moves when the edge moves, so (1 - (rms_trunc/rms_tot)^2) IS the share
    # of the integral that lies above each truncated edge, and the two of them
    # give the per-decade shrink rate that bounds what is left above F_HI.
    n("nz_rms_trunc1", band_hz=[F_LO, F_TRUNC[0]], unit="V"),
    n("nz_rms_trunc2", band_hz=[F_LO, F_TRUNC[1]], unit="V"),
    # Gated per corner: the truncated rms must already agree with the
    # full-band rms, i.e. the integral has stopped growing before the edge.
    e("trunc_vs_total_rms_rel", "abs(1 - nz_rms_trunc2/nz_rms_tot)",
      None, {"max": TRUNC_TOL}),
    # The spot density at the first truncated edge, against the 100 MHz probe:
    # the roll-off itself, so the record shows the slope and not only the
    # integral it produces.
    n("nz_dens_top", at_hz=F_DENS_TOP),
    # Independent cross-check of klt's trapezoid against ngspice's own
    # integral over the same swept range: it checks the integration scheme and
    # the 20-points/decade grid density. It says nothing about the upper edge
    # -- both numbers span the identical sweep.
    e("nz_total_native", "onoise_total", "V"),
    e("total_vs_native_rel", "abs(nz_rms_tot/nz_total_native - 1)", None, {"max": NATIVE_TOL}),
]


def variant_request(v):
    d = VARIANTS[v]
    return request(f"integrator_noise_{v}.cir", MEASUREMENTS,
                   analysis={"kind": "noise",
                             "args": f"{d['output']} Vinp dec {PTS_PER_DECADE} {F_LO:g} {F_HI:g}"},
                   timeout_s=600, poll_timeout_s=7200,
                   options={"ngspice_init": ["set numdgt=12"]})


if __name__ == "__main__":
    tmpl = (HERE / "integrator_noise.cir.tmpl").read_text()
    for v, d in VARIANTS.items():
        deck = tmpl.replace("@VARIANT@", v).replace("@VARIANTNOTE@", d["note"])
        # Order-independent: the closing delimiter keeps @PHI1@ from matching
        # inside @PHI1B@/@PHI1E@, so no substitution can shadow another.
        for k, val in d["clocks"].items():
            deck = deck.replace(f"@{k}@", val)
        (HERE / f"integrator_noise_{v}.cir").write_text(deck)
        (HERE / f"request_{v}.json").write_text(
            json.dumps(variant_request(v), indent=2) + "\n")
    print(f"wrote {len(VARIANTS)} decks and requests")

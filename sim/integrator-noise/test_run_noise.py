"""Fixture tests for the noise runner's derivations. Run:
python3 -I -m unittest discover -s sim/integrator-noise -p 'test_*.py'

No fleet, no ngspice, no klt: every corner set here is hand-built. What is
covered is the arithmetic the record depends on -- the input referral, the
V^2 -> FS^2 conversion, the two in-band links and the OSR factor between
them, kT/C -> Cs_eff, the per-corner budget verdicts -- and that a partial or
unmeasured grid is refused as a record.
"""
import contextlib
import io
import math
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import make_request as mkn
import run_noise as rn
import settling_common as sc

PROCESS = ("tt", "ss", "ff", "sf", "fs")
VDDA = ("1.620V", "1.800V", "1.980V")
TEMP = ("-40C", "27C", "125C")
CORNER_IDS = tuple(f"{p}/{v}/{t}" for p in PROCESS for v in VDDA for t in TEMP)


def measured(rms=1.207258251372e-4, bb=None, audio=None, status="pass", diagnostics=(),
             dens_top=1.5e-10, trunc=(0.93, 0.983)):
    """A corner that simulated. `bb` defaults to a white spectrum's baseband
    share, i.e. tiny next to the total. `trunc` gives the two truncated-band
    rms values as fractions of the full-band rms; the default is a converged
    integral (14% / 3.4% of the variance above the two truncated edges, the
    shape the real tt corner shows). `dens_top` is the density one decade
    below F_HI."""
    bb = rms * 1e-2 if bb is None else bb
    return {"status": status, "nz_rms_tot": rms, "nz_rms_bb": bb,
            "nz_rms_audio": audio if audio is not None else bb,
            "nz_dens_20": 7.4e-9, "nz_dens_1k": 7.4e-9, "nz_dens_20k": 7.4e-9,
            "nz_dens_1meg": 7.4e-9, "nz_dens_100meg": 6.1e-9,
            "nz_dens_top": dens_top,
            "nz_rms_trunc1": rms * trunc[0], "nz_rms_trunc2": rms * trunc[1],
            "trunc_vs_total_rms_rel": abs(1.0 - trunc[1]),
            "nz_total_native": rms, "total_vs_native_rel": 1e-3,
            "diagnostics": list(diagnostics)}


def unmeasured(status="fail", diagnostics=("batch_job_failed",)):
    c = {"status": status, "diagnostics": list(diagnostics)}
    c.update({k: None for k in rn.KEYS})
    return c


def corner_set(n=sc.GRID_POINTS, factory=measured, **kw):
    return {cid: factory(**kw) for cid in CORNER_IDS[:n]}


def call(fn, *args, **kw):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        verdict = fn(*args, **kw)
    return verdict, err.getvalue()


class InputReferral(unittest.TestCase):
    def test_ktc_is_already_at_the_integrator_input(self):
        self.assertEqual(rn.INPUT_REFERRAL["ktc"], 1.0)
        p = rn.part("tt/1.800V/27C", measured(rms=1e-4), "ktc")
        self.assertAlmostEqual(p["var_total_V2"], 1e-8)

    def test_amp_is_divided_by_the_charge_transfer_gain(self):
        """Measured at the output; one Cs/Ci = 0.5 transfer back to the input."""
        self.assertAlmostEqual(rn.INPUT_REFERRAL["amp"], 1.0 / rn.C1)
        p = rn.part("tt/1.800V/27C", measured(rms=1e-4), "amp")
        self.assertAlmostEqual(p["var_total_V2"], 1e-8 / rn.C1 ** 2)
        self.assertAlmostEqual(p["var_total_V2"], 4e-8)


class Conversions(unittest.TestCase):
    def test_one_fs_of_input_becomes_c1_squared_in_fs2(self):
        """A 1.2 V rms differential input (1 FS) must land at C1^2 = 0.25 FS^2."""
        p = rn.part("tt/1.800V/27C", measured(rms=rn.VFS_DIFF_V), "ktc")
        self.assertAlmostEqual(p["var_total_fs2"], rn.C1 ** 2, places=12)

    def test_fs2_scale_factor_is_the_documented_one(self):
        p = rn.part("tt/1.800V/27C", measured(rms=1e-4), "ktc")
        self.assertAlmostEqual(p["var_total_fs2"],
                               (rn.C1 / rn.VFS_DIFF_V) ** 2 * p["var_total_V2"])

    def test_white_inband_link_is_exactly_one_over_osr(self):
        p = rn.part("tt/1.800V/27C", measured(rms=1e-4), "ktc")
        self.assertAlmostEqual(p["inband_white_V2"] * rn.OSR, p["var_total_V2"])

    def test_split_link_divides_only_the_aliased_share(self):
        p = rn.part("tt/1.800V/27C", measured(rms=1e-4, bb=2e-5), "ktc")
        self.assertAlmostEqual(p["var_baseband_V2"], 4e-10)
        self.assertAlmostEqual(p["var_aliased_V2"], 1e-8 - 4e-10)
        self.assertAlmostEqual(p["inband_V2"], 4e-10 + (1e-8 - 4e-10) / rn.OSR)

    def test_white_spectrum_makes_the_two_links_agree(self):
        """Baseband negligible => inband == inband_white to a part in 1e3."""
        p = rn.part("tt/1.800V/27C", measured(rms=1e-4, bb=1e-4 * 1e-3), "ktc")
        self.assertAlmostEqual(p["inband_V2"] / p["inband_white_V2"], 1.0, places=3)

    def test_flicker_spectrum_makes_the_split_link_larger(self):
        """A baseband-heavy spectrum is under-counted by the white link."""
        p = rn.part("tt/1.800V/27C", measured(rms=1e-4, bb=3e-5), "amp")
        self.assertGreater(p["inband_V2"], p["inband_white_V2"])

    def test_model_b_equivalent_round_trips_through_the_osr_link(self):
        """The loaded parameter must reproduce inband_V2 under model B's 1/OSR."""
        p = rn.part("tt/1.800V/27C", measured(rms=1e-4, bb=3e-5), "amp")
        self.assertAlmostEqual(p["model_b_equiv_var_V2"] / rn.OSR, p["inband_V2"])
        self.assertAlmostEqual(p["model_b_equiv_ktc_noise_var_fs2"],
                               (rn.C1 / rn.VFS_DIFF_V) ** 2 * p["model_b_equiv_var_V2"])

    def test_aliased_share_never_goes_negative(self):
        """Rounding can put the baseband integral a hair above the total."""
        p = rn.part("tt/1.800V/27C", measured(rms=1e-4, bb=1.000001e-4), "ktc")
        self.assertEqual(p["var_aliased_V2"], 0.0)


class UpperEdge(unittest.TestCase):
    """The blocking finding of PR #139's review: the klt-vs-ngspice gate cannot
    show the upper band edge is far enough out, and a verdict depends on it --
    99% of ktc's inband_V2 is the aliased share of the full-band integral."""

    def test_the_truncated_edges_sit_below_the_swept_edge(self):
        self.assertEqual(mkn.F_HI, 1e11)
        self.assertEqual(mkn.F_TRUNC, (1e9, 1e10))
        for f in mkn.F_TRUNC:
            self.assertLess(f, mkn.F_HI)
        names = {m["name"] for m in mkn.MEASUREMENTS}
        self.assertLessEqual({"nz_rms_trunc1", "nz_rms_trunc2"}, names)
        for i, name in enumerate(("nz_rms_trunc1", "nz_rms_trunc2")):
            m = next(m for m in mkn.MEASUREMENTS if m["name"] == name)
            self.assertEqual(m["noise"]["band_hz"], [mkn.F_LO, mkn.F_TRUNC[i]])

    def test_the_share_above_an_edge_is_one_minus_the_rms_ratio_squared(self):
        """The direct test: an integral with content left above its edge moves
        when the edge moves, and by exactly this much."""
        p = rn.part("tt/1.800V/27C", measured(rms=1e-4, trunc=(0.8, 0.9)), "ktc")
        u = p["upper_edge"]
        self.assertAlmostEqual(u["var_above_trunc1_frac"], 1 - 0.8 ** 2)
        self.assertAlmostEqual(u["var_above_trunc2_frac"], 1 - 0.9 ** 2)

    def test_the_shares_are_independent_of_the_input_referral(self):
        """`g` scales the truncated and the full integral alike, so the shares
        are comparable with var_total_V2 on either variant."""
        k = rn.part("tt/1.800V/27C", measured(rms=1e-4, trunc=(0.8, 0.9)), "ktc")
        a = rn.part("tt/1.800V/27C", measured(rms=1e-4, trunc=(0.8, 0.9)), "amp")
        self.assertNotEqual(rn.INPUT_REFERRAL["ktc"], rn.INPUT_REFERRAL["amp"])
        for key in ("var_above_trunc1_frac", "var_above_trunc2_frac",
                    "per_decade_shrink", "extrapolated_frac_above_F_HI"):
            self.assertAlmostEqual(k["upper_edge"][key], a["upper_edge"][key], msg=key)

    def test_the_extrapolation_carries_the_measured_shrink_one_decade_further(self):
        p = rn.part("tt/1.800V/27C", measured(rms=1e-4, trunc=(0.8, 0.9)), "ktc")
        u = p["upper_edge"]
        f1, f2 = 1 - 0.8 ** 2, 1 - 0.9 ** 2
        self.assertAlmostEqual(u["per_decade_shrink"], f2 / f1)
        self.assertAlmostEqual(u["extrapolated_frac_above_F_HI"], f2 * (f2 / f1))
        self.assertLess(u["extrapolated_frac_above_F_HI"], u["var_above_trunc2_frac"])

    def test_a_converged_integral_leaves_a_negligible_tail(self):
        """The default fixture is the measured tt shape: ~1% above F_HI."""
        u = rn.part("tt/1.800V/27C", measured(), "ktc")["upper_edge"]
        self.assertLess(u["var_above_trunc2_frac"], 0.05)
        self.assertLess(u["extrapolated_frac_above_F_HI"], 0.02)
        self.assertLess(u["trunc_vs_total_rms_rel"], mkn.TRUNC_TOL)

    def test_a_truncated_integral_is_caught_by_the_share_and_the_gate(self):
        """A band cut inside the noise bandwidth: the truncated integral is far
        short of the full one. This is the condition the klt-vs-ngspice gate is
        blind to, since both of its numbers span the same sweep."""
        c = measured(rms=1e-4, trunc=(0.5, 0.6))
        u = rn.part("tt/1.800V/27C", c, "ktc")["upper_edge"]
        self.assertGreater(u["var_above_trunc2_frac"], 0.5)
        self.assertGreater(u["trunc_vs_total_rms_rel"], mkn.TRUNC_TOL)
        # ...while the integration-scheme gate is perfectly happy.
        self.assertLess(c["total_vs_native_rel"], mkn.NATIVE_TOL)

    def test_the_gate_limit_is_carried_beside_the_value(self):
        u = rn.part("tt/1.800V/27C", measured(), "ktc")["upper_edge"]
        self.assertEqual(u["trunc_vs_total_rms_rel_limit"], mkn.TRUNC_TOL)
        gate = next(m for m in mkn.MEASUREMENTS if m["name"] == "trunc_vs_total_rms_rel")
        self.assertEqual(gate["limits"]["max"], mkn.TRUNC_TOL)

    def test_the_rolloff_slope_is_recorded_beside_the_integral(self):
        u = rn.part("tt/1.800V/27C", measured(dens_top=6.1e-10), "ktc")["upper_edge"]
        self.assertAlmostEqual(u["rolloff_trunc2_over_100meg"], 0.1)
        self.assertEqual(u["dens_at_trunc2_V_per_rtHz"], 6.1e-10)
        p = rn.part("tt/1.800V/27C", measured(dens_top=3e-12), "ktc")
        self.assertEqual(p["spectrum_V_per_rtHz"][f"{mkn.F_DENS_TOP:g}Hz"], 3e-12)

    def test_an_unmeasured_truncated_band_gives_no_share_rather_than_zero(self):
        c = measured()
        c["nz_rms_trunc1"] = c["nz_rms_trunc2"] = None
        u = rn.part("tt/1.800V/27C", c, "ktc")["upper_edge"]
        self.assertIsNone(u["var_above_trunc1_frac"])
        self.assertIsNone(u["var_above_trunc2_frac"])
        self.assertIsNone(u["per_decade_shrink"])
        self.assertIsNone(u["extrapolated_frac_above_F_HI"])

    def test_summary_carries_the_worsts_over_both_variants(self):
        sets = {"ktc": {"tt/1.800V/27C": measured(trunc=(0.93, 0.983))},
                "amp": {"tt/1.800V/27C": measured(trunc=(0.90, 0.97))}}
        s = rn.summarize(rn.derive(sets))
        rows = rn.derive(sets)["tt/1.800V/27C"]
        self.assertAlmostEqual(s["worst_var_above_trunc2_frac"],
                               rows["amp"]["upper_edge"]["var_above_trunc2_frac"])
        self.assertAlmostEqual(s["worst_extrapolated_frac_above_F_HI"],
                               rows["amp"]["upper_edge"]["extrapolated_frac_above_F_HI"])
        self.assertAlmostEqual(s["worst_trunc_vs_total_rms_rel"], 0.03)

    def test_summary_states_what_the_tail_is_worth_on_a_budget_margin(self):
        """The verdict-bearing link: dB, against the dB of margin reported."""
        sets = {"ktc": {"tt/1.800V/27C": measured()},
                "amp": {"tt/1.800V/27C": measured()}}
        s = rn.summarize(rn.derive(sets))
        frac = s["worst_extrapolated_frac_above_F_HI"]
        import math
        self.assertAlmostEqual(s["extrapolated_tail_margin_impact_db"],
                               10.0 * math.log10(1.0 + frac))
        self.assertLess(s["extrapolated_tail_margin_impact_db"], 0.1)

    def test_the_integration_gate_is_not_cited_as_upper_edge_evidence(self):
        """The defect the review caught: one sentence claiming both things."""
        scheme = rn.CONVERGENCE["integration_scheme"]
        self.assertIn("klt_vs_ngspice_integral_rel", scheme)
        self.assertIn("identical sweep", scheme)
        self.assertIn("not cited as upper-edge evidence", scheme)
        edge = rn.CONVERGENCE["upper_edge"]
        self.assertNotIn("klt_vs_ngspice", edge)
        self.assertIn("truncated", edge)
        self.assertIn("extrapolated_frac_above_F_HI", edge)


class CsEffSpread(unittest.TestCase):
    def test_the_record_quotes_the_range_not_one_corner(self):
        caps = {"cs_drawn_F": 1.0e-12}
        summary = {"cs_eff_F_range": [{"corner_id": "fs/1.800V/125C", "value": 1.11e-12},
                                      {"corner_id": "fs/1.620V/-40C", "value": 1.285e-12}]}
        text = rn.cs_eff_spread(summary, caps)
        self.assertIn("+11.0%", text)
        self.assertIn("+28.5%", text)
        self.assertIn("fs/1.800V/125C", text)
        self.assertIn("fs/1.620V/-40C", text)
        self.assertIn("spread", text)

    def test_a_missing_range_degrades_instead_of_crashing(self):
        self.assertIn("cs_eff_F", rn.cs_eff_spread({}, {}))


class Temperature(unittest.TestCase):
    def test_corner_id_temperature(self):
        self.assertAlmostEqual(rn.temp_k("ss/1.620V/-40C"), 233.15)
        self.assertAlmostEqual(rn.temp_k("tt/1.800V/27C"), 300.15)
        self.assertAlmostEqual(rn.temp_k("ff/1.980V/125C"), 398.15)

    def test_unparseable_corner_id_is_none(self):
        self.assertIsNone(rn.temp_k("tt/1.800V/hot"))


class CsEff(unittest.TestCase):
    def test_cs_eff_inverts_four_kt_over_c(self):
        """The output sums four independent kT/C samplers, so var = 4kT/Cs."""
        cs = 1e-12
        t = 300.15
        var = 4.0 * rn.K_B * t / cs
        p = rn.part("tt/1.800V/27C", measured(rms=var ** 0.5), "ktc")
        self.assertAlmostEqual(p["cs_eff_F"] / cs, 1.0, places=9)

    def test_cs_eff_is_only_derived_for_the_switch_variant(self):
        self.assertNotIn("cs_eff_F", rn.part("tt/1.800V/27C", measured(), "amp"))

    def test_drawn_caps_are_the_drawn_geometry_not_the_planning_values(self):
        d = rn.drawn_caps()
        self.assertEqual(d["cs_drawn_geometry_um"], [22.17, 22.17])
        self.assertEqual(d["ci_drawn_geometry_um"], [31.43, 31.43])
        # Near but not equal to the 1 pF / 2 pF planning values.
        self.assertNotAlmostEqual(d["cs_drawn_F"], 1e-12, places=15)
        self.assertAlmostEqual(d["cs_drawn_F"], 1e-12, places=13)
        self.assertAlmostEqual(d["drawn_ratio_cs_over_ci"], 0.5, places=3)


class Verdicts(unittest.TestCase):
    def sets(self, ktc_rms, amp_rms, amp_bb=None):
        return {"ktc": {"tt/1.800V/27C": measured(rms=ktc_rms)},
                "amp": {"tt/1.800V/27C": measured(rms=amp_rms, bb=amp_bb)}}

    def test_quiet_grid_passes_both_budgets(self):
        rows = rn.derive(self.sets(1e-5, 1e-5))
        v = rows["tt/1.800V/27C"]["verdict"]
        self.assertTrue(v["ktc_pass"])
        self.assertTrue(v["total_thermal_pass"])
        self.assertGreater(v["ktc_margin_db"], 0.0)

    def test_loud_switches_fail_the_ktc_budget(self):
        rows = rn.derive(self.sets(1e-3, 1e-6))
        v = rows["tt/1.800V/27C"]["verdict"]
        self.assertFalse(v["ktc_pass"])
        self.assertLess(v["ktc_margin_db"], 0.0)

    def test_total_is_the_sum_of_both_parts(self):
        rows = rn.derive(self.sets(1e-4, 2e-4))
        r = rows["tt/1.800V/27C"]
        self.assertAlmostEqual(r["verdict"]["total_thermal_inband_V2"],
                               r["ktc"]["inband_V2"] + r["amp"]["inband_V2"])

    def test_budgets_are_the_ratified_spec_values(self):
        self.assertEqual(rn.KTC_BUDGET_V2, 4.5e-10)
        self.assertEqual(rn.THERMAL_BUDGET_V2, 9.0e-10)
        self.assertEqual(rn.OSR, 128)

    def test_a_quiet_switch_part_cannot_rescue_a_loud_amplifier(self):
        rows = rn.derive(self.sets(1e-5, 1e-3))
        v = rows["tt/1.800V/27C"]["verdict"]
        self.assertTrue(v["ktc_pass"])
        self.assertFalse(v["total_thermal_pass"])

    def test_unmeasured_corner_gives_no_verdict_rather_than_a_pass(self):
        sets = {"ktc": {"tt/1.800V/27C": unmeasured()},
                "amp": {"tt/1.800V/27C": measured()}}
        v = rn.derive(sets)["tt/1.800V/27C"]["verdict"]
        self.assertIsNone(v["ktc_pass"])
        self.assertIsNone(v["total_thermal_pass"])

    def test_summary_names_the_binding_corner_and_the_failures(self):
        sets = {"ktc": {"tt/1.800V/27C": measured(rms=1e-5),
                        "ss/1.620V/125C": measured(rms=1e-3)},
                "amp": {"tt/1.800V/27C": measured(rms=1e-5),
                        "ss/1.620V/125C": measured(rms=1e-5)}}
        s = rn.summarize(rn.derive(sets))
        self.assertEqual(s["binding_ktc_corner"]["corner_id"], "ss/1.620V/125C")
        self.assertEqual(s["ktc_fail_corners"], ["ss/1.620V/125C"])
        self.assertEqual(s["ktc_pass_count"], 1)


class RecordGates(unittest.TestCase):
    def test_both_full_measured_sets_pass_both_gates(self):
        sets = [corner_set(), corner_set()]
        self.assertTrue(sc.grid_complete(sets))
        self.assertTrue(sc.measurements_present(sets, key="nz_rms_tot"))

    def test_one_short_variant_refuses_the_whole_record(self):
        verdict, err = call(sc.grid_complete, [corner_set(), corner_set(n=44)])
        self.assertFalse(verdict)
        self.assertIn("not all 45 grid points returned", err)

    def test_dead_fleet_job_is_refused_even_at_full_count(self):
        dead = corner_set(factory=unmeasured)
        self.assertTrue(sc.grid_complete([dead, dead]))
        verdict, err = call(sc.measurements_present, [dead, corner_set()], key="nz_rms_tot")
        self.assertFalse(verdict)
        self.assertIn("returned no nz_rms_tot", err)
        self.assertIn("batch_job_failed", err)


class RequestShape(unittest.TestCase):
    def test_both_variants_are_the_dr_002_full_grid_on_a_noise_analysis(self):
        for v in mkn.VARIANTS:
            r = mkn.variant_request(v)
            self.assertEqual(r["analysis"]["kind"], "noise", v)
            self.assertEqual(r["backend"], "batch", v)
            self.assertIn(mkn.VARIANTS[v]["output"], r["analysis"]["args"], v)
            c = r["corners"]
            self.assertEqual(len(c["process"]) * len(c["supply_v"]["vdda"])
                             * len(c["temperature_c"]), sc.GRID_POINTS, v)
            self.assertEqual(r["batch"]["capacity_wait_s"], sc.CAPACITY_WAIT_S, v)

    def test_committed_requests_and_decks_match_the_builder(self):
        import json
        tmpl = (HERE / "integrator_noise.cir.tmpl").read_text()
        for v, d in mkn.VARIANTS.items():
            self.assertEqual(json.loads((HERE / f"request_{v}.json").read_text()),
                             mkn.variant_request(v), v)
            self.assertEqual((HERE / f"integrator_noise_{v}.cir").read_text(),
                             mkn.deck_text(v, tmpl), v)
            self.assertNotIn("@", (HERE / f"integrator_noise_{v}.cir").read_text()
                             .split(".include")[-1], v)

    def test_the_two_variants_are_complementary_clock_states(self):
        k, m = mkn.VARIANTS["ktc"]["clocks"], mkn.VARIANTS["amp"]["clocks"]
        self.assertEqual(k["PHI1"], "1")
        self.assertEqual(k["PHI2"], "0")
        self.assertEqual(m["PHI1"], "0")
        self.assertEqual(m["PHI2"], "1")
        for d in (k, m):   # phi1b is the complement of phi1, as the cell expects
            self.assertNotEqual(d["PHI1"], d["PHI1B"])

    def test_every_measurement_key_the_runner_reads_is_requested(self):
        names = {m["name"] for m in mkn.MEASUREMENTS}
        self.assertEqual(set(rn.KEYS) - names, set())

    def test_the_band_integrals_lie_inside_the_swept_range(self):
        for m in mkn.MEASUREMENTS:
            body = m.get("noise")
            if not body:
                continue
            edges = [body["at_hz"]] if "at_hz" in body else body["band_hz"]
            for hz in edges:
                self.assertGreaterEqual(hz, mkn.F_LO, m["name"])
                self.assertLessEqual(hz, mkn.F_HI, m["name"])

    def test_the_baseband_edge_is_the_spec_bandwidth(self):
        self.assertEqual(mkn.BW_HZ, 2.0e4)
        bb = next(m for m in mkn.MEASUREMENTS if m["name"] == "nz_rms_bb")
        self.assertEqual(bb["noise"]["band_hz"], [mkn.F_LO, mkn.BW_HZ])


if __name__ == "__main__":
    unittest.main()


# --- issue #140: the accumulating referral and the per-device split ---------

def amp_pair(rms_vod=1.0e-4, ratio_v=0.5, bb_frac=0.9, **kw):
    """An (amp, ampq) corner pair with a known amplitude transfer `ratio_v`.

    `bb_frac` is the baseband SHARE of the full-band variance, so a flicker-
    dominated part (the real amplifier) is bb_frac near 1 and a white part is
    bb_frac near 0. The same share is used for both outputs, so the transfer
    is flat across the band and every band ratio must come back as ratio_v^2.
    """
    def one(rms):
        return measured(rms=rms, bb=rms * math.sqrt(bb_frac), **kw)
    return one(rms_vod), one(rms_vod * ratio_v)


class AccumulatingReferral(unittest.TestCase):
    def test_ampq_carries_the_same_input_referral_as_amp(self):
        # The #140 correction is WHERE the noise is read, not the referral: a
        # per-cycle increment refers to the input by the same 1/C1 as a static
        # output. A different constant here would double-count the correction.
        self.assertEqual(rn.INPUT_REFERRAL["ampq"], rn.INPUT_REFERRAL["amp"])
        self.assertEqual(rn.INPUT_REFERRAL["ampq"], 1.0 / rn.C1)

    def test_the_transfer_is_the_ratio_of_the_two_band_integrals(self):
        amp, ampq = amp_pair(ratio_v=0.5)
        t = rn.transfer(rn.part("tt/1.800V/27C", amp, "amp"),
                        rn.part("tt/1.800V/27C", ampq, "ampq"))
        for band in ("total", "baseband", "audio_band", "aliased", "inband"):
            self.assertAlmostEqual(t["power_ratio_by_band"][band], 0.25, places=9,
                                   msg=band)
            self.assertAlmostEqual(t["power_ratio_db_by_band"][band],
                                   10.0 * math.log10(0.25), places=7, msg=band)

    def test_the_input_referral_cancels_out_of_the_transfer(self):
        # Both parts carry 1/C1, so the measured transfer must not depend on
        # it. Guards against a future referral change silently moving it.
        amp, ampq = amp_pair(ratio_v=0.4)
        a = rn.part("tt/1.800V/27C", amp, "amp")
        q = rn.part("tt/1.800V/27C", ampq, "ampq")
        k = rn.part("tt/1.800V/27C", ampq, "ktc")       # referral 1.0, not 1/C1
        self.assertNotEqual(q["var_total_V2"], k["var_total_V2"])
        self.assertAlmostEqual(rn.transfer(a, q)["power_ratio_by_band"]["total"],
                               0.16, places=9)

    def test_the_bands_can_carry_different_transfers(self):
        # The real block's baseband and aliased transfers differ by about 1 dB,
        # so the record reports them separately rather than one scalar.
        amp = measured(rms=1.0e-4, bb=9.0e-5)
        ampq = measured(rms=4.0e-5, bb=4.5e-5)           # quieter total, louder bb
        t = rn.transfer(rn.part("tt/1.800V/27C", amp, "amp"),
                        rn.part("tt/1.800V/27C", ampq, "ampq"))
        self.assertGreater(t["power_ratio_by_band"]["baseband"],
                           t["power_ratio_by_band"]["aliased"])

    def test_the_hand_analysis_residual_is_measured_minus_predicted(self):
        caps = rn.drawn_caps()
        cs, ci = caps["cs_drawn_F"], caps["ci_drawn_F"]
        hand_v = (2.0 * cs) / (ci + 2.0 * cs)
        amp, ampq = amp_pair(ratio_v=hand_v)             # exactly the prediction
        t = rn.transfer(rn.part("tt/1.800V/27C", amp, "amp"),
                        rn.part("tt/1.800V/27C", ampq, "ampq"), caps)
        self.assertAlmostEqual(t["hand_analysis_amplitude_ratio"], hand_v, places=12)
        self.assertAlmostEqual(t["hand_analysis_residual_db"], 0.0, places=9)

    def test_a_measured_transfer_above_the_prediction_gives_a_positive_residual(self):
        caps = rn.drawn_caps()
        hand_v = (2.0 * caps["cs_drawn_F"]) / (caps["ci_drawn_F"] + 2.0 * caps["cs_drawn_F"])
        amp, ampq = amp_pair(ratio_v=hand_v * 1.1)
        t = rn.transfer(rn.part("tt/1.800V/27C", amp, "amp"),
                        rn.part("tt/1.800V/27C", ampq, "ampq"), caps)
        self.assertAlmostEqual(t["hand_analysis_residual_db"],
                               20.0 * math.log10(1.1), places=7)

    def test_implied_cp_inverts_the_static_noise_gain(self):
        # Round trip: a chosen Cp -> the amplitude ratio it predicts -> back.
        caps = rn.drawn_caps()
        cs_tot, ci = 2.0 * caps["cs_drawn_F"], caps["ci_drawn_F"]
        for cp in (0.0, 50e-15, 150e-15, 400e-15):
            r = (cs_tot + cp) / (ci + cs_tot + cp)
            self.assertAlmostEqual(rn.implied_summing_node_cp_F(r, caps) / 1e-15,
                                   cp / 1e-15, places=6, msg=str(cp))

    def test_implied_cp_is_zero_when_the_ratio_matches_the_drawn_caps(self):
        caps = rn.drawn_caps()
        hand_v = (2.0 * caps["cs_drawn_F"]) / (caps["ci_drawn_F"] + 2.0 * caps["cs_drawn_F"])
        self.assertAlmostEqual(rn.implied_summing_node_cp_F(hand_v, caps), 0.0, places=18)

    def test_implied_cp_degrades_instead_of_crashing(self):
        caps = rn.drawn_caps()
        for bad in (None, 0.0, 1.0, 1.5, -0.2):
            self.assertIsNone(rn.implied_summing_node_cp_F(bad, caps), msg=str(bad))
        self.assertIsNone(rn.implied_summing_node_cp_F(0.5, None))
        self.assertIsNone(rn.implied_summing_node_cp_F(0.5, {}))

    def test_an_unmeasured_variant_gives_no_transfer_rather_than_zero(self):
        a = rn.part("tt/1.800V/27C", unmeasured(), "amp")
        q = rn.part("tt/1.800V/27C", measured(), "ampq")
        t = rn.transfer(a, q)
        self.assertIsNone(t["power_ratio_by_band"]["total"])
        self.assertIsNone(t["power_ratio_db_by_band"]["total"])
        self.assertIsNone(t["implied_summing_node_cp_F"])


class AccumulatingVerdicts(unittest.TestCase):
    def rows(self, ratio_v=0.5, amp_rms=1.0e-4, ktc_rms=1.0e-5, n=sc.GRID_POINTS):
        amp, ampq = amp_pair(rms_vod=amp_rms, ratio_v=ratio_v)
        return rn.derive({"ktc": corner_set(n, rms=ktc_rms),
                          "amp": {cid: amp for cid in CORNER_IDS[:n]},
                          "ampq": {cid: ampq for cid in CORNER_IDS[:n]}},
                         rn.drawn_caps())

    def test_the_accumulating_verdict_uses_the_same_budget(self):
        v = list(self.rows().values())[0]["verdict"]
        self.assertEqual(v["total_thermal_budget_V2"], rn.THERMAL_BUDGET_V2)
        self.assertEqual(v["total_thermal_budget_V2"], 9.0e-10)

    def test_the_accumulating_total_is_switches_plus_the_accumulating_amplifier(self):
        r = list(self.rows().values())[0]
        self.assertAlmostEqual(r["verdict"]["total_thermal_inband_accumulated_V2"],
                               r["ktc"]["inband_V2"] + r["ampq"]["inband_V2"], places=18)
        # and the static one still uses amp, unchanged by #140
        self.assertAlmostEqual(r["verdict"]["total_thermal_inband_V2"],
                               r["ktc"]["inband_V2"] + r["amp"]["inband_V2"], places=18)

    def test_a_quieter_accumulating_part_improves_the_margin_by_the_transfer(self):
        # With the switch part negligible, the margin must improve by exactly
        # the transfer in dB -- the headline claim of issue #140.
        r = list(self.rows(ratio_v=0.5, ktc_rms=1.0e-12).values())[0]
        self.assertAlmostEqual(r["verdict"]["accumulated_vs_static_db"],
                               10.0 * math.log10(0.25), places=6)
        self.assertAlmostEqual(r["verdict"]["total_thermal_accumulated_margin_db"]
                               - r["verdict"]["total_thermal_margin_db"],
                               -10.0 * math.log10(0.25), places=6)

    def test_the_corrected_treatment_can_turn_a_miss_into_a_pass(self):
        rows = self.rows(ratio_v=0.05, amp_rms=1.0e-4, ktc_rms=1.0e-12)
        v = list(rows.values())[0]["verdict"]
        self.assertFalse(v["total_thermal_pass"])
        self.assertTrue(v["total_thermal_accumulated_pass"])
        s = rn.summarize(rows)
        self.assertEqual(s["total_thermal_fail_corners"], sorted(CORNER_IDS))
        self.assertEqual(s["total_thermal_accumulated_fail_corners"], [])
        self.assertEqual(s["total_thermal_accumulated_pass_count"], sc.GRID_POINTS)

    def test_the_corrected_treatment_does_not_rescue_a_loud_enough_amplifier(self):
        v = list(self.rows(ratio_v=0.5, amp_rms=1.0e-4).values())[0]["verdict"]
        self.assertFalse(v["total_thermal_pass"])
        self.assertFalse(v["total_thermal_accumulated_pass"])

    def test_the_model_b_number_follows_the_accumulating_total(self):
        r = list(self.rows().values())[0]
        v, fs2 = r["verdict"], (rn.C1 / rn.VFS_DIFF_V) ** 2
        self.assertAlmostEqual(v["model_b_equiv_ktc_noise_var_fs2_accumulated"],
                               fs2 * v["total_thermal_inband_accumulated_V2"] * rn.OSR,
                               places=18)
        self.assertAlmostEqual(v["model_b_equiv_ktc_noise_var_fs2_static"],
                               fs2 * v["total_thermal_inband_V2"] * rn.OSR, places=18)
        self.assertLess(v["model_b_equiv_ktc_noise_var_fs2_accumulated"],
                        v["model_b_equiv_ktc_noise_var_fs2_static"])

    def test_summary_reports_the_transfer_over_the_grid(self):
        s = rn.summarize(self.rows(ratio_v=0.5))
        for key in ("transfer_baseband_db_range", "transfer_aliased_db_range",
                    "transfer_inband_db_range", "implied_summing_node_cp_F_range",
                    "accumulated_vs_static_db_range"):
            lo, hi = s[key]
            self.assertIsNotNone(lo, key)
            self.assertLessEqual(lo["value"], hi["value"], key)
        self.assertAlmostEqual(s["transfer_baseband_db_range"][0]["value"],
                               10.0 * math.log10(0.25), places=6)
        self.assertIsNotNone(s["binding_total_thermal_accumulated_corner"]["corner_id"])

    def test_an_unmeasured_corner_gives_no_accumulating_verdict_rather_than_a_pass(self):
        rows = rn.derive({"ktc": corner_set(1), "amp": corner_set(1),
                          "ampq": {CORNER_IDS[0]: unmeasured()}})
        v = list(rows.values())[0]["verdict"]
        self.assertIsNone(v["total_thermal_inband_accumulated_V2"])
        self.assertIsNone(v["total_thermal_accumulated_pass"])
        self.assertNotIn(CORNER_IDS[0],
                         rn.summarize(rows)["total_thermal_accumulated_fail_corners"])

    def test_the_record_gates_cover_the_third_variant(self):
        full, short = corner_set(), corner_set(sc.GRID_POINTS - 1)
        self.assertTrue(sc.grid_complete([full, full, full]))
        verdict, err = call(sc.grid_complete, [full, full, short])
        self.assertFalse(verdict)
        self.assertIn("45, 45, 44", err)
        dead = corner_set(factory=unmeasured)
        verdict, err = call(sc.measurements_present, [full, full, dead],
                            key="nz_rms_tot")
        self.assertFalse(verdict)
        self.assertIn("returned no nz_rms_tot", err)


def dev_print(total, entries, tag="inband_nqci"):
    """A synthetic ngspice `print all` block.

    `entries` maps a flat instance path to {mechanism: rms_in_volts}. The
    device line ngspice emits alongside is the RMS sum in quadrature of that
    device's mechanisms, which is what the real output does.
    """
    out = [f"@@BLOCK {tag}", f"onoise_total = {total:.12e}"]
    for inst, mechs in entries.items():
        dev = math.sqrt(sum(v * v for v in mechs.values()))
        out.append(f"onoise_total.m.{inst}.msky130_fd_pr__nfet_01v8 = {dev:.12e}")
        for mech, v in mechs.items():
            out.append(
                f"onoise_total.m.{inst}.msky130_fd_pr__nfet_01v8.{mech} = {v:.12e}")
    return "\n".join(out) + "\n"


def dev_entries(*pairs):
    """`pairs` of (instance, flicker_V, thermal_V) -> the entries mapping."""
    return {inst: {"1overf": fl, "id": th} for inst, fl, th in pairs}


class DeviceSplitParsing(unittest.TestCase):
    def test_the_vectors_are_read_as_rms_volts_not_variances(self):
        # The identity that defines the reading: sum(v_i^2) == onoise_total^2.
        # Reading them as variances over-counts by ~4e4 on the real block, so
        # this is the single most load-bearing assumption of the split.
        e = dev_entries(("xint.xota.xm1", 3.0e-5, 4.0e-5),
                        ("xint.xota.xm2", 0.0, 1.2e-4))
        total = math.sqrt(3.0e-5 ** 2 + 4.0e-5 ** 2 + 1.2e-4 ** 2)
        b = rn.device_block(rn.parse_device_print(dev_print(total, e))["inband_nqci"])
        self.assertAlmostEqual(b["closure_devices_rel"], 0.0, places=12)
        self.assertAlmostEqual(b["closure_mechanisms_rel"], 0.0, places=12)
        self.assertAlmostEqual(b["total_V2"], total ** 2, places=20)

    def test_the_mechanism_split_separates_flicker_from_thermal(self):
        e = dev_entries(("xint.xota.xm1", 3.0e-5, 4.0e-5))
        b = rn.device_block(rn.parse_device_print(
            dev_print(5.0e-5, e))["inband_nqci"])
        self.assertAlmostEqual(b["flicker_V2"], 9.0e-10, places=20)
        self.assertAlmostEqual(b["thermal_and_shot_V2"], 1.6e-09, places=20)
        self.assertAlmostEqual(b["flicker_share"], 0.36, places=12)
        self.assertAlmostEqual(b["thermal_and_shot_share"], 0.64, places=12)
        self.assertAlmostEqual(b["flicker_share"] + b["thermal_and_shot_share"],
                               1.0, places=12)

    def test_the_named_devices_reach_the_coverage_target(self):
        # Four equal devices at 25% each: three of them reach 75%, so the list
        # must run to the fourth to cross 90%.
        e = dev_entries(*[(f"xint.xota.xm{i}", 1.0e-5, 0.0) for i in range(1, 5)])
        b = rn.device_block(rn.parse_device_print(
            dev_print(2.0e-5, e))["inband_nqci"])
        self.assertEqual(len(b["devices_to_coverage"]), 4)
        self.assertGreaterEqual(b["devices_to_coverage_share"], rn.DEV_COVERAGE)
        self.assertEqual(b["coverage_target"], 0.90)

    def test_one_dominant_device_ends_the_list_early(self):
        e = dev_entries(("xint.xota.xm1", 1.0e-4, 0.0),
                        *[(f"xint.xsin_p_n{i}", 1.0e-7, 0.0) for i in range(1, 20)])
        b = rn.device_block(rn.parse_device_print(
            dev_print(1.0e-4, e))["inband_nqci"])
        self.assertEqual([d["instance"] for d in b["devices_to_coverage"]],
                         ["xint.xota.xm1"])
        self.assertEqual(b["device_count"], 20)

    def test_the_devices_are_ranked_loudest_first(self):
        e = dev_entries(("xint.xota.quiet", 1.0e-6, 0.0),
                        ("xint.xota.loud", 1.0e-4, 0.0),
                        ("xint.xota.mid", 1.0e-5, 0.0))
        b = rn.device_block(rn.parse_device_print(
            dev_print(1.0e-4, e))["inband_nqci"])
        shares = [d["share"] for d in b["devices_to_coverage"]]
        self.assertEqual(shares, sorted(shares, reverse=True))
        self.assertEqual(b["devices_to_coverage"][0]["instance"], "xint.xota.loud")

    def test_the_instance_path_strips_the_model_and_the_m_prefix(self):
        e = dev_entries(("xint.xota.xm1", 1.0e-5, 0.0))
        b = rn.device_block(rn.parse_device_print(
            dev_print(1.0e-5, e))["inband_nqci"])
        self.assertEqual(b["devices_to_coverage"][0]["instance"], "xint.xota.xm1")

    def test_every_block_of_the_run_is_parsed_separately(self):
        text = "".join(dev_print(1.0e-5, dev_entries(("xint.xota.xm1", 1.0e-5, 0.0)),
                                 tag=tag) for tag, *_ in rn.DEV_BLOCKS)
        blocks = rn.parse_device_print(text)
        self.assertEqual(sorted(blocks), sorted(t for t, *_ in rn.DEV_BLOCKS))
        self.assertEqual(len(rn.DEV_BLOCKS), 4)

    def test_lines_before_any_block_marker_are_ignored(self):
        text = "onoise_total = 9.9e-1\n" + dev_print(
            1.0e-5, dev_entries(("xint.xota.xm1", 1.0e-5, 0.0)))
        b = rn.parse_device_print(text)["inband_nqci"]
        self.assertAlmostEqual(b["total_V2"], 1.0e-10, places=20)

    def test_the_four_blocks_cover_both_outputs_and_both_lower_edges(self):
        nodes = {node for _, node, _, _ in rn.DEV_BLOCKS}
        self.assertEqual(nodes, {"v(nqci)", "v(vod)"})
        los = {lo for _, _, lo, _ in rn.DEV_BLOCKS}
        self.assertEqual(los, {mkn.F_LO, mkn.AUDIO_LO_HZ})
        for _, _, _, hi in rn.DEV_BLOCKS:
            self.assertEqual(hi, mkn.BW_HZ)

    def test_the_summary_pts_exceeds_any_plausible_point_count(self):
        # One summary block per analysis depends on this; a value below the
        # point count would emit several and the parse would sum them twice.
        pts = mkn.PTS_PER_DECADE * math.log10(mkn.F_HI / mkn.F_LO)
        self.assertGreater(rn.DEV_PTS_PER_SUMMARY, 10 * pts)

    def test_flicker_is_the_only_non_thermal_mechanism(self):
        self.assertIn(rn.DEV_FLICKER, rn.DEV_MECHANISMS)
        self.assertEqual(rn.DEV_FLICKER, "1overf")
        # Everything else ngspice can emit for a BSIM4 device is thermal or
        # gate-leakage shot noise, which the record folds into the thermal side.
        for m in rn.DEV_MECHANISMS:
            self.assertTrue(m == "1overf" or m[0] in "irq", m)

    def test_a_decomposition_that_does_not_close_is_outside_the_gate(self):
        # The variance-vs-RMS misreading inflates the sum by ~4e4; any closure
        # that far out must land outside DEV_CLOSURE_TOL so device_split()
        # refuses rather than recording an untrustworthy split.
        e = dev_entries(("xint.xota.xm1", 3.0e-5, 4.0e-5))
        wrong_total = 5.0e-5 * 10.0                      # total 20 dB off
        b = rn.device_block(rn.parse_device_print(
            dev_print(wrong_total, e))["inband_nqci"])
        self.assertGreater(abs(b["closure_devices_rel"]), rn.DEV_CLOSURE_TOL)
        self.assertGreater(abs(b["closure_mechanisms_rel"]), rn.DEV_CLOSURE_TOL)
        self.assertEqual(b["closure_tol"], rn.DEV_CLOSURE_TOL)


class DeviceGeometry(unittest.TestCase):
    def setUp(self):
        self.geo = rn.device_geometry()

    def test_the_ota_input_pair_is_found_with_its_drawn_geometry(self):
        # #138 names XM1/XM2 (W 16 / L 0.5) as the likely cause; the geometry
        # the split quotes beside them has to come from the netlist, not here.
        for k in ("xm1", "xm2"):
            g = self.geo[k]
            self.assertEqual(g["design_instance"], k.upper())
            self.assertEqual(g["model"], "sky130_fd_pr__nfet_01v8")
            self.assertEqual((g["W_um"], g["L_um"]), (16.0, 0.5))
            self.assertEqual(g["netlist"], "design/ota/ota_fd.spice")

    def test_devices_from_both_design_netlists_are_indexed(self):
        self.assertEqual(self.geo["xsci_p"]["netlist"],
                         "design/integrator/integrator.spice")
        self.assertEqual(self.geo["xm1"]["netlist"], "design/ota/ota_fd.spice")

    def test_the_key_is_the_ngspice_flattened_instance_name(self):
        # `xint.xota.xm1` -> `xm1`: the leading X is part of the key, which is
        # the bug this test exists for. A key of `m1` silently finds nothing
        # and every named device loses its geometry.
        self.assertIn("xm1", self.geo)
        self.assertNotIn("m1", self.geo)

    def test_name_devices_adds_geometry_without_losing_the_flat_path(self):
        named = rn.name_devices(
            [{"instance": "xint.xota.xm1", "var_V2": 1.0, "share": 1.0}], self.geo)
        self.assertEqual(named[0]["instance"], "xint.xota.xm1")
        self.assertEqual(named[0]["design_instance"], "XM1")
        self.assertAlmostEqual(named[0]["wl_um2"], 8.0, places=9)

    def test_an_unknown_instance_is_left_alone_rather_than_crashing(self):
        named = rn.name_devices(
            [{"instance": "xint.not_a_device", "var_V2": 1.0, "share": 1.0}], self.geo)
        self.assertNotIn("design_instance", named[0])
        self.assertEqual(named[0]["instance"], "xint.not_a_device")

    def test_the_bias_devices_have_a_much_smaller_gate_area_than_the_pair(self):
        # Flicker power goes as 1/(W*L), so this is the ratio that explains why
        # a bias device competes with the input pair in band. Read from the
        # netlist, so it tracks a resizing in #143 rather than going stale.
        pair = self.geo["xm1"]["W_um"] * self.geo["xm1"]["L_um"]
        bias = self.geo["xmn1"]["W_um"] * self.geo["xmn1"]["L_um"]
        self.assertGreater(pair, bias)
        self.assertAlmostEqual(pair / bias, 8.0, places=9)

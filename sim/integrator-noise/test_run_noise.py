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
            deck = tmpl.replace("@VARIANT@", v).replace("@VARIANTNOTE@", d["note"])
            for k, val in d["clocks"].items():
                deck = deck.replace(f"@{k}@", val)
            self.assertEqual((HERE / f"integrator_noise_{v}.cir").read_text(), deck, v)
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

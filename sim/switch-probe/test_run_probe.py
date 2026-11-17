"""Tests for the switch-probe runner's pure parts. Run:
python3 -I -m unittest discover -s sim/switch-probe -p 'test_*.py'

No ngspice, no PDK, no klt: only `tg_points()`, `sci_points()`, `vtag()`,
`geom()` and the CLI's point-set / result-file wiring are exercised. The
simulated numbers themselves are evidence, not test fixtures -- they live in
probe-i92.json / probe-i106.json / probe-i147.json and are reproduced by
re-running the bench, not asserted here.

What is pinned here (issue #106): the pass-gate sweep really covers the input
range spec row 11 asks for, at the resolution the bench claims, and its device
pair really is the one design/integrator/integrator.spice builds. A later edit
that narrows the sweep or drifts from the netlist fails a test instead of
quietly shrinking the evidence.

What is pinned here for issue #147: the `Sci` sweep reuses the i106 condition
list and voltage grid rather than restating them, its as-built variant really
is the NMOS-only pair the cell builds (PMOS absent), and its variant pairs are
the precedents the record names them as. It also pins the committed decks'
bytes against the hashes in probe-i92.json / probe-i106.json, so a later edit
of those templates fails here instead of silently invalidating the records'
provenance.
"""
import importlib.util
import pathlib
import re
import unittest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]


def load_runner():
    """Load run_probe.py by path: 'switch-probe' is not an importable name."""
    spec = importlib.util.spec_from_file_location(
        "run_probe_under_test", HERE / "run_probe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = load_runner()

# spec row 11 / section 5.4: each input side within +/-0.3 V of vcm = 0.9 V.
RANGE_LO, RANGE_HI = 0.6, 1.2
RESOLUTION = 0.05 + 1e-9    # the resolution the module comment claims


class Vtag(unittest.TestCase):
    def test_decimal_point_and_sign_become_name_safe(self):
        self.assertEqual(R.vtag(0.45), "0p45")
        self.assertEqual(R.vtag(-40), "m40")
        self.assertEqual(R.vtag(1.62), "1p62")

    def test_tags_never_contain_a_character_a_key_cannot_hold(self):
        for x in R.TG_VIN + R.I129_VIN + tuple(t for _, t, _ in R.TG_CONDITIONS):
            self.assertRegex(R.vtag(x), r"^[0-9pm]+$", f"{x!r} tagged unsafely")


class PassGateSweep(unittest.TestCase):
    def test_sweep_spans_the_reference_rails(self):
        """0.3 V and 1.5 V: the DR-005 rails the same gate family also passes."""
        self.assertLessEqual(min(R.TG_VIN), 0.3)
        self.assertGreaterEqual(max(R.TG_VIN), 1.5)

    def test_input_range_is_resolved_at_the_claimed_step(self):
        inside = sorted(v for v in R.TG_VIN if RANGE_LO - 1e-9 <= v <= RANGE_HI + 1e-9)
        self.assertEqual(inside[0], RANGE_LO)
        self.assertEqual(inside[-1], RANGE_HI)
        gaps = [(b - a, a, b) for a, b in zip(inside, inside[1:])]
        worst = max(gaps)
        self.assertLessEqual(
            worst[0], RESOLUTION,
            f"{RANGE_LO}..{RANGE_HI} V is claimed resolved at 50 mV, but there is a "
            f"{worst[0] * 1e3:.0f} mV gap between {worst[1]} and {worst[2]} V")

    def test_vcm_itself_is_a_point(self):
        """Ron peaks at vcm, which is where a delta-sigma input spends its time."""
        self.assertIn(R.VCM, R.TG_VIN)

    def test_every_process_skew_is_probed_at_the_low_cold_corner(self):
        low_cold = {c for c, t, v in R.TG_CONDITIONS if (t, v) == (-40, 1.620)}
        self.assertEqual(low_cold, {"tt", "ss", "ff", "sf", "fs"})

    def test_the_sizing_md_probe_condition_is_reproduced_too(self):
        """SIZING.md's "Probe Ron" column is tt/27 C/1.8 V (its "Labelling")."""
        self.assertIn(("tt", 27, 1.800), R.TG_CONDITIONS)

    def test_one_row_per_condition_and_voltage_with_unique_keys(self):
        pts = R.tg_points()
        self.assertEqual(len(pts), len(R.TG_CONDITIONS) * len(R.TG_VIN))
        keys = [p[0] for p in pts]
        self.assertEqual(len(set(keys)), len(keys), "duplicate point key")

    def test_a_key_names_its_whole_condition(self):
        """A result file is read by key, so the key has to be self-describing."""
        by_key = {p[0]: p for p in R.tg_points()}
        key = "tg_sin_ss_m40c_1p62v_0p9v"
        self.assertIn(key, by_key)
        self.assertEqual(by_key[key][1:], ("ss", -40, 1.620, 0.9))


class DevicePair(unittest.TestCase):
    """The probed pairs and the cell's pairs, after issue #129's change.

    The i106 bench (`TG_NMOS`/`TG_PMOS`) documents what probe-i106.json
    probed: the PRE-#129 standard-Vth gate. That pair is pinned as history --
    `Sr_*`/`Mra_*`/`Mrb_*` still build it, and the i106 record remains the
    before side of the sizing argument. The `Sin` halves themselves are the
    low-Vth pair issue #129 chose, and the tests below hold them to the
    committed sizing sweep's candidate set.
    """

    def setUp(self):
        # Device parameters continue onto `+` lines, so the physical lines have
        # to be joined before a parameter can be looked up -- the same join
        # self_check() does against this file at run time.
        text = (R.REPO / "design/integrator/integrator.spice").read_text()
        joined, cur = [], None
        for ln in text.splitlines():
            if ln.startswith("+") and cur is not None:
                cur += " " + ln[1:].strip()
            else:
                if cur is not None:
                    joined.append(cur)
                cur = ln
        if cur is not None:
            joined.append(cur)
        self.lines = joined

    def _line(self, inst):
        for ln in self.lines:
            m = re.match(rf"{inst} \S+ \S+ \S+ \S+ (sky130_fd_pr__\S+) (.*)$", ln)
            if m:
                return m.group(1), R.kv(m.group(2))
        self.fail(f"{inst} not found in integrator.spice")

    def _sweep_candidate_widths(self):
        import json
        rec = json.loads((HERE / "probe-i129.json").read_text())
        out = set()
        for k, v in rec["method"]["i129_candidates"].items():
            out.add((v["nmos"]["W_um"], v["pmos"]["W_um"]))
        return out

    def test_the_i106_bench_still_documents_the_pre_change_gate(self):
        """probe-i106.json's pair is history and must not be silently rewritten."""
        self.assertEqual(R.TG_NMOS, ("sky130_fd_pr__nfet_01v8", 4.0, 0.15))
        self.assertEqual(R.TG_PMOS, ("sky130_fd_pr__pfet_01v8", 8.0, 0.15))

    def test_sin_halves_are_low_vth(self):
        """Issue #129's remedy: all four `Sin` devices are `*_lvt`."""
        for inst in ("XSin_p_n", "XSin_p_p", "XSin_n_n", "XSin_n_p"):
            model, _ = self._line(inst)
            self.assertIn("lvt", model, f"{inst} is not a low-Vth device")

    def test_sin_lengths_are_the_lvt_models_own(self):
        """`nfet_01v8_lvt` at L 0.15; `pfet_01v8_lvt` at its L = 0.35 minimum."""
        for inst in ("XSin_p_n", "XSin_n_n"):
            model, got = self._line(inst)
            self.assertEqual(model, R.I129_NMOS[0], inst)
            self.assertEqual(got["L"], R.I129_NMOS[1], inst)
        for inst in ("XSin_p_p", "XSin_n_p"):
            model, got = self._line(inst)
            self.assertEqual(model, R.I129_PMOS[0], inst)
            self.assertEqual(got["L"], R.I129_PMOS[1], inst)

    def test_sin_widths_are_a_committed_sweep_candidate(self):
        """The chosen size is read from probe-i129.json, not invented."""
        sides = []
        for side in ("p", "n"):
            _, n = self._line(f"XSin_{side}_n")
            _, p = self._line(f"XSin_{side}_p")
            sides.append((n["W"], p["W"]))
        self.assertEqual(sides[0], sides[1], "the two sides differ")
        self.assertIn(sides[0], self._sweep_candidate_widths(),
                      f"W pair {sides[0]} is not one of the swept candidates")

    def test_the_other_gate_families_are_still_the_standard_pair(self):
        """Out of #129's scope: `Sr`/`Mra`/`Mrb` keep the pre-#129 pair."""
        for inst in ("XSr_p_n", "XSr_p_p", "XMra_p_n", "XMra_p_p",
                     "XMrb_p_n", "XMrb_p_p"):
            model, got = self._line(inst)
            self.assertIn((model, got["W"], got["L"]), (R.TG_NMOS, R.TG_PMOS),
                          f"{inst} drifted from the standard-Vth pair")

    def test_geom_reproduces_both_sin_halves_from_the_netlist(self):
        """geom() is shared with the i92 rows; self_check() gates it at run time."""
        for inst in ("XSin_p_n", "XSin_p_p"):
            _, got = self._line(inst)
            want = R.kv(R.geom(got["W"], got["L"]))
            for k, v in want.items():
                self.assertIn(k, got, f"{inst} has no {k}")
                self.assertAlmostEqual(got[k], v, delta=1e-6 * max(1.0, abs(v)),
                                       msg=f"{inst} {k}")

    # -------------------------------------- issue #147: the Sci pair ----

    def test_sci_nmos_matches_xsci_p(self):
        """The as-built probed NMOS is the lone device the cell builds, no lvt drift."""
        model, got = self._line("XSci_p")
        self.assertEqual(R.SCI_NMOS, (model, got["W"], got["L"]))

    def test_sci_as_built_variant_is_the_pre_change_counterfactual(self):
        """probe-i147.json's as_built rows document the cell BEFORE issue #147
        added the PMOS half: a lone nfet_01v8_lvt on phi1e, no phi1eb-gated
        pfet. The committed record pins that cell's netlist hash; the current
        cell's hash differs, which is what makes the record historical
        evidence rather than a description of this file."""
        nmos, pmos, _ = R.SCI_VARIANTS["as_built"]
        self.assertEqual(nmos, R.SCI_NMOS)
        self.assertIsNone(pmos)
        import hashlib
        import json
        rec = json.loads((HERE / "probe-i147.json").read_text())
        now = hashlib.sha256(
            (REPO / "design/integrator/integrator.spice").read_bytes()).hexdigest()
        self.assertNotEqual(rec["integrator_netlist_sha256"], now,
                            "probe-i147.json was measured on the pre-#147 cell; "
                            "if the cell reverted, re-measure instead of relabelling")

    def test_the_cell_now_builds_the_p_sti4_pair(self):
        """The #147 decision, pinned where it cannot silently revert: the cell
        builds Sci/Scr with a PMOS half at the Sti precedent -- pfet_01v8_lvt
        W 4 / L 0.35, drain on the top plate, source on vcm, gate on the local
        phi1eb, n-well at vdda -- which is the p_sti4 variant's pair."""
        for inst, top in (("XSci_p_p", "tpi_p"), ("XSci_n_p", "tpi_n"),
                          ("XScr_p_p", "tpr_p"), ("XScr_n_p", "tpr_n")):
            model, got = self._line(inst)
            self.assertEqual(R.SCI_PMOS_STI, (model, got["W"], got["L"]),
                             f"{inst} device pair drifted")
            ln = next(l for l in self.lines if l.split()[0] == inst)
            self.assertEqual(ln.split()[1:5], [top, "phi1eb", "vcm", "vdda"],
                             f"{inst} terminals drifted")
        nmos, pmos, _ = R.SCI_VARIANTS["p_sti4"]
        self.assertIs(pmos, R.SCI_PMOS_STI)

    def test_the_cell_has_the_local_phi1eb_inverter(self):
        """The phi1eb complement is generated in-cell by the same pattern as
        phi2b (XIphi2b_n/p): nfet_01v8 W 2 / pfet_01v8 W 4, both L 0.15 m 4,
        input phi1e, output phi1eb -- so the port list stays untouched."""
        for inst, model, w in (("XIphi1eb_n", "sky130_fd_pr__nfet_01v8", 2),
                               ("XIphi1eb_p", "sky130_fd_pr__pfet_01v8", 4)):
            got_model, got = self._line(inst)
            self.assertEqual(got_model, model, f"{inst} model")
            self.assertEqual(got["W"], w, f"{inst} W")
            self.assertEqual(got["L"], 0.15, f"{inst} L")
        for inst, d, g, s, b in (
                ("XIphi1eb_n", "phi1eb", "phi1e", "vssa", "vssa"),
                ("XIphi1eb_p", "vdda", "phi1e", "phi1eb", "vdda")):
            ln = next(l for l in self.lines if l.split()[0] == inst)
            self.assertEqual(ln.split()[1:5], [d, g, s, b], f"{inst} terminals")

    def test_sci_variant_pmos_pairs_are_the_cell_own_precedents(self):
        """p_sti4/p_sbi24 name the #92 precedents; pin them to their devices."""
        model, got = self._line("XSti_p_p")
        self.assertEqual(R.SCI_PMOS_STI, (model, got["W"], got["L"]))
        model, got = self._line("XSbi_p_p")
        self.assertEqual(R.SCI_PMOS_SBI, (model, got["W"], got["L"]))
        self.assertEqual(R.SCI_VARIANTS["p_sti4"][1], R.SCI_PMOS_STI)
        self.assertEqual(R.SCI_VARIANTS["p_sbi24"][1], R.SCI_PMOS_SBI)

    def test_sci_wide_counterfactual_is_the_same_device_wider(self):
        """n96 widens the as-built NMOS itself -- not a model or L change."""
        self.assertEqual(R.SCI_NMOS_WIDE[0], R.SCI_NMOS[0])
        self.assertEqual(R.SCI_NMOS_WIDE[2], R.SCI_NMOS[2])
        self.assertGreater(R.SCI_NMOS_WIDE[1], R.SCI_NMOS[1])


class DeckTemplate(unittest.TestCase):
    def test_every_placeholder_the_runner_substitutes_exists_in_the_deck(self):
        deck = (HERE / "tg_probe.cir.tmpl").read_text()
        for ph in ("{{PDK_LIB}}", "{{CORNER}}", "{{TEMP}}", "{{VDDA}}", "{{VS}}",
                   "{{VD}}", "{{VGN}}", "{{VGP}}", "{{NMODEL}}", "{{NGEOM}}",
                   "{{PMODEL}}", "{{PGEOM}}", "{{BIAS}}"):
            self.assertIn(ph, deck, f"{ph} is substituted but not in the deck")

    def test_both_halves_sit_between_the_same_two_nodes(self):
        """Parallel, not series: the 0 V ammeters must not change the topology."""
        deck = (HERE / "tg_probe.cir.tmpl").read_text()
        self.assertIn("Van dn d 0", deck)
        self.assertIn("Vap dp d 0", deck)
        self.assertRegex(deck, r"(?m)^X1 dn gn s 0 ")
        self.assertRegex(deck, r"(?m)^X2 dp gp s vdda ")

    def test_the_i92_deck_is_not_reused_for_the_pass_gate(self):
        """probe-i92.json records switch_probe.cir.tmpl's sha; it must not move."""
        self.assertNotEqual((HERE / "tg_probe.cir.tmpl").read_bytes(),
                            (HERE / "switch_probe.cir.tmpl").read_bytes())


class SciDeck(unittest.TestCase):
    """The i147 deck generalizes the tg deck: the PMOS half is a whole line."""

    def test_every_placeholder_the_runner_substitutes_exists_in_the_deck(self):
        deck = (HERE / "sci_probe.cir.tmpl").read_text()
        for ph in ("{{PDK_LIB}}", "{{CORNER}}", "{{TEMP}}", "{{VDDA}}", "{{VS}}",
                   "{{VD}}", "{{VGN}}", "{{VGP}}", "{{NMODEL}}", "{{NGEOM}}",
                   "{{PMOS_LINE}}"):
            self.assertIn(ph, deck, f"{ph} is substituted but not in the deck")

    def test_the_deck_prints_currents_only_ron_is_derived_by_the_runner(self):
        """Regression (both first sweep attempts aborted here): on NMOS-only
        rows the branch current underflows to the gmin floor and an in-deck
        `bias/i_dev` divide aborts the point. Ron is the runner's job --
        `ron_from_current` reports a gmin-floor current as null + flag."""
        deck = (HERE / "sci_probe.cir.tmpl").read_text()
        self.assertNotIn("{{BIAS}}", deck, "the deck must not compute Ron")
        self.assertNotRegex(deck, r"(?m)^\s*let\s+r_on\b",
                            "the deck must not compute Ron")
        self.assertIn("print i_dev i_nmos i_pmos", deck)

    def test_the_pmos_half_is_a_whole_line_not_model_placeholders(self):
        """So the as-built rows can leave it out entirely, not fake a device."""
        deck = (HERE / "sci_probe.cir.tmpl").read_text()
        self.assertNotIn("{{PMODEL}}", deck)
        self.assertNotIn("{{PGEOM}}", deck)
        self.assertIn("{{PMOS_LINE}}", deck)

    def test_both_halves_sit_between_the_same_two_nodes(self):
        deck = (HERE / "sci_probe.cir.tmpl").read_text()
        self.assertIn("Van dn d 0", deck)
        self.assertIn("Vap dp d 0", deck)
        self.assertRegex(deck, r"(?m)^X1 dn gn s 0 ")
        self.assertRegex(deck, r"(?m)^\{\{PMOS_LINE\}\}$")

    def test_the_ammeters_and_the_share_measurement_survive_an_absent_pmos(self):
        """With no X2 substituted, `dp` hangs off Vap alone, i_pmos reads 0,
        and nmos_current_share stays well-defined -- that is what the record's
        PMOS-absent rows rely on."""
        deck = (HERE / "sci_probe.cir.tmpl").read_text()
        self.assertIn("Vap dp d 0", deck)
        self.assertIn("let i_pmos = abs(i(vap))", deck)
        self.assertIn("let i_nmos = abs(i(van))", deck)

    def test_the_i147_deck_is_its_own_template(self):
        """Not a copy drift: a distinct file, so tg_probe.cir.tmpl's bytes --
        and probe-i106.json's pinned tg_deck_sha256 -- stay untouched."""
        self.assertNotEqual((HERE / "sci_probe.cir.tmpl").read_bytes(),
                            (HERE / "tg_probe.cir.tmpl").read_bytes())


class RonFromCurrent(unittest.TestCase):
    """Ron = bias / I is derived by the runner, with the gmin floor explicit.

    The as-built Sci rows at the top of the sweep resolve zero branch current
    (the divide-by-zero that aborted both first sweep attempts); those rows
    must report null + `current_at_gmin_floor`, never a floored fake number.
    """

    def test_a_real_current_divides(self):
        self.assertAlmostEqual(R.ron_from_current(1e-3), 10.0)
        self.assertAlmostEqual(R.ron_from_current(7.5e-13), R.RON_BIAS / 7.5e-13)

    def test_the_gmin_floor_is_null_not_a_number(self):
        self.assertIsNone(R.ron_from_current(0.0))
        self.assertIsNone(R.ron_from_current(R.GMIN_FLOOR),
                          "at the floor itself, Ron is not a measurement")
        self.assertIsNone(R.ron_from_current(1e-18))

    def test_the_floor_boundary_is_inclusive_and_just_above_is_measured(self):
        self.assertIsNone(R.ron_from_current(R.GMIN_FLOOR))
        self.assertIsNotNone(R.ron_from_current(R.GMIN_FLOOR * (1 + 1e-9)))

    def test_the_floor_matches_what_the_decks_set(self):
        """`option gmin=1e-15` in both tg decks; the runner's floor is that."""
        for tmpl in ("tg_probe.cir.tmpl", "sci_probe.cir.tmpl"):
            deck = (HERE / tmpl).read_text()
            self.assertIn("option gmin=1e-15", deck)
        self.assertEqual(R.GMIN_FLOOR, 1e-15)
        self.assertAlmostEqual(R.RON_BIAS / R.GMIN_FLOOR, 1e13)


class SciSweep(unittest.TestCase):
    """The i147 set reuses the i106 grid and probes the cell's own devices."""

    def test_three_sets_are_selectable(self):
        self.assertEqual(R.POINT_SETS, ("i92", "i106", "i147", "i129"))

    def test_the_condition_list_is_reused_not_restated(self):
        """TG_CONDITIONS by identity: one list of conditions, two consumers."""
        for name in R.SCI_FULL_CONDITION_VARIANTS:
            conds = {(c, t, v) for c, t, v in R.TG_CONDITIONS}
            rows = {p[2:5] for p in R.sci_points() if p[1] == name}
            self.assertEqual(rows, conds,
                             f"{name} does not cover TG_CONDITIONS exactly")

    def test_the_voltage_grid_is_reused_not_restated(self):
        for name in R.SCI_FULL_CONDITION_VARIANTS:
            vins = {p[5] for p in R.sci_points() if p[1] == name}
            self.assertEqual(vins, set(R.TG_VIN),
                             f"{name} does not sweep TG_VIN exactly")

    def test_row_count_and_unique_keys(self):
        full = [n for n in R.SCI_VARIANTS if n in R.SCI_FULL_CONDITION_VARIANTS]
        fs_only = [n for n in R.SCI_VARIANTS if n not in R.SCI_FULL_CONDITION_VARIANTS]
        want = ((len(full) * len(R.TG_CONDITIONS) + len(fs_only))
                * len(R.TG_VIN))
        pts = R.sci_points()
        self.assertEqual(len(pts), want)
        self.assertEqual(len({p[0] for p in pts}), len(pts), "duplicate point key")

    def test_full_condition_variants_are_the_decision_pair(self):
        """AC 1: the as-built switch and the candidate remedy over the whole
        grid; the size cross-check and counterfactual at the binding corner."""
        self.assertEqual(R.SCI_FULL_CONDITION_VARIANTS, ("as_built", "p_sti4"))
        for name in ("p_sbi24", "n96"):
            conds = {p[2:5] for p in R.sci_points() if p[1] == name}
            self.assertEqual(conds, {("fs", -40, 1.620)},
                             f"{name} must be fs-only (binding corner)")

    def test_a_key_names_its_whole_condition_and_variant(self):
        by_key = {p[0]: p for p in R.sci_points()}
        key = "tg_sci_as_built_fs_m40c_1p62v_0p95v"
        self.assertIn(key, by_key)
        self.assertEqual(by_key[key][1:], ("as_built", "fs", -40, 1.620, 0.95))
        key = "tg_sci_n96_fs_m40c_1p62v_1p2v"
        self.assertIn(key, by_key)
        self.assertEqual(by_key[key][1:], ("n96", "fs", -40, 1.620, 1.2))

    def test_the_binding_voltage_is_inside_every_variant_sweep(self):
        """tpip_s4 = 0.97866 V at the phi1e fall (record-i106.json); the sweep
        must resolve the curve around it. 0.95 and 1.0 bracket it at 50 mV."""
        for name in R.SCI_VARIANTS:
            vins = {p[5] for p in R.sci_points() if p[1] == name}
            self.assertIn(0.95, vins)
            self.assertIn(1.0, vins)


class CommittedRecordProvenance(unittest.TestCase):
    """The committed records pin the deck bytes they were measured with.

    probe-i92.json / probe-i106.json are append-only evidence; editing their
    templates would leave the records pointing at bytes that no longer exist.
    These checks fail on such an edit, before CI or a re-run has to discover
    it. (probe-i147.json pins its own deck the same way, via the runner.)
    """

    def _sha(self, path):
        import hashlib
        return hashlib.sha256((HERE / path).read_bytes()).hexdigest()

    def test_probe_i92_still_matches_its_deck(self):
        import json
        rec = json.loads((HERE / "probe-i92.json").read_text())
        self.assertEqual(rec["deck_sha256"], self._sha("switch_probe.cir.tmpl"))

    def test_probe_i106_still_matches_its_deck(self):
        import json
        rec = json.loads((HERE / "probe-i106.json").read_text())
        self.assertEqual(rec["tg_deck_sha256"], self._sha("tg_probe.cir.tmpl"))


class PointSets(unittest.TestCase):
    def test_the_sets_are_selectable(self):
        self.assertEqual(set(R.POINT_SETS), {"i92", "i106", "i147", "i129"})

    def test_the_i92_rows_are_untouched_by_this_issue(self):
        """The single-device rows probe-i92.json was written from.

        Compared as a key SET, not a count: `ron_pfet_lvt_w48_fs` appears twice
        in POINTS (once in the five-skew table, once in the 1/W scaling row), so
        there are 22 rows and 21 result keys. Pre-existing, harmless -- the row
        is simulated twice and lands on the same value -- and out of scope here.
        """
        import json
        committed = json.loads((HERE / "probe-i92.json").read_text())["points"]
        self.assertEqual({p[0] for p in R.POINTS}, set(committed),
                         "the i92 point set drifted from the committed record")
        self.assertEqual({p[7] for p in R.POINTS}, {"ron", "leakage"})

    def test_the_i106_rows_are_untouched_by_this_issue(self):
        """The as-built-gate sweep probe-i106.json was written from."""
        import json
        committed = json.loads((HERE / "probe-i106.json").read_text())["points"]
        self.assertEqual({p[0] for p in R.TG_POINTS}, set(committed),
                         "the i106 point set drifted from the committed record")

    def test_result_files_are_one_per_set(self):
        """Append-only: the i106 rows may not be written into probe-i92.json."""
        self.assertTrue((HERE / "probe-i92.json").exists())
        self.assertNotEqual("probe-i92.json", "probe-i106.json")
        self.assertNotEqual("probe-i106.json", "probe-i129.json")


class SizingSweep(unittest.TestCase):
    """The i129 candidate set and sweep shape (issue #129)."""

    def test_candidates_start_at_the_vcm_switch_geometry_and_go_down(self):
        """The #92 remedy's widths are the ceiling; `Sin` loads the input."""
        self.assertIn((12, 24), R.I129_CANDIDATES)
        for nw, pw in R.I129_CANDIDATES:
            self.assertLessEqual(nw, 12, f"NMOS candidate W {nw} exceeds the vcm switch")
            self.assertLessEqual(pw, 24, f"PMOS candidate W {pw} exceeds the vcm switch")

    def test_the_lvt_models_sit_at_their_own_lengths(self):
        """nfet_01v8_lvt at L 0.15; pfet_01v8_lvt at its L = 0.35 minimum."""
        self.assertEqual(R.I129_NMOS, ("sky130_fd_pr__nfet_01v8_lvt", 0.15))
        self.assertEqual(R.I129_PMOS, ("sky130_fd_pr__pfet_01v8_lvt", 0.35))

    def test_the_sweep_spans_the_reference_rails_and_resolves_the_peak_window(self):
        """0.3 / 1.5 V for context; 0.7 .. 1.1 V at the i106 resolution."""
        self.assertLessEqual(min(R.I129_VIN), 0.3)
        self.assertGreaterEqual(max(R.I129_VIN), 1.5)
        inside = sorted(v for v in R.I129_VIN if 0.7 - 1e-9 <= v <= 1.1 + 1e-9)
        gaps = [b - a for a, b in zip(inside, inside[1:])]
        self.assertLessEqual(max(gaps), 0.05 + 1e-9,
                             "the 0.7..1.1 V peak window is claimed at 50 mV")
        self.assertIn(0.9, inside, "vcm itself must be a point")

    def test_the_conditions_are_the_i106_conditions(self):
        pts = R.i129_points()
        conds = {(p[7], p[8], p[9]) for p in pts}
        self.assertEqual(conds, set(R.TG_CONDITIONS))

    def test_one_row_per_candidate_condition_and_voltage_with_unique_keys(self):
        pts = R.i129_points()
        self.assertEqual(len(pts), len(R.I129_CANDIDATES)
                         * len(R.TG_CONDITIONS) * len(R.I129_VIN))
        keys = [p[0] for p in pts]
        self.assertEqual(len(set(keys)), len(keys), "duplicate point key")

    def test_a_key_names_its_whole_condition(self):
        by_key = {p[0]: p for p in R.i129_points()}
        key = "tg129_lvt_n12_p24_ss_m40c_1p62v_0p9v"
        self.assertIn(key, by_key)
        p = by_key[key]
        self.assertEqual(p[1:], (12, 24) + R.I129_NMOS + R.I129_PMOS
                         + ("ss", -40, 1.620, 0.9))

    def test_derived_reduces_each_candidate_to_its_peak(self):
        pts = R.i129_points()
        fake = {p[0]: {"ron_ohm": 100.0 + i, "vin_V": 0.9, "nmos_current_share": 0.4}
                for i, p in enumerate(pts)}
        d = R.i129_derived(fake)
        self.assertEqual(set(d), {f"nmos_w{nw:g}_pmos_w{pw:g}"
                                  for nw, pw in R.I129_CANDIDATES})
        for nw, pw in R.I129_CANDIDATES:
            blk = d[f"nmos_w{nw:g}_pmos_w{pw:g}"]
            self.assertEqual(len(blk["per_condition"]), len(R.TG_CONDITIONS))
            self.assertEqual(
                blk["overall_worst_peak_ron_ohm"],
                max(c["peak_ron_ohm"] for c in blk["per_condition"].values()))
            self.assertIn(blk["overall_worst_condition"], blk["per_condition"])

    def test_derived_takes_the_max_not_the_last(self):
        """A peak away from vcm must be found, wherever in the sweep it sits."""
        pts = R.i129_points()
        fake = {}
        for p in pts:
            peak = p[10] == 0.85        # the vin coordinate
            fake[p[0]] = {"ron_ohm": 900.0 if peak else 100.0,
                          "vin_V": p[10],
                          "nmos_current_share": 0.5}
        d = R.i129_derived(fake)
        for nw, pw in R.I129_CANDIDATES:
            blk = d[f"nmos_w{nw:g}_pmos_w{pw:g}"]
            self.assertEqual(blk["overall_worst_peak_ron_ohm"], 900.0)
            self.assertEqual(blk["overall_worst_peak_at_vin_V"], 0.85)


if __name__ == "__main__":
    unittest.main()

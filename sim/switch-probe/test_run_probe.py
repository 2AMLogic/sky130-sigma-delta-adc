"""Tests for the switch-probe runner's pure parts. Run:
python3 -I -m unittest discover -s sim/switch-probe -p 'test_*.py'

No ngspice, no PDK, no klt: only `tg_points()`, `vtag()`, `geom()` and the CLI's
point-set / result-file wiring are exercised. The simulated numbers themselves
are evidence, not test fixtures -- they live in probe-i92.json / probe-i106.json
and are reproduced by re-running the bench, not asserted here.

What is pinned here (issue #106): the pass-gate sweep really covers the input
range spec row 11 asks for, at the resolution the bench claims, and its device
pair really is the one design/integrator/integrator.spice builds. A later edit
that narrows the sweep or drifts from the netlist fails a test instead of
quietly shrinking the evidence.
"""
import importlib.util
import pathlib
import re
import unittest

HERE = pathlib.Path(__file__).resolve().parent


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
        for x in R.TG_VIN + tuple(t for _, t, _ in R.TG_CONDITIONS):
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
    """The probed pair must be the pair the cell actually builds."""

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

    def test_nmos_half_matches_xsin_p_n(self):
        model, got = self._line("XSin_p_n")
        self.assertEqual((model, got["W"], got["L"]), (R.TG_NMOS[0], 4.0, 0.15))
        self.assertEqual(R.TG_NMOS, (model, got["W"], got["L"]))

    def test_pmos_half_matches_xsin_p_p(self):
        model, got = self._line("XSin_p_p")
        self.assertEqual(R.TG_PMOS, (model, got["W"], got["L"]))

    def test_neither_half_is_low_vth(self):
        """The whole mechanism: unlike the phi2 switches #92 fixed, no lvt half."""
        self.assertNotIn("lvt", R.TG_NMOS[0])
        self.assertNotIn("lvt", R.TG_PMOS[0])

    def test_the_other_three_gate_families_are_the_same_pair(self):
        """So the record may name Sr/Mra/Mrb as sharing the measured curve."""
        for inst in ("XSr_p_n", "XSr_p_p", "XSin_n_n", "XSin_n_p"):
            model, got = self._line(inst)
            self.assertIn((model, got["W"], got["L"]), (R.TG_NMOS, R.TG_PMOS),
                          f"{inst} is not one of the probed devices")

    def test_geom_reproduces_both_halves_from_the_netlist(self):
        """geom() is shared with the i92 rows; self_check() gates it at run time."""
        for inst, (_, w, l) in (("XSin_p_n", (None, 4, 0.15)),
                                ("XSin_p_p", (None, 8, 0.15))):
            _, got = self._line(inst)
            want = R.kv(R.geom(w, l))
            for k, v in want.items():
                self.assertIn(k, got, f"{inst} has no {k}")
                self.assertAlmostEqual(got[k], v, delta=1e-6 * max(1.0, abs(v)),
                                       msg=f"{inst} {k}")


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


class PointSets(unittest.TestCase):
    def test_both_sets_are_selectable(self):
        self.assertEqual(R.POINT_SETS, ("i92", "i106"))

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

    def test_result_files_are_one_per_set(self):
        """Append-only: the i106 rows may not be written into probe-i92.json."""
        self.assertTrue((HERE / "probe-i92.json").exists())
        self.assertNotEqual("probe-i92.json", "probe-i106.json")


if __name__ == "__main__":
    unittest.main()

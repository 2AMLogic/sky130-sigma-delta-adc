"""Tests for the extracted-netlist parsers in layout/analog/layout_common.py
(issue #191). Run:
python3 -I -m unittest discover -s layout/analog -p 'test_layout_common.py'

No klt, no PDK, no EDA tool, no network. Two visibly separate groups:

- FixtureDrivenParserTests feed the parsers *captured* `klt extract` output
  (layout/analog/fixtures/*.extract.spice -- real extractor runs over the
  committed GDS, provenance in extract-fixtures.provenance.json) and assert
  the results against each cell's committed `extract-device-count.json` and
  the extractor's own device/net tallies. The expectations are read from the
  committed JSON, never retyped here, so this is a regression test on the
  evidence of record.

- SymmetricTerminalTests and ModelTokenTests are literal-token unit tests of
  the two pure predicates. The issue's "do not hand-write a netlist" rule is
  about the netlist-shape input -- a hand-written fixture would encode the
  parser's own assumption about `klt extract`'s output and then confirm it
  against itself. It does not extend to pure string/tuple predicates, whose
  contract is their specification; literals are the only way to reach the
  two axes the captured netlists cannot exercise (the bare `nfet`/`pfet`
  short form, absent from both captures, and the mid-token negative, the
  one behaviour #179 changed).

What is pinned here:

- parse_extract_devices reproduces both cells' committed raw_counts AND
  merged_counts model for model; extract_nets reproduces the committed
  extracted net counts (21 for ota_fd, 43 for the integrator).
- The parser's raw total and net count equal the extractor's own
  device_count / net_count for the same fixture -- a tally the parser did
  not compute, so a change in `klt extract`'s output shape diverges instead
  of passing silently.
- The raw -> merged merge bites (ota_fd: 50 -> 14 nfet, 31 -> 9 pfet), and
  merged collapses to the per-model count of distinct symmetric-terminal
  groups, so dropping the grouping or the terminal normalisation turns the
  suite red rather than silently passing.
- The integrator subtraction model (merged(integrator) - merged(ota_fd))
  reproduces the committed found_own_devices: this cell's own 50 devices.
- Parser edges: empty and comment-only netlists return empty counters and
  an empty net list rather than raising; a `+` continuation line is never
  parsed as a device (both captured netlists wrap PS=/PD= onto one); an
  X-device wrapped at any token -- the model token or the terminals on the
  `+` line -- folds into one logical line and is counted exactly once
  (issue #204: the wrapped shapes used to be dropped silently); a joined
  label net name (`outn|voutn`) survives extract_nets intact.
"""
import contextlib
import io
import json
import pathlib
import shutil
import tempfile
import unittest
from collections import Counter
from unittest import mock

import layout_common

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
CELLS = ("ota_fd", "integrator")

NETLIST_TEXT = {cell: (FIXTURES / f"{cell}.extract.spice").read_text()
                for cell in CELLS}
PROVENANCE = json.loads(
    (FIXTURES / "extract-fixtures.provenance.json").read_text())["fixtures"]

# The two cells' committed evidence files have different shapes: ota_fd's
# counts are flat and its net count is net_count.extracted; the integrator's
# counts are nested under the cell name (it also carries the ota_fd's counts,
# subtracted to get its own) and its net count is net_count.extracted_total.
EVIDENCE = {cell: json.loads(
    (HERE / cell / "extract-device-count.json").read_text()) for cell in CELLS}


def committed_expectations(cell: str):
    """(raw_counts, merged_counts, extracted_net_count) as committed."""
    d = EVIDENCE[cell]
    if cell == "ota_fd":
        return d["raw_counts"], d["merged_counts"], d["net_count"]["extracted"]
    return (d["raw_counts"][cell], d["merged_counts"][cell],
            d["net_count"]["extracted_total"])


PARSED = {cell: layout_common.parse_extract_devices(NETLIST_TEXT[cell])
          for cell in CELLS}
NETS = {cell: layout_common.extract_nets(NETLIST_TEXT[cell]) for cell in CELLS}


class FixtureDrivenParserTests(unittest.TestCase):
    """The parsers over the captured netlists, against the committed evidence."""

    def test_reproduces_committed_raw_counts(self):
        for cell in CELLS:
            with self.subTest(cell=cell):
                raw, _merged, _nets = committed_expectations(cell)
                self.assertEqual(dict(PARSED[cell][0]), raw)

    def test_reproduces_committed_merged_counts(self):
        for cell in CELLS:
            with self.subTest(cell=cell):
                _raw, merged, _nets = committed_expectations(cell)
                self.assertEqual(dict(PARSED[cell][1]), merged)

    def test_reproduces_committed_extracted_net_count(self):
        for cell in CELLS:
            with self.subTest(cell=cell):
                _raw, _merged, net_count = committed_expectations(cell)
                self.assertEqual(len(NETS[cell]), net_count)
                self.assertEqual(NETS[cell], sorted(NETS[cell]))

    def test_parser_totals_match_klt_own_tally(self):
        # `klt extract --format json` reports device_count / net_count itself;
        # committing that tally beside the netlist means a change in the
        # extractor's output shape diverges from the parser instead of both
        # agreeing on a misread. Numbers via the committed provenance record.
        for cell in CELLS:
            with self.subTest(cell=cell):
                report = PROVENANCE[cell]["klt_extract_report"]
                raw, _merged = PARSED[cell]
                self.assertEqual(report["device_count"], sum(raw.values()))
                self.assertEqual(report["net_count"], len(NETS[cell]))

    def test_merge_bites_on_ota_fd(self):
        # The merge must do visible work, not merely run: raw != merged on the
        # ota_fd fixture, with the mult-expanded unit devices collapsing
        # 50 -> 14 nfet and 31 -> 9 pfet, and the merged basis equalling the
        # committed check.expected block (EXPECTED_DEVICES, transcribed from
        # the 29 X-lines of design/ota/ota_fd.spice -- a source independent
        # of this parser). The sibling check.found block is NOT independent:
        # the generator writes it from this same parser's merged counts,
        # re-expressed in short model names, so asserting against it would
        # compare the parser with itself.
        raw, merged = PARSED["ota_fd"]
        evidence = EVIDENCE["ota_fd"]
        self.assertNotEqual(dict(raw), dict(merged))
        self.assertEqual(raw["sky130_fd_pr__nfet_01v8"], 50)
        self.assertEqual(merged["sky130_fd_pr__nfet_01v8"], 14)
        self.assertEqual(raw["sky130_fd_pr__pfet_01v8"], 31)
        self.assertEqual(merged["sky130_fd_pr__pfet_01v8"], 9)
        # The committed check block uses the models' short names plus a total.
        expected = evidence["check"]["expected"]
        for model, count in merged.items():
            self.assertEqual(count, expected[model.split("__", 1)[-1]], model)
        self.assertEqual(sum(merged.values()), expected["total"])

    def test_merged_collapses_to_per_model_distinct_groups(self):
        # merged[model] must be the number of distinct symmetric-terminal
        # groups for that model in the fixture -- so dropping the grouping
        # (merged := raw) or the normalisation shows up here, not just
        # against the committed JSON. The model token is located without
        # _is_model_token so this recomputation stays independent of the
        # predicate under test.
        for cell in CELLS:
            groups = set()
            for line in NETLIST_TEXT[cell].splitlines():
                tok = line.split()
                if not tok or not tok[0].startswith("X"):
                    continue
                model = next(
                    (t for t in tok if t.startswith("sky130_fd_pr__")), None)
                if model is None:
                    continue
                groups.add((model, layout_common._symmetric_terminals(
                    tuple(tok[1:tok.index(model)]))))
            per_model = Counter(m for m, _terminals in groups)
            with self.subTest(cell=cell):
                for model, count in PARSED[cell][1].items():
                    self.assertEqual(per_model[model], count, model)

    def test_integrator_own_devices_subtraction_model(self):
        # The integrator's committed evidence is a difference: klt extract
        # over the assembled cell flattens through the placed ota_fd
        # instance, so this cell's own devices are
        # merged(integrator) - merged(ota_fd), zeros dropped (the same
        # convention gen_integrator.py uses when it wrote the record).
        merged_int = PARSED["integrator"][1]
        merged_ota = PARSED["ota_fd"][1]
        own = {m: merged_int.get(m, 0) - merged_ota.get(m, 0)
               for m in set(merged_int) | set(merged_ota)}
        own = {m: c for m, c in own.items() if c}
        self.assertEqual({**own, "total": sum(own.values())},
                         EVIDENCE["integrator"]["found_own_devices"])
        self.assertEqual(sum(own.values()), 50)

    def test_joined_label_net_survives_extract_nets(self):
        # The integrator's met1 label overlap joins outn and voutn into one
        # extracted net name; the pipe form must survive intact.
        self.assertIn("outn|voutn", NETS["integrator"])
        self.assertIn("outp|voutp", NETS["integrator"])


class ParserEdgeCaseTests(unittest.TestCase):
    """Parser corners the captured netlists do not contain.

    In-memory strings, NOT stand-ins for the fixtures: the fixture-driven
    group above owns the "real extractor output" contract. These only pin
    behaviour on shapes a netlist can legally have.
    """

    def test_empty_netlist_returns_empty(self):
        raw, merged = layout_common.parse_extract_devices("")
        self.assertEqual(raw, Counter())
        self.assertEqual(merged, Counter())
        self.assertEqual(layout_common.extract_nets(""), [])

    def test_comment_only_netlist_returns_empty(self):
        text = "* extracted by klt extract --deck sky130\n" \
               "* device instance $1 r0 *1 6.795,72.47 nfet\n"
        raw, merged = layout_common.parse_extract_devices(text)
        self.assertEqual(raw, Counter())
        self.assertEqual(merged, Counter())
        self.assertEqual(layout_common.extract_nets(text), [])

    def test_continuation_line_is_not_parsed_as_a_device(self):
        # SPICE wraps long parameter lists onto a '+' line (both captured
        # netlists do it for PS=/PD=); the continuation must not be counted
        # as a device of its own nor contribute nets.
        text = "X$1 a b c d sky130_fd_pr__nfet_01v8 L=0.5 W=2\n" \
               "+ PS=4.84 PD=4.84\n"
        raw, merged = layout_common.parse_extract_devices(text)
        self.assertEqual(dict(raw), {"sky130_fd_pr__nfet_01v8": 1})
        self.assertEqual(dict(merged), {"sky130_fd_pr__nfet_01v8": 1})
        self.assertEqual(layout_common.extract_nets(text), ["a", "b", "c", "d"])

    def test_wrapped_model_token_is_counted(self):
        # A writer may break an X-line at any token, the model token
        # included; the device must be counted from the folded logical
        # line, not silently dropped (issue #204 -- before the fold this
        # returned empty counters and no nets: the X-line found no model
        # token and the '+' line does not start with X).
        text = "X$1 a b c d\n+ sky130_fd_pr__nfet_01v8 L=0.5 W=2\n"
        raw, merged = layout_common.parse_extract_devices(text)
        self.assertEqual(dict(raw), {"sky130_fd_pr__nfet_01v8": 1})
        self.assertEqual(dict(merged), {"sky130_fd_pr__nfet_01v8": 1})
        self.assertEqual(layout_common.extract_nets(text), ["a", "b", "c", "d"])

    def test_wrapped_terminals_and_model_are_counted(self):
        # Terminals precede the model token on an X-line, so a tight wrap
        # can push both onto the '+' line; the same fold must still count
        # the one device and collect all four terminals.
        text = "X$1 a b\n+ c d sky130_fd_pr__nfet_01v8 L=0.5 W=2\n"
        raw, merged = layout_common.parse_extract_devices(text)
        self.assertEqual(dict(raw), {"sky130_fd_pr__nfet_01v8": 1})
        self.assertEqual(dict(merged), {"sky130_fd_pr__nfet_01v8": 1})
        self.assertEqual(layout_common.extract_nets(text), ["a", "b", "c", "d"])

    def test_multiple_continuations_fold_into_one_device(self):
        # Several '+' lines are one logical line: counted exactly once,
        # and every wrapped net reaches extract_nets exactly once.
        text = "X$1 a b\n" \
               "+ c d sky130_fd_pr__nfet_01v8\n" \
               "+ L=0.5 W=2\n" \
               "+ PS=4.84 PD=4.84\n"
        raw, merged = layout_common.parse_extract_devices(text)
        self.assertEqual(dict(raw), {"sky130_fd_pr__nfet_01v8": 1})
        self.assertEqual(dict(merged), {"sky130_fd_pr__nfet_01v8": 1})
        self.assertEqual(layout_common.extract_nets(text), ["a", "b", "c", "d"])

    def test_orphan_continuation_line_yields_nothing(self):
        # A '+' line with nothing before it has no line to fold into (the
        # joiner keeps it as it stands); it starts with '+', not X, so it
        # is neither a device nor a net source.
        text = "+ sky130_fd_pr__nfet_01v8 L=0.5 W=2\n"
        raw, merged = layout_common.parse_extract_devices(text)
        self.assertEqual(raw, Counter())
        self.assertEqual(merged, Counter())
        self.assertEqual(layout_common.extract_nets(text), [])

    def test_continuation_after_comment_line_is_not_a_device(self):
        # A '+' line folds onto whatever precedes it, a comment included;
        # the folded logical line still starts with '*' and must count no
        # device even though it now carries a device-shaped body.
        text = "* device instance $1 r0 *1 6.795,72.47 nfet\n" \
               "+ X$1 a b c d sky130_fd_pr__nfet_01v8\n"
        raw, merged = layout_common.parse_extract_devices(text)
        self.assertEqual(raw, Counter())
        self.assertEqual(merged, Counter())
        self.assertEqual(layout_common.extract_nets(text), [])

    def test_continuation_of_subckt_port_list_is_not_a_device(self):
        # The integrator fixture wraps the .SUBCKT port list onto a '+'
        # line; folded, the logical line starts with .SUBCKT and must stay
        # a non-device.
        text = ".SUBCKT integrator dn dp ibias inn inp outn|voutn outp|voutp" \
               " phi1 phi1b phi1e\n" \
               "+ phi2 vcm vdda vinn vinp vrefn vrefp vssa\n"
        raw, merged = layout_common.parse_extract_devices(text)
        self.assertEqual(raw, Counter())
        self.assertEqual(merged, Counter())
        self.assertEqual(layout_common.extract_nets(text), [])

    def test_non_device_lines_are_ignored(self):
        text = ".SUBCKT ota_fd ibias vdda vssa\n" \
               "C0 a b sky130_fd_pr__cap_mim_m3_1\n" \
               "M1 d g s b sky130_fd_pr__nfet_01v8\n" \
               ".ENDS\n"
        raw, merged = layout_common.parse_extract_devices(text)
        self.assertEqual(raw, Counter())
        self.assertEqual(merged, Counter())
        self.assertEqual(layout_common.extract_nets(text), [])

    def test_subckt_wrapped_bare_short_form_is_counted(self):
        # `klt extract` can emit the bare short names for subckt-wrapped
        # devices; both forms must reach the same counters.
        text = "X$1 a b c d nfet L=0.5 W=2\n"
        raw, merged = layout_common.parse_extract_devices(text)
        self.assertEqual(dict(raw), {"nfet": 1})
        self.assertEqual(dict(merged), {"nfet": 1})
        self.assertEqual(layout_common.extract_nets(text), ["a", "b", "c", "d"])


class SymmetricTerminalTests(unittest.TestCase):
    """_symmetric_terminals over literal terminal tuples: all four branches."""

    def test_four_terminal_mosfet_normalises_drain_source_swap(self):
        # D-G-S-B: the drain/source swap must produce one key -- this is what
        # makes a multi-finger device, whose fingers extract with the two
        # orders alternating, count once rather than twice.
        forward = layout_common._symmetric_terminals(("d1", "g", "s1", "vb"))
        backward = layout_common._symmetric_terminals(("s1", "g", "d1", "vb"))
        self.assertEqual(forward, backward)
        self.assertEqual(forward, ("d1", "g", "s1", "vb"))

    def test_four_terminal_gate_and_bulk_are_not_swappable(self):
        # Only D/S are symmetric: swapping gate or bulk must change the key.
        self.assertNotEqual(
            layout_common._symmetric_terminals(("d1", "g1", "s1", "vb1")),
            layout_common._symmetric_terminals(("d1", "s1", "g1", "vb1")))
        self.assertNotEqual(
            layout_common._symmetric_terminals(("d1", "g1", "s1", "vb1")),
            layout_common._symmetric_terminals(("d1", "g1", "vb1", "s1")))

    def test_three_terminal_resistor_normalises(self):
        # A B bulk: both terminal orders are one resistor, bulk stays third.
        forward = layout_common._symmetric_terminals(("a", "b", "vssa"))
        backward = layout_common._symmetric_terminals(("b", "a", "vssa"))
        self.assertEqual(forward, backward)
        self.assertEqual(forward, ("a", "b", "vssa"))

    def test_two_terminal_capacitor_normalises(self):
        forward = layout_common._symmetric_terminals(("p", "n"))
        backward = layout_common._symmetric_terminals(("n", "p"))
        self.assertEqual(forward, backward)
        self.assertEqual(forward, ("n", "p"))

    def test_other_arities_fall_back_to_sorted(self):
        self.assertEqual(
            layout_common._symmetric_terminals(("z", "y", "x", "w", "v")),
            ("v", "w", "x", "y", "z"))
        self.assertEqual(layout_common._symmetric_terminals(("only",)), ("only",))


class ModelTokenTests(unittest.TestCase):
    """_is_model_token over literal tokens: every axis it actually decides."""

    def test_prefixed_sky130_forms_are_model_tokens(self):
        for token in ("sky130_fd_pr__nfet_01v8",
                      "sky130_fd_pr__nfet_01v8_lvt",
                      "sky130_fd_pr__pfet_01v8",
                      "sky130_fd_pr__cap_mim_m3_1",
                      "sky130_fd_pr__res_high_po",
                      "sky130_fd_pr__res_xhigh_po"):
            with self.subTest(token=token):
                self.assertTrue(layout_common._is_model_token(token))

    def test_bare_short_forms_are_model_tokens(self):
        # Emitted for subckt-wrapped devices; absent from both captured
        # netlists, so only literals can reach this axis.
        self.assertTrue(layout_common._is_model_token("nfet"))
        self.assertTrue(layout_common._is_model_token("pfet"))

    def test_prefix_mid_token_is_not_a_model_token(self):
        # The one behavioural axis #179 changed: the old per-generator
        # predicate was `"sky130_fd_pr__" in t`, which matched a token
        # merely carrying the prefix -- e.g. an X-prefixed instance name --
        # and mis-split the line at tok.index(model).
        self.assertFalse(
            layout_common._is_model_token("x_sky130_fd_pr__nfet_01v8"))

    def test_non_model_tokens_are_rejected(self):
        for token in ("nfet_01v8",          # short name without the prefix
                      "nfet_01v8_lvt",      # ... and not a bare nfet/pfet
                      "L=0.5", "W=2",       # parameters
                      "ibias", "vssa",      # net names
                      "X$1"):               # instance names
            with self.subTest(token=token):
                self.assertFalse(layout_common._is_model_token(token))


class RunCliTests(unittest.TestCase):
    """The shared `--check` CLI driver's contract (issue #258): exit 0 pass,
    1 geometry regression, 2 cannot verify -- with the recorded pin, the
    host pin and the cell's `flow` faked, so no klt, no PDK, no scratch and
    no uvx resolution is involved.  The two generators' `main` copies used
    to pin this contract by hand; after #258 it is pinned once, here.
    """

    PROG = "gen_x.py"

    PIN = {"klt": "0.9.2", "git_commit": "c0ffee0000000000000000000000000000000000",
           "reinstall_spec": "klayout-tools==0.9.2", "klayout": "0.30.13"}

    def setUp(self):
        self.cell_dir = pathlib.Path(tempfile.mkdtemp(prefix="runcli-cell-"))
        self.addCleanup(shutil.rmtree, self.cell_dir, ignore_errors=True)
        self.calls: list[tuple] = []

    def fake_flow(self, payload: bytes | None = None, top: str = "x"):
        """A flow stand-in recording its calls; `payload` is the GDS bytes
        it regenerates (None: write the generate-path deliverables instead).
        """
        def flow(klt_cmd, pdk_root, out_dir, **kwargs):
            self.calls.append((list(klt_cmd), pdk_root, pathlib.Path(out_dir),
                               kwargs))
            out_dir.mkdir(parents=True, exist_ok=True)
            if payload is not None:
                (out_dir / f"{top}.gds").write_bytes(payload)
            else:
                (out_dir / f"{top}.gds").write_bytes(b"generated")
                (out_dir / "drc.report.json").write_text("{}\n")
                (out_dir / "extract-device-count.json").write_text("{}\n")
                (out_dir / "route.summary.json").write_text("{}\n")
            return {"drc": {"status": "clean", "violation_count": 0}}

        return flow

    def run_cli(self, *argv, top="x", flow=None, pin=None, pin_error=None,
                host=None, which=None):
        flow = self.fake_flow(top=top) if flow is None else flow
        pin = self.PIN if pin is None else pin
        host = self.PIN if host is None else host
        out, err = io.StringIO(), io.StringIO()
        pin_patch = mock.patch.object(
            layout_common, "recorded_pin",
            side_effect=pin_error) if pin_error is not None else \
            mock.patch.object(layout_common, "recorded_pin",
                              return_value=pin)
        with pin_patch, \
             mock.patch.object(layout_common, "klt_pin",
                               return_value=host), \
             mock.patch("sys.argv", [self.PROG, *argv]), \
             mock.patch("shutil.which", return_value=which), \
             contextlib.redirect_stdout(out), \
             contextlib.redirect_stderr(err):
            rc = layout_common.run_cli(self.PROG, self.cell_dir, top, flow)
        return rc, out.getvalue(), err.getvalue()

    def committed(self, top="x", payload=b"committed-bytes"):
        (self.cell_dir / f"{top}.gds").write_bytes(payload)

    def test_check_pass_returns_0(self):
        self.committed(payload=b"same")
        flow = self.fake_flow(payload=b"same")
        rc, out, err = self.run_cli("--check", flow=flow)
        self.assertEqual(rc, 0)
        self.assertIn(f"{self.PROG} --check: PASS -- regenerated GDS is "
                      "byte-identical", out)
        self.assertIn("evaluated against recorded klt 0.9.2", out)
        self.assertEqual(err, "")

    def test_check_pass_runs_the_flow_quietly_into_a_scratch_dir(self):
        self.committed(payload=b"same")
        flow = self.fake_flow(payload=b"same")
        self.run_cli("--check", flow=flow)
        (klt_cmd, pdk_root, out_dir, kwargs), = self.calls
        self.assertEqual(klt_cmd, ["klt"])
        self.assertEqual(kwargs, {"verbose": False})
        self.assertTrue(out_dir.name.startswith("x-check-"),
                        out_dir.name)
        self.assertFalse(out_dir.exists(), "scratch must be removed")

    def test_check_geometry_regression_returns_1(self):
        self.committed(payload=b"committed-bytes")
        flow = self.fake_flow(payload=b"regressed")
        rc, out, err = self.run_cli("--check", flow=flow)
        self.assertEqual(rc, 1)
        self.assertIn(f"{self.PROG} --check: FAIL -- regenerated GDS "
                      "differs", err)
        self.assertIn("a generator or geometry regression, not a "
                      "toolchain mismatch", err)

    def test_check_missing_committed_gds_returns_2(self):
        rc, out, err = self.run_cli("--check")
        self.assertEqual(rc, 2)
        self.assertIn("does not exist yet", err)
        self.assertEqual(self.calls, [], "no flow may run")

    def test_check_unreadable_pin_returns_2(self):
        self.committed()
        rc, out, err = self.run_cli("--check",
                                    pin_error=layout_common.PinError("no pin"))
        self.assertEqual(rc, 2)
        self.assertIn("CANNOT VERIFY -- no pin", err)
        self.assertEqual(self.calls, [])

    def test_check_host_klayout_mismatch_returns_2(self):
        self.committed()
        rc, out, err = self.run_cli(
            "--check", host={**self.PIN, "klayout": "0.30.12"})
        self.assertEqual(rc, 2)
        self.assertIn("CANNOT VERIFY", err)
        self.assertIn("runs klayout 0.30.12, not the recorded 0.30.13", err)
        self.assertEqual(self.calls, [])

    def test_check_host_klt_unknown_without_uvx_returns_2(self):
        self.committed()
        rc, out, err = self.run_cli("--check", host={"klt": "unknown"},
                                    which=None)
        self.assertEqual(rc, 2)
        self.assertIn("uvx is not on PATH", err)
        self.assertEqual(self.calls, [])

    def test_scratch_prefix_maps_underscores_to_dashes(self):
        self.committed(top="a_b", payload=b"same")
        flow = self.fake_flow(payload=b"same", top="a_b")
        rc, out, err = self.run_cli("--check", top="a_b", flow=flow)
        self.assertEqual(rc, 0)
        (_, _, out_dir, _), = self.calls
        self.assertTrue(out_dir.name.startswith("a-b-check-"), out_dir.name)

    def test_generate_path_emits_deliverables_and_returns_0(self):
        rc, out, err = self.run_cli()
        self.assertEqual(rc, 0)
        self.assertIn(f"{self.PROG}: wrote x.gds + evidence to {self.cell_dir}",
                      out)
        self.assertIn("drc status='clean', violations=0", out)
        (klt_cmd, pdk_root, out_dir, kwargs), = self.calls
        self.assertEqual(klt_cmd, ["klt"])
        self.assertEqual(kwargs, {})
        self.assertEqual(out_dir, self.cell_dir / "_gen")
        for name in ("x.gds", "drc.report.json", "extract-device-count.json",
                     "route-summary.json"):
            self.assertTrue((self.cell_dir / name).exists(), name)


if __name__ == "__main__":
    unittest.main()

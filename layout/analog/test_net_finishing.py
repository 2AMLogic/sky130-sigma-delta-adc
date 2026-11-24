"""Tests for the analog generators' shared net finishing and compose/DRC
steps (issue #377). Run:
python3 -I -m unittest discover -s layout/analog -p 'test_*.py'

The helpers live once, in layout/analog/layout_common.py (#377 moved them in
from the two generators, whose copies had been verified identical): the
eight MiM/via geometry constants, `group_anchors_by_net`/`finish_net`/
`finalize_routing` (the post-anchor-placement net finishing and the
`draw.request.json` payload), `compose_request` (the placement-only
`klt.gen_compose.request/1` dict) and `draw_compose_and_drc` (the three
flow documents plus the `klt draw` + `klt gen-compose` + `klt drc` steps).
No klt, no PDK, no subprocess: `run` is replaced by a recorder, so the
command lines, the call order, the file writes and the error contracts are
pinned without a toolchain.

What is pinned here:

- Both generators carry the shared table: each re-exports the five helpers
  and the eight constants as the one layout_common object (same identity,
  no re-pasted copy), so divergence cannot come back through an import.
- `group_anchors_by_net` buckets by net and raises the `net table mismatch`
  `RouteError` both ways: a net not in the table, and a table net with no
  anchors.
- `finish_net` sorts the placements by column then y, routes one spine per
  consecutive pair, records the summary entry, and labels a pin net on
  `L_MET1_PIN` at its *first label-plane* anchor -- a MiM riser that sorts
  first is skipped, and a pin net with no label-plane anchor raises. The
  integrator's `label_planes=("met1", "ota")` extension accepts an OTA
  landing the default rejects.
- `finalize_routing` finishes the trunks (the met2 vwire lands in the
  payload), rounds each net's `wire_length_um` to 3 decimals, serialises
  the labels, and appends `extra_shapes` *after* the router's own shapes.
- `compose_request` builds the exact placement-only request: the route
  block appended last with its generator report, origin (0, 0) merged into
  the caller's origins, no `routing` block, and the top cell named in the
  options.
- `draw_compose_and_drc` writes the three documents with the indents the
  two flows used, runs the three klt commands in order with `cwd=out_dir`,
  files `klt draw`'s stdout *verbatim* to `draw.json`, raises when
  gen-compose wrote no GDS (after `draw.json` exists), writes
  `drc.report.json` *before* `assert_drc_clean` raises on a dirty report,
  maps empty drc stdout to `{"error": stderr}`, and says the caller's step
  lines plus the status line in flow order.
"""
import json
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

import layout_common
from layout_common import (L_MET1_PIN, L_MET2, Anchor, Rect, RouteError,
                           Router, compose_request, draw_compose_and_drc,
                           finalize_routing, finish_net,
                           group_anchors_by_net)
from layout_test_common import load_generator


INTEGRATOR = load_generator("integrator/gen_integrator.py")
OTA_FD = load_generator("ota_fd/gen_ota_fd.py")

PDK_ARGS = ["--pdk", "sky130A", "--pdk-root", "/nonexistent-pdk"]

HELPERS = ("group_anchors_by_net", "finish_net", "finalize_routing",
           "compose_request", "draw_compose_and_drc")
CONSTANTS = ("L_MET1_PIN", "L_VIA2", "L_VIA3", "VIA2_UM", "VIA3_UM",
             "MET34_W_UM", "MET34_SPACE_UM", "PAD34_UM")


class AddMet1Router(Router):
    """The base Router leaves add_met1 to the cell generators; the tests
    need exactly the bucket index met1_free reads, so this subclass mirrors
    the generators' override with nothing else added (the
    test_router_core.py pattern)."""

    def add_met1(self, net, rects):
        for rect in rects:
            for b in range(rect.y0 // layout_common.BUCKET_NM,
                           rect.y1 // layout_common.BUCKET_NM + 1):
                self.met1_index[b].append((net, rect))


class Recorder:
    """A `run` stand-in that records each (argv, cwd) and replies in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[tuple[list[str], pathlib.Path | None]] = []

    def __call__(self, cmd, cwd=None, check=True):
        self.calls.append((list(cmd), cwd))
        reply = mock.Mock()
        reply.stdout, reply.stderr = self.replies.pop(0)
        return reply


class BothGeneratorsCarryTheHelpersTests(unittest.TestCase):

    def test_generators_reexport_the_shared_helpers(self):
        for name, mod in (("gen_integrator", INTEGRATOR),
                          ("gen_ota_fd", OTA_FD)):
            with self.subTest(generator=name):
                for helper in HELPERS:
                    self.assertIs(getattr(mod, helper),
                                  getattr(layout_common, helper))

    def test_generators_import_the_shared_constants(self):
        for name, mod in (("gen_integrator", INTEGRATOR),
                          ("gen_ota_fd", OTA_FD)):
            with self.subTest(generator=name):
                for const in CONSTANTS:
                    self.assertIs(getattr(mod, const),
                                  getattr(layout_common, const))


class GroupAnchorsByNetTests(unittest.TestCase):

    def test_buckets_by_net_keeping_anchor_order(self):
        a1 = Anchor("a", "b1", "met1", 1.0, 0.0, 1.0, ["p"])
        a2 = Anchor("a", "b2", "met1", 2.0, 0.0, 1.0, ["q"])
        b1 = Anchor("b", "b1", "met1", 3.0, 0.0, 1.0, ["r"])
        by_net = group_anchors_by_net([a1, b1, a2], ("a", "b"))
        self.assertEqual(by_net["a"], [a1, a2])
        self.assertEqual(by_net["b"], [b1])

    def test_net_not_in_the_table_raises(self):
        stray = Anchor("zz", "b1", "met1", 1.0, 0.0, 1.0, ["p"])
        with self.assertRaises(RouteError) as ctx:
            group_anchors_by_net([stray], ("a",))
        self.assertIn("net table mismatch", str(ctx.exception))
        self.assertIn("not in NET_ORDER ['zz']", str(ctx.exception))

    def test_table_net_without_anchors_raises(self):
        a1 = Anchor("a", "b1", "met1", 1.0, 0.0, 1.0, ["p"])
        with self.assertRaises(RouteError) as ctx:
            group_anchors_by_net([a1], ("a", "b"))
        self.assertIn("no anchors ['b']", str(ctx.exception))


class FinishNetTests(unittest.TestCase):

    def setUp(self):
        self.router = AddMet1Router(0.0, 20.0, 0.0, 20.0)

    def test_sorts_placements_and_routes_one_spine_per_pair(self):
        hi = Anchor("n", "b2", "met1", 10.0, 0.0, 1.0, ["p2"])
        lo = Anchor("n", "b1", "met1", 12.0, 0.0, 1.0, ["p1"])
        # lo carries the smaller column, so column order differs from the
        # hand-off order and the sort is what fixes the spine endpoints.
        summary: dict = {}
        finish_net(self.router, summary, "n", [(5.0, 10.0, hi),
                                               (1.0, 12.0, lo)], ())
        self.assertEqual(summary["n"]["anchors"], [
            {"block": "b1", "plane": "met1", "ports": ["p1"],
             "column_x_um": 1.0, "y_um": 12.0},
            {"block": "b2", "plane": "met1", "ports": ["p2"],
             "column_x_um": 5.0, "y_um": 10.0}])
        # pref is the endpoints' mid-y 11.0, on the 0.5um track grid and
        # free, so the spine lands exactly there.
        self.assertEqual(summary["n"]["spine_y_um"], [11.0])
        self.assertEqual(self.router.labels, [])

    def test_pin_net_label_skips_a_riser_that_sorts_first(self):
        riser = Anchor("vdda", "ccm", "cap3", 5.0, 0.0, 1.0, ["A"])
        pad = Anchor("vdda", "mb1", "met1", 6.0, 0.0, 1.0, ["B"])
        summary: dict = {}
        finish_net(self.router, summary, "vdda",
                   [(0.5, 5.0, riser), (0.75, 6.0, pad)], ("vdda",))
        # The label lands on the met1 anchor (column 0.75), never on the
        # MiM riser that sorted ahead of it.
        self.assertEqual(self.router.labels, [(L_MET1_PIN, "vdda", 0.75, 6.0)])

    def test_pin_net_without_a_label_plane_anchor_raises(self):
        riser = Anchor("vdda", "ccm", "cap4", 5.0, 0.0, 1.0, ["A"])
        with self.assertRaises(RouteError) as ctx:
            finish_net(self.router, {}, "vdda", [(0.75, 5.0, riser)],
                       ("vdda",))
        self.assertIn("port net vdda has no met1 anchor to label",
                      str(ctx.exception))

    def test_label_planes_extension_accepts_an_ota_landing(self):
        landing = Anchor("inp", "ota", "ota", 8.0, 2.0, 2.0, ["inp"])
        finish_net(self.router, {}, "inp", [(2.0, 8.0, landing)], ("inp",),
                   label_planes=("met1", "ota"))
        self.assertEqual(self.router.labels, [(L_MET1_PIN, "inp", 2.0, 8.0)])
        # The default rejects it: only the integrator passes the extension.
        self.router.labels.clear()
        with self.assertRaises(RouteError):
            finish_net(self.router, {}, "inp", [(2.0, 8.0, landing)],
                       ("inp",))


class FinalizeRoutingTests(unittest.TestCase):

    def test_finishes_trunks_rounds_wire_lengths_and_serialises(self):
        router = AddMet1Router(0.0, 20.0, 0.0, 20.0)
        router.add_trunk_via("n", 2.0, 4.0)
        router.add_trunk_via("n", 2.0, 8.0)
        router.wire_um["m"] = 1.23456
        router.labels.append(((68, 5), "vdda", 1.0, 2.0))
        summary = {"n": {}, "m": {}}
        marker = Rect.um(0.0, 0.0, 1.0, 0.38)
        draw_params = finalize_routing(
            router, summary, extra_shapes=[((125, 44), marker)])
        # finish_trunks drew the one met2 trunk over its via span (4->8um
        # plus half a wire each side), after the two via1 cuts the trunk
        # vias dropped, and the marker follows them all.
        self.assertEqual(draw_params["shapes"], [
            {"layer": [68, 44], "rect_um": [1.925, 3.925, 2.075, 4.075]},
            {"layer": [68, 44], "rect_um": [1.925, 7.925, 2.075, 8.075]},
            {"layer": list(L_MET2), "rect_um": [1.83, 3.83, 2.17, 8.17]},
            {"layer": [125, 44], "rect_um": [0.0, 0.0, 1.0, 0.38]}])
        self.assertEqual(draw_params["labels"], [
            {"layer": [68, 5], "text": "vdda", "at_um": [1.0, 2.0]}])
        # The trunk's own 4.0um span, and the rounding to 3 decimals.
        self.assertEqual(summary["n"]["wire_length_um"], 4.0)
        self.assertEqual(summary["m"]["wire_length_um"], 1.235)


class ComposeRequestTests(unittest.TestCase):

    def test_appends_the_route_block_last_at_origin_zero(self):
        req = compose_request(
            "ota_fd",
            [{"id": "mb1", "generator_report": "mb1.json"},
             {"id": "ota", "cell": {"gds_path": "ota_fd.gds",
                                    "cell_name": "ota_fd"}}],
            ["mb1", "ota"],
            {"mb1": {"x": 1.0, "y": 2.0}, "ota": {"x": 0.5, "y": 0.25}})
        self.assertEqual(req, {
            "schema": "klt.gen_compose.request/1",
            "pdk": {"variant": "sky130A"},
            "blocks": [{"id": "mb1", "generator_report": "mb1.json"},
                       {"id": "ota", "cell": {"gds_path": "ota_fd.gds",
                                              "cell_name": "ota_fd"}},
                       {"id": "route", "generator_report": "draw.json"}],
            "placement": {
                "strategy": "explicit",
                "order": ["mb1", "ota", "route"],
                "origins_um": {"mb1": {"x": 1.0, "y": 2.0},
                               "ota": {"x": 0.5, "y": 0.25},
                               "route": {"x": 0.0, "y": 0.0}},
            },
            "connectivity": [],
            "options": {"cell_name": "ota_fd", "output": "ota_fd.gds"},
        })

    def test_pdk_variant_is_parameterised(self):
        req = compose_request("x", [], [], {}, pdk_variant="sky130B")
        self.assertEqual(req["pdk"], {"variant": "sky130B"})


DRAW_STDOUT = '{\n  "cells": "not canonical json"\n}'
CLEAN_DRC = '{"status": "clean", "violation_count": 0}'
DIRTY_DRC = ('{"status": "fail", "violation_count": 2, '
             '"rule_counts": {"met1.space.1": 2}}')
DRAW_PARAMS = {"shapes": [{"layer": [68, 20], "rect_um": [0.0, 0.0, 1.0, 1.0]}],
               "labels": []}
COMPOSE_REQ = {"schema": "klt.gen_compose.request/1",
               "pdk": {"variant": "sky130A"},
               "blocks": [{"id": "route", "generator_report": "draw.json"}],
               "placement": {"strategy": "explicit", "order": ["route"],
                             "origins_um": {"route": {"x": 0.0, "y": 0.0}}},
               "connectivity": [],
               "options": {"cell_name": "cell", "output": "cell.gds"}}
ROUTE_SUMMARY = {"nets": {}}


class DrawComposeAndDrcTests(unittest.TestCase):

    def setUp(self):
        self.out_dir = pathlib.Path(tempfile.mkdtemp(prefix="drawcompose-"))
        self.addCleanup(shutil.rmtree, self.out_dir, ignore_errors=True)

    def test_commands_in_order_with_cwd_and_documents_written(self):
        (self.out_dir / "cell.gds").write_text("gds")
        rec = Recorder([(DRAW_STDOUT, ""), ("{}", ""), (CLEAN_DRC, "")])
        said: list[str] = []
        with mock.patch.object(layout_common, "run", rec):
            drc = draw_compose_and_drc(
                ["klt"], PDK_ARGS, self.out_dir, "cell", DRAW_PARAMS,
                COMPOSE_REQ, ROUTE_SUMMARY, say=said.append,
                draw_step="[4/6] draw", drc_step="[5/6] drc")
        self.assertEqual([cmd for cmd, _cwd in rec.calls], [
            ["klt", "draw", "--params", "draw.request.json",
             "--cell-name", "ROUTE", "-o", "route.gds", "--format", "json"],
            ["klt", "gen-compose", "compose.request.json", "--format", "json"],
            ["klt", "drc", "cell.gds", "--deck", "sky130", "--top", "cell"]
            + PDK_ARGS + ["--format", "json"]])
        for _cmd, cwd in rec.calls:
            self.assertIs(cwd, self.out_dir)
        # The three documents, with the indents the two flows used.
        self.assertEqual(
            (self.out_dir / "draw.request.json").read_text(),
            json.dumps(DRAW_PARAMS, indent=1) + "\n")
        self.assertEqual(
            (self.out_dir / "compose.request.json").read_text(),
            json.dumps(COMPOSE_REQ, indent=2) + "\n")
        self.assertEqual(
            (self.out_dir / "route.summary.json").read_text(),
            json.dumps(ROUTE_SUMMARY, indent=2) + "\n")
        # klt draw's stdout is filed verbatim, never re-serialised.
        self.assertEqual((self.out_dir / "draw.json").read_text(), DRAW_STDOUT)
        self.assertEqual(drc, {"status": "clean", "violation_count": 0})
        # The step lines and the status line, in flow order.
        self.assertEqual(said, ["[4/6] draw", "[5/6] drc",
                                "  drc: status='clean' violations=0"])

    def test_missing_gds_raises_after_draw_json_is_written(self):
        rec = Recorder([(DRAW_STDOUT, ""), ("{}", "")])
        with mock.patch.object(layout_common, "run", rec):
            with self.assertRaises(RuntimeError) as ctx:
                draw_compose_and_drc(["klt"], PDK_ARGS, self.out_dir, "cell",
                                     DRAW_PARAMS, COMPOSE_REQ, ROUTE_SUMMARY)
        self.assertIn("gen-compose did not write", str(ctx.exception))
        self.assertIn("cell.gds", str(ctx.exception))
        self.assertEqual((self.out_dir / "draw.json").read_text(), DRAW_STDOUT)
        # drc never ran.
        self.assertEqual(len(rec.calls), 2)
        self.assertFalse((self.out_dir / "drc.report.json").exists())

    def test_drc_report_written_before_the_guard_raises(self):
        (self.out_dir / "cell.gds").write_text("gds")
        rec = Recorder([("", ""), ("{}", ""), (DIRTY_DRC, "")])
        with mock.patch.object(layout_common, "run", rec):
            with self.assertRaises(RuntimeError):
                draw_compose_and_drc(["klt"], PDK_ARGS, self.out_dir, "cell",
                                     DRAW_PARAMS, COMPOSE_REQ, ROUTE_SUMMARY)
        # The report is on disk for the raise to point at, and holds the
        # parsed verdict.
        self.assertEqual(
            json.loads((self.out_dir / "drc.report.json").read_text()),
            {"status": "fail", "violation_count": 2,
             "rule_counts": {"met1.space.1": 2}})

    def test_empty_drc_stdout_becomes_the_error_dict(self):
        (self.out_dir / "cell.gds").write_text("gds")
        rec = Recorder([("", ""), ("{}", ""), ("", "klt exploded")])
        with mock.patch.object(layout_common, "run", rec):
            with self.assertRaises(RuntimeError) as ctx:
                draw_compose_and_drc(["klt"], PDK_ARGS, self.out_dir, "cell",
                                     DRAW_PARAMS, COMPOSE_REQ, ROUTE_SUMMARY)
        self.assertEqual(
            json.loads((self.out_dir / "drc.report.json").read_text()),
            {"error": "klt exploded"})
        self.assertIn("None", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

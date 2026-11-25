"""Tests for the shared anchor collection and guard-ring sizing in
layout/analog/layout_common.py plus the two generators' thin adapters over
them (issue #347). Run:
python3 -I -m unittest discover -s layout/analog -p 'test_*.py'

No klt, no PDK, no EDA tool, no network, no fixtures: synthetic placed ports
and row extents, exactly like test_router_core.py.  Before #347 the two
generators carried these ~196 lines as paste-copies with zero test coverage
-- `git grep -l collect_anchors layout/` matched no test module -- so subtle
drift (gate-row x-ordering on mirrored diff pairs, pad-ladder headroom)
could only surface in a full klt regeneration.  The move was verified
message-for-message against the deleted copies over synthetic inputs for
every branch first; this suite then pins the shared code's contract so the
equivalence cannot drift back.

What is pinned here:

- `ring_params`: the bounding-box-plus-pad arithmetic, the contact-count
  floor of 4 (a 12um-tall ring wants int(12/4)=3 and gets 4), the
  `add_well` flag pass-through, the ring-width origin offset, and the
  `pad_um`/`width_um` keyword overrides.
- `collect_anchors`: the S/D pad-row ladder (three nets on one tall pad row
  land at y-0.5/y/y+0.5, one strap and one mcon row per net), the narrow
  single-pad-row case (y pinned, no ladder, no error), both `RouteError`
  contracts word-for-word (a strapped net with no ladder headroom; a gate
  row mixing several nets with a multi-pad net), gate-row straps ordered by
  x and never by port name (the diff_pair mirrored-numbering trap), the
  `cap3`/`cap4` MiM terminals (one anchor per pad, `port_dir` and the
  block's y extent passed through, no straps), unmapped-port skipping, the
  unexpected-layer error, and the caller-fixed cell order.
- The OTA adapter: report ports carry `layer` as a
  ``{"layer": .., "datatype": ..}`` dict and coordinates in the generator's
  own frame; the adapter translates both by the block origin before the
  shared collector sees them.
- The integrator adapter: `Block.ports()` placement (mirror_x negates x
  and swaps the 0/180 directions), the real `port_nets_of` mapping
  (mos_array `U0_*`, cap_array `C0_*`), and the `sorted(blocks)` order the
  cell's stream is generated in -- a dict inserted ``zz``-first emits
  ``aa``'s anchors first.

The generator modules are loaded by path the way test_drc_guard.py and
test_integrator_summing_pair.py do it.
"""
import unittest

from layout_common import (JOG_REACH_UM, L_LI1, L_MET3, L_MET4, Rect,
                           RouteError, collect_anchors, ring_params)
from layout_test_common import load_generator


GO = load_generator("ota_fd/gen_ota_fd.py")
GI = load_generator("integrator/gen_integrator.py")


def port(name, x, y, w, direction, layer=L_LI1):
    """One port in the shared collector's placed form: tuple layer."""
    return {"name": name, "layer": layer, "x_um": x, "y_um": y,
            "width_um": w, "direction_deg": direction}


def report_port(name, x, y, w, direction, layer=L_LI1):
    """One port in the raw ``klt gen`` report form the OTA feeds its adapter:
    dict layer, generator-frame coordinates."""
    return {"name": name,
            "layer": {"layer": layer[0], "datatype": layer[1]},
            "x_um": x, "y_um": y, "width_um": w, "direction_deg": direction}


def bbox(x0, y0, x1, y1):
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


def strap_rects(straps):
    return [rect for _net, rect in straps]


class RingParamsTests(unittest.TestCase):
    """The shared guard_ring sizing both generators' rings call."""

    def test_encloses_rows_with_pad_and_scales_contacts(self):
        params, origin = ring_params(
            [(0.0, 0.0, 20.0, 4.0), (2.0, 10.0, 26.0, 18.0)], False)
        # bounding box (-2, -2, 28, 20): 30 x 22 um of inner area
        self.assertEqual(params, {
            "inner_width_um": 30.0, "inner_height_um": 22.0,
            "ring_width_um": 0.42,
            "contacts_per_side_ns": 7, "contacts_per_side_ew": 5,
            "add_well": False})
        self.assertEqual(origin, {"x": -2.42, "y": -2.42})

    def test_contact_count_floors_at_four(self):
        # one 20x14 um row -> ew wants int(14/4)=3 and must still get 4
        params, _origin = ring_params([(4.0, 30.0, 24.0, 40.0)], True)
        self.assertEqual(params["contacts_per_side_ew"], 4)
        self.assertEqual(params["contacts_per_side_ns"], 6)
        self.assertTrue(params["add_well"])

    def test_pad_and_width_overrides(self):
        params, origin = ring_params([(0.0, 0.0, 10.0, 4.0)], False,
                                     pad_um=1.0, width_um=0.6)
        self.assertEqual(params["inner_width_um"], 12.0)
        self.assertEqual(params["inner_height_um"], 6.0)
        self.assertEqual(params["ring_width_um"], 0.6)
        self.assertEqual(origin, {"x": -1.6, "y": -1.6})


class SharedCollectAnchorsTests(unittest.TestCase):
    """The shared collector over synthetic placed cells."""

    def test_sd_ladder_straps_each_net_at_its_own_rung(self):
        ports = [port("P1a", 1.0, 2.0, 2.0, 0),
                 port("P1b", 2.0, 2.0, 2.0, 180),
                 port("P2a", 4.0, 2.0, 2.0, 0),
                 port("P2b", 5.0, 2.0, 2.0, 180),
                 port("P3a", 7.0, 2.0, 2.0, 0),
                 port("P3b", 8.0, 2.0, 2.0, 180)]
        cells = [("bs", 0.0, 4.0, ports,
                  {"P1a": "n1", "P1b": "n1", "P2a": "n2", "P2b": "n2",
                   "P3a": "n3", "P3b": "n3"})]
        anchors, straps, mcons = collect_anchors(cells)
        self.assertEqual([(a.net, a.y) for a in anchors],
                         [("n1", 1.5), ("n2", 2.0), ("n3", 2.5)])
        self.assertEqual([(a.x0, a.x1, a.pad_xs) for a in anchors],
                         [(1.0, 2.0, (1.0, 2.0)), (4.0, 5.0, (4.0, 5.0)),
                          (7.0, 8.0, (7.0, 8.0))])
        self.assertEqual([a.plane for a in anchors], ["met1"] * 3)
        self.assertTrue(all(a.jog_um == JOG_REACH_UM for a in anchors))
        self.assertEqual([n for n, _r in straps], ["n1", "n2", "n3"])
        self.assertEqual(strap_rects(straps)[0].as_um(),
                         Rect.hwire(1.0, 2.0, 1.5, 0.34).as_um())
        self.assertEqual(sorted(mcons),
                         [(1.0, 1.5), (2.0, 1.5), (4.0, 2.0), (5.0, 2.0),
                          (7.0, 2.5), (8.0, 2.5)])

    def test_sd_narrow_single_pad_row_pins_y(self):
        # two 0.42um pads, one net each: no net needs a strap, so no ladder
        # is needed and neither y may move
        cells = [("bn", 0.0, 4.0,
                  [port("A", 1.0, 1.0, 0.42, 0), port("B", 3.0, 1.0, 0.42, 180)],
                  {"A": "na", "B": "nb"})]
        anchors, straps, mcons = collect_anchors(cells)
        self.assertEqual([(a.net, a.y) for a in anchors],
                         [("na", 1.0), ("nb", 1.0)])
        self.assertEqual([n for n, _r in straps], ["na", "nb"])
        self.assertEqual(sorted(mcons), [(1.0, 1.0), (3.0, 1.0)])

    def test_sd_strapped_net_without_ladder_headroom_raises(self):
        # 0.60um pads leave half = 0.01um of ladder headroom; the strapped
        # net needs 0.25um -- the exact contract the OTA's pad rows obey
        cells = [("br", 0.0, 4.0,
                  [port("A1", 1.0, 1.0, 0.60, 0), port("A2", 2.0, 1.0, 0.60, 0),
                   port("B", 4.0, 1.0, 0.60, 180)],
                  {"A1": "na", "A2": "na", "B": "nb"})]
        with self.assertRaises(RouteError) as ctx:
            collect_anchors(cells)
        self.assertEqual(
            str(ctx.exception),
            "br: 2 nets share a 0.26um pad row at y=1.0 and one of them "
            "needs a strap -- no room for a ladder")

    def test_gate_row_strap_spans_pads_in_x_order_not_name_order(self):
        # diff_pair numbers its top row in the mirrored order: name order
        # would leave the row's outermost gate outside the strap
        cells = [("bg", 0.0, 4.0,
                  [port("U2", 5.0, 1.5, 0.42, 90), port("U0", 1.0, 1.5, 0.42, 90),
                   port("U1", 3.0, 1.5, 0.42, 270)],
                  {"U0": "g1", "U1": "g1", "U2": "g1"})]
        anchors, straps, mcons = collect_anchors(cells)
        self.assertEqual(len(anchors), 1)
        a = anchors[0]
        self.assertEqual((a.net, a.y, a.x0, a.x1, a.pad_xs),
                         ("g1", 1.5, 1.0, 5.0, (1.0, 3.0, 5.0)))
        self.assertEqual(a.ports, ["U0", "U1", "U2"])
        self.assertEqual(strap_rects(straps)[0].as_um(),
                         Rect.hwire(1.0, 5.0, 1.5, 0.34).as_um())
        self.assertEqual(sorted(mcons), [(1.0, 1.5), (3.0, 1.5), (5.0, 1.5)])

    def test_gate_row_mixing_nets_and_multi_pad_net_raises(self):
        cells = [("bg", 0.0, 4.0,
                  [port("A", 1.0, 1.5, 0.42, 90), port("B", 2.0, 1.5, 0.42, 90),
                   port("C", 4.0, 1.5, 0.42, 270)],
                  {"A": "g1", "B": "g1", "C": "g2"})]
        with self.assertRaises(RouteError) as ctx:
            collect_anchors(cells)
        self.assertEqual(
            str(ctx.exception),
            "bg: gate row y=1.5 holds 2 nets and net g1 has 2 pads "
            "-- cannot strap")

    def test_mim_terminals_become_cap_planes_without_straps(self):
        cells = [("bc", 1.0, 5.0,
                  [port("T1", 1.5, 2.0, 0.6, 0, layer=L_MET3),
                   port("T0", 1.0, 2.0, 0.6, 0, layer=L_MET3),
                   port("B0", 4.0, 3.0, 0.6, 90, layer=L_MET4)],
                  {"T0": "c1", "T1": "c1", "B0": "c2"})]
        anchors, straps, mcons = collect_anchors(cells)
        self.assertEqual([(a.net, a.plane, a.y, a.x0, a.x1, a.port_dir,
                           a.block_y0, a.block_y1) for a in anchors],
                         [("c1", "cap3", 2.0, 1.0, 1.0, 0, 1.0, 5.0),
                          ("c1", "cap3", 2.0, 1.5, 1.5, 0, 1.0, 5.0),
                          ("c2", "cap4", 3.0, 4.0, 4.0, 90, 1.0, 5.0)])
        self.assertEqual([a.ports for a in anchors], [["T0"], ["T1"], ["B0"]])
        self.assertEqual((straps, mcons), ([], []))

    def test_port_missing_from_net_table_is_skipped(self):
        cells = [("bu", 0.0, 4.0,
                  [port("U0", 1.0, 1.5, 0.42, 90), port("U9_X", 9.0, 1.5, 0.42, 90)],
                  {"U0": "g1"})]
        anchors, straps, mcons = collect_anchors(cells)
        self.assertEqual([a.net for a in anchors], ["g1"])
        self.assertEqual([a.ports for a in anchors], [["U0"]])

    def test_port_on_unexpected_layer_raises(self):
        cells = [("bl", 0.0, 4.0,
                  [port("U0", 1.0, 1.5, 0.42, 90, layer=(64, 16))],
                  {"U0": "g1"})]
        with self.assertRaises(RouteError) as ctx:
            collect_anchors(cells)
        self.assertEqual(str(ctx.exception),
                         "bl: unexpected port layer (64, 16)")

    def test_cell_order_is_the_callers(self):
        # the shared collector must not re-order: the OTA's stream follows
        # floorplan order, the integrator's sorted(blocks)
        cells = [("zz", 0.0, 4.0, [port("A", 1.0, 1.0, 0.42, 0)], {"A": "nz"}),
                 ("aa", 0.0, 4.0, [port("B", 1.0, 1.0, 0.42, 0)], {"B": "nna"})]
        anchors, _straps, _mcons = collect_anchors(cells)
        self.assertEqual([a.block for a in anchors], ["zz", "aa"])


class OtaAdapterTests(unittest.TestCase):
    """gen_ota_fd.collect_anchors: report ports -> placed cells."""

    def test_projects_dict_layers_and_origin_into_placed_frame(self):
        blocks = [("bs", "mos_array", "BS", {})]
        reports = {"bs": {"bbox_um": bbox(0.0, 0.0, 10.0, 4.0),
                          "ports": [report_port("P1a", 1.0, 2.0, 2.0, 0),
                                    report_port("P1b", 2.0, 2.0, 2.0, 180),
                                    report_port("T0", 1.0, 3.0, 0.6, 0,
                                                layer=L_MET3)]}}
        origins = {"bs": {"x": 3.0, "y": 7.0}}
        port_nets = {"bs": {"P1a": "n1", "P1b": "n1", "T0": "c1"}}
        anchors, straps, mcons = GO.collect_anchors(
            blocks, reports, origins, port_nets)
        met1 = [a for a in anchors if a.plane == "met1"]
        cap3 = [a for a in anchors if a.plane == "cap3"]
        # li1 row keys on the placed y (2.0 + 7.0), xs carry dx
        self.assertEqual([(a.net, a.y, a.x0, a.x1) for a in met1],
                         [("n1", 9.0, 4.0, 5.0)])
        # cap anchors carry the placed bbox extent, not the report's
        self.assertEqual([(a.net, a.y, a.block_y0, a.block_y1) for a in cap3],
                         [("c1", 10.0, 7.0, 11.0)])
        self.assertEqual(strap_rects(straps)[0].as_um(),
                         Rect.hwire(4.0, 5.0, 9.0, 0.34).as_um())
        self.assertEqual(sorted(mcons), [(4.0, 9.0), (5.0, 9.0)])

    def test_unmapped_report_port_is_skipped(self):
        blocks = [("bu", "mos_array", "BU", {})]
        reports = {"bu": {"bbox_um": bbox(0.0, 0.0, 4.0, 4.0),
                          "ports": [report_port("U0", 1.0, 1.5, 0.42, 90),
                                    report_port("U9_X", 9.0, 1.5, 0.42, 90)]}}
        origins = {"bu": {"x": 0.0, "y": 0.0}}
        port_nets = {"bu": {"U0": "g1"}}
        anchors, _straps, _mcons = GO.collect_anchors(
            blocks, reports, origins, port_nets)
        self.assertEqual([a.ports for a in anchors], [["U0"]])

    def test_keeps_floorplan_block_order(self):
        blocks = [("zz", "mos_array", "ZZ", {}), ("aa", "mos_array", "AA", {})]

        def report(name):
            return {"bbox_um": bbox(0.0, 0.0, 4.0, 4.0),
                    "ports": [report_port(name, 1.0, 1.0, 0.42, 0)]}
        reports = {"zz": report("A"), "aa": report("B")}
        origins = {"zz": {"x": 0.0, "y": 0.0}, "aa": {"x": 0.0, "y": 0.0}}
        port_nets = {"zz": {"A": "nz"}, "aa": {"B": "nna"}}
        anchors, _straps, _mcons = GO.collect_anchors(
            blocks, reports, origins, port_nets)
        self.assertEqual([a.block for a in anchors], ["zz", "aa"])


class IntegratorAdapterTests(unittest.TestCase):
    """gen_integrator.collect_anchors: placed Blocks -> shared cells."""

    @staticmethod
    def block(bid, geometry, nets, ports, orientation="none",
              origin=(3.0, 7.0), bb=None):
        b = GI.Block(bid, geometry, orientation, nets)
        b.report = {"bbox_um": bb or bbox(0.0, 0.0, 10.0, 4.0), "ports": ports}
        b.origin = {"x": origin[0], "y": origin[1]}
        return b

    def test_block_ports_and_port_nets_feed_the_collector(self):
        blocks = {"bs": self.block(
            "bs", "n4", {"S": "n1", "D": "n2"},
            [report_port("U0_S", 1.0, 2.0, 2.0, 0),
             report_port("U0_D", 4.0, 2.0, 2.0, 180)])}
        anchors, straps, mcons = GI.collect_anchors(blocks)
        # port_nets_of maps U0_S/U0_D through .nets; ports() places them;
        # the 2um pads have ladder headroom, so the two nets spread +-0.25
        self.assertEqual([(a.net, a.y, a.x0) for a in anchors],
                         [("n1", 8.75, 4.0), ("n2", 9.25, 7.0)])
        self.assertEqual(len(straps), 2)
        self.assertEqual(sorted(mcons), [(4.0, 8.75), (7.0, 9.25)])

    def test_mirror_x_negates_x_and_swaps_sd_directions(self):
        blocks = {"bm": self.block(
            "bm", "n4", {"S": "ms", "D": "md"},
            [report_port("U0_S", 1.0, 2.0, 2.0, 0),
             report_port("U0_D", 4.0, 2.0, 2.0, 180)],
            orientation="mirror_x", origin=(30.0, 40.0))}
        anchors, _straps, _mcons = GI.collect_anchors(blocks)
        # mirror_x: x -> -x + 30 lands the pads at 26/29 on the y=42 row,
        # where they spread +-0.25 (md first: sorted net order); the 0/180
        # directions swap, which the anchors carry through port_dir
        self.assertEqual([(a.net, a.y, a.x0) for a in anchors],
                         [("md", 41.75, 26.0), ("ms", 42.25, 29.0)])
        # met1 anchors do not carry port_dir (it defaults to 0; only the
        # cap3/cap4 planes pass it through) -- the direction swap matters
        # here only because both 0 and 180 stay S/D-direction ports

    def test_cap_geometry_ports_map_with_cap_prefix(self):
        blocks = {"bc": self.block(
            "bc", "cap1p", {"TOP": "c1", "BOT": "c2"},
            [report_port("C0_TOP", 1.0, 2.0, 0.6, 0, layer=L_MET3),
             report_port("C0_BOT", 2.0, 2.0, 0.6, 90, layer=L_MET4)])}
        anchors, straps, mcons = GI.collect_anchors(blocks)
        self.assertEqual([(a.net, a.plane, a.y, a.block_y0, a.block_y1)
                          for a in anchors],
                         [("c1", "cap3", 9.0, 7.0, 11.0),
                          ("c2", "cap4", 9.0, 7.0, 11.0)])
        self.assertEqual((straps, mcons), ([], []))

    def test_sorted_block_order_not_insertion_order(self):
        blocks = {"zz": self.block("zz", "n4", {"S": "nz"},
                                   [report_port("U0_S", 1.0, 1.0, 0.42, 0)]),
                  "aa": self.block("aa", "n4", {"S": "nna"},
                                   [report_port("U0_S", 1.0, 1.0, 0.42, 0)])}
        anchors, _straps, _mcons = GI.collect_anchors(blocks)
        self.assertEqual([a.block for a in anchors], ["aa", "zz"])

    def test_ring_block_wires_only_its_west_tap(self):
        ring = self.block("ptap", "ptap", {"TAP": "vssa"},
                          [report_port("TAP_W", 1.0, 1.0, 0.42, 0),
                           report_port("TAP_N", 5.0, 5.0, 0.42, 90)])
        ring.is_ring = True
        anchors, _straps, _mcons = GI.collect_anchors({"ptap": ring})
        # port_nets_of keeps TAP_W only; TAP_N is unmapped and skipped
        self.assertEqual([(a.net, a.ports) for a in anchors],
                         [("vssa", ["TAP_W"])])


if __name__ == "__main__":
    unittest.main()

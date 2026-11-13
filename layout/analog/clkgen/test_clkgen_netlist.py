"""Tests for the clkgen netlist reader and gate recogniser. Run:

    python3 -I -m unittest discover -s layout/analog/clkgen -p 'test_*.py'

The layout generator derives everything it draws from `design/clkgen/clkgen.spice`,
so these tests pin the two things a silent drift would corrupt: the device count
the layout is graded against, and the gate decomposition the floorplan is built
from. No PDK and no `klt` are needed -- this is pure netlist reading.
"""

import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))

from clkgen_netlist import (  # noqa: E402
    VDD,
    VSS,
    NetlistError,
    build_gates,
    check_identifiers,
    device_counts,
    net_names,
    parse_netlist,
    parse_ports,
    size_groups,
)

NETLIST = REPO / "design/clkgen/clkgen.spice"


def netlist_text():
    return NETLIST.read_text()


class Parsing(unittest.TestCase):
    def test_ports_are_the_subckt_line(self):
        self.assertEqual(
            parse_ports(netlist_text()),
            ["vdda", "vssa", "clk", "phi1", "phi1b", "phi1e", "phi2"],
        )

    def test_continuation_lines_are_joined(self):
        """Every device line in this netlist wraps onto a `+` line.

        Read line-by-line instead, and `L`/`W`/`m` land on a line the reader
        never associates with its device -- the 21/21 split would still look
        right while every size was wrong.
        """
        devices = parse_netlist(netlist_text())
        self.assertEqual(len(devices), 42)
        for device in devices:
            self.assertGreater(device.l_um, 0.0, device.name)
            self.assertGreater(device.w_um, 0.0, device.name)

    def test_device_line_count_per_model(self):
        counts = device_counts(parse_netlist(netlist_text()))
        self.assertEqual(counts["nfet"]["lines"], 21)
        self.assertEqual(counts["pfet"]["lines"], 21)

    def test_m_expands_the_drawn_device_count(self):
        """`m=` is a device count, not a size.

        Eight of the 42 lines carry `m=2`/`3`/`4` -- the four phase-output
        inverters. SPICE reads that as that many devices in parallel, so the
        layout draws 56, and 42 is the *line* count, not the device count.
        This is the number `klt extract` is compared against.
        """
        counts = device_counts(parse_netlist(netlist_text()))
        self.assertEqual(counts["nfet"]["drawn"], 28)
        self.assertEqual(counts["pfet"]["drawn"], 28)

    def test_multiplied_devices_are_exactly_the_output_inverters(self):
        multiplied = sorted(
            d.name for d in parse_netlist(netlist_text()) if d.m != 1
        )
        self.assertEqual(
            multiplied,
            [
                "XIphi1_n", "XIphi1_p",
                "XIphi1b_n", "XIphi1b_p",
                "XIphi1e_n", "XIphi1e_p",
                "XIphi2_n", "XIphi2_p",
            ],
        )

    def test_size_groups_sum_to_the_drawn_count(self):
        devices = parse_netlist(netlist_text())
        self.assertEqual(sum(size_groups(devices).values()), 56)

    def test_every_net_name_is_a_usable_identifier(self):
        check_identifiers(net_names(netlist_text()) + parse_ports(netlist_text()))


class Rejections(unittest.TestCase):
    """The reader refuses what the layout builder cannot draw."""

    def test_multi_finger_device_is_refused(self):
        text = ".subckt t a\nXa d g s b sky130_fd_pr__nfet_01v8 L=0.15 W=1 nf=2 m=1\n.ends\n"
        with self.assertRaisesRegex(NetlistError, "nf=2"):
            parse_netlist(text)

    def test_unknown_model_is_refused(self):
        text = ".subckt t a\nXa d g s b sky130_fd_pr__nfet_g5v0d10v5 L=0.15 W=1 nf=1\n.ends\n"
        with self.assertRaisesRegex(NetlistError, "unsupported model"):
            parse_netlist(text)

    def test_mult_disagreeing_with_m_is_refused(self):
        text = (
            ".subckt t a\n"
            "Xa d g s b sky130_fd_pr__nfet_01v8 L=0.15 W=1 nf=1 mult=2 m=3\n.ends\n"
        )
        with self.assertRaisesRegex(NetlistError, "disagrees"):
            parse_netlist(text)


class GateRecognition(unittest.TestCase):
    def setUp(self):
        self.devices = parse_netlist(netlist_text())
        self.gates = {g.out: g for g in build_gates(self.devices)}

    def test_every_device_lands_in_exactly_one_gate(self):
        assigned = [
            d.name
            for g in self.gates.values()
            for d in (*g.pull_down, *g.pull_up)
        ]
        self.assertEqual(len(assigned), 42)
        self.assertEqual(sorted(assigned), sorted(d.name for d in self.devices))

    def test_eighteen_gates_fifteen_inverters_three_nor2(self):
        self.assertEqual(len(self.gates), 18)
        kinds = sorted(g.kind for g in self.gates.values())
        self.assertEqual(kinds.count("inv"), 15)
        self.assertEqual(kinds.count("nor2"), 3)

    def test_the_three_nor2_gates_are_the_cross_coupled_core_and_phi1(self):
        """SIZING.md's structure section, re-derived from the netlist.

        `core1 = NOR(clkb, p2d)` and `core2 = NOR(clk, p1d)` are the
        cross-coupled pair; `n1 = NOR(core1, d1_3)` is the phi1 widener. A
        fourth NOR appearing, or one of these turning into an inverter, means
        the schematic changed under the layout.
        """
        nor2 = {out for out, g in self.gates.items() if g.kind == "nor2"}
        self.assertEqual(nor2, {"core1", "core2", "n1"})
        self.assertEqual(self.gates["core1"].inputs, ["clkb", "p2d"])
        self.assertEqual(self.gates["core2"].inputs, ["clk", "p1d"])
        self.assertEqual(self.gates["n1"].inputs, ["core1", "d1_3"])

    def test_pull_up_is_ordered_from_the_rail(self):
        """A NOR2's stack order decides which array unit is which.

        `_walk` returns the rail-side device first; the layout puts that one on
        array unit 0 and abuts `U0_D` with `U1_S` to make the series node. Get
        the order backwards and the stack is wired inside out.
        """
        for out in ("core1", "core2", "n1"):
            stack = self.gates[out].pull_up
            self.assertEqual(len(stack), 2)
            self.assertIn(VDD, (stack[0].ta, stack[0].tb))
            self.assertIn(out, (stack[1].ta, stack[1].tb))
            self.assertEqual(stack[0].other(VDD), stack[1].other(out))

    def test_output_inverter_multiplicities_match_sizing_md(self):
        """phi1e/phi1 x2, phi1b x3, phi2 x4 -- sized by their load."""
        self.assertEqual(self.gates["phi1e"].m, 2)
        self.assertEqual(self.gates["phi1"].m, 2)
        self.assertEqual(self.gates["phi1b"].m, 3)
        self.assertEqual(self.gates["phi2"].m, 4)

    def test_unit_counts_sum_to_the_drawn_device_count(self):
        total = sum(g.nfet_units + g.pfet_units for g in self.gates.values())
        self.assertEqual(total, 56)

    def test_every_gate_is_balanced_and_body_tied(self):
        for out, gate in self.gates.items():
            self.assertEqual(len(gate.pull_down), len(gate.pull_up), out)
            for device in gate.pull_down:
                self.assertEqual(device.bulk, VSS, device.name)
                self.assertEqual(device.other(out), VSS, device.name)
            for device in gate.pull_up:
                self.assertEqual(device.bulk, VDD, device.name)

    def test_series_nfet_stack_is_refused(self):
        """Only parallel pull-downs are laid out; a NAND would need new code."""
        text = (
            ".subckt t vdda vssa a y\n"
            "Xn0 y a mid vssa sky130_fd_pr__nfet_01v8 L=0.15 W=1 nf=1 m=1\n"
            "Xn1 mid a vssa vssa sky130_fd_pr__nfet_01v8 L=0.15 W=1 nf=1 m=1\n"
            "Xp0 vdda a y vdda sky130_fd_pr__pfet_01v8 L=0.15 W=2 nf=1 m=1\n"
            "Xp1 vdda a y vdda sky130_fd_pr__pfet_01v8 L=0.15 W=2 nf=1 m=1\n"
            ".ends\n"
        )
        with self.assertRaisesRegex(NetlistError, "series stack"):
            build_gates(parse_netlist(text))

    def test_mixed_multiplicity_within_a_gate_is_refused(self):
        text = (
            ".subckt t vdda vssa a y\n"
            "Xn y a vssa vssa sky130_fd_pr__nfet_01v8 L=0.15 W=1 nf=1 m=2\n"
            "Xp vdda a y vdda sky130_fd_pr__pfet_01v8 L=0.15 W=2 nf=1 m=1\n"
            ".ends\n"
        )
        with self.assertRaisesRegex(NetlistError, "disagree on m"):
            build_gates(parse_netlist(text))


if __name__ == "__main__":
    unittest.main()

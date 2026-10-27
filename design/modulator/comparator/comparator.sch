v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {sky130-comparator -- design/comparator.sch  (issue #34)

Static-preamplifier + dynamic latch per DR-004 (issue #34): a
continuously-biased resistive-load NMOS preamplifier in front of a
clocked StrongARM-class latch stage (PMOS-cross-coupled, NMOS steering
pair gated by the preamp outputs). This supersedes BOTH clauses DR-001
scoped against the preamp class -- Decision 1 ("No static preamp",
rejected then on headroom) and Decision 2's single-tail/no-double-tail
scoping -- with the four-corner headroom evidence DR-001 asked a
supersession to carry. DR-001's Decision 3 reset property is preserved on
the latch stage; DR-003's soft-clock shaper stays on the clock port.

16 devices -- 13 MOSFETs + 3 poly resistors:
  1 preamp tail NMOS        M_PTAIL   (gate VDD, static current source)
  2 preamp input NMOS       M_PINN, M_PINP  (gates VINN/VINP; drains
                                OUTN1/OUTP1 -- the offset lever, unchanged)
  2 preamp load resistors   R_LP, R_LN  (res_high_po, VDD -> OUTx1)
  2 OUT1 absorber caps      M_C1P, M_C1N (OUTx1 -> GND, nfet MOS caps --
                                absorb the steering pair's gate kick so
                                it never reaches the pins)
  2 latch steering NMOS     M_STN_P, M_STN_N (gates OUTP1/OUTN1, sources
                                TAIL2, drains OUTP/OUTN)
  2 cross-coupled latch PMOS M_LATP_P, M_LATP_N
  1 latch tail NMOS         M_TAIL2   (gate CLKT, strong switch)
  2 output-node reset PMOS  M_RST_P, M_RST_N  (gates CLKT)
  1 poly clock resistor     R_CLKS   (CLK -> CLKT, res_high_po; DR-003)
  1 clock MOS capacitor     M_CLKCAP (CLKT -> GND, nfet_01v8; DR-003)

WHY A STATIC PREAMP (the measured evidence, in DR-004). The double-tail
topology (evaluated FIRST, per this issue's guidance, with the committed
probe deck spec/dr-004-support/double_tail_probe.spice) removes the
regenerative DIP/DIN collapse that dominated DR-003's 85.71 mV -- but its
remaining disturbance is the input pair's own channel formation: a
dynamic NMOS input stage starts evaluate with its source node high (Vgs
below Vth, no channel), and the source node's evaluate transition forms
both channels, charging Cox*W*L*delta(Vgs) of gate charge through
whatever drives the pins -- 1 kOhm, common-mode. That transient is gated
by the SAME source-node ramp that gates the stage's transconductance, so
kickback and decision speed stay ~1:1 elastic -- the double-tail variant
measured a worst-node 7.5 mV at 0.77 ns and (one shaper step softer,
tau ~ 500 ps) 7.1 mV at 1.14 ns: still above the ratified 5 mV bound
while the decision time stretches 1.5x, the same trade DR-003 measured
on the single tail. A continuously-biased preamp breaks the mechanism at
its root: the input pair's channels are ALWAYS formed (Vgs constant, zero
formation charge to supply at the edge), and whatever the latch kicks
back arrives at the preamp OUTPUT nodes, where explicit capacitance
absorbs it before it can reach the pins. Measured: 1.89 mV worst-node
peak at 0.40 ns (tt/27C, kickback record in DR-004's citation list).

Reset (CLK=0, CLKT=0): M_RST_P/M_RST_N precharge OUTP/OUTN to VDD. Every
latch PMOS then sits at Vgs = 0 exactly (gate at VDD from the opposite
precharged output, source at VDD), so the cross-coupled loop's gain is
zero and the reset state is a stable, all-devices-off equilibrium with no
VDD->GND path -- DR-001 Decision 3's property on the latch stage. The
steering pair's gates sit at the preamp's static output common mode
(measured 1.10-1.25 V across the four headroom-probe corners), so those
devices conduct only while TAIL2 charges to ~Vgs-Vth; M_TAIL2 is off, so
no supply path exists (run.py's reset
negative control + gnd-tied positive control -- the steering pair's
sources moved TAIL2->GND, the same counterfactual shape DR-001 Decision 3
established -- verify exactly this). The preamp never resets: it is
statically biased at all times, which is the point.

Evaluate (CLK rising, shaped to tau ~ 250 ps by R_CLKS + M_CLKCAP):
M_TAIL2 turns on and grounds TAIL2; the steering pair -- whose gates have
carried the preamp's differential since long before the edge -- discharges
the precharged outputs with that differential already present (a ~A*Vin
head start, A ~= gm_in*R_load), and the PMOS latch regenerates.
Vin,diff = VINP - VINN > 0  =>  M_PINP conducts more  =>  OUTP1 falls
  => M_STN_P (gate OUTP1) weakens  =>  OUTP kept high by M_LATP_P
  (gate OUTN) while M_STN_N (gate OUTN1, the higher static gate) pulls
  OUTN down  =>  OUTP settles high, same polarity convention as every
  prior revision of this design.

Ports (flat, top level -- drop-in DUT fragment for
sim/comparator-decision/testbench/comparator_core.spice; UNCHANGED --
the preamp is internally biased, no new port):
  VDD, GND, CLK, VINP, VINN, OUTP, OUTN.     Internal nodes: TAILP,
  OUTP1, OUTN1, TAIL2, CLKT.

Every device is sky130_fd_pr__{n,p}fet_01v8 -- the 1.8V core flavour, the only
complementary pair sky130 ships (top-level README, "Supply / power" row) and
the flavour this repo's 1.8V headroom constraint (CLAUDE.md) refers to.} -60 -980 0 0 0.35 0.35 {}

T {SIZING RATIONALE (issue #34) -- first-principles against the same
installed sky130 models, same conventions as DR-001 Amendment 1. Full
evidence and the measured option ladder: DR-004
(spec/decision-records/DR-004-*.md) and the records it cites.

  Device group          Devices                 W (um)  L (um)   set by
  --------------------  ----------------------  ------  ------   ----------------
  preamp tail           M_PTAIL                   0.8    0.5     static current
                                                                 (supply row)
  preamp input pair     M_PINN, M_PINP            13     0.5     offset + noise
                                                                 budget
  preamp loads          R_LP, R_LN                --     22      gain A ~ gm*R and
                                                                 output CM ~ 1.1-1.25 V
  OUT1 absorber caps    M_C1P, M_C1N              40     0.5     kickback: absorb the
                                                                 steering gate kick
  latch steering pair   M_STN_P, M_STN_N           8     0.5     steer strength /
                                                                 offset (2nd)
  latch tail            M_TAIL2                    8     0.5     output descent +
                                                                 regeneration speed
  cross-coupled PMOS    M_LATP_P, M_LATP_N        16     0.5     trip point (as
                                                                 DR-001 Amd 1)
  output reset PMOS     M_RST_P, M_RST_N           8     0.5     reset tau / C_out
  clock shaper R        R_CLKS                    --    1.75    kickback (DR-003)
  clock shaper C        M_CLKCAP                  20     0.5     kickback (DR-003)

L = 0.5um common to all MOSFETs, unchanged from DR-001 Amendment 1 (same
Pelgrom argument; keeps the DR-001 probe geometry so that record's
four-corner Vth/Vdsat table transfers). The poly loads are
res_high_po_0p35 (~1.37 kohm/um nominal): L = 22um gives ~30 kohm per
side (solved large-signal value ~30.1 kohm at the tt bias, per
spec/dr-004-support/preamp_op_probe.spice -- res_high_po is nonlinear, so
the solved value is the one the gain actually realizes).

W_in = 13um -- the offset lever, widened one step from DR-001 Amd 1's
10um. sigma_Vth,pair = sqrt(2)*AVT_n/sqrt(W*L) = 1.86 mV at 13um
(AVT_n = 3.356 mV.um), the same 70%-of-variance budget DR-001 Amendment
1 set; the measured N=16 MC record (tt_mm, seed 1) lands at 1.79 mV
input-referred. The widening is NOT for offset -- it is the noise row's
lever (input-referred thermal noise falls as 1/gm, gm as sqrt(W) at
fixed current): at the 10um/25uA first cut the measured input-referred
noise was 0.72 mV rms differential, clearing the ratified 1.0 mV target
but missing the 0.6 mV stretch; the 13um pair + the raised bias current
bring the measured value to 0.57 mV, clearing both. The steering pair's
Vth mismatch is referred to the input divided by the preamp gain
A ~= gm_in*R_load (~13-18 V/V across the four probe corners): W_stn = 8um
holds its contribution well under half a millivolt. Poly-load matching
on this PDK is not a local-mismatch model term (the _mm corners mismatch
only Vth, per DR-001 Amd 1's AVT probe) -- the MC record measures
whatever it contributes.

M_PTAIL W=0.8um at L=0.5, gate at VDD -- a gate-at-supply NMOS current
source: the cheapest bias that needs no new port and no reference. Sized
with R_L for a total preamp current of ~37-47 uA across the four probe
corners (per side 18-24 uA; tt ~ 22 uA/side, CM ~ 1.15 V): the static
power cost of the preamp class, ~65-85 uW at 1.8 V, recorded against the
DRAFT (open) Supply/power row's figures -- the row's "one decision per
clock edge at TBD clock rate" framing is itself re-anchored by this class
change, per DR-004 (which also measures the evaluate-phase current the
DC-biased steering pair adds). gm_in at that bias is 0.43-0.59 mS across
corners, which is also the noise sub-model's real transconductance: the
noise sub-model is now a REAL static stage (a continuous operating
point, not an integration-phase proxy).

R_load ~ 30 kohm -- sets both the gain (A = gm_in*R_eff ~ 13-18 V/V
across corners) and the output common mode (VDD - I_side*R ~ 1.10-1.25 V,
i.e. the steering pair's static Vgs: comfortably above Vth,n for steering
headroom at every corner, and with M_TAIL2 off in reset no supply path
exists for it to hold alive -- the reset record verifies exactly this).

Kickback budget, stated as the design's central claim and measured in the
records: the pins are coupled to the latch only through the preamp input
pair's Cgd with the preamp outputs moving (the steering gates are kicked
when TAIL2 slams down; the preamp's own output differential is static).
The kick absorbed at OUTx1 is set by the steering pair's channel-charge
demand against the OUTx1 node capacitance; the pin sees that node's
swing through the Cgd/Cgs divider of the input pair. DR-004's kickback
records measure the residual end to end.

Headroom, the clause this design supersedes (DR-001 Decision 1), measured
by the committed four-corner probe (spec/dr-004-support/preamp_op_probe.spice,
the dr-001-support discipline re-run on this stack). The input pair's
saturation margin Vds,in - Vdsat,in -- the region question DR-001's
planning formula was a proxy for -- is +1.008 V at ss/-40C, +0.876 V at
tt/27C, +0.989 V at ss/27C, +0.881 V at tt/-40C: positive with room at
every corner, because the preamp's load is a resistor hanging from the
rail, not a stacked device -- the stack is SHORTER than the DR-001
single-tail latch stack it replaces (Vds,in ~ 0.97-1.08 V vs the old
design's DIP/DIN sitting a Vth above the tail switch). M_PTAIL itself
sits in deep triode at every corner (Vds = 0.13-0.18 V against Vdsat =
0.54-0.65 V): a switch-like gate-at-supply source, so the DR-001 Amd 1
finding that a CLK-gated tail's Vdsat budget is recoverable transfers to
this always-on tail verbatim.} -60 -680 0 0 0.28 0.28 {}

C {sky130_fd_pr/nfet_01v8.sym} 0 0 0 0 {name=M_PTAIL L=0.5 W=0.8 nf=1 model=nfet_01v8}
C {sky130_fd_pr/nfet_01v8.sym} 150 0 0 0 {name=M_PINN L=0.5 W=13 nf=1 model=nfet_01v8}
C {sky130_fd_pr/nfet_01v8.sym} 300 0 0 0 {name=M_PINP L=0.5 W=13 nf=1 model=nfet_01v8}
C {sky130_fd_pr/nfet_01v8.sym} 450 0 0 0 {name=M_TAIL2 L=0.5 W=8 nf=1 model=nfet_01v8}
C {sky130_fd_pr/nfet_01v8.sym} 600 0 0 0 {name=M_STN_P L=0.5 W=8 nf=1 model=nfet_01v8}
C {sky130_fd_pr/nfet_01v8.sym} 750 0 0 0 {name=M_STN_N L=0.5 W=8 nf=1 model=nfet_01v8}

C {sky130_fd_pr/pfet_01v8.sym} 450 200 0 0 {name=M_LATP_P L=0.5 W=16 nf=1 model=pfet_01v8}
C {sky130_fd_pr/pfet_01v8.sym} 600 200 0 0 {name=M_LATP_N L=0.5 W=16 nf=1 model=pfet_01v8}
C {sky130_fd_pr/pfet_01v8.sym} 750 200 0 0 {name=M_RST_P L=0.5 W=8 nf=1 model=pfet_01v8}
C {sky130_fd_pr/pfet_01v8.sym} 900 200 0 0 {name=M_RST_N L=0.5 W=8 nf=1 model=pfet_01v8}

C {sky130_fd_pr/res_high_po_0p35.sym} 150 -150 0 0 {name=R_LP L=22 mult=1 model=res_high_po_0p35 spiceprefix=X}
C {lab_wire.sym} 150 -180 0 0 {name=l_lp_a lab=VDD}
C {lab_wire.sym} 150 -120 0 0 {name=l_lp_b lab=OUTN1}
C {lab_wire.sym} 130 -150 0 0 {name=l_lp_s lab=GND}
C {sky130_fd_pr/res_high_po_0p35.sym} 300 -150 0 0 {name=R_LN L=22 mult=1 model=res_high_po_0p35 spiceprefix=X}
C {lab_wire.sym} 300 -180 0 0 {name=l_ln_a lab=VDD}
C {lab_wire.sym} 300 -120 0 0 {name=l_ln_b lab=OUTP1}
C {lab_wire.sym} 280 -150 0 0 {name=l_ln_s lab=GND}
C {sky130_fd_pr/res_high_po_0p35.sym} 0 -150 0 0 {name=R_CLKS L=1.75 mult=1 model=res_high_po_0p35 spiceprefix=X}
C {lab_wire.sym} 0 -120 0 0 {name=l_clks_p lab=CLKT}
C {lab_wire.sym} -20 -150 0 0 {name=l_clks_b lab=GND}
C {lab_wire.sym} 0 -180 0 0 {name=l_clks_m lab=CLK}
C {sky130_fd_pr/nfet_01v8.sym} 750 -150 0 0 {name=M_CLKCAP L=0.5 W=20 nf=1 model=nfet_01v8}
C {lab_wire.sym} 770 -180 0 0 {name=l_clkcap_d lab=GND}
C {lab_wire.sym} 730 -150 0 0 {name=l_clkcap_g lab=CLKT}
C {lab_wire.sym} 770 -120 0 0 {name=l_clkcap_s lab=GND}
C {lab_wire.sym} 770 -150 0 0 {name=l_clkcap_b lab=GND}
C {sky130_fd_pr/nfet_01v8.sym} 600 -150 0 0 {name=M_C1P L=0.5 W=40 nf=1 model=nfet_01v8}
C {lab_wire.sym} 620 -180 0 0 {name=l_c1p_d lab=GND}
C {lab_wire.sym} 580 -150 0 0 {name=l_c1p_g lab=OUTP1}
C {lab_wire.sym} 620 -120 0 0 {name=l_c1p_s lab=GND}
C {lab_wire.sym} 620 -150 0 0 {name=l_c1p_b lab=GND}
C {sky130_fd_pr/nfet_01v8.sym} 450 -150 0 0 {name=M_C1N L=0.5 W=40 nf=1 model=nfet_01v8}
C {lab_wire.sym} 470 -180 0 0 {name=l_c1n_d lab=GND}
C {lab_wire.sym} 430 -150 0 0 {name=l_c1n_g lab=OUTN1}
C {lab_wire.sym} 470 -120 0 0 {name=l_c1n_s lab=GND}
C {lab_wire.sym} 470 -150 0 0 {name=l_c1n_b lab=GND}

C {lab_wire.sym} 20 -30 0 0 {name=l_ptail_d lab=TAILP}
C {lab_wire.sym} -20 0 0 0 {name=l_ptail_g lab=VDD}
C {lab_wire.sym} 20 30 0 0 {name=l_ptail_s lab=GND}
C {lab_wire.sym} 20 0 0 0 {name=l_ptail_b lab=GND}

C {lab_wire.sym} 170 -30 0 0 {name=l_pinn_d lab=OUTN1}
C {lab_wire.sym} 130 0 0 0 {name=l_pinn_g lab=VINN}
C {lab_wire.sym} 170 30 0 0 {name=l_pinn_s lab=TAILP}
C {lab_wire.sym} 170 0 0 0 {name=l_pinn_b lab=GND}

C {lab_wire.sym} 320 -30 0 0 {name=l_pinp_d lab=OUTP1}
C {lab_wire.sym} 280 0 0 0 {name=l_pinp_g lab=VINP}
C {lab_wire.sym} 320 30 0 0 {name=l_pinp_s lab=TAILP}
C {lab_wire.sym} 320 0 0 0 {name=l_pinp_b lab=GND}

C {lab_wire.sym} 470 -30 0 0 {name=l_tail2_d lab=TAIL2}
C {lab_wire.sym} 430 0 0 0 {name=l_tail2_g lab=CLKT}
C {lab_wire.sym} 470 30 0 0 {name=l_tail2_s lab=GND}
C {lab_wire.sym} 470 0 0 0 {name=l_tail2_b lab=GND}

C {lab_wire.sym} 620 -30 0 0 {name=l_stnp_d lab=OUTP}
C {lab_wire.sym} 580 0 0 0 {name=l_stnp_g lab=OUTP1}
C {lab_wire.sym} 620 30 0 0 {name=l_stnp_s lab=TAIL2}
C {lab_wire.sym} 620 0 0 0 {name=l_stnp_b lab=GND}

C {lab_wire.sym} 770 -30 0 0 {name=l_stnn_d lab=OUTN}
C {lab_wire.sym} 730 0 0 0 {name=l_stnn_g lab=OUTN1}
C {lab_wire.sym} 770 30 0 0 {name=l_stnn_s lab=TAIL2}
C {lab_wire.sym} 770 0 0 0 {name=l_stnn_b lab=GND}

C {lab_wire.sym} 470 230 0 0 {name=l_latpp_d lab=OUTP}
C {lab_wire.sym} 430 200 0 0 {name=l_latpp_g lab=OUTN}
C {lab_wire.sym} 470 170 0 0 {name=l_latpp_s lab=VDD}
C {lab_wire.sym} 470 200 0 0 {name=l_latpp_b lab=VDD}

C {lab_wire.sym} 620 230 0 0 {name=l_latpn_d lab=OUTN}
C {lab_wire.sym} 580 200 0 0 {name=l_latpn_g lab=OUTP}
C {lab_wire.sym} 620 170 0 0 {name=l_latpn_s lab=VDD}
C {lab_wire.sym} 620 200 0 0 {name=l_latpn_b lab=VDD}

C {lab_wire.sym} 770 230 0 0 {name=l_rstp_d lab=OUTP}
C {lab_wire.sym} 730 200 0 0 {name=l_rstp_g lab=CLKT}
C {lab_wire.sym} 770 170 0 0 {name=l_rstp_s lab=VDD}
C {lab_wire.sym} 770 200 0 0 {name=l_rstp_b lab=VDD}

C {lab_wire.sym} 920 230 0 0 {name=l_rstn_d lab=OUTN}
C {lab_wire.sym} 880 200 0 0 {name=l_rstn_g lab=CLKT}
C {lab_wire.sym} 920 170 0 0 {name=l_rstn_s lab=VDD}
C {lab_wire.sym} 920 200 0 0 {name=l_rstn_b lab=VDD}

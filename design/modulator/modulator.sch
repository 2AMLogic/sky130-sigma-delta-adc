v {xschem version=3.4.7 file_version=1.2
* modulator -- second-order single-bit switched-capacitor delta-sigma modulator
* (issue #41). Structure follows behavioural model B (sim/bmodel/model.py:41-42):
* two delaying integrators (the one design/integrator cell, C1 = C2 = 0.5),
* the 1-bit decision fed back to BOTH integrators, a clocked comparator
* (vendored sky130-comparator at the reuse.lock.json pin) and an SR latch that
* holds the decision through the sampling phase.
*   x1 -> integrator xi1 (vin, y), x2 -> integrator xi2 (x1, y), y = comparator(x2).
* Boundary ports (DR-005): vrefp vrefn vcm ibias vdda vssa, differential input
* vinp/vinn, bitstream bs, modulator clock clk. Decision timing: comparator
* clock is phi1, so it evaluates as phi1 rises (integrator outputs are held
* from the end of phi2) and precharges while phi2 integrates; the NAND SR latch
* (both comparator outputs high = hold) keeps dp/dn stable until the next phi1.
* Ports: vdda vssa vinp vinn vrefp vrefn vcm ibias clk bs.
}
G {}
K {}
V {}
S {}
E {}
C {sky130_fd_pr/nfet_01v8.sym} 0 0 0 0 {name=Nq_na L=0.15 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 20 -30 0 0 {name=l1 lab=Nq_m}
C {lab_wire.sym} -20 0 0 0 {name=l2 lab=outn}
C {lab_wire.sym} 20 30 0 0 {name=l3 lab=vssa}
C {lab_wire.sym} 20 0 0 0 {name=l4 lab=vssa}
C {sky130_fd_pr/nfet_01v8.sym} 150 0 0 0 {name=Nq_nb L=0.15 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 170 -30 0 0 {name=l5 lab=q}
C {lab_wire.sym} 130 0 0 0 {name=l6 lab=qb}
C {lab_wire.sym} 170 30 0 0 {name=l7 lab=Nq_m}
C {lab_wire.sym} 170 0 0 0 {name=l8 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 300 0 0 0 {name=Nq_pa L=0.15 W=1.5 nf=1 mult=1 ad=0.435 as=0.435 pd=3.58 ps=3.58 nrd=0.193333 nrs=0.193333 sa=0 sb=0 sd=0}
C {lab_wire.sym} 320 -30 0 0 {name=l9 lab=q}
C {lab_wire.sym} 280 0 0 0 {name=l10 lab=outn}
C {lab_wire.sym} 320 30 0 0 {name=l11 lab=vdda}
C {lab_wire.sym} 320 0 0 0 {name=l12 lab=vdda}
C {sky130_fd_pr/pfet_01v8.sym} 450 0 0 0 {name=Nq_pb L=0.15 W=1.5 nf=1 mult=1 ad=0.435 as=0.435 pd=3.58 ps=3.58 nrd=0.193333 nrs=0.193333 sa=0 sb=0 sd=0}
C {lab_wire.sym} 470 -30 0 0 {name=l13 lab=q}
C {lab_wire.sym} 430 0 0 0 {name=l14 lab=qb}
C {lab_wire.sym} 470 30 0 0 {name=l15 lab=vdda}
C {lab_wire.sym} 470 0 0 0 {name=l16 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 600 0 0 0 {name=Nqb_na L=0.15 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 620 -30 0 0 {name=l17 lab=Nqb_m}
C {lab_wire.sym} 580 0 0 0 {name=l18 lab=outp}
C {lab_wire.sym} 620 30 0 0 {name=l19 lab=vssa}
C {lab_wire.sym} 620 0 0 0 {name=l20 lab=vssa}
C {sky130_fd_pr/nfet_01v8.sym} 750 0 0 0 {name=Nqb_nb L=0.15 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 770 -30 0 0 {name=l21 lab=qb}
C {lab_wire.sym} 730 0 0 0 {name=l22 lab=q}
C {lab_wire.sym} 770 30 0 0 {name=l23 lab=Nqb_m}
C {lab_wire.sym} 770 0 0 0 {name=l24 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 900 0 0 0 {name=Nqb_pa L=0.15 W=1.5 nf=1 mult=1 ad=0.435 as=0.435 pd=3.58 ps=3.58 nrd=0.193333 nrs=0.193333 sa=0 sb=0 sd=0}
C {lab_wire.sym} 920 -30 0 0 {name=l25 lab=qb}
C {lab_wire.sym} 880 0 0 0 {name=l26 lab=outp}
C {lab_wire.sym} 920 30 0 0 {name=l27 lab=vdda}
C {lab_wire.sym} 920 0 0 0 {name=l28 lab=vdda}
C {sky130_fd_pr/pfet_01v8.sym} 1050 0 0 0 {name=Nqb_pb L=0.15 W=1.5 nf=1 mult=1 ad=0.435 as=0.435 pd=3.58 ps=3.58 nrd=0.193333 nrs=0.193333 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1070 -30 0 0 {name=l29 lab=qb}
C {lab_wire.sym} 1030 0 0 0 {name=l30 lab=q}
C {lab_wire.sym} 1070 30 0 0 {name=l31 lab=vdda}
C {lab_wire.sym} 1070 0 0 0 {name=l32 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 1200 0 0 0 {name=Idpa_n L=0.15 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1220 -30 0 0 {name=l33 lab=dpn}
C {lab_wire.sym} 1180 0 0 0 {name=l34 lab=q}
C {lab_wire.sym} 1220 30 0 0 {name=l35 lab=vssa}
C {lab_wire.sym} 1220 0 0 0 {name=l36 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 1350 0 0 0 {name=Idpa_p L=0.15 W=4 nf=1 mult=1 ad=1.16 as=1.16 pd=8.58 ps=8.58 nrd=0.0725 nrs=0.0725 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1370 -30 0 0 {name=l37 lab=dpn}
C {lab_wire.sym} 1330 0 0 0 {name=l38 lab=q}
C {lab_wire.sym} 1370 30 0 0 {name=l39 lab=vdda}
C {lab_wire.sym} 1370 0 0 0 {name=l40 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 1500 0 0 0 {name=Idpb_n L=0.15 W=4 nf=1 mult=2 ad=1.16 as=1.16 pd=8.58 ps=8.58 nrd=0.0725 nrs=0.0725 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1520 -30 0 0 {name=l41 lab=dp}
C {lab_wire.sym} 1480 0 0 0 {name=l42 lab=dpn}
C {lab_wire.sym} 1520 30 0 0 {name=l43 lab=vssa}
C {lab_wire.sym} 1520 0 0 0 {name=l44 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 1650 0 0 0 {name=Idpb_p L=0.15 W=8 nf=1 mult=2 ad=2.32 as=2.32 pd=16.58 ps=16.58 nrd=0.03625 nrs=0.03625 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1670 -30 0 0 {name=l45 lab=dp}
C {lab_wire.sym} 1630 0 0 0 {name=l46 lab=dpn}
C {lab_wire.sym} 1670 30 0 0 {name=l47 lab=vdda}
C {lab_wire.sym} 1670 0 0 0 {name=l48 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 1800 0 0 0 {name=Idna_n L=0.15 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1820 -30 0 0 {name=l49 lab=dnn}
C {lab_wire.sym} 1780 0 0 0 {name=l50 lab=qb}
C {lab_wire.sym} 1820 30 0 0 {name=l51 lab=vssa}
C {lab_wire.sym} 1820 0 0 0 {name=l52 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 1950 0 0 0 {name=Idna_p L=0.15 W=4 nf=1 mult=1 ad=1.16 as=1.16 pd=8.58 ps=8.58 nrd=0.0725 nrs=0.0725 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1970 -30 0 0 {name=l53 lab=dnn}
C {lab_wire.sym} 1930 0 0 0 {name=l54 lab=qb}
C {lab_wire.sym} 1970 30 0 0 {name=l55 lab=vdda}
C {lab_wire.sym} 1970 0 0 0 {name=l56 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 2100 0 0 0 {name=Idnb_n L=0.15 W=4 nf=1 mult=2 ad=1.16 as=1.16 pd=8.58 ps=8.58 nrd=0.0725 nrs=0.0725 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2120 -30 0 0 {name=l57 lab=dn}
C {lab_wire.sym} 2080 0 0 0 {name=l58 lab=dnn}
C {lab_wire.sym} 2120 30 0 0 {name=l59 lab=vssa}
C {lab_wire.sym} 2120 0 0 0 {name=l60 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 2250 0 0 0 {name=Idnb_p L=0.15 W=8 nf=1 mult=2 ad=2.32 as=2.32 pd=16.58 ps=16.58 nrd=0.03625 nrs=0.03625 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2270 -30 0 0 {name=l61 lab=dn}
C {lab_wire.sym} 2230 0 0 0 {name=l62 lab=dnn}
C {lab_wire.sym} 2270 30 0 0 {name=l63 lab=vdda}
C {lab_wire.sym} 2270 0 0 0 {name=l64 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 2400 0 0 0 {name=Ibsa_n L=0.15 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2420 -30 0 0 {name=l65 lab=bsn}
C {lab_wire.sym} 2380 0 0 0 {name=l66 lab=q}
C {lab_wire.sym} 2420 30 0 0 {name=l67 lab=vssa}
C {lab_wire.sym} 2420 0 0 0 {name=l68 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 2550 0 0 0 {name=Ibsa_p L=0.15 W=4 nf=1 mult=1 ad=1.16 as=1.16 pd=8.58 ps=8.58 nrd=0.0725 nrs=0.0725 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2570 -30 0 0 {name=l69 lab=bsn}
C {lab_wire.sym} 2530 0 0 0 {name=l70 lab=q}
C {lab_wire.sym} 2570 30 0 0 {name=l71 lab=vdda}
C {lab_wire.sym} 2570 0 0 0 {name=l72 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 2700 0 0 0 {name=Ibsb_n L=0.15 W=4 nf=1 mult=1 ad=1.16 as=1.16 pd=8.58 ps=8.58 nrd=0.0725 nrs=0.0725 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2720 -30 0 0 {name=l73 lab=bs}
C {lab_wire.sym} 2680 0 0 0 {name=l74 lab=bsn}
C {lab_wire.sym} 2720 30 0 0 {name=l75 lab=vssa}
C {lab_wire.sym} 2720 0 0 0 {name=l76 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 2850 0 0 0 {name=Ibsb_p L=0.15 W=8 nf=1 mult=1 ad=2.32 as=2.32 pd=16.58 ps=16.58 nrd=0.03625 nrs=0.03625 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2870 -30 0 0 {name=l77 lab=bs}
C {lab_wire.sym} 2830 0 0 0 {name=l78 lab=bsn}
C {lab_wire.sym} 2870 30 0 0 {name=l79 lab=vdda}
C {lab_wire.sym} 2870 0 0 0 {name=l80 lab=vdda}
C {clkgen/clkgen.sym} 0 4000 0 0 {name=xclk}
C {lab_wire.sym} -150 3920 0 0 {name=l81 lab=vdda}
C {lab_wire.sym} -150 3940 0 0 {name=l82 lab=vssa}
C {lab_wire.sym} -150 3960 0 0 {name=l83 lab=clk}
C {lab_wire.sym} 150 3920 0 0 {name=l84 lab=phi1}
C {lab_wire.sym} 150 3940 0 0 {name=l85 lab=phi1b}
C {lab_wire.sym} 150 3960 0 0 {name=l86 lab=phi1e}
C {lab_wire.sym} 150 3980 0 0 {name=l87 lab=phi2}
C {integrator/integrator.sym} 600 4000 0 0 {name=xi1}
C {lab_wire.sym} 450 3720 0 0 {name=l88 lab=vdda}
C {lab_wire.sym} 450 3740 0 0 {name=l89 lab=vssa}
C {lab_wire.sym} 450 3760 0 0 {name=l90 lab=vinp}
C {lab_wire.sym} 450 3780 0 0 {name=l91 lab=vinn}
C {lab_wire.sym} 450 3800 0 0 {name=l92 lab=vrefp}
C {lab_wire.sym} 450 3820 0 0 {name=l93 lab=vrefn}
C {lab_wire.sym} 450 3840 0 0 {name=l94 lab=vcm}
C {lab_wire.sym} 450 3860 0 0 {name=l95 lab=ibias}
C {lab_wire.sym} 450 3880 0 0 {name=l96 lab=phi1}
C {lab_wire.sym} 450 3900 0 0 {name=l97 lab=phi1b}
C {lab_wire.sym} 450 3920 0 0 {name=l98 lab=phi1e}
C {lab_wire.sym} 450 3940 0 0 {name=l99 lab=phi2}
C {lab_wire.sym} 450 3960 0 0 {name=l100 lab=dp}
C {lab_wire.sym} 450 3980 0 0 {name=l101 lab=dn}
C {lab_wire.sym} 750 3720 0 0 {name=l102 lab=o1p}
C {lab_wire.sym} 750 3740 0 0 {name=l103 lab=o1n}
C {integrator/integrator.sym} 1200 4000 0 0 {name=xi2}
C {lab_wire.sym} 1050 3720 0 0 {name=l104 lab=vdda}
C {lab_wire.sym} 1050 3740 0 0 {name=l105 lab=vssa}
C {lab_wire.sym} 1050 3760 0 0 {name=l106 lab=o1p}
C {lab_wire.sym} 1050 3780 0 0 {name=l107 lab=o1n}
C {lab_wire.sym} 1050 3800 0 0 {name=l108 lab=vrefp}
C {lab_wire.sym} 1050 3820 0 0 {name=l109 lab=vrefn}
C {lab_wire.sym} 1050 3840 0 0 {name=l110 lab=vcm}
C {lab_wire.sym} 1050 3860 0 0 {name=l111 lab=ibias}
C {lab_wire.sym} 1050 3880 0 0 {name=l112 lab=phi1}
C {lab_wire.sym} 1050 3900 0 0 {name=l113 lab=phi1b}
C {lab_wire.sym} 1050 3920 0 0 {name=l114 lab=phi1e}
C {lab_wire.sym} 1050 3940 0 0 {name=l115 lab=phi2}
C {lab_wire.sym} 1050 3960 0 0 {name=l116 lab=dp}
C {lab_wire.sym} 1050 3980 0 0 {name=l117 lab=dn}
C {lab_wire.sym} 1350 3720 0 0 {name=l118 lab=o2p}
C {lab_wire.sym} 1350 3740 0 0 {name=l119 lab=o2n}
C {modulator/comparator/comparator.sym} 1800 4000 0 0 {name=xcmp}
C {lab_wire.sym} 1650 3900 0 0 {name=l120 lab=vdda}
C {lab_wire.sym} 1650 3920 0 0 {name=l121 lab=vssa}
C {lab_wire.sym} 1650 3940 0 0 {name=l122 lab=phi1}
C {lab_wire.sym} 1650 3960 0 0 {name=l123 lab=o2p}
C {lab_wire.sym} 1650 3980 0 0 {name=l124 lab=o2n}
C {lab_wire.sym} 1950 3900 0 0 {name=l125 lab=outp}
C {lab_wire.sym} 1950 3920 0 0 {name=l126 lab=outn}
C {devices/iopin.sym} -400 -300 0 0 {name=p_vdda lab=vdda}
C {devices/iopin.sym} -400 -200 0 0 {name=p_vssa lab=vssa}
C {devices/ipin.sym} -400 -100 0 0 {name=p_vinp lab=vinp}
C {devices/ipin.sym} -400 0 0 0 {name=p_vinn lab=vinn}
C {devices/ipin.sym} -400 100 0 0 {name=p_vrefp lab=vrefp}
C {devices/ipin.sym} -400 200 0 0 {name=p_vrefn lab=vrefn}
C {devices/ipin.sym} -400 300 0 0 {name=p_vcm lab=vcm}
C {devices/ipin.sym} -400 400 0 0 {name=p_ibias lab=ibias}
C {devices/ipin.sym} -400 500 0 0 {name=p_clk lab=clk}
C {devices/opin.sym} -400 600 0 0 {name=p_bs lab=bs}

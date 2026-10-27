v {xschem version=3.4.7 file_version=1.2
* clkgen -- non-overlapping two-phase clock generator for the SC modulator
* (issue #41). Input clk (5.12 MHz, 50 %), outputs phi1 (sample), phi1b (its
* complement), phi1e (early phi1: falls before phi1, bottom-plate sampling) and
* phi2 (integrate). Cross-coupled NOR core: phi1e rises only after phi2 has
* fallen (p2d), phi2 rises only after phi1 has fallen (p1d). phi1 = phi1e OR
* delay(phi1e), so phi1 falls later than phi1e. All devices 1.8 V core flavour.
* Sizing trace: design/clkgen/SIZING.md. Ports: vdda vssa clk phi1 phi1b phi1e phi2.
}
G {}
K {}
V {}
S {}
E {}
C {sky130_fd_pr/nfet_01v8.sym} 0 0 0 0 {name=Ickb_n L=0.15 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 20 -30 0 0 {name=l1 lab=clkb}
C {lab_wire.sym} -20 0 0 0 {name=l2 lab=clk}
C {lab_wire.sym} 20 30 0 0 {name=l3 lab=vssa}
C {lab_wire.sym} 20 0 0 0 {name=l4 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 150 0 0 0 {name=Ickb_p L=0.15 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 170 -30 0 0 {name=l5 lab=clkb}
C {lab_wire.sym} 130 0 0 0 {name=l6 lab=clk}
C {lab_wire.sym} 170 30 0 0 {name=l7 lab=vdda}
C {lab_wire.sym} 170 0 0 0 {name=l8 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 300 0 0 0 {name=Ncore1_na L=0.15 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 320 -30 0 0 {name=l9 lab=core1}
C {lab_wire.sym} 280 0 0 0 {name=l10 lab=clkb}
C {lab_wire.sym} 320 30 0 0 {name=l11 lab=vssa}
C {lab_wire.sym} 320 0 0 0 {name=l12 lab=vssa}
C {sky130_fd_pr/nfet_01v8.sym} 450 0 0 0 {name=Ncore1_nb L=0.15 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 470 -30 0 0 {name=l13 lab=core1}
C {lab_wire.sym} 430 0 0 0 {name=l14 lab=p2d}
C {lab_wire.sym} 470 30 0 0 {name=l15 lab=vssa}
C {lab_wire.sym} 470 0 0 0 {name=l16 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 600 0 0 0 {name=Ncore1_pa L=0.15 W=4 nf=1 mult=1 ad=1.16 as=1.16 pd=8.58 ps=8.58 nrd=0.0725 nrs=0.0725 sa=0 sb=0 sd=0}
C {lab_wire.sym} 620 -30 0 0 {name=l17 lab=Ncore1_m}
C {lab_wire.sym} 580 0 0 0 {name=l18 lab=clkb}
C {lab_wire.sym} 620 30 0 0 {name=l19 lab=vdda}
C {lab_wire.sym} 620 0 0 0 {name=l20 lab=vdda}
C {sky130_fd_pr/pfet_01v8.sym} 750 0 0 0 {name=Ncore1_pb L=0.15 W=4 nf=1 mult=1 ad=1.16 as=1.16 pd=8.58 ps=8.58 nrd=0.0725 nrs=0.0725 sa=0 sb=0 sd=0}
C {lab_wire.sym} 770 -30 0 0 {name=l21 lab=core1}
C {lab_wire.sym} 730 0 0 0 {name=l22 lab=p2d}
C {lab_wire.sym} 770 30 0 0 {name=l23 lab=Ncore1_m}
C {lab_wire.sym} 770 0 0 0 {name=l24 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 900 0 0 0 {name=Ie1_n L=0.15 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 920 -30 0 0 {name=l25 lab=e1}
C {lab_wire.sym} 880 0 0 0 {name=l26 lab=core1}
C {lab_wire.sym} 920 30 0 0 {name=l27 lab=vssa}
C {lab_wire.sym} 920 0 0 0 {name=l28 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 1050 0 0 0 {name=Ie1_p L=0.15 W=4 nf=1 mult=1 ad=1.16 as=1.16 pd=8.58 ps=8.58 nrd=0.0725 nrs=0.0725 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1070 -30 0 0 {name=l29 lab=e1}
C {lab_wire.sym} 1030 0 0 0 {name=l30 lab=core1}
C {lab_wire.sym} 1070 30 0 0 {name=l31 lab=vdda}
C {lab_wire.sym} 1070 0 0 0 {name=l32 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 1200 0 0 0 {name=Iphi1e_n L=0.15 W=6 nf=1 mult=2 ad=1.74 as=1.74 pd=12.58 ps=12.58 nrd=0.0483333 nrs=0.0483333 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1220 -30 0 0 {name=l33 lab=phi1e}
C {lab_wire.sym} 1180 0 0 0 {name=l34 lab=e1}
C {lab_wire.sym} 1220 30 0 0 {name=l35 lab=vssa}
C {lab_wire.sym} 1220 0 0 0 {name=l36 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 1350 0 0 0 {name=Iphi1e_p L=0.15 W=12 nf=1 mult=2 ad=3.48 as=3.48 pd=24.58 ps=24.58 nrd=0.0241667 nrs=0.0241667 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1370 -30 0 0 {name=l37 lab=phi1e}
C {lab_wire.sym} 1330 0 0 0 {name=l38 lab=e1}
C {lab_wire.sym} 1370 30 0 0 {name=l39 lab=vdda}
C {lab_wire.sym} 1370 0 0 0 {name=l40 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 1500 0 0 0 {name=Id1_0_n L=0.5 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1520 -30 0 0 {name=l41 lab=d1_0}
C {lab_wire.sym} 1480 0 0 0 {name=l42 lab=core1}
C {lab_wire.sym} 1520 30 0 0 {name=l43 lab=vssa}
C {lab_wire.sym} 1520 0 0 0 {name=l44 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 1650 0 0 0 {name=Id1_0_p L=0.5 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1670 -30 0 0 {name=l45 lab=d1_0}
C {lab_wire.sym} 1630 0 0 0 {name=l46 lab=core1}
C {lab_wire.sym} 1670 30 0 0 {name=l47 lab=vdda}
C {lab_wire.sym} 1670 0 0 0 {name=l48 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 1800 0 0 0 {name=Id1_1_n L=0.5 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1820 -30 0 0 {name=l49 lab=d1_1}
C {lab_wire.sym} 1780 0 0 0 {name=l50 lab=d1_0}
C {lab_wire.sym} 1820 30 0 0 {name=l51 lab=vssa}
C {lab_wire.sym} 1820 0 0 0 {name=l52 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 1950 0 0 0 {name=Id1_1_p L=0.5 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1970 -30 0 0 {name=l53 lab=d1_1}
C {lab_wire.sym} 1930 0 0 0 {name=l54 lab=d1_0}
C {lab_wire.sym} 1970 30 0 0 {name=l55 lab=vdda}
C {lab_wire.sym} 1970 0 0 0 {name=l56 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 2100 0 0 0 {name=Id1_2_n L=0.5 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2120 -30 0 0 {name=l57 lab=d1_2}
C {lab_wire.sym} 2080 0 0 0 {name=l58 lab=d1_1}
C {lab_wire.sym} 2120 30 0 0 {name=l59 lab=vssa}
C {lab_wire.sym} 2120 0 0 0 {name=l60 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 2250 0 0 0 {name=Id1_2_p L=0.5 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2270 -30 0 0 {name=l61 lab=d1_2}
C {lab_wire.sym} 2230 0 0 0 {name=l62 lab=d1_1}
C {lab_wire.sym} 2270 30 0 0 {name=l63 lab=vdda}
C {lab_wire.sym} 2270 0 0 0 {name=l64 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 2400 0 0 0 {name=Id1_3_n L=0.5 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2420 -30 0 0 {name=l65 lab=d1_3}
C {lab_wire.sym} 2380 0 0 0 {name=l66 lab=d1_2}
C {lab_wire.sym} 2420 30 0 0 {name=l67 lab=vssa}
C {lab_wire.sym} 2420 0 0 0 {name=l68 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 2550 0 0 0 {name=Id1_3_p L=0.5 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2570 -30 0 0 {name=l69 lab=d1_3}
C {lab_wire.sym} 2530 0 0 0 {name=l70 lab=d1_2}
C {lab_wire.sym} 2570 30 0 0 {name=l71 lab=vdda}
C {lab_wire.sym} 2570 0 0 0 {name=l72 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 2700 0 0 0 {name=Nphi1_na L=0.15 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2720 -30 0 0 {name=l73 lab=n1}
C {lab_wire.sym} 2680 0 0 0 {name=l74 lab=core1}
C {lab_wire.sym} 2720 30 0 0 {name=l75 lab=vssa}
C {lab_wire.sym} 2720 0 0 0 {name=l76 lab=vssa}
C {sky130_fd_pr/nfet_01v8.sym} 2850 0 0 0 {name=Nphi1_nb L=0.15 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2870 -30 0 0 {name=l77 lab=n1}
C {lab_wire.sym} 2830 0 0 0 {name=l78 lab=d1_3}
C {lab_wire.sym} 2870 30 0 0 {name=l79 lab=vssa}
C {lab_wire.sym} 2870 0 0 0 {name=l80 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 3000 0 0 0 {name=Nphi1_pa L=0.15 W=8 nf=1 mult=1 ad=2.32 as=2.32 pd=16.58 ps=16.58 nrd=0.03625 nrs=0.03625 sa=0 sb=0 sd=0}
C {lab_wire.sym} 3020 -30 0 0 {name=l81 lab=Nphi1_m}
C {lab_wire.sym} 2980 0 0 0 {name=l82 lab=core1}
C {lab_wire.sym} 3020 30 0 0 {name=l83 lab=vdda}
C {lab_wire.sym} 3020 0 0 0 {name=l84 lab=vdda}
C {sky130_fd_pr/pfet_01v8.sym} 0 250 0 0 {name=Nphi1_pb L=0.15 W=8 nf=1 mult=1 ad=2.32 as=2.32 pd=16.58 ps=16.58 nrd=0.03625 nrs=0.03625 sa=0 sb=0 sd=0}
C {lab_wire.sym} 20 220 0 0 {name=l85 lab=n1}
C {lab_wire.sym} -20 250 0 0 {name=l86 lab=d1_3}
C {lab_wire.sym} 20 280 0 0 {name=l87 lab=Nphi1_m}
C {lab_wire.sym} 20 250 0 0 {name=l88 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 150 250 0 0 {name=Iphi1_n L=0.15 W=6 nf=1 mult=2 ad=1.74 as=1.74 pd=12.58 ps=12.58 nrd=0.0483333 nrs=0.0483333 sa=0 sb=0 sd=0}
C {lab_wire.sym} 170 220 0 0 {name=l89 lab=phi1}
C {lab_wire.sym} 130 250 0 0 {name=l90 lab=n1}
C {lab_wire.sym} 170 280 0 0 {name=l91 lab=vssa}
C {lab_wire.sym} 170 250 0 0 {name=l92 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 300 250 0 0 {name=Iphi1_p L=0.15 W=12 nf=1 mult=2 ad=3.48 as=3.48 pd=24.58 ps=24.58 nrd=0.0241667 nrs=0.0241667 sa=0 sb=0 sd=0}
C {lab_wire.sym} 320 220 0 0 {name=l93 lab=phi1}
C {lab_wire.sym} 280 250 0 0 {name=l94 lab=n1}
C {lab_wire.sym} 320 280 0 0 {name=l95 lab=vdda}
C {lab_wire.sym} 320 250 0 0 {name=l96 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 450 250 0 0 {name=Iphi1b_n L=0.15 W=6 nf=1 mult=3 ad=1.74 as=1.74 pd=12.58 ps=12.58 nrd=0.0483333 nrs=0.0483333 sa=0 sb=0 sd=0}
C {lab_wire.sym} 470 220 0 0 {name=l97 lab=phi1b}
C {lab_wire.sym} 430 250 0 0 {name=l98 lab=phi1}
C {lab_wire.sym} 470 280 0 0 {name=l99 lab=vssa}
C {lab_wire.sym} 470 250 0 0 {name=l100 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 600 250 0 0 {name=Iphi1b_p L=0.15 W=12 nf=1 mult=3 ad=3.48 as=3.48 pd=24.58 ps=24.58 nrd=0.0241667 nrs=0.0241667 sa=0 sb=0 sd=0}
C {lab_wire.sym} 620 220 0 0 {name=l101 lab=phi1b}
C {lab_wire.sym} 580 250 0 0 {name=l102 lab=phi1}
C {lab_wire.sym} 620 280 0 0 {name=l103 lab=vdda}
C {lab_wire.sym} 620 250 0 0 {name=l104 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 750 250 0 0 {name=Ip1d_0_n L=0.5 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 770 220 0 0 {name=l105 lab=p1d_a}
C {lab_wire.sym} 730 250 0 0 {name=l106 lab=phi1}
C {lab_wire.sym} 770 280 0 0 {name=l107 lab=vssa}
C {lab_wire.sym} 770 250 0 0 {name=l108 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 900 250 0 0 {name=Ip1d_0_p L=0.5 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 920 220 0 0 {name=l109 lab=p1d_a}
C {lab_wire.sym} 880 250 0 0 {name=l110 lab=phi1}
C {lab_wire.sym} 920 280 0 0 {name=l111 lab=vdda}
C {lab_wire.sym} 920 250 0 0 {name=l112 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 1050 250 0 0 {name=Ip1d_1_n L=0.5 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1070 220 0 0 {name=l113 lab=p1d}
C {lab_wire.sym} 1030 250 0 0 {name=l114 lab=p1d_a}
C {lab_wire.sym} 1070 280 0 0 {name=l115 lab=vssa}
C {lab_wire.sym} 1070 250 0 0 {name=l116 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 1200 250 0 0 {name=Ip1d_1_p L=0.5 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1220 220 0 0 {name=l117 lab=p1d}
C {lab_wire.sym} 1180 250 0 0 {name=l118 lab=p1d_a}
C {lab_wire.sym} 1220 280 0 0 {name=l119 lab=vdda}
C {lab_wire.sym} 1220 250 0 0 {name=l120 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 1350 250 0 0 {name=Ncore2_na L=0.15 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1370 220 0 0 {name=l121 lab=core2}
C {lab_wire.sym} 1330 250 0 0 {name=l122 lab=clk}
C {lab_wire.sym} 1370 280 0 0 {name=l123 lab=vssa}
C {lab_wire.sym} 1370 250 0 0 {name=l124 lab=vssa}
C {sky130_fd_pr/nfet_01v8.sym} 1500 250 0 0 {name=Ncore2_nb L=0.15 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1520 220 0 0 {name=l125 lab=core2}
C {lab_wire.sym} 1480 250 0 0 {name=l126 lab=p1d}
C {lab_wire.sym} 1520 280 0 0 {name=l127 lab=vssa}
C {lab_wire.sym} 1520 250 0 0 {name=l128 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 1650 250 0 0 {name=Ncore2_pa L=0.15 W=4 nf=1 mult=1 ad=1.16 as=1.16 pd=8.58 ps=8.58 nrd=0.0725 nrs=0.0725 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1670 220 0 0 {name=l129 lab=Ncore2_m}
C {lab_wire.sym} 1630 250 0 0 {name=l130 lab=clk}
C {lab_wire.sym} 1670 280 0 0 {name=l131 lab=vdda}
C {lab_wire.sym} 1670 250 0 0 {name=l132 lab=vdda}
C {sky130_fd_pr/pfet_01v8.sym} 1800 250 0 0 {name=Ncore2_pb L=0.15 W=4 nf=1 mult=1 ad=1.16 as=1.16 pd=8.58 ps=8.58 nrd=0.0725 nrs=0.0725 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1820 220 0 0 {name=l133 lab=core2}
C {lab_wire.sym} 1780 250 0 0 {name=l134 lab=p1d}
C {lab_wire.sym} 1820 280 0 0 {name=l135 lab=Ncore2_m}
C {lab_wire.sym} 1820 250 0 0 {name=l136 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 1950 250 0 0 {name=Ic2a_n L=0.15 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 1970 220 0 0 {name=l137 lab=c2a}
C {lab_wire.sym} 1930 250 0 0 {name=l138 lab=core2}
C {lab_wire.sym} 1970 280 0 0 {name=l139 lab=vssa}
C {lab_wire.sym} 1970 250 0 0 {name=l140 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 2100 250 0 0 {name=Ic2a_p L=0.15 W=4 nf=1 mult=1 ad=1.16 as=1.16 pd=8.58 ps=8.58 nrd=0.0725 nrs=0.0725 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2120 220 0 0 {name=l141 lab=c2a}
C {lab_wire.sym} 2080 250 0 0 {name=l142 lab=core2}
C {lab_wire.sym} 2120 280 0 0 {name=l143 lab=vdda}
C {lab_wire.sym} 2120 250 0 0 {name=l144 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 2250 250 0 0 {name=Iphi2_n L=0.15 W=6 nf=1 mult=4 ad=1.74 as=1.74 pd=12.58 ps=12.58 nrd=0.0483333 nrs=0.0483333 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2270 220 0 0 {name=l145 lab=phi2}
C {lab_wire.sym} 2230 250 0 0 {name=l146 lab=c2a}
C {lab_wire.sym} 2270 280 0 0 {name=l147 lab=vssa}
C {lab_wire.sym} 2270 250 0 0 {name=l148 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 2400 250 0 0 {name=Iphi2_p L=0.15 W=12 nf=1 mult=4 ad=3.48 as=3.48 pd=24.58 ps=24.58 nrd=0.0241667 nrs=0.0241667 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2420 220 0 0 {name=l149 lab=phi2}
C {lab_wire.sym} 2380 250 0 0 {name=l150 lab=c2a}
C {lab_wire.sym} 2420 280 0 0 {name=l151 lab=vdda}
C {lab_wire.sym} 2420 250 0 0 {name=l152 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 2550 250 0 0 {name=Ip2d_0_n L=0.5 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2570 220 0 0 {name=l153 lab=p2d_a}
C {lab_wire.sym} 2530 250 0 0 {name=l154 lab=phi2}
C {lab_wire.sym} 2570 280 0 0 {name=l155 lab=vssa}
C {lab_wire.sym} 2570 250 0 0 {name=l156 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 2700 250 0 0 {name=Ip2d_0_p L=0.5 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2720 220 0 0 {name=l157 lab=p2d_a}
C {lab_wire.sym} 2680 250 0 0 {name=l158 lab=phi2}
C {lab_wire.sym} 2720 280 0 0 {name=l159 lab=vdda}
C {lab_wire.sym} 2720 250 0 0 {name=l160 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 2850 250 0 0 {name=Ip2d_1_n L=0.5 W=1 nf=1 mult=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0}
C {lab_wire.sym} 2870 220 0 0 {name=l161 lab=p2d}
C {lab_wire.sym} 2830 250 0 0 {name=l162 lab=p2d_a}
C {lab_wire.sym} 2870 280 0 0 {name=l163 lab=vssa}
C {lab_wire.sym} 2870 250 0 0 {name=l164 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 3000 250 0 0 {name=Ip2d_1_p L=0.5 W=2 nf=1 mult=1 ad=0.58 as=0.58 pd=4.58 ps=4.58 nrd=0.145 nrs=0.145 sa=0 sb=0 sd=0}
C {lab_wire.sym} 3020 220 0 0 {name=l165 lab=p2d}
C {lab_wire.sym} 2980 250 0 0 {name=l166 lab=p2d_a}
C {lab_wire.sym} 3020 280 0 0 {name=l167 lab=vdda}
C {lab_wire.sym} 3020 250 0 0 {name=l168 lab=vdda}
C {devices/iopin.sym} -400 -300 0 0 {name=p_vdda lab=vdda}
C {devices/iopin.sym} -400 -200 0 0 {name=p_vssa lab=vssa}
C {devices/ipin.sym} -400 -100 0 0 {name=p_clk lab=clk}
C {devices/opin.sym} -400 0 0 0 {name=p_phi1 lab=phi1}
C {devices/opin.sym} -400 100 0 0 {name=p_phi1b lab=phi1b}
C {devices/opin.sym} -400 200 0 0 {name=p_phi1e lab=phi1e}
C {devices/opin.sym} -400 300 0 0 {name=p_phi2 lab=phi2}

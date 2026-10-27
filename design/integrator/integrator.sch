v {xschem version=3.4.7 file_version=1.2
* integrator -- fully-differential switched-capacitor integrator with 1-bit
* feedback DAC (issue #40). One cell, used twice (coefficients C1 = C2 = 0.5).
* Cs_in = Cs_ref = 1 pF (spec 5.3 planning value), Ci = 2 pF (Cs/Ci = 0.5,
* model B, sim/bmodel/model.py:41-42). Sizing trace: design/integrator/SIZING.md.
*
* Charge transfer polarity: the OTA drives outp inverting from inn and outn
* inverting from inp, so the p-side sampling caps sum at the OTA inn node
* (net sump, feedback Ci_p to outp) and the n-side caps at inp (net sumn,
* Ci_n to outn). Then outp-outn steps by +0.5*(vin_diff + rsel_p - rsel_n).
*
* Phases (generated outside this block): phi1 sample / phi1b its complement /
* phi1e early phi1 (top plates open first: bottom-plate sampling) / phi2
* integrate. Decision dp (y = +1) and its complement dn: dp = 1 samples VREFN
* on the p-side reference cap and VREFP on the n-side (feedback -VREF),
* dn = 1 the opposite. VREFP/VREFN/vcm/ibias are boundary ports (DR-005).
*
* Pins: vdda vssa vinp vinn voutp voutn vrefp vrefn vcm ibias phi1 phi1b phi1e
* phi2 dp dn.
}
G {}
K {}
V {}
S {}
E {}
* p-side input path: Cs_in, TG sample switch, bottom-plate and top-plate switches
C {sky130_fd_pr/nfet_01v8.sym} -800 0 0 0 {name=Sin_p_n
L=0.15
W=4
nf=1
mult=1
ad=1.16
as=1.16
pd=8.58
ps=8.58
nrd=0.0725
nrs=0.0725
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N -780 -30 -760 -40 {}
C {devices/lab_pin.sym} -760 -40 0 0 {name=l1 lab=vinp}
N -780 30 -760 40 {}
C {devices/lab_pin.sym} -760 40 0 0 {name=l2 lab=bpi_p}
N -820 0 -840 0 {}
C {devices/lab_pin.sym} -840 0 0 0 {name=l3 lab=phi1}
N -780 0 -750 0 {}
C {devices/lab_pin.sym} -750 0 0 0 {name=l4 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} -600 0 0 0 {name=Sin_p_p
L=0.15
W=8
nf=1
mult=1
ad=2.32
as=2.32
pd=16.58
ps=16.58
nrd=0.03625
nrs=0.03625
sa=0
sb=0
sd=0
model=pfet_01v8
spiceprefix=X}
N -580 30 -560 40 {}
C {devices/lab_pin.sym} -560 40 0 0 {name=l5 lab=vinp}
N -580 -30 -560 -40 {}
C {devices/lab_pin.sym} -560 -40 0 0 {name=l6 lab=bpi_p}
N -620 0 -640 0 {}
C {devices/lab_pin.sym} -640 0 0 0 {name=l7 lab=phi1b}
N -580 0 -550 0 {}
C {devices/lab_pin.sym} -550 0 0 0 {name=l8 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 100 0 0 0 {name=Sbi_p
L=0.15
W=12
nf=1
mult=1
ad=3.48
as=3.48
pd=24.58
ps=24.58
nrd=0.02416667
nrs=0.02416667
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 120 -30 140 -40 {}
C {devices/lab_pin.sym} 140 -40 0 0 {name=l9 lab=bpi_p}
N 120 30 140 40 {}
C {devices/lab_pin.sym} 140 40 0 0 {name=l10 lab=vcm}
N 80 0 60 0 {}
C {devices/lab_pin.sym} 60 0 0 0 {name=l11 lab=phi2}
N 120 0 150 0 {}
C {devices/lab_pin.sym} 150 0 0 0 {name=l12 lab=vssa}
C {sky130_fd_pr/nfet_01v8.sym} 550 0 0 0 {name=Sci_p
L=0.15
W=12
nf=1
mult=1
ad=3.48
as=3.48
pd=24.58
ps=24.58
nrd=0.02416667
nrs=0.02416667
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 570 -30 590 -40 {}
C {devices/lab_pin.sym} 590 -40 0 0 {name=l13 lab=tpi_p}
N 570 30 590 40 {}
C {devices/lab_pin.sym} 590 40 0 0 {name=l14 lab=vcm}
N 530 0 510 0 {}
C {devices/lab_pin.sym} 510 0 0 0 {name=l15 lab=phi1e}
N 570 0 600 0 {}
C {devices/lab_pin.sym} 600 0 0 0 {name=l16 lab=vssa}
C {sky130_fd_pr/nfet_01v8.sym} 1000 0 0 0 {name=Sti_p
L=0.15
W=12
nf=1
mult=1
ad=3.48
as=3.48
pd=24.58
ps=24.58
nrd=0.02416667
nrs=0.02416667
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 1020 -30 1040 -40 {}
C {devices/lab_pin.sym} 1040 -40 0 0 {name=l17 lab=tpi_p}
N 1020 30 1040 40 {}
C {devices/lab_pin.sym} 1040 40 0 0 {name=l18 lab=sump}
N 980 0 960 0 {}
C {devices/lab_pin.sym} 960 0 0 0 {name=l19 lab=phi2}
N 1020 0 1050 0 {}
C {devices/lab_pin.sym} 1050 0 0 0 {name=l20 lab=vssa}
C {sky130_fd_pr/cap_mim_m3_1.sym} 1450 0 0 0 {name=Csi_p
model=cap_mim_m3_1
W=22.17
L=22.17
MF=1
spiceprefix=X}
N 1450 -30 1450 -50 {}
C {devices/lab_pin.sym} 1450 -50 0 0 {name=l21 lab=tpi_p}
N 1450 30 1450 50 {}
C {devices/lab_pin.sym} 1450 50 0 0 {name=l22 lab=bpi_p}
* p-side 1-bit DAC: reference mux (dp/dn) -> rsel_p, TG sample switch, Cs_ref
C {sky130_fd_pr/nfet_01v8.sym} -800 500 0 0 {name=Mra_p_n
L=0.15
W=4
nf=1
mult=1
ad=1.16
as=1.16
pd=8.58
ps=8.58
nrd=0.0725
nrs=0.0725
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N -780 470 -760 460 {}
C {devices/lab_pin.sym} -760 460 0 0 {name=l23 lab=vrefp}
N -780 530 -760 540 {}
C {devices/lab_pin.sym} -760 540 0 0 {name=l24 lab=rsel_p}
N -820 500 -840 500 {}
C {devices/lab_pin.sym} -840 500 0 0 {name=l25 lab=dn}
N -780 500 -750 500 {}
C {devices/lab_pin.sym} -750 500 0 0 {name=l26 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} -600 500 0 0 {name=Mra_p_p
L=0.15
W=8
nf=1
mult=1
ad=2.32
as=2.32
pd=16.58
ps=16.58
nrd=0.03625
nrs=0.03625
sa=0
sb=0
sd=0
model=pfet_01v8
spiceprefix=X}
N -580 530 -560 540 {}
C {devices/lab_pin.sym} -560 540 0 0 {name=l27 lab=vrefp}
N -580 470 -560 460 {}
C {devices/lab_pin.sym} -560 460 0 0 {name=l28 lab=rsel_p}
N -620 500 -640 500 {}
C {devices/lab_pin.sym} -640 500 0 0 {name=l29 lab=dp}
N -580 500 -550 500 {}
C {devices/lab_pin.sym} -550 500 0 0 {name=l30 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} -800 750 0 0 {name=Mrb_p_n
L=0.15
W=4
nf=1
mult=1
ad=1.16
as=1.16
pd=8.58
ps=8.58
nrd=0.0725
nrs=0.0725
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N -780 720 -760 710 {}
C {devices/lab_pin.sym} -760 710 0 0 {name=l31 lab=vrefn}
N -780 780 -760 790 {}
C {devices/lab_pin.sym} -760 790 0 0 {name=l32 lab=rsel_p}
N -820 750 -840 750 {}
C {devices/lab_pin.sym} -840 750 0 0 {name=l33 lab=dp}
N -780 750 -750 750 {}
C {devices/lab_pin.sym} -750 750 0 0 {name=l34 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} -600 750 0 0 {name=Mrb_p_p
L=0.15
W=8
nf=1
mult=1
ad=2.32
as=2.32
pd=16.58
ps=16.58
nrd=0.03625
nrs=0.03625
sa=0
sb=0
sd=0
model=pfet_01v8
spiceprefix=X}
N -580 780 -560 790 {}
C {devices/lab_pin.sym} -560 790 0 0 {name=l35 lab=vrefn}
N -580 720 -560 710 {}
C {devices/lab_pin.sym} -560 710 0 0 {name=l36 lab=rsel_p}
N -620 750 -640 750 {}
C {devices/lab_pin.sym} -640 750 0 0 {name=l37 lab=dn}
N -580 750 -550 750 {}
C {devices/lab_pin.sym} -550 750 0 0 {name=l38 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 0 500 0 0 {name=Sr_p_n
L=0.15
W=4
nf=1
mult=1
ad=1.16
as=1.16
pd=8.58
ps=8.58
nrd=0.0725
nrs=0.0725
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 20 470 40 460 {}
C {devices/lab_pin.sym} 40 460 0 0 {name=l39 lab=rsel_p}
N 20 530 40 540 {}
C {devices/lab_pin.sym} 40 540 0 0 {name=l40 lab=bpr_p}
N -20 500 -40 500 {}
C {devices/lab_pin.sym} -40 500 0 0 {name=l41 lab=phi1}
N 20 500 50 500 {}
C {devices/lab_pin.sym} 50 500 0 0 {name=l42 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 200 500 0 0 {name=Sr_p_p
L=0.15
W=8
nf=1
mult=1
ad=2.32
as=2.32
pd=16.58
ps=16.58
nrd=0.03625
nrs=0.03625
sa=0
sb=0
sd=0
model=pfet_01v8
spiceprefix=X}
N 220 530 240 540 {}
C {devices/lab_pin.sym} 240 540 0 0 {name=l43 lab=rsel_p}
N 220 470 240 460 {}
C {devices/lab_pin.sym} 240 460 0 0 {name=l44 lab=bpr_p}
N 180 500 160 500 {}
C {devices/lab_pin.sym} 160 500 0 0 {name=l45 lab=phi1b}
N 220 500 250 500 {}
C {devices/lab_pin.sym} 250 500 0 0 {name=l46 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 650 500 0 0 {name=Sbr_p
L=0.15
W=12
nf=1
mult=1
ad=3.48
as=3.48
pd=24.58
ps=24.58
nrd=0.02416667
nrs=0.02416667
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 670 470 690 460 {}
C {devices/lab_pin.sym} 690 460 0 0 {name=l47 lab=bpr_p}
N 670 530 690 540 {}
C {devices/lab_pin.sym} 690 540 0 0 {name=l48 lab=vcm}
N 630 500 610 500 {}
C {devices/lab_pin.sym} 610 500 0 0 {name=l49 lab=phi2}
N 670 500 700 500 {}
C {devices/lab_pin.sym} 700 500 0 0 {name=l50 lab=vssa}
C {sky130_fd_pr/nfet_01v8.sym} 1100 500 0 0 {name=Scr_p
L=0.15
W=12
nf=1
mult=1
ad=3.48
as=3.48
pd=24.58
ps=24.58
nrd=0.02416667
nrs=0.02416667
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 1120 470 1140 460 {}
C {devices/lab_pin.sym} 1140 460 0 0 {name=l51 lab=tpr_p}
N 1120 530 1140 540 {}
C {devices/lab_pin.sym} 1140 540 0 0 {name=l52 lab=vcm}
N 1080 500 1060 500 {}
C {devices/lab_pin.sym} 1060 500 0 0 {name=l53 lab=phi1e}
N 1120 500 1150 500 {}
C {devices/lab_pin.sym} 1150 500 0 0 {name=l54 lab=vssa}
C {sky130_fd_pr/nfet_01v8.sym} 1550 500 0 0 {name=Str_p
L=0.15
W=12
nf=1
mult=1
ad=3.48
as=3.48
pd=24.58
ps=24.58
nrd=0.02416667
nrs=0.02416667
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 1570 470 1590 460 {}
C {devices/lab_pin.sym} 1590 460 0 0 {name=l55 lab=tpr_p}
N 1570 530 1590 540 {}
C {devices/lab_pin.sym} 1590 540 0 0 {name=l56 lab=sump}
N 1530 500 1510 500 {}
C {devices/lab_pin.sym} 1510 500 0 0 {name=l57 lab=phi2}
N 1570 500 1600 500 {}
C {devices/lab_pin.sym} 1600 500 0 0 {name=l58 lab=vssa}
C {sky130_fd_pr/cap_mim_m3_1.sym} 2000 500 0 0 {name=Csr_p
model=cap_mim_m3_1
W=22.17
L=22.17
MF=1
spiceprefix=X}
N 2000 470 2000 450 {}
C {devices/lab_pin.sym} 2000 450 0 0 {name=l59 lab=tpr_p}
N 2000 530 2000 550 {}
C {devices/lab_pin.sym} 2000 550 0 0 {name=l60 lab=bpr_p}
* p-side integrating cap Ci between the summing node and the output
C {sky130_fd_pr/cap_mim_m3_1.sym} 2550 0 0 0 {name=Ci_p
model=cap_mim_m3_1
W=31.43
L=31.43
MF=1
spiceprefix=X}
N 2550 -30 2550 -50 {}
C {devices/lab_pin.sym} 2550 -50 0 0 {name=l61 lab=sump}
N 2550 30 2550 50 {}
C {devices/lab_pin.sym} 2550 50 0 0 {name=l62 lab=voutp}
* n-side input path: Cs_in, TG sample switch, bottom-plate and top-plate switches
C {sky130_fd_pr/nfet_01v8.sym} -800 1500 0 0 {name=Sin_n_n
L=0.15
W=4
nf=1
mult=1
ad=1.16
as=1.16
pd=8.58
ps=8.58
nrd=0.0725
nrs=0.0725
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N -780 1470 -760 1460 {}
C {devices/lab_pin.sym} -760 1460 0 0 {name=l63 lab=vinn}
N -780 1530 -760 1540 {}
C {devices/lab_pin.sym} -760 1540 0 0 {name=l64 lab=bpi_n}
N -820 1500 -840 1500 {}
C {devices/lab_pin.sym} -840 1500 0 0 {name=l65 lab=phi1}
N -780 1500 -750 1500 {}
C {devices/lab_pin.sym} -750 1500 0 0 {name=l66 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} -600 1500 0 0 {name=Sin_n_p
L=0.15
W=8
nf=1
mult=1
ad=2.32
as=2.32
pd=16.58
ps=16.58
nrd=0.03625
nrs=0.03625
sa=0
sb=0
sd=0
model=pfet_01v8
spiceprefix=X}
N -580 1530 -560 1540 {}
C {devices/lab_pin.sym} -560 1540 0 0 {name=l67 lab=vinn}
N -580 1470 -560 1460 {}
C {devices/lab_pin.sym} -560 1460 0 0 {name=l68 lab=bpi_n}
N -620 1500 -640 1500 {}
C {devices/lab_pin.sym} -640 1500 0 0 {name=l69 lab=phi1b}
N -580 1500 -550 1500 {}
C {devices/lab_pin.sym} -550 1500 0 0 {name=l70 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 100 1500 0 0 {name=Sbi_n
L=0.15
W=12
nf=1
mult=1
ad=3.48
as=3.48
pd=24.58
ps=24.58
nrd=0.02416667
nrs=0.02416667
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 120 1470 140 1460 {}
C {devices/lab_pin.sym} 140 1460 0 0 {name=l71 lab=bpi_n}
N 120 1530 140 1540 {}
C {devices/lab_pin.sym} 140 1540 0 0 {name=l72 lab=vcm}
N 80 1500 60 1500 {}
C {devices/lab_pin.sym} 60 1500 0 0 {name=l73 lab=phi2}
N 120 1500 150 1500 {}
C {devices/lab_pin.sym} 150 1500 0 0 {name=l74 lab=vssa}
C {sky130_fd_pr/nfet_01v8.sym} 550 1500 0 0 {name=Sci_n
L=0.15
W=12
nf=1
mult=1
ad=3.48
as=3.48
pd=24.58
ps=24.58
nrd=0.02416667
nrs=0.02416667
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 570 1470 590 1460 {}
C {devices/lab_pin.sym} 590 1460 0 0 {name=l75 lab=tpi_n}
N 570 1530 590 1540 {}
C {devices/lab_pin.sym} 590 1540 0 0 {name=l76 lab=vcm}
N 530 1500 510 1500 {}
C {devices/lab_pin.sym} 510 1500 0 0 {name=l77 lab=phi1e}
N 570 1500 600 1500 {}
C {devices/lab_pin.sym} 600 1500 0 0 {name=l78 lab=vssa}
C {sky130_fd_pr/nfet_01v8.sym} 1000 1500 0 0 {name=Sti_n
L=0.15
W=12
nf=1
mult=1
ad=3.48
as=3.48
pd=24.58
ps=24.58
nrd=0.02416667
nrs=0.02416667
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 1020 1470 1040 1460 {}
C {devices/lab_pin.sym} 1040 1460 0 0 {name=l79 lab=tpi_n}
N 1020 1530 1040 1540 {}
C {devices/lab_pin.sym} 1040 1540 0 0 {name=l80 lab=sumn}
N 980 1500 960 1500 {}
C {devices/lab_pin.sym} 960 1500 0 0 {name=l81 lab=phi2}
N 1020 1500 1050 1500 {}
C {devices/lab_pin.sym} 1050 1500 0 0 {name=l82 lab=vssa}
C {sky130_fd_pr/cap_mim_m3_1.sym} 1450 1500 0 0 {name=Csi_n
model=cap_mim_m3_1
W=22.17
L=22.17
MF=1
spiceprefix=X}
N 1450 1470 1450 1450 {}
C {devices/lab_pin.sym} 1450 1450 0 0 {name=l83 lab=tpi_n}
N 1450 1530 1450 1550 {}
C {devices/lab_pin.sym} 1450 1550 0 0 {name=l84 lab=bpi_n}
* n-side 1-bit DAC: reference mux (dp/dn) -> rsel_n, TG sample switch, Cs_ref
C {sky130_fd_pr/nfet_01v8.sym} -800 2000 0 0 {name=Mra_n_n
L=0.15
W=4
nf=1
mult=1
ad=1.16
as=1.16
pd=8.58
ps=8.58
nrd=0.0725
nrs=0.0725
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N -780 1970 -760 1960 {}
C {devices/lab_pin.sym} -760 1960 0 0 {name=l85 lab=vrefn}
N -780 2030 -760 2040 {}
C {devices/lab_pin.sym} -760 2040 0 0 {name=l86 lab=rsel_n}
N -820 2000 -840 2000 {}
C {devices/lab_pin.sym} -840 2000 0 0 {name=l87 lab=dn}
N -780 2000 -750 2000 {}
C {devices/lab_pin.sym} -750 2000 0 0 {name=l88 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} -600 2000 0 0 {name=Mra_n_p
L=0.15
W=8
nf=1
mult=1
ad=2.32
as=2.32
pd=16.58
ps=16.58
nrd=0.03625
nrs=0.03625
sa=0
sb=0
sd=0
model=pfet_01v8
spiceprefix=X}
N -580 2030 -560 2040 {}
C {devices/lab_pin.sym} -560 2040 0 0 {name=l89 lab=vrefn}
N -580 1970 -560 1960 {}
C {devices/lab_pin.sym} -560 1960 0 0 {name=l90 lab=rsel_n}
N -620 2000 -640 2000 {}
C {devices/lab_pin.sym} -640 2000 0 0 {name=l91 lab=dp}
N -580 2000 -550 2000 {}
C {devices/lab_pin.sym} -550 2000 0 0 {name=l92 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} -800 2250 0 0 {name=Mrb_n_n
L=0.15
W=4
nf=1
mult=1
ad=1.16
as=1.16
pd=8.58
ps=8.58
nrd=0.0725
nrs=0.0725
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N -780 2220 -760 2210 {}
C {devices/lab_pin.sym} -760 2210 0 0 {name=l93 lab=vrefp}
N -780 2280 -760 2290 {}
C {devices/lab_pin.sym} -760 2290 0 0 {name=l94 lab=rsel_n}
N -820 2250 -840 2250 {}
C {devices/lab_pin.sym} -840 2250 0 0 {name=l95 lab=dp}
N -780 2250 -750 2250 {}
C {devices/lab_pin.sym} -750 2250 0 0 {name=l96 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} -600 2250 0 0 {name=Mrb_n_p
L=0.15
W=8
nf=1
mult=1
ad=2.32
as=2.32
pd=16.58
ps=16.58
nrd=0.03625
nrs=0.03625
sa=0
sb=0
sd=0
model=pfet_01v8
spiceprefix=X}
N -580 2280 -560 2290 {}
C {devices/lab_pin.sym} -560 2290 0 0 {name=l97 lab=vrefp}
N -580 2220 -560 2210 {}
C {devices/lab_pin.sym} -560 2210 0 0 {name=l98 lab=rsel_n}
N -620 2250 -640 2250 {}
C {devices/lab_pin.sym} -640 2250 0 0 {name=l99 lab=dn}
N -580 2250 -550 2250 {}
C {devices/lab_pin.sym} -550 2250 0 0 {name=l100 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 0 2000 0 0 {name=Sr_n_n
L=0.15
W=4
nf=1
mult=1
ad=1.16
as=1.16
pd=8.58
ps=8.58
nrd=0.0725
nrs=0.0725
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 20 1970 40 1960 {}
C {devices/lab_pin.sym} 40 1960 0 0 {name=l101 lab=rsel_n}
N 20 2030 40 2040 {}
C {devices/lab_pin.sym} 40 2040 0 0 {name=l102 lab=bpr_n}
N -20 2000 -40 2000 {}
C {devices/lab_pin.sym} -40 2000 0 0 {name=l103 lab=phi1}
N 20 2000 50 2000 {}
C {devices/lab_pin.sym} 50 2000 0 0 {name=l104 lab=vssa}
C {sky130_fd_pr/pfet_01v8.sym} 200 2000 0 0 {name=Sr_n_p
L=0.15
W=8
nf=1
mult=1
ad=2.32
as=2.32
pd=16.58
ps=16.58
nrd=0.03625
nrs=0.03625
sa=0
sb=0
sd=0
model=pfet_01v8
spiceprefix=X}
N 220 2030 240 2040 {}
C {devices/lab_pin.sym} 240 2040 0 0 {name=l105 lab=rsel_n}
N 220 1970 240 1960 {}
C {devices/lab_pin.sym} 240 1960 0 0 {name=l106 lab=bpr_n}
N 180 2000 160 2000 {}
C {devices/lab_pin.sym} 160 2000 0 0 {name=l107 lab=phi1b}
N 220 2000 250 2000 {}
C {devices/lab_pin.sym} 250 2000 0 0 {name=l108 lab=vdda}
C {sky130_fd_pr/nfet_01v8.sym} 650 2000 0 0 {name=Sbr_n
L=0.15
W=12
nf=1
mult=1
ad=3.48
as=3.48
pd=24.58
ps=24.58
nrd=0.02416667
nrs=0.02416667
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 670 1970 690 1960 {}
C {devices/lab_pin.sym} 690 1960 0 0 {name=l109 lab=bpr_n}
N 670 2030 690 2040 {}
C {devices/lab_pin.sym} 690 2040 0 0 {name=l110 lab=vcm}
N 630 2000 610 2000 {}
C {devices/lab_pin.sym} 610 2000 0 0 {name=l111 lab=phi2}
N 670 2000 700 2000 {}
C {devices/lab_pin.sym} 700 2000 0 0 {name=l112 lab=vssa}
C {sky130_fd_pr/nfet_01v8.sym} 1100 2000 0 0 {name=Scr_n
L=0.15
W=12
nf=1
mult=1
ad=3.48
as=3.48
pd=24.58
ps=24.58
nrd=0.02416667
nrs=0.02416667
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 1120 1970 1140 1960 {}
C {devices/lab_pin.sym} 1140 1960 0 0 {name=l113 lab=tpr_n}
N 1120 2030 1140 2040 {}
C {devices/lab_pin.sym} 1140 2040 0 0 {name=l114 lab=vcm}
N 1080 2000 1060 2000 {}
C {devices/lab_pin.sym} 1060 2000 0 0 {name=l115 lab=phi1e}
N 1120 2000 1150 2000 {}
C {devices/lab_pin.sym} 1150 2000 0 0 {name=l116 lab=vssa}
C {sky130_fd_pr/nfet_01v8.sym} 1550 2000 0 0 {name=Str_n
L=0.15
W=12
nf=1
mult=1
ad=3.48
as=3.48
pd=24.58
ps=24.58
nrd=0.02416667
nrs=0.02416667
sa=0
sb=0
sd=0
model=nfet_01v8
spiceprefix=X}
N 1570 1970 1590 1960 {}
C {devices/lab_pin.sym} 1590 1960 0 0 {name=l117 lab=tpr_n}
N 1570 2030 1590 2040 {}
C {devices/lab_pin.sym} 1590 2040 0 0 {name=l118 lab=sumn}
N 1530 2000 1510 2000 {}
C {devices/lab_pin.sym} 1510 2000 0 0 {name=l119 lab=phi2}
N 1570 2000 1600 2000 {}
C {devices/lab_pin.sym} 1600 2000 0 0 {name=l120 lab=vssa}
C {sky130_fd_pr/cap_mim_m3_1.sym} 2000 2000 0 0 {name=Csr_n
model=cap_mim_m3_1
W=22.17
L=22.17
MF=1
spiceprefix=X}
N 2000 1970 2000 1950 {}
C {devices/lab_pin.sym} 2000 1950 0 0 {name=l121 lab=tpr_n}
N 2000 2030 2000 2050 {}
C {devices/lab_pin.sym} 2000 2050 0 0 {name=l122 lab=bpr_n}
* n-side integrating cap Ci between the summing node and the output
C {sky130_fd_pr/cap_mim_m3_1.sym} 2550 1500 0 0 {name=Ci_n
model=cap_mim_m3_1
W=31.43
L=31.43
MF=1
spiceprefix=X}
N 2550 1470 2550 1450 {}
C {devices/lab_pin.sym} 2550 1450 0 0 {name=l123 lab=sumn}
N 2550 1530 2550 1550 {}
C {devices/lab_pin.sym} 2550 1550 0 0 {name=l124 lab=voutn}
* OTA (design/ota/ota_fd.sym): p-side sum node on inn, n-side on inp
C {ota/ota_fd.sym} 3600 700 0 0 {name=xota}
N 3750 630 3770 630 {}
C {devices/lab_pin.sym} 3770 630 0 0 {name=l125 lab=vdda}
N 3750 650 3770 650 {}
C {devices/lab_pin.sym} 3770 650 0 0 {name=l126 lab=vssa}
N 3750 670 3770 670 {}
C {devices/lab_pin.sym} 3770 670 0 0 {name=l127 lab=sumn}
N 3750 690 3770 690 {}
C {devices/lab_pin.sym} 3770 690 0 0 {name=l128 lab=sump}
N 3750 710 3770 710 {}
C {devices/lab_pin.sym} 3770 710 0 0 {name=l129 lab=voutp}
N 3750 730 3770 730 {}
C {devices/lab_pin.sym} 3770 730 0 0 {name=l130 lab=voutn}
N 3750 750 3770 750 {}
C {devices/lab_pin.sym} 3770 750 0 0 {name=l131 lab=vcm}
N 3750 770 3770 770 {}
C {devices/lab_pin.sym} 3770 770 0 0 {name=l132 lab=ibias}
* Block pins. Order sets the .subckt terminal order.
C {devices/iopin.sym} -1400 -300 0 0 {name=p_vdda lab=vdda}
C {devices/iopin.sym} -1400 -200 0 0 {name=p_vssa lab=vssa}
C {devices/ipin.sym} -1400 -100 0 0 {name=p_vinp lab=vinp}
C {devices/ipin.sym} -1400 0 0 0 {name=p_vinn lab=vinn}
C {devices/opin.sym} -1400 100 0 0 {name=p_voutp lab=voutp}
C {devices/opin.sym} -1400 200 0 0 {name=p_voutn lab=voutn}
C {devices/ipin.sym} -1400 300 0 0 {name=p_vrefp lab=vrefp}
C {devices/ipin.sym} -1400 400 0 0 {name=p_vrefn lab=vrefn}
C {devices/ipin.sym} -1400 500 0 0 {name=p_vcm lab=vcm}
C {devices/ipin.sym} -1400 600 0 0 {name=p_ibias lab=ibias}
C {devices/ipin.sym} -1400 700 0 0 {name=p_phi1 lab=phi1}
C {devices/ipin.sym} -1400 800 0 0 {name=p_phi1b lab=phi1b}
C {devices/ipin.sym} -1400 900 0 0 {name=p_phi1e lab=phi1e}
C {devices/ipin.sym} -1400 1000 0 0 {name=p_phi2 lab=phi2}
C {devices/ipin.sym} -1400 1100 0 0 {name=p_dp lab=dp}
C {devices/ipin.sym} -1400 1200 0 0 {name=p_dn lab=dn}

v {xschem version=3.4.7 file_version=1.2
* ota_fd -- fully-differential folded-cascode OTA with continuous-time CMFB
* (issue #38; DR-003 keeps an own integrator amplifier).
* 1.8 V core devices only (sky130_fd_pr__nfet_01v8 / __pfet_01v8).
* Sizing source and the "not simulated" ledger: design/ota/SIZING.md.
*
* Topology: NMOS input pair M1/M2 on tail MT; folded into PMOS top sources
* MP1/MP2 (gate = CMFB node cr) with PMOS cascodes MPC1/MPC2 and NMOS
* cascodes MNC1/MNC2 over bottom sinks MN1/MN2. Outputs outn (M1 side,
* inverting from inp) and outp (M2 side). CMFB: sense pair MCS1/MCS2 (gates
* outp, outn) against reference MCR (gate vcm) with PMOS mirror load
* MCPS/MCPR; cr drives MP1/MP2. All branch currents mirror the external
* ibias (5 uA, DR-005) through MB1; cascode biases vcn/vcp are made on-block
* (legs MBP1/MBN1/MBP2/MBCN and MBCP/MBN2).
*
* Pins: vdda vssa inp inn outp outn vcm ibias. vcm = 0.9 V (DR-005).
}
G {}
K {}
V {}
S {}
E {}

* M1: input pair, inp side -> drives fold node fa (outn)
C {sky130_fd_pr/nfet_01v8.sym} -900 -400 0 0 {name=M1
L=0.5
W=8.0
nf=1
mult=1
model=nfet_01v8
spiceprefix=X}
N -880 -430 -860 -410 {}
C {devices/lab_pin.sym} -860 -410 0 0 {name=l1 lab=fa}
N -920 -400 -940 -400 {}
C {devices/lab_pin.sym} -940 -400 0 0 {name=l2 lab=inp}
N -880 -370 -860 -390 {}
C {devices/lab_pin.sym} -860 -390 0 0 {name=l3 lab=tail}
N -880 -400 -860 -400 {}
C {devices/lab_pin.sym} -860 -400 0 0 {name=l4 lab=vssa}

* M2: input pair, inn side -> drives fold node fb (outp)
C {sky130_fd_pr/nfet_01v8.sym} -500 -400 0 0 {name=M2
L=0.5
W=8.0
nf=1
mult=1
model=nfet_01v8
spiceprefix=X}
N -480 -430 -460 -410 {}
C {devices/lab_pin.sym} -460 -410 0 0 {name=l5 lab=fb}
N -520 -400 -540 -400 {}
C {devices/lab_pin.sym} -540 -400 0 0 {name=l6 lab=inn}
N -480 -370 -460 -390 {}
C {devices/lab_pin.sym} -460 -390 0 0 {name=l7 lab=tail}
N -480 -400 -460 -400 {}
C {devices/lab_pin.sym} -460 -400 0 0 {name=l8 lab=vssa}

* MT: input-pair tail, 8x MB1 (40 uA from 5 uA ibias)
C {sky130_fd_pr/nfet_01v8.sym} -100 -400 0 0 {name=MT
L=0.5
W=2.0
nf=1
mult=8
model=nfet_01v8
spiceprefix=X}
N -80 -430 -60 -410 {}
C {devices/lab_pin.sym} -60 -410 0 0 {name=l9 lab=tail}
N -120 -400 -140 -400 {}
C {devices/lab_pin.sym} -140 -400 0 0 {name=l10 lab=ibias}
N -80 -370 -60 -390 {}
C {devices/lab_pin.sym} -60 -390 0 0 {name=l11 lab=vssa}
N -80 -400 -60 -400 {}
C {devices/lab_pin.sym} -60 -400 0 0 {name=l12 lab=vssa}

* MP1: top current source, CMFB-controlled gate cr
C {sky130_fd_pr/pfet_01v8.sym} 300 -400 0 0 {name=MP1
L=0.5
W=10.0
nf=1
mult=4
model=pfet_01v8
spiceprefix=X}
N 320 -370 340 -390 {}
C {devices/lab_pin.sym} 340 -390 0 0 {name=l13 lab=fa}
N 280 -400 260 -400 {}
C {devices/lab_pin.sym} 260 -400 0 0 {name=l14 lab=cr}
N 320 -430 340 -410 {}
C {devices/lab_pin.sym} 340 -410 0 0 {name=l15 lab=vdda}
N 320 -400 340 -400 {}
C {devices/lab_pin.sym} 340 -400 0 0 {name=l16 lab=vdda}

* MP2: top current source, CMFB-controlled gate cr
C {sky130_fd_pr/pfet_01v8.sym} 700 -400 0 0 {name=MP2
L=0.5
W=10.0
nf=1
mult=4
model=pfet_01v8
spiceprefix=X}
N 720 -370 740 -390 {}
C {devices/lab_pin.sym} 740 -390 0 0 {name=l17 lab=fb}
N 680 -400 660 -400 {}
C {devices/lab_pin.sym} 660 -400 0 0 {name=l18 lab=cr}
N 720 -430 740 -410 {}
C {devices/lab_pin.sym} 740 -410 0 0 {name=l19 lab=vdda}
N 720 -400 740 -400 {}
C {devices/lab_pin.sym} 740 -400 0 0 {name=l20 lab=vdda}

* MPC1: PMOS cascode
C {sky130_fd_pr/pfet_01v8.sym} 1100 -400 0 0 {name=MPC1
L=0.5
W=10.0
nf=1
mult=2
model=pfet_01v8
spiceprefix=X}
N 1120 -370 1140 -390 {}
C {devices/lab_pin.sym} 1140 -390 0 0 {name=l21 lab=outn}
N 1080 -400 1060 -400 {}
C {devices/lab_pin.sym} 1060 -400 0 0 {name=l22 lab=vcp}
N 1120 -430 1140 -410 {}
C {devices/lab_pin.sym} 1140 -410 0 0 {name=l23 lab=fa}
N 1120 -400 1140 -400 {}
C {devices/lab_pin.sym} 1140 -400 0 0 {name=l24 lab=vdda}

* MPC2: PMOS cascode
C {sky130_fd_pr/pfet_01v8.sym} -900 50 0 0 {name=MPC2
L=0.5
W=10.0
nf=1
mult=2
model=pfet_01v8
spiceprefix=X}
N -880 80 -860 60 {}
C {devices/lab_pin.sym} -860 60 0 0 {name=l25 lab=outp}
N -920 50 -940 50 {}
C {devices/lab_pin.sym} -940 50 0 0 {name=l26 lab=vcp}
N -880 20 -860 40 {}
C {devices/lab_pin.sym} -860 40 0 0 {name=l27 lab=fb}
N -880 50 -860 50 {}
C {devices/lab_pin.sym} -860 50 0 0 {name=l28 lab=vdda}

* MNC1: NMOS cascode
C {sky130_fd_pr/nfet_01v8.sym} -500 50 0 0 {name=MNC1
L=0.5
W=7.0
nf=1
mult=1
model=nfet_01v8
spiceprefix=X}
N -480 20 -460 40 {}
C {devices/lab_pin.sym} -460 40 0 0 {name=l29 lab=outn}
N -520 50 -540 50 {}
C {devices/lab_pin.sym} -540 50 0 0 {name=l30 lab=vcn}
N -480 80 -460 60 {}
C {devices/lab_pin.sym} -460 60 0 0 {name=l31 lab=sa}
N -480 50 -460 50 {}
C {devices/lab_pin.sym} -460 50 0 0 {name=l32 lab=vssa}

* MNC2: NMOS cascode
C {sky130_fd_pr/nfet_01v8.sym} -100 50 0 0 {name=MNC2
L=0.5
W=7.0
nf=1
mult=1
model=nfet_01v8
spiceprefix=X}
N -80 20 -60 40 {}
C {devices/lab_pin.sym} -60 40 0 0 {name=l33 lab=outp}
N -120 50 -140 50 {}
C {devices/lab_pin.sym} -140 50 0 0 {name=l34 lab=vcn}
N -80 80 -60 60 {}
C {devices/lab_pin.sym} -60 60 0 0 {name=l35 lab=sb}
N -80 50 -60 50 {}
C {devices/lab_pin.sym} -60 50 0 0 {name=l36 lab=vssa}

* MN1: bottom sink, 4x MB1 (20 uA)
C {sky130_fd_pr/nfet_01v8.sym} 300 50 0 0 {name=MN1
L=0.5
W=2.0
nf=1
mult=4
model=nfet_01v8
spiceprefix=X}
N 320 20 340 40 {}
C {devices/lab_pin.sym} 340 40 0 0 {name=l37 lab=sa}
N 280 50 260 50 {}
C {devices/lab_pin.sym} 260 50 0 0 {name=l38 lab=ibias}
N 320 80 340 60 {}
C {devices/lab_pin.sym} 340 60 0 0 {name=l39 lab=vssa}
N 320 50 340 50 {}
C {devices/lab_pin.sym} 340 50 0 0 {name=l40 lab=vssa}

* MN2: bottom sink, 4x MB1 (20 uA)
C {sky130_fd_pr/nfet_01v8.sym} 700 50 0 0 {name=MN2
L=0.5
W=2.0
nf=1
mult=4
model=nfet_01v8
spiceprefix=X}
N 720 20 740 40 {}
C {devices/lab_pin.sym} 740 40 0 0 {name=l41 lab=sb}
N 680 50 660 50 {}
C {devices/lab_pin.sym} 660 50 0 0 {name=l42 lab=ibias}
N 720 80 740 60 {}
C {devices/lab_pin.sym} 740 60 0 0 {name=l43 lab=vssa}
N 720 50 740 50 {}
C {devices/lab_pin.sym} 740 50 0 0 {name=l44 lab=vssa}

* MB1: bias diode, ibias in (5 uA)
C {sky130_fd_pr/nfet_01v8.sym} 1100 50 0 0 {name=MB1
L=0.5
W=2.0
nf=1
mult=1
model=nfet_01v8
spiceprefix=X}
N 1120 20 1140 40 {}
C {devices/lab_pin.sym} 1140 40 0 0 {name=l45 lab=ibias}
N 1080 50 1060 50 {}
C {devices/lab_pin.sym} 1060 50 0 0 {name=l46 lab=ibias}
N 1120 80 1140 60 {}
C {devices/lab_pin.sym} 1140 60 0 0 {name=l47 lab=vssa}
N 1120 50 1140 50 {}
C {devices/lab_pin.sym} 1140 50 0 0 {name=l48 lab=vssa}

* MBP1: bias leg B: PMOS diode
C {sky130_fd_pr/pfet_01v8.sym} -900 500 0 0 {name=MBP1
L=0.5
W=5.0
nf=1
mult=1
model=pfet_01v8
spiceprefix=X}
N -880 530 -860 510 {}
C {devices/lab_pin.sym} -860 510 0 0 {name=l49 lab=vbpd}
N -920 500 -940 500 {}
C {devices/lab_pin.sym} -940 500 0 0 {name=l50 lab=vbpd}
N -880 470 -860 490 {}
C {devices/lab_pin.sym} -860 490 0 0 {name=l51 lab=vdda}
N -880 500 -860 500 {}
C {devices/lab_pin.sym} -860 500 0 0 {name=l52 lab=vdda}

* MBN1: bias leg B: sink 5 uA
C {sky130_fd_pr/nfet_01v8.sym} -500 500 0 0 {name=MBN1
L=0.5
W=2.0
nf=1
mult=1
model=nfet_01v8
spiceprefix=X}
N -480 470 -460 490 {}
C {devices/lab_pin.sym} -460 490 0 0 {name=l53 lab=vbpd}
N -520 500 -540 500 {}
C {devices/lab_pin.sym} -540 500 0 0 {name=l54 lab=ibias}
N -480 530 -460 510 {}
C {devices/lab_pin.sym} -460 510 0 0 {name=l55 lab=vssa}
N -480 500 -460 500 {}
C {devices/lab_pin.sym} -460 500 0 0 {name=l56 lab=vssa}

* MBP2: bias leg C: PMOS source 5 uA
C {sky130_fd_pr/pfet_01v8.sym} -100 500 0 0 {name=MBP2
L=0.5
W=5.0
nf=1
mult=1
model=pfet_01v8
spiceprefix=X}
N -80 530 -60 510 {}
C {devices/lab_pin.sym} -60 510 0 0 {name=l57 lab=vcn}
N -120 500 -140 500 {}
C {devices/lab_pin.sym} -140 500 0 0 {name=l58 lab=vbpd}
N -80 470 -60 490 {}
C {devices/lab_pin.sym} -60 490 0 0 {name=l59 lab=vdda}
N -80 500 -60 500 {}
C {devices/lab_pin.sym} -60 500 0 0 {name=l60 lab=vdda}

* MBCN: bias leg C: narrow NMOS diode -> vcn
C {sky130_fd_pr/nfet_01v8.sym} 300 500 0 0 {name=MBCN
L=1.0
W=0.42
nf=1
mult=1
model=nfet_01v8
spiceprefix=X}
N 320 470 340 490 {}
C {devices/lab_pin.sym} 340 490 0 0 {name=l61 lab=vcn}
N 280 500 260 500 {}
C {devices/lab_pin.sym} 260 500 0 0 {name=l62 lab=vcn}
N 320 530 340 510 {}
C {devices/lab_pin.sym} 340 510 0 0 {name=l63 lab=vssa}
N 320 500 340 500 {}
C {devices/lab_pin.sym} 340 500 0 0 {name=l64 lab=vssa}

* MBCP: bias leg D: narrow PMOS diode -> vcp
C {sky130_fd_pr/pfet_01v8.sym} 700 500 0 0 {name=MBCP
L=0.6
W=0.42
nf=1
mult=1
model=pfet_01v8
spiceprefix=X}
N 720 530 740 510 {}
C {devices/lab_pin.sym} 740 510 0 0 {name=l65 lab=vcp}
N 680 500 660 500 {}
C {devices/lab_pin.sym} 660 500 0 0 {name=l66 lab=vcp}
N 720 470 740 490 {}
C {devices/lab_pin.sym} 740 490 0 0 {name=l67 lab=vdda}
N 720 500 740 500 {}
C {devices/lab_pin.sym} 740 500 0 0 {name=l68 lab=vdda}

* MBN2: bias leg D: sink 5 uA
C {sky130_fd_pr/nfet_01v8.sym} 1100 500 0 0 {name=MBN2
L=0.5
W=2.0
nf=1
mult=1
model=nfet_01v8
spiceprefix=X}
N 1120 470 1140 490 {}
C {devices/lab_pin.sym} 1140 490 0 0 {name=l69 lab=vcp}
N 1080 500 1060 500 {}
C {devices/lab_pin.sym} 1060 500 0 0 {name=l70 lab=ibias}
N 1120 530 1140 510 {}
C {devices/lab_pin.sym} 1140 510 0 0 {name=l71 lab=vssa}
N 1120 500 1140 500 {}
C {devices/lab_pin.sym} 1140 500 0 0 {name=l72 lab=vssa}

* MCS1: CMFB sense, gate outp
C {sky130_fd_pr/nfet_01v8.sym} -900 950 0 0 {name=MCS1
L=0.5
W=2.0
nf=1
mult=1
model=nfet_01v8
spiceprefix=X}
N -880 920 -860 940 {}
C {devices/lab_pin.sym} -860 940 0 0 {name=l73 lab=cs}
N -920 950 -940 950 {}
C {devices/lab_pin.sym} -940 950 0 0 {name=l74 lab=outp}
N -880 980 -860 960 {}
C {devices/lab_pin.sym} -860 960 0 0 {name=l75 lab=ct}
N -880 950 -860 950 {}
C {devices/lab_pin.sym} -860 950 0 0 {name=l76 lab=vssa}

* MCS2: CMFB sense, gate outn
C {sky130_fd_pr/nfet_01v8.sym} -500 950 0 0 {name=MCS2
L=0.5
W=2.0
nf=1
mult=1
model=nfet_01v8
spiceprefix=X}
N -480 920 -460 940 {}
C {devices/lab_pin.sym} -460 940 0 0 {name=l77 lab=cs}
N -520 950 -540 950 {}
C {devices/lab_pin.sym} -540 950 0 0 {name=l78 lab=outn}
N -480 980 -460 960 {}
C {devices/lab_pin.sym} -460 960 0 0 {name=l79 lab=ct}
N -480 950 -460 950 {}
C {devices/lab_pin.sym} -460 950 0 0 {name=l80 lab=vssa}

* MCR: CMFB reference, gate vcm (2x one sense device)
C {sky130_fd_pr/nfet_01v8.sym} -100 950 0 0 {name=MCR
L=0.5
W=2.0
nf=1
mult=2
model=nfet_01v8
spiceprefix=X}
N -80 920 -60 940 {}
C {devices/lab_pin.sym} -60 940 0 0 {name=l81 lab=cr}
N -120 950 -140 950 {}
C {devices/lab_pin.sym} -140 950 0 0 {name=l82 lab=vcm}
N -80 980 -60 960 {}
C {devices/lab_pin.sym} -60 960 0 0 {name=l83 lab=ct}
N -80 950 -60 950 {}
C {devices/lab_pin.sym} -60 950 0 0 {name=l84 lab=vssa}

* MCT: CMFB tail 2x MB1 (10 uA)
C {sky130_fd_pr/nfet_01v8.sym} 300 950 0 0 {name=MCT
L=0.5
W=2.0
nf=1
mult=2
model=nfet_01v8
spiceprefix=X}
N 320 920 340 940 {}
C {devices/lab_pin.sym} 340 940 0 0 {name=l85 lab=ct}
N 280 950 260 950 {}
C {devices/lab_pin.sym} 260 950 0 0 {name=l86 lab=ibias}
N 320 980 340 960 {}
C {devices/lab_pin.sym} 340 960 0 0 {name=l87 lab=vssa}
N 320 950 340 950 {}
C {devices/lab_pin.sym} 340 950 0 0 {name=l88 lab=vssa}

* MCPS: CMFB load, diode on sense side
C {sky130_fd_pr/pfet_01v8.sym} 700 950 0 0 {name=MCPS
L=0.5
W=5.0
nf=1
mult=1
model=pfet_01v8
spiceprefix=X}
N 720 980 740 960 {}
C {devices/lab_pin.sym} 740 960 0 0 {name=l89 lab=cs}
N 680 950 660 950 {}
C {devices/lab_pin.sym} 660 950 0 0 {name=l90 lab=cs}
N 720 920 740 940 {}
C {devices/lab_pin.sym} 740 940 0 0 {name=l91 lab=vdda}
N 720 950 740 950 {}
C {devices/lab_pin.sym} 740 950 0 0 {name=l92 lab=vdda}

* MCPR: CMFB load, mirror -> control node cr
C {sky130_fd_pr/pfet_01v8.sym} 1100 950 0 0 {name=MCPR
L=0.5
W=5.0
nf=1
mult=1
model=pfet_01v8
spiceprefix=X}
N 1120 980 1140 960 {}
C {devices/lab_pin.sym} 1140 960 0 0 {name=l93 lab=cr}
N 1080 950 1060 950 {}
C {devices/lab_pin.sym} 1060 950 0 0 {name=l94 lab=cs}
N 1120 920 1140 940 {}
C {devices/lab_pin.sym} 1140 940 0 0 {name=l95 lab=vdda}
N 1120 950 1140 950 {}
C {devices/lab_pin.sym} 1140 950 0 0 {name=l96 lab=vdda}

* Ccm: CMFB control-node (cr) capacitor to vdda, 0.50 pF (hand-calc, not simulated)
C {sky130_fd_pr/cap_mim_m3_1.sym} -900 1400 0 0 {name=Ccm
model=cap_mim_m3_1
W=15.62
L=15.62
MF=1
spiceprefix=X}
N -900 1370 -900 1350 {}
C {devices/lab_pin.sym} -900 1350 0 0 {name=l97 lab=cr}
N -900 1430 -900 1450 {}
C {devices/lab_pin.sym} -900 1450 0 0 {name=l98 lab=vdda}

* Block pins. Order sets the .subckt terminal order.
C {devices/iopin.sym} -1400 -300 0 0 {name=p_vdda lab=vdda}
C {devices/iopin.sym} -1400 -200 0 0 {name=p_vssa lab=vssa}
C {devices/ipin.sym} -1400 -100 0 0 {name=p_inp lab=inp}
C {devices/ipin.sym} -1400 0 0 0 {name=p_inn lab=inn}
C {devices/opin.sym} -1400 100 0 0 {name=p_outp lab=outp}
C {devices/opin.sym} -1400 200 0 0 {name=p_outn lab=outn}
C {devices/ipin.sym} -1400 300 0 0 {name=p_vcm lab=vcm}
C {devices/ipin.sym} -1400 400 0 0 {name=p_ibias lab=ibias}

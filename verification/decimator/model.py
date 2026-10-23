"""Bit-exact, cycle-accurate fixed-point model of rtl/decimator.v, and the
analytic whole-chain frequency response of the quantized filter.

Every register of the RTL has a counterpart here, updated with the same
"all registers take their next value from the old values" semantics, so the
cocotb test can compare valid and dout on every clock. Coefficients are read
from rtl/decimator_coef.v, the file the RTL (and the synthesis run) uses.
"""
import math
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
COEF_V = REPO / "rtl/decimator_coef.v"
DECIMATOR_V = REPO / "rtl/decimator.v"

FS = 5.12e6          # modulator clock (spec row 5)
BW = 20e3            # signal bandwidth (spec row 1)
FOUT = 80e3          # output word rate (spec row 6)
CIC_N = 4            # CIC order (design note: order 3 cannot reach spec row 9)
CIC_LOG2R = 4        # CIC ratio R = 16
CIC_R = 1 << CIC_LOG2R
FIR_LOG2D = 2        # FIR decimation 4
FRAME = 1 << (CIC_LOG2R + FIR_LOG2D)   # clocks per output word = 64
CIC_W = CIC_N * CIC_LOG2R + 1          # 17-bit modular CIC registers
N_TAPS = 41
COEF_FRAC = 18       # coefficient scale 2**-18
COEF_W = 17          # coefficient width, signed
OUT_W = 16
MID = 1 << (CIC_N * CIC_LOG2R - 1)     # 32768: CIC unipolar mid-scale
VALID_EDGE = N_TAPS                    # clock edge (0-based, after reset) that registers dout
SR_DEPTH = N_TAPS + ((N_TAPS - 1) >> CIC_LOG2R)


def load_coefs(path=COEF_V):
    """Quantized integer coefficients as used by the RTL ROM."""
    text = pathlib.Path(path).read_text()
    got = {int(k): int(v) for k, v in re.findall(r"6'd(\d+):\s*h\s*=\s*(-?\d+);", text)}
    if sorted(got) != list(range(N_TAPS)):
        raise ValueError(f"{path}: expected taps 0..{N_TAPS - 1}, found {sorted(got)}")
    return [got[k] for k in range(N_TAPS)]


def acc_bits_needed(coefs):
    """Signed accumulator width that cannot overflow for any CIC output."""
    peak = MID * sum(abs(c) for c in coefs)
    return peak.bit_length() + 1


def _wrap(v, bits):
    return v & ((1 << bits) - 1)


def _signed(v, bits):
    v = _wrap(v, bits)
    return v - (1 << bits) if v >> (bits - 1) else v


class Decimator:
    """One call to step() is one rising clock edge with rst low."""

    def __init__(self, coefs=None):
        self.h = list(coefs) if coefs is not None else load_coefs()
        self.reset()

    def reset(self):
        self.i = [0] * CIC_N
        self.z = [0] * CIC_N
        self.fc = 0
        self.sr = [0] * SR_DEPTH
        self.acc = 0
        self.dout = 0
        self.valid = 0

    def step(self, din):
        """Advance one clock edge; return (valid, dout) as seen after it."""
        i, z, sr, fc = self.i, self.z, self.sr, self.fc
        n_i = [_wrap(i[0] + (din & 1), CIC_W)] + [_wrap(i[k] + i[k - 1], CIC_W) for k in range(1, CIC_N)]
        n_z, n_sr = list(z), list(sr)
        if fc & (CIC_R - 1) == CIC_R - 1:
            c = i[CIC_N - 1]
            for k in range(CIC_N):
                n_z[k] = c
                c = _wrap(c - z[k], CIC_W)
            n_sr = [_signed(c - MID, CIC_W)] + sr[:-1]
        acc, dout, valid = self.acc, self.dout, 0
        if fc < N_TAPS:
            idx = fc + (fc >> CIC_LOG2R)
            acc = (0 if fc == 0 else acc) + sr[idx] * self.h[fc]
        if fc == N_TAPS:
            r = (self.acc + (1 << (COEF_FRAC - 1))) >> COEF_FRAC
            dout = max(-(1 << (OUT_W - 1)), min((1 << (OUT_W - 1)) - 1, r))
            valid = 1
        self.i, self.z, self.sr = n_i, n_z, n_sr
        self.acc, self.dout, self.valid = acc, dout, valid
        self.fc = (fc + 1) & (FRAME - 1)
        return valid, dout

    def run(self, bits):
        """Feed bits; return the list of output words (one per valid strobe)."""
        out = []
        for b in bits:
            v, d = self.step(b)
            if v:
                out.append(d)
        return out


# ---- analytic response of the quantized chain (no simulation) ----

def cic_mag(f):
    x = math.pi * f / FS
    s = math.sin(x)
    if abs(s) < 1e-15:
        return 1.0
    return abs(math.sin(CIC_R * x) / (CIC_R * s)) ** CIC_N


def fir_mag(f, coefs):
    w = 2 * math.pi * f / (FS / CIC_R)
    re_ = sum(c * math.cos(w * n) for n, c in enumerate(coefs))
    im_ = sum(c * math.sin(w * n) for n, c in enumerate(coefs))
    return math.hypot(re_, im_) / (1 << COEF_FRAC)


def chain_mag(f, coefs):
    return cic_mag(f) * fir_mag(f, coefs)

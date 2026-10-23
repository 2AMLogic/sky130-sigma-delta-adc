"""Reference decimator and SNDR per spec section 1.2 (behavioural model B).

Decimator: float64 sinc^3 (CIC order 3 = modulator order + 1, spec row 10),
decimate by 64 (fout = 4*BW = 80 kSps), no droop compensation, no FIR.

SNDR: coherent tone at an odd number of cycles M in the N-sample output
record, 4-term Blackman-Harris window. Signal = tone bin +/- LOBE bins;
noise = bins above DC_EXCL_BINS up to the band edge, excluding the tone lobe,
ENBW-corrected.
"""
import numpy as np

DECIM = 64
FOUT_HZ = 80e3
BW_HZ = 20e3
LOBE = 4          # main-lobe half width of the 4-term Blackman-Harris window
DC_EXCL_BINS = 4  # bins 0..4 excluded as DC leakage
BH4 = (0.35875, 0.48829, 0.14128, 0.01168)


def sinc3_decimate(y, decim=DECIM):
    """sinc^3 filter + decimate. Output k covers input clocks [decim*k, decim*k+3*(decim-1)]."""
    box = np.ones(decim)
    kern = np.convolve(np.convolve(box, box), box) / float(decim) ** 3
    n_out = (len(y) - len(kern)) // decim + 1
    acc = np.zeros(n_out)
    for j, c in enumerate(kern):
        acc += c * y[j : j + decim * n_out : decim]
    return acc


def blackman_harris(n):
    i = np.arange(n)
    return sum(c * (-1) ** m * np.cos(2.0 * np.pi * m * i / n) for m, c in enumerate(BH4))


def odd_cycles(n_out, f_target_hz=2e3, fout_hz=FOUT_HZ):
    """Odd integer M near f_target*N/fout."""
    m = int(round(f_target_hz * n_out / fout_hz))
    return m if m % 2 else m + 1


def sndr_db(rec, cycles, fout_hz=FOUT_HZ, bw_hz=BW_HZ):
    """SNDR in dB of a coherent single-tone record. Returns (sndr_db, details)."""
    n = len(rec)
    win = blackman_harris(n)
    p = np.abs(np.fft.rfft(rec * win)) ** 2
    edge = int(round(bw_hz * n / fout_hz))
    lobe = np.arange(cycles - LOBE, cycles + LOBE + 1)
    band = np.arange(DC_EXCL_BINS + 1, edge + 1)
    noise_bins = np.setdiff1d(band, lobe)
    enbw = n * np.sum(win**2) / np.sum(win) ** 2
    sig = p[lobe].sum()
    noise = p[noise_bins].sum()
    val = 10.0 * np.log10(sig / noise * enbw)
    det = {
        "bin_bw_hz": fout_hz / n,
        "band_edge_bin": edge,
        "tone_bin": int(cycles),
        "excluded_bins": {
            "dc": [0, DC_EXCL_BINS],
            "tone_lobe": [int(cycles) - LOBE, int(cycles) + LOBE],
        },
        "enbw_bins": float(enbw),
        "window": "Blackman-Harris 4-term",
    }
    return float(val), det

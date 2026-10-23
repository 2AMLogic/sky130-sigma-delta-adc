"""cocotb tests for rtl/decimator.v against the bit-exact model (model.py).

Every test compares (dout_valid, dout) with the model on every clock edge, so
output values, valid timing and first-output latency are all pinned at once.
"""
import math
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

import model as m
import response


def tone_bits(amp, cycles_per_clock, n_clocks, seed_phase=0.0):
    """2nd-order single-bit modulator (python, ideal) -> 0/1 stream."""
    u1 = u2 = 0.0
    y = 1.0
    bits = []
    for n in range(n_clocks):
        x = amp * math.sin(2 * math.pi * cycles_per_clock * n + seed_phase)
        u1 += 0.5 * (x - y)
        u2 += 0.5 * (u1 - y)
        y = 1.0 if u2 >= 0 else -1.0
        bits.append(1 if y > 0 else 0)
    return bits


def to_signed16(v):
    return v - 65536 if v & 0x8000 else v


class Bench:
    def __init__(self, dut):
        self.dut = dut
        self.model = m.Decimator()
        self.edges = 0          # clock edges since reset release
        self.words = []         # (edge, value) of every valid strobe seen
        self.mismatches = 0

    async def start(self):
        cocotb.start_soon(Clock(self.dut.clk, 10, unit="ns").start())
        self.dut.din.value = 0
        await self.reset()

    async def reset(self, cycles=3):
        self.dut.rst.value = 1
        for _ in range(cycles):
            await RisingEdge(self.dut.clk)
        await Timer(1, unit="ns")
        self.model.reset()
        self.edges = 0
        self.dut.rst.value = 0
        self.check("reset")

    def check(self, what):
        v, d = int(self.dut.dout_valid.value), to_signed16(int(self.dut.dout.value.to_unsigned()))
        mv, md = self.model.valid, self.model.dout
        assert (v, d) == (mv, md), f"{what}: edge {self.edges}: rtl valid={v} dout={d}, model valid={mv} dout={md}"

    async def clock(self, bit):
        self.dut.din.value = bit
        await RisingEdge(self.dut.clk)
        await Timer(1, unit="ns")
        self.model.step(bit)
        self.check("clock")
        if int(self.dut.dout_valid.value):
            self.words.append((self.edges, to_signed16(int(self.dut.dout.value.to_unsigned()))))
        self.edges += 1

    async def feed(self, bits):
        for b in bits:
            await self.clock(b)


@cocotb.test()
async def random_bits(dut):
    b = Bench(dut)
    await b.start()
    rng = random.Random(16)
    await b.feed([rng.getrandbits(1) for _ in range(64 * 60 + 17)])
    assert len(b.words) == 60, f"expected 60 output words, got {len(b.words)}"


@cocotb.test()
async def biased_random_bits(dut):
    """Random streams with 25 % / 75 % one-density exercise the CIC away from mid-scale."""
    b = Bench(dut)
    await b.start()
    rng = random.Random(1616)
    for p in (0.25, 0.75, 0.5):
        await b.feed([1 if rng.random() < p else 0 for _ in range(64 * 25)])


@cocotb.test()
async def first_output_latency(dut):
    """First strobe on edge VALID_EDGE after reset, then every FRAME edges, one clock wide."""
    b = Bench(dut)
    await b.start()
    await b.feed([1, 0] * (64 * 5 // 2))
    edges = [e for e, _ in b.words]
    assert edges == [m.VALID_EDGE + m.FRAME * k for k in range(5)], edges


@cocotb.test()
async def alternating_input_is_midscale(dut):
    """0101... is a zero-mean +/-1 stream; settled output must be ~0 and match the model."""
    b = Bench(dut)
    await b.start()
    await b.feed([n & 1 for n in range(64 * 40)])
    assert abs(b.words[-1][1]) <= 2, b.words[-1]


@cocotb.test()
async def full_scale_saturates(dut):
    """All-ones: raw result +32768 saturates to +32767 (wrap would give -32768). All-zeros: -32768."""
    b = Bench(dut)
    await b.start()
    await b.feed([1] * (64 * 40))
    assert b.words[-1][1] == 32767, b.words[-1]
    assert all(v != -32768 for _, v in b.words[8:]), "positive overflow wrapped"
    await b.feed([0] * (64 * 40))
    assert b.words[-1][1] == -32768, b.words[-1]


@cocotb.test()
async def step_response_overshoot(dut):
    """Full-scale square wave: filter overshoot is clipped identically in RTL and model."""
    b = Bench(dut)
    await b.start()
    for _ in range(6):
        await b.feed([1] * (64 * 20) + [0] * (64 * 20))
    vals = [v for _, v in b.words]
    assert max(vals) == 32767 and min(vals) == -32768


@cocotb.test()
async def reset_mid_stream(dut):
    b = Bench(dut)
    await b.start()
    rng = random.Random(7)
    await b.feed([rng.getrandbits(1) for _ in range(64 * 6 + 23)])    # reset lands mid-frame
    await b.reset(cycles=2)
    assert not int(dut.dout_valid.value) and int(dut.dout.value.to_unsigned()) == 0
    b.words.clear()
    await b.feed([rng.getrandbits(1) for _ in range(64 * 8)])
    assert b.words[0][0] == m.VALID_EDGE, b.words[0]
    # a reset held across a strobe suppresses it
    await b.feed([1] * (m.VALID_EDGE - 2))
    await b.reset(cycles=4)
    await b.feed([rng.getrandbits(1) for _ in range(64 * 3)])


async def _tone_gain_db(dut, bin_k, n_out=256, settle=16):
    f0 = bin_k * m.FOUT / n_out
    b = Bench(dut)
    await b.start()
    amp = 0.5
    bits = tone_bits(amp, f0 / m.FS, m.FRAME * (n_out + settle))
    await b.feed(bits)
    y = [v for _, v in b.words][settle:settle + n_out]
    assert len(y) == n_out
    # Output word k was computed at edge VALID_EDGE + FRAME*k; its time origin cancels in |X|.
    re_ = sum(v * math.cos(2 * math.pi * bin_k * n / n_out) for n, v in enumerate(y))
    im_ = sum(v * math.sin(2 * math.pi * bin_k * n / n_out) for n, v in enumerate(y))
    meas = 2 * math.hypot(re_, im_) / n_out / (amp * m.MID)
    want = response.chain_mag(f0)
    return f0, 20 * math.log10(meas), 20 * math.log10(want)


@cocotb.test()
async def tone_gain_matches_analytic_response(dut):
    """RTL tone gain at 5 kHz and at the 20 kHz band edge equals the quantized-coefficient response."""
    for k in (16, 64):
        f0, got, want = await _tone_gain_db(dut, k)
        dut._log.info(f"tone {f0/1e3:.1f} kHz: rtl gain {got:+.4f} dB, analytic {want:+.4f} dB")
        assert abs(got - want) < 0.02, (f0, got, want)

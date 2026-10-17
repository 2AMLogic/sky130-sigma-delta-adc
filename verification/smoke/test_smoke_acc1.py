# SMOKE FIXTURE, NOT DESIGN
import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


@cocotb.test()
async def accumulates_ones(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    dut.din.value = 0
    for _ in range(2):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    rng = random.Random(1)
    expect = 0
    for _ in range(200):
        b = rng.getrandbits(1)
        dut.din.value = b
        await RisingEdge(dut.clk)
        expect = (expect + b) & 0xFF
        await Timer(1, unit="ns")
        assert int(dut.acc.value) == expect, f"acc={int(dut.acc.value)} expected {expect}"

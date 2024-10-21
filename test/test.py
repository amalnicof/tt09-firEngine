# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from cocotb.handle import SimHandleBase

async def resetCore(dut: SimHandleBase) -> None:
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)

class SPIModel(object):
    def __init__(self, dut: SimHandleBase) -> None:
        self.sclk = dut.ui_in[3]
        self.mosi = dut.ui_in[1]
        self.cs = dut.ui_in[0]

        # 1MHz clock
        Clock(self.sclk, 500, units="ns")

    def sendData(self, data: bytes, dropTail: int) -> None:
        """Send data to dut.
        starts from LSB of first byte.
        """

        RisingEdge(self.sclk)
        self.cs.value = 0

        for i, byte in enumerate(data):
            if i == len(data)-1:
                stop = dropTail
            else:
                stop = 8

            for j in range(stop):
                FallingEdge(self.sclk)
                # self
        pass
    pass


@cocotb.test()
async def test_project(dut: SimHandleBase):
    # Set the clock period to 20ns 50MHz
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())



    await resetCore(dut)
    return

    # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1

    dut._log.info("Test project behavior")

    # Set the input values you want to test
    dut.ui_in.value = 20
    dut.uio_in.value = 30

    # Wait for one clock cycle to see the output values
    await ClockCycles(dut.clk, 1)

    # The following assersion is just an example of how to check the output values.
    # Change it to match the actual expected output of your module:
    assert dut.uo_out.value == 50

    # Keep testing the module by changing the input values, waiting for
    # one or more clock cycles, and asserting the expected output values.

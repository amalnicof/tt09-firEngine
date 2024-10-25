import random
from typing import Generator, TypedDict, cast

import cocotb
import cocotb.utils
import debugpy
import numpy as np
from cocotb.clock import Clock
from cocotb.handle import SimHandleBase
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from fxpmath import Fxp
from fxpmath.utils import twos_complement_repr

DEBUGGING = False


class FixedPointConfiguration(TypedDict):
    signed: bool
    n_word: int
    n_frac: int


COEFF_CONFIG: FixedPointConfiguration = {
    "signed": True,
    "n_word": 12,
    "n_frac": 11,
}

IO_SAMPLE_CONFIG: FixedPointConfiguration = {
    "signed": True,
    "n_word": 24,
    "n_frac": 0,
}

SAMPLE_CONFIG: FixedPointConfiguration = {
    "signed": True,
    "n_word": 12,
    "n_frac": 0,
}


def generateConfig(
    clockConfig: int,
    symCoeffs: bool,
    coeffs: list[Fxp],
    clockConfigWidth: int,
    dataWidth: int,
    symCoeffsWidth: int,
) -> bytes:
    data = 0
    offset = 0

    data |= clockConfig
    offset += clockConfigWidth

    data |= symCoeffs << offset
    offset += symCoeffsWidth

    for coeff in coeffs:
        data |= (int(cast(int, coeff.val)) & 0xFFF) << offset
        offset += dataWidth

    byteData = data.to_bytes((offset + 8) // 8, "big")
    return byteData


def FilterResponseGenerator(
    nTaps: int, symCoeffs: bool, dataWidth: int, coeffs: list[Fxp]
) -> Generator[Fxp, Fxp | None, None]:
    dataMax = Fxp(0, **SAMPLE_CONFIG).set_val(
        twos_complement_repr((1 << (dataWidth - 1)) - 1, 12), raw=True
    )
    dataMin = Fxp(0, **SAMPLE_CONFIG).set_val(
        twos_complement_repr(1 << (dataWidth - 1), 12), raw=True
    )

    samples = [Fxp(0, **SAMPLE_CONFIG) for _ in range(nTaps)]
    nCoeffs = (nTaps + 1) // 2
    assert nCoeffs == len(coeffs)

    while True:
        # Compute response
        acc = Fxp(0, **SAMPLE_CONFIG)
        for i in range(nCoeffs - 1):
            if symCoeffs:
                acc += (samples[i] + samples[nTaps - 1 - i]) * coeffs[i]
            else:
                acc += (samples[i] - samples[nTaps - 1 - i]) * coeffs[i]
        acc += coeffs[-1] * samples[nTaps // 2]

        # Convert to output
        acc = cast(Fxp, np.floor(acc))
        if acc > dataMax:
            out = dataMax
        elif acc < dataMin:
            out = dataMin
        else:
            out = acc

        out <<= 12
        out.resize(**IO_SAMPLE_CONFIG)

        # Shift in sample
        sample = yield out
        assert sample is not None

        sample = cast(Fxp, np.floor(sample >> 12))
        samples[1:nTaps] = samples[0 : nTaps - 1]
        samples[0] = sample


async def resetCore(dut: SimHandleBase) -> None:
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


class SPIModel(object):
    def __init__(self, dut: SimHandleBase) -> None:
        self.spiClk = dut.top.spiClk
        self.mosi = dut.top.mosi
        self.cs = dut.top.cs

        # 1MHz clock
        clock = Clock(self.spiClk, 500, units="ns")
        cocotb.start_soon(clock.start())

    async def sendData(self, data: bytes) -> None:
        """Send data to dut.
        starts from MSB of first byte.
        """

        await RisingEdge(self.spiClk)
        self.cs.value = 0

        for i, byte in enumerate(data):
            for j in range(8):
                await FallingEdge(self.spiClk)
                self.mosi.value = (byte >> (8 - 1 - j)) & 0x1

        await FallingEdge(self.spiClk)
        self.cs.value = 1


class I2SModel(object):
    def __init__(self, dut: SimHandleBase) -> None:
        self.dataWidth = dut.top.firEngine.DataWidth.value
        self.mclk = dut.top.mclk
        self.lrck = dut.top.lrck
        self.sclk = dut.top.sclk
        self.dac = dut.top.dac
        self.adc = dut.top.adc

        self.adc.value = 0

    async def sendAdc(self, value: Fxp) -> None:
        await RisingEdge(self.lrck)  # Only send data on high lrck

        valueRaw = int(cast(int, value.val))
        for i in range(24):
            await FallingEdge(self.sclk)
            self.adc.value = (valueRaw >> (24 - 1 - i)) & 0x1

        await FallingEdge(self.sclk)
        self.adc.value = 0

    async def readDac(self) -> Fxp:
        await RisingEdge(self.lrck)  # Only read on high lrck
        await RisingEdge(self.sclk)  # Skip first sample pulse

        valueRaw = 0
        for _ in range(24):
            await RisingEdge(self.sclk)
            valueRaw = (valueRaw << 1) | int(self.dac.value)

        return Fxp(
            0,
            **IO_SAMPLE_CONFIG,
        ).set_val(twos_complement_repr(valueRaw, 24), raw=True)


@cocotb.test()
async def test_project(dut: SimHandleBase):
    if DEBUGGING:
        debugpy.listen(("localhost", 5678))
        print("Please attach debugger now")
        debugpy.wait_for_client()
        breakpoint()

    dut._log.info("===================\nFIREngine Testbench\n===================")

    random.seed("fce2ab28-479d-47c7-bc6d-e530344faf14")

    # Parameters
    nTaps = dut.top.firEngine.NTaps.value
    nCoeffs = (nTaps + 1) // 2
    clockConfigWidth = dut.top.firEngine.ClockConfigWidth.value
    dataWidth = dut.top.firEngine.DataWidth.value
    symCoeffsWidth = 1

    clockConfig = 0
    symCoeffs = True
    coeffs = [Fxp(0, **COEFF_CONFIG) for _ in range(nCoeffs)]

    def genConfigLocal() -> bytes:
        return generateConfig(
            clockConfig, symCoeffs, coeffs, clockConfigWidth, dataWidth, symCoeffsWidth
        )

    spi = SPIModel(dut)
    i2s = I2SModel(dut)

    # Set the clock period to 20ns 50MHz
    clock = Clock(dut.clk, 20, units="ns")
    await cocotb.start(clock.start())

    #
    # Test Clock Generation
    #
    dut._log.info("Test Clock Generation")
    await resetCore(dut)

    clockConfig = 15
    await spi.sendData(genConfigLocal())

    # lock clock generator
    await RisingEdge(i2s.lrck)
    await RisingEdge(i2s.lrck)

    await RisingEdge(i2s.mclk)
    start = cocotb.utils.get_sim_time(units="ps")
    await RisingEdge(i2s.mclk)
    end = cocotb.utils.get_sim_time(units="ps")
    assert end - start == 640000, "mclk period incorrect"

    await RisingEdge(i2s.sclk)
    start = cocotb.utils.get_sim_time(units="ps")
    await RisingEdge(i2s.sclk)
    end = cocotb.utils.get_sim_time(units="ps")
    assert end - start == 2560000, "sclk period incorrect"

    await RisingEdge(i2s.lrck)
    start = cocotb.utils.get_sim_time(units="ps")
    await RisingEdge(i2s.lrck)
    end = cocotb.utils.get_sim_time(units="ps")
    assert end - start == 163840000, "lrck period incorrect"

    #
    # Test Impulse Response
    #
    dut._log.info("Test Impulse Response")
    await resetCore(dut)

    filterRespGen = FilterResponseGenerator(nTaps, symCoeffs, dataWidth, coeffs)
    filterRespGen.send(None)

    clockConfig = 0
    for i in range(nCoeffs):
        rand = random.randint(0, 0xFFF)
        coeffs[i].set_val(twos_complement_repr(rand, 12), raw=True)

    await spi.sendData(genConfigLocal())

    adcData = Fxp(1 << 22, **IO_SAMPLE_CONFIG)
    await i2s.sendAdc(adcData)

    for i in range(nTaps * 2):
        resp = filterRespGen.send(adcData if i == 0 else Fxp(0, **IO_SAMPLE_CONFIG))
        dacData = await i2s.readDac()
        assert (
            dacData == resp
        ), f"Impulse response incorrect, at {i} should be {resp} not {dacData}"

    #
    # Test Random Data
    #
    dut._log.info("Test Random Data")
    await resetCore(dut)
    await spi.sendData(genConfigLocal())

    adcData = Fxp(random.randint(-0x800000, 0x7FFFFF), **IO_SAMPLE_CONFIG)
    await i2s.sendAdc(adcData)

    for i in range(nTaps * 2):
        resp = filterRespGen.send(adcData)

        adcData = Fxp(random.randint(-0x800000, 0x7FFFFF), **IO_SAMPLE_CONFIG)
        adcTask = cocotb.start_soon(i2s.sendAdc(adcData))

        dacData = await i2s.readDac()
        await adcTask

        assert (
            dacData == resp
        ), f"Random response incorrect, at {i} should be {resp} not {dacData}"

    for i in range(nTaps + 1):
        resp = filterRespGen.send(adcData if i == 0 else Fxp(0, **IO_SAMPLE_CONFIG))

        adcTask = cocotb.start_soon(i2s.sendAdc(Fxp(0, **IO_SAMPLE_CONFIG)))
        dacData = await i2s.readDac()
        await adcTask

        assert (
            dacData == resp
        ), f"Random fading response incorrect, at {i} should be {resp} not {dacData}"

    #
    # Test Asymetric Impulse
    #
    dut._log.info("Test Asymetric Impulse Response")
    await resetCore(dut)

    symCoeffs = False
    await spi.sendData(genConfigLocal())

    filterRespGen = FilterResponseGenerator(nTaps, symCoeffs, dataWidth, coeffs)
    filterRespGen.send(None)

    adcData = Fxp(1 << 22, **IO_SAMPLE_CONFIG)
    await i2s.sendAdc(adcData)

    for i in range(nTaps * 2):
        resp = filterRespGen.send(adcData if i == 0 else Fxp(0, **IO_SAMPLE_CONFIG))
        dacData = await i2s.readDac()
        assert (
            dacData == resp
        ), f"Asymetric impulse response incorrect, at {i} should be {resp} not {dacData}"

    #
    # Test Asymetric Random Data
    #
    dut._log.info("Test Asymetric Random Data")
    await resetCore(dut)
    await spi.sendData(genConfigLocal())

    adcData = Fxp(random.randint(-0x800000, 0x7FFFFF), **IO_SAMPLE_CONFIG)
    await i2s.sendAdc(adcData)

    for i in range(nTaps * 2):
        resp = filterRespGen.send(adcData)

        adcData = Fxp(random.randint(-0x800000, 0x7FFFFF), **IO_SAMPLE_CONFIG)
        adcTask = cocotb.start_soon(i2s.sendAdc(adcData))

        dacData = await i2s.readDac()
        await adcTask

        assert (
            dacData == resp
        ), f"Asymetric random response incorrect, at {i} should be {resp} not {dacData}"

    for i in range(nTaps + 1):
        resp = filterRespGen.send(adcData if i == 0 else Fxp(0, **IO_SAMPLE_CONFIG))

        adcTask = cocotb.start_soon(i2s.sendAdc(Fxp(0, **IO_SAMPLE_CONFIG)))
        dacData = await i2s.readDac()
        await adcTask

        assert (
            dacData == resp
        ), f"Asymetric random fading response incorrect, at {i} should be {resp} not {dacData}"

    await ClockCycles(dut.clk, 16)
    dut._log.info("Testing Complete")

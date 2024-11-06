import random
from dataclasses import dataclass
from typing import Generator, TypedDict, cast

import cocotb
import cocotb.triggers
import cocotb.utils
import debugpy
import numpy as np
from cocotb.clock import Clock
from cocotb.handle import SimHandleBase
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from fxpmath import Fxp
from fxpmath.utils import twos_complement_repr

DEBUGGING = False

CLOCK_PERIOD = 20
SERIAL_DATA_WIDTH = 24


class FixedPointConfiguration(TypedDict):
    signed: bool
    n_word: int
    n_frac: int


@dataclass
class Constants(object):
    nTaps: int
    dataWidth: int
    clockConfigWidth: int
    symCoeffsWidth: int

    @property
    def nCoeffs(self) -> int:
        return (self.nTaps + 1) // 2

    @property
    def coeffConfig(self) -> FixedPointConfiguration:
        return {
            "signed": True,
            "n_word": self.dataWidth,
            "n_frac": self.dataWidth - 1,
        }

    @property
    def ioSampleConfig(self) -> FixedPointConfiguration:
        return {
            "signed": True,
            "n_word": SERIAL_DATA_WIDTH,
            "n_frac": 0,
        }

    @property
    def sampleConfig(self) -> FixedPointConfiguration:
        return {
            "signed": True,
            "n_word": self.dataWidth,
            "n_frac": 0,
        }

    @property
    def dataSampleShift(self) -> int:
        return SERIAL_DATA_WIDTH - self.dataWidth


GATE_LEVEL_SIM_PARAMETERS = Constants(
    nTaps=11,
    dataWidth=8,
    clockConfigWidth=4,
    symCoeffsWidth=1,
)


def generateConfig(
    consts: Constants,
    clockConfig: int,
    symCoeffs: bool,
    coeffs: list[Fxp],
) -> bytes:
    data = 0
    offset = 0

    data |= clockConfig
    offset += consts.clockConfigWidth

    data |= symCoeffs << offset
    offset += consts.symCoeffsWidth

    for coeff in coeffs:
        data |= (int(cast(int, coeff.val)) & ((1 << consts.dataWidth) - 1)) << offset
        offset += consts.dataWidth

    byteData = data.to_bytes((offset + 8) // 8, "big")
    return byteData


def FilterResponseGenerator(
    consts: Constants, symCoeffs: bool, coeffs: list[Fxp]
) -> Generator[Fxp, Fxp | None, None]:
    dataMax = Fxp(0, **consts.sampleConfig).set_val(
        twos_complement_repr((1 << (consts.dataWidth - 1)) - 1, consts.dataWidth),
        raw=True,
    )
    dataMin = Fxp(0, **consts.sampleConfig).set_val(
        twos_complement_repr(1 << (consts.dataWidth - 1), consts.dataWidth), raw=True
    )

    samples = [Fxp(0, **consts.sampleConfig) for _ in range(consts.nTaps)]
    nCoeffs = (consts.nTaps + 1) // 2
    assert nCoeffs == len(coeffs)

    while True:
        # Compute response
        acc = Fxp(0, **consts.sampleConfig)
        for i in range(nCoeffs - 1):
            if symCoeffs:
                acc += (samples[i] + samples[consts.nTaps - 1 - i]) * coeffs[i]
            else:
                acc += (samples[i] - samples[consts.nTaps - 1 - i]) * coeffs[i]
        acc += coeffs[-1] * samples[consts.nTaps // 2]

        # Convert to output
        acc = cast(Fxp, np.floor(acc))
        if acc > dataMax:
            out = dataMax
        elif acc < dataMin:
            out = dataMin
        else:
            out = acc

        out <<= consts.dataSampleShift
        out.resize(**consts.ioSampleConfig)

        # Shift in sample
        sample = yield out
        assert sample is not None

        sample = cast(Fxp, np.floor(sample >> consts.dataSampleShift))
        samples[1 : consts.nTaps] = samples[0 : consts.nTaps - 1]
        samples[0] = sample


async def resetCore(dut: SimHandleBase) -> None:
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


class SPIModel(object):
    def __init__(self, dut: SimHandleBase) -> None:
        self.spiClk = dut.spiClk
        self.mosi = dut.mosi
        self.cs = dut.cs

        self.cs.value = 1
        self.mosi.value = 0

        # 1MHz clock
        clock = Clock(dut.spiClk, 500, units="ns")
        cocotb.start_soon(clock.start())

    async def sendData(self, data: bytes) -> None:
        """Send data to dut.
        starts from MSB of first byte.
        """

        await RisingEdge(self.spiClk)
        self.cs.value = 0

        for byte in data:
            for j in range(8):
                await FallingEdge(self.spiClk)
                self.mosi.value = (byte >> (8 - 1 - j)) & 0x1

        await FallingEdge(self.spiClk)
        self.cs.value = 1
        self.mosi.value = 0


class I2SModel(object):
    def __init__(self, dut: SimHandleBase, consts: Constants) -> None:
        self.consts = consts
        self.mclk = dut.mclk
        self.lrck = dut.lrck
        self.sclk = dut.sclk
        self.dac = dut.dac
        self.adc = dut.adc

        self.adc.value = 0

    async def sendAdc(self, value: Fxp) -> None:
        await RisingEdge(self.lrck)  # Only send data on high lrck
        await cocotb.triggers.Timer(1, units="ps")  # type: ignore

        valueRaw = int(cast(int, value.val))
        for i in range(SERIAL_DATA_WIDTH):
            await FallingEdge(self.sclk)
            self.adc.value = (valueRaw >> (SERIAL_DATA_WIDTH - 1 - i)) & 0x1

        await FallingEdge(self.sclk)
        self.adc.value = 0

    async def readDac(self) -> Fxp:
        await RisingEdge(self.lrck)  # Only read on high lrck
        await RisingEdge(self.sclk)  # Skip first sample pulse

        valueRaw = 0
        for _ in range(SERIAL_DATA_WIDTH):
            await RisingEdge(self.sclk)
            valueRaw = (valueRaw << 1) | int(self.dac.value)

        return Fxp(
            0,
            **self.consts.ioSampleConfig,
        ).set_val(twos_complement_repr(valueRaw, SERIAL_DATA_WIDTH), raw=True)


@cocotb.test
async def test_project(dut: SimHandleBase):
    if DEBUGGING:
        debugpy.listen(("localhost", 5678))
        print("Please attach debugger now")
        debugpy.wait_for_client()
        breakpoint()

    dut._log.info("===================\nFIREngine Testbench\n===================")

    random.seed("fce2ab28-479d-47c7-bc6d-e530344faf14")

    # Parameters
    if hasattr(dut.top, "firEngine"):
        # RTL Sim
        consts = Constants(
            nTaps=dut.top.firEngine.NTaps.value,
            dataWidth=dut.top.firEngine.DataWidth.value,
            clockConfigWidth=dut.top.firEngine.ClockConfigWidth.value,
            symCoeffsWidth=1,
        )
    else:
        # Gate Level Sim
        consts = GATE_LEVEL_SIM_PARAMETERS

    clockConfig = 0
    symCoeffs = True
    coeffs = [Fxp(0, **consts.coeffConfig) for _ in range(consts.nCoeffs)]

    def genConfigLocal() -> bytes:
        return generateConfig(consts, clockConfig, symCoeffs, coeffs)

    spi = SPIModel(dut)
    i2s = I2SModel(dut, consts)

    # Set the clock period to 20ns 50MHz
    clock = Clock(dut.clk, CLOCK_PERIOD, units="ns")
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

    filterRespGen = FilterResponseGenerator(consts, symCoeffs, coeffs)
    filterRespGen.send(None)

    clockConfig = 0
    for i in range(consts.nCoeffs):
        rand = random.randint(0, 0xFFF)
        coeffs[i].set_val(twos_complement_repr(rand, consts.dataWidth), raw=True)

    await spi.sendData(genConfigLocal())

    adcData = Fxp(1 << 22, **consts.ioSampleConfig)
    await i2s.sendAdc(adcData)

    for i in range(consts.nTaps * 2):
        resp = filterRespGen.send(
            adcData if i == 0 else Fxp(0, **consts.ioSampleConfig)
        )
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

    adcData = Fxp(random.randint(-0x800000, 0x7FFFFF), **consts.ioSampleConfig)
    await i2s.sendAdc(adcData)

    for i in range(consts.nTaps * 2):
        resp = filterRespGen.send(adcData)

        adcData = Fxp(random.randint(-0x800000, 0x7FFFFF), **consts.ioSampleConfig)
        adcTask = cocotb.start_soon(i2s.sendAdc(adcData))

        dacData = await i2s.readDac()
        await adcTask

        assert (
            dacData == resp
        ), f"Random response incorrect, at {i} should be {resp} not {dacData}"

    for i in range(consts.nTaps + 1):
        resp = filterRespGen.send(
            adcData if i == 0 else Fxp(0, **consts.ioSampleConfig)
        )

        adcTask = cocotb.start_soon(i2s.sendAdc(Fxp(0, **consts.ioSampleConfig)))
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

    filterRespGen = FilterResponseGenerator(consts, symCoeffs, coeffs)
    filterRespGen.send(None)

    adcData = Fxp(1 << 22, **consts.ioSampleConfig)
    await i2s.sendAdc(adcData)

    for i in range(consts.nTaps * 2):
        resp = filterRespGen.send(
            adcData if i == 0 else Fxp(0, **consts.ioSampleConfig)
        )
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

    adcData = Fxp(random.randint(-0x800000, 0x7FFFFF), **consts.ioSampleConfig)
    await i2s.sendAdc(adcData)

    for i in range(consts.nTaps * 2):
        resp = filterRespGen.send(adcData)

        adcData = Fxp(random.randint(-0x800000, 0x7FFFFF), **consts.ioSampleConfig)
        adcTask = cocotb.start_soon(i2s.sendAdc(adcData))

        dacData = await i2s.readDac()
        await adcTask

        assert (
            dacData == resp
        ), f"Asymetric random response incorrect, at {i} should be {resp} not {dacData}"

    for i in range(consts.nTaps + 1):
        resp = filterRespGen.send(
            adcData if i == 0 else Fxp(0, **consts.ioSampleConfig)
        )

        adcTask = cocotb.start_soon(i2s.sendAdc(Fxp(0, **consts.ioSampleConfig)))
        dacData = await i2s.readDac()
        await adcTask

        assert (
            dacData == resp
        ), f"Asymetric random fading response incorrect, at {i} should be {resp} not {dacData}"

    await ClockCycles(dut.clk, 16)
    dut._log.info("Testing Complete")

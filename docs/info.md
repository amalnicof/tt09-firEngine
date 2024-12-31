<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

FIREngine is a Digital FIR filter that filters inputs from an I2S2 PMOD ADC and DAC module. The purpose of this design is to filter audio from an I2S2 PMOD device found here: https://digilent.com/shop/pmod-i2s2-stereo-audio-input-and-output/. Although the number of taps the filter is not adjustable and must be determined before synthesis, the coefficients of each tap are programmable. This allows for different low, band, and high pass filters to be constructed for multiple audio filtering configurations. It is a parametrizable filter with either symmetric or antisymmetric coefficients, and 11 taps. Uses 2s complement and fixed-point data. Coefficients are set via an SDI Interface.
The filter implementation was tested on an FPGA prior to submission to ensure proper functionality.

## How to test

Use TinyTapeout Demo board to connect PMOD to Tiny Tapeout project, program filter coefficients serially, and experience the results! Filter coefficients can be determined using a filter design tool such as MATLAB filterDesigner. The filter coefficients must be:
- Either symmetric or asymmetric
- 11 Taps (6 filter coefficients)
- 8 bit cofficients, having format SFix<1,7>

SPI Data transimission starts from the MSB of the first byte (right-most) where bytes are ordered:

{coeff[5],...,coeff[0],SYM_COEFFS,clockConfig}

Examples of this SPI communication can be seen in the Cocotb test (test/test.py) or in our script used to program the test implementation on FPGA through SPI ([SPI Script](https://github.com/amalnicof/tinytapeout_09_cadence/blob/main/scripts/config.py)).

## External hardware

- I2S2 PMOD device: https://digilent.com/shop/pmod-i2s2-stereo-audio-input-and-output/
- Serial programmer: (non-specific, but we use Adafruit FT232H Breakout: https://www.adafruit.com/product/2264?gad_source=1)

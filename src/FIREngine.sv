/*
 * Module `FIREngine`
 *
 * Top module for the FIREngine
 */

module FIREngine #(
    parameter integer NTaps = 9,
    parameter integer DataWidth = 12,

    localparam integer ClockConfigWidth = 4
) (
    input wire clk,
    input wire resetN,

    // I2S2 Port
    output wire mclk,
    output wire sclk,
    output wire lrck,
    input  wire adc,
    output wire dac,

    // SPI Port
    input wire spiClk,
    input wire mosi,
    input wire cs
);
  // Serial signals
  wire serial;  // from spi to config
  wire serialFir;  // from config to fir
  wire serialEn;

  // Configuration signals
  wire [ClockConfigWidth-1:0] clockConfig;
  wire symCoeffs;

  // Data signals
  wire signed [DataWidth-1:0] adcData;
  wire adcDataValid;

  wire signed [DataWidth-1:0] firData;
  wire firDataValid;

  // Instantiations
  I2SController #(
      .ClockConfigWidth(ClockConfigWidth),
      .DataWidth(DataWidth)
  ) i2sController (
      .clk(clk),
      .resetN(resetN),
      .clockConfig(clockConfig),
      .adcData(adcData),
      .adcDataValid(adcDataValid),
      .dacData(firData),
      .dacDataValid(firDataValid),
      .mclk(mclk),
      .sclk(sclk),
      .lrck(lrck),
      .adc(adc),
      .dac(dac)
  );

  fir #(
      .DataWidth(DataWidth),
      .NTaps(NTaps)
  ) firInst (
      .clk(clk),
      .rstN(resetN),
      .start(adcDataValid),
      .lock(!cs),  // Lock when spi is writing data
      .done(firDataValid),
      .symCoeffs(symCoeffs),
      .coeff_load_in(serialEn),
      .coeff_in(serialFir),
      .x(adcData),
      .y(firData)
  );

  SPISlave spiSlave (
      .clk(clk),
      .resetN(resetN),
      .serialOut(serial),
      .serialEn(serialEn),
      .rawSCLK(spiClk),
      .rawMOSI(mosi),
      .rawCS(cs)
  );

  ConfigStore #(
      .ClockConfigWidth(ClockConfigWidth)
  ) configStore (
      .clk(clk),
      .resetN(resetN),
      .serialEn(serialEn),
      .serialIn(serial),
      .serialOut(serialFir),
      .clockConfig(clockConfig),
      .symCoeffs(symCoeffs)
  );
endmodule

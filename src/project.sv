/*
 * Copyright (c) 2024 Your Name
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_arandomdev_fir_engine_top (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  wire mclk;
  wire lrck;
  wire sclk;
  wire dac;
  wire adc = uio_in[7];

  wire cs = ui_in[0];
  wire mosi = ui_in[1];
  wire spiClk = ui_in[3];

  assign uio_out[0] = mclk;
  assign uio_out[1] = lrck;
  assign uio_out[2] = sclk;
  assign uio_out[3] = dac;
  assign uio_out[4] = mclk;
  assign uio_out[5] = lrck;
  assign uio_out[6] = sclk;
  assign uio_out[7] = 1'b0;

  assign uio_oe = 8'b01111111;
  assign uo_out = 8'b0;

  FIREngine #(
      .NTaps(11),
      .DataWidth(8)
  ) firEngine (
      .clk(clk),
      .resetN(rst_n),

      // I2S2 Port
      .mclk(mclk),
      .sclk(sclk),
      .lrck(lrck),
      .adc (adc),
      .dac (dac),

      // SPI Port
      .spiClk(spiClk),
      .mosi(mosi),
      .cs(cs)
  );

  // List all unused inputs to prevent warnings
  wire _unused = &{ena, uio_in[6:0], ui_in[2], ui_in[7:4], 1'b0};

endmodule

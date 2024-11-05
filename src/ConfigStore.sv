/*
 * Module `ConfigStore`
 *
 * Stores configuration values using a shift register.
 */

module ConfigStore #(
    parameter integer ClockConfigWidth = 4,
    parameter integer SymCoeffsWidth   = 1,

    parameter logic [ClockConfigWidth-1:0] DefaultClockConfig = 4'hf,  // Around 7kHz for 32MHz Clk
    parameter logic DefaultSymCoeffs = 1'b1,

    localparam integer ShiftRegSize = ClockConfigWidth + SymCoeffsWidth
) (
    input wire clk,
    input wire resetN,

    // Shift register port
    input  wire serialEn,
    input  wire serialIn,
    output wire serialOut,

    // Config
    output wire [ClockConfigWidth-1:0] clockConfig,
    output wire symCoeffs
);
  logic [ShiftRegSize-1:0] shiftReg;

  assign {symCoeffs, clockConfig} = shiftReg;
  assign serialOut = shiftReg[ShiftRegSize-1];

  always @(posedge clk) begin
    if (!resetN) begin
      shiftReg <= {DefaultSymCoeffs, DefaultClockConfig};
    end else if (serialEn) begin
      shiftReg <= {shiftReg[ShiftRegSize-2:0], serialIn};
    end
  end
endmodule

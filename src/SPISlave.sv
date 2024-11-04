/*
 * Module `SPISlave`
 *
 * Half duplex SPI slave that pipes input to an external shift register.
 * The size of the shift registers must be byte aligned.
 */

module SPISlave (
    input wire clk,
    input wire resetN,

    // Shift register port
    output logic serialOut,
    output logic serialEn,

    // SPI slave port
    input wire rawSCLK,
    input wire rawMOSI,
    input wire rawCS
);
  // Synchronizers
  logic [2:0] sclkSynchronizer;  // One bit bigger for edge detector
  logic [1:0] mosiSynchronizer;
  logic [1:0] csSynchronizer;

  // Signals
  wire sclkRe = sclkSynchronizer[2:1] == 2'b01;

  wire mosi = mosiSynchronizer[1];
  wire cs = csSynchronizer[1];

  always_ff @(posedge clk) begin : Synchronizers
    if (!resetN) begin
      sclkSynchronizer <= 0;
      mosiSynchronizer <= 0;
      csSynchronizer   <= 0;
    end else begin
      sclkSynchronizer <= {sclkSynchronizer[1:0], rawSCLK};
      mosiSynchronizer <= {mosiSynchronizer[0], rawMOSI};
      csSynchronizer   <= {csSynchronizer[0], rawCS};
    end
  end

  always_comb begin : SerialOutput
    if (!cs && sclkRe) begin
      serialOut = mosi;
      serialEn  = 1;
    end else begin
      serialOut = 0;
      serialEn  = 0;
    end
  end
endmodule

/*
 * Module `fir`
 *
 * FIR Filter
 * Coefficients have the format SFix<1,m>, where m is DataWidth-1. For 12 bit data, the format is 1
 * sign bit and 11 fractional bits.
 * Input and output samples are unsigned integers of size DataWidth.
 */

module fir #(
    parameter integer DataWidth = 12,
    parameter integer NTaps = 9,

    localparam integer NCoeffs = (NTaps + 1) / 2,

    // The sum of coeff must be in [-1,1]
    // int + extra int bit + frac bits + sign
    localparam integer AccumulatorWidth = DataWidth + 1 + DataWidth - 1 + 1,
    localparam logic signed [DataWidth-1:0] DataMax = (1 << (DataWidth - 1)) - 1,
    localparam logic signed [DataWidth-1:0] DataMin = 1 << (DataWidth - 1)

) (
    input wire clk,
    input wire rstN,
    input wire start,
    input wire lock,  // lock signal to stop coefficient shifting
    output logic done,  // Done pulse when output data is valid
    input wire symCoeffs,  // If the coefficients are symmetric as compared to anti-symmetric
    input wire coeff_load_in,
    input wire coeff_in,  // Coefficients, SFix<1,11>
    input wire signed [DataWidth-1:0] x,  // Input samples SFix<12,0>
    output logic signed [DataWidth-1:0] y  // Output samples SFix<12,0>
);
  generate
    if (NTaps % 2 == 0) begin : g_ParameterVerification_NTaps
      ParameterVerificationFailure nTaps_must_be_odd ();
    end
  endgenerate

  localparam integer SAMPLE_CNT_BITS = $clog2(NCoeffs);
  localparam integer BITS_CNT_BITS = $clog2(DataWidth);

  // control signals
  logic sft, sample_cnt_en, bit_cnt_en, mac_en, sample_cnt_rst;

  reg [SAMPLE_CNT_BITS-1:0] sample_cnt;

  // samples LSFR
  // When a new sample is shifted in, the entire LSFR advances.
  // During the MAC operation, the LSFR is split in half, and advances in opposite directions.
  // This allows the MAC process to just select from the LSB and MSB of the entire lsfr
  logic signed [DataWidth-1:0] samples[NTaps];
  always_ff @(posedge clk) begin
    if (!rstN) begin
      // reset
      for (integer i = 0; i < NTaps; i++) begin
        samples[i] <= DataWidth'(0);
      end
    end else begin
      // shifting
      if (start) begin
        // Shift in new sample
        samples[0] <= x;
        for (integer i = 0; i < NTaps - 1; i++) begin
          samples[i+1] <= samples[i];
        end
      end else if (sft && sample_cnt != SAMPLE_CNT_BITS'(NTaps / 2)) begin
        // Split the LSFR in 2
        // x1 x2 x3 x4 | x5 | x6 x7 x8 x9
        // x2 x3 x4 x1 | x5 | x9 x6 x7 x8
        // x3 x4 x1 x2 | x5 | x8 x9 x6 x7
        // ...
        for (integer i = 0; i < (NTaps / 2) - 1; i++) begin
          samples[i] <= samples[i+1];
        end
        samples[(NTaps/2)-1] <= samples[0];

        for (integer i = (NTaps / 2) + 1; i < NTaps - 1; i++) begin
          samples[i+1] <= samples[i];
        end
        samples[(NTaps/2)+1] <= samples[NTaps-1];
      end
    end
  end

  integer k;
  integer f;
  // coefficients LSFR
  // When loading coefficients, it becomes a bit lsfr, where the new bit is shifted from the LSB
  // During the MAC operation, it shifts by DataWidth downwards
  logic signed [DataWidth-1:0] coeffs[NCoeffs];
  always_ff @(posedge clk) begin
    if (!rstN) begin
      // reset
      for (integer i = 0; i < NCoeffs; i++) begin
        coeffs[i] <= DataWidth'(0);
      end
    end else begin
      // shifting
      if (coeff_load_in) begin
        coeffs[0][0] <= coeff_in;
        for (k = 0; k < NCoeffs - 1; k++) begin
          // connection between coeffs
          coeffs[k+1][0] <= coeffs[k][DataWidth-1];

          // Connection within coeffs
          for (f = 0; f < DataWidth - 1; f++) begin
            coeffs[k][f+1] <= coeffs[k][f];
          end
        end

        // Connection within last coeff
        for (f = 0; f < DataWidth - 1; f++) begin
          coeffs[NCoeffs-1][f+1] <= coeffs[NCoeffs-1][f];
        end
      end else if (sft && !lock) begin
        coeffs[NCoeffs-1] <= coeffs[0];
        for (integer i = 0; i < NCoeffs - 1; i++) begin
          coeffs[i] <= coeffs[i+1];
        end
      end
    end
  end

  // sample counter
  always_ff @(posedge clk) begin
    if (!rstN) begin
      sample_cnt <= 'd0;
    end else begin
      if (sample_cnt_en) begin
        sample_cnt <= sample_cnt + 1'b1;
      end else if (sample_cnt_rst) begin
        sample_cnt <= 'd0;
      end
    end
  end

  // bit counter
  reg [BITS_CNT_BITS-1:0] bit_cnt;
  always_ff @(posedge clk) begin
    if (!rstN) begin
      bit_cnt <= 'd0;
    end else begin
      if ((bit_cnt_en == 1'b1) && (bit_cnt < BITS_CNT_BITS'(DataWidth - 1))) begin
        bit_cnt <= bit_cnt + 1'b1;
      end else begin
        bit_cnt <= 'd0;
      end
    end
  end

  // MAC: Multiply and Accumulate
  logic [1:0] sel;
  logic signed [AccumulatorWidth-1:0] mux_out;
  logic signed [AccumulatorWidth-1:0] acc_in;
  logic signed [AccumulatorWidth-1:0] accQ;
  always_comb begin
    // create select signal through filter symmetry
    if (sample_cnt == SAMPLE_CNT_BITS'(NTaps / 2)) begin
      // Use middle sample
      sel = {1'b0, samples[NTaps/2][bit_cnt]};
    end else begin
      // Use shifted samples
      if (symCoeffs) begin
        sel = samples[0][bit_cnt] + samples[NTaps-1][bit_cnt];
      end else begin
        if (!samples[0][bit_cnt] && samples[NTaps-1][bit_cnt]) begin
          // Should subtract coefficient
          sel = 2'b11;
        end else begin
          // results in 0, 1, or 2
          sel = samples[0][bit_cnt] - samples[NTaps-1][bit_cnt];
        end
      end
    end

    // MUX
    case (sel)
      2'b00:   mux_out = AccumulatorWidth'(0);
      2'b01:   mux_out = AccumulatorWidth'(coeffs[0]) << bit_cnt;
      2'b10:   mux_out = AccumulatorWidth'(coeffs[0]) << (bit_cnt + 1);
      2'b11:   mux_out = -(AccumulatorWidth'(coeffs[0]) << bit_cnt);
      default: mux_out = AccumulatorWidth'(0);
    endcase

    if (bit_cnt == BITS_CNT_BITS'(DataWidth - 1)) begin
      // Sign should be subtraction
      acc_in = accQ - mux_out;
    end else begin
      acc_in = accQ + mux_out;
    end
  end

  // accumulator register
  always_ff @(posedge clk) begin
    if (!rstN) begin
      accQ <= 'd0;
    end else begin
      if (start) begin
        accQ <= 'd0;
      end else if (mac_en) begin
        accQ <= acc_in;
      end
    end
  end

  // Output value
  localparam integer yIntWidth = DataWidth + 2;
  wire signed [yIntWidth-1:0] yInt = yIntWidth'(accQ >>> (DataWidth - 1));
  wire signed [DataWidth-1:0] yIntPart = yInt[DataWidth-1:0];
  always_comb begin
    // Remove fractional bits
    // truncate to DataWidth, saturating
    if (yInt > yIntWidth'(DataMax)) begin
      y = DataMax;
    end else if (yInt < yIntWidth'(DataMin)) begin
      y = DataMin;
    end else begin
      y = yIntPart;
    end
  end

  // STATE MACHINE
  typedef enum logic [1:0] {
    IDLE,
    COEFF_LD,
    OP,
    SHIFT
  } state_e;

  state_e n_state, state;
  // transition states
  always_ff @(posedge clk) begin
    if (!rstN) begin
      state <= IDLE;
    end else begin
      state <= n_state;

      if (state == SHIFT && n_state == IDLE) begin
        done <= 1'b1;
      end else begin
        done <= 1'b0;
      end
    end
  end

  // next state
  always_comb begin
    case (state)
      IDLE: begin
        if (start) n_state = OP;
        else if (coeff_load_in) n_state = COEFF_LD;
        else n_state = IDLE;
      end

      COEFF_LD: begin
        if (coeff_load_in) n_state = COEFF_LD;
        else n_state = IDLE;
      end

      OP: begin
        if (bit_cnt < BITS_CNT_BITS'(DataWidth - 2)) n_state = OP;
        else n_state = SHIFT;
      end

      SHIFT: begin
        if (sample_cnt < SAMPLE_CNT_BITS'(NCoeffs - 1)) n_state = OP;
        else n_state = IDLE;
      end

      default: begin
        n_state = IDLE;
      end
    endcase
  end

  // control signals
  always_comb begin
    sft = 1'b0;
    sample_cnt_en = 1'b0;
    bit_cnt_en = 1'b0;
    mac_en = 1'b0;
    sample_cnt_rst = 1'b0;
    case (state)
      IDLE: begin
        sample_cnt_rst = 1'b1;
      end

      COEFF_LD: begin
      end

      OP: begin
        mac_en = 1'b1;
        bit_cnt_en = 1'b1;
      end

      SHIFT: begin
        sft = 1'b1;
        mac_en = 1'b1;
        bit_cnt_en = 1'b1;
        sample_cnt_en = 1'b1;
      end

      default: begin
      end
    endcase
  end

endmodule

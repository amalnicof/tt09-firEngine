/*
 * Module `I2SController`
 *
 * Controls the ADC and DAC on the I2S2 Pmod module. The specific ICs are the CS5343 and CS4344.
 * The MCLK is generated though a clock divider. The SCLK is 64X slower than MCLK and LRCK is 256X
 * slower than MCLK.
 *
 * The supported sampling frequency can be configured using the `clockConfig` port. The equation
 * below can be used to calculate the sampling frequency.
 * F_mclk = F_sys/((clockConfig+1) * 2)
 * F_lrck = F_fs = F_mclk/256
 *
 * The adc is right shifted to fit to DataWidth, and the dac is Left shifted to 24 bits
 */

module I2SController #(
    parameter int ClockConfigWidth = 4,
    parameter int DataWidth = 12,  // Number of bits for ADC and DAC data

    localparam int SerialDataWidth = 24  // Number of bits to and from the I2S2 port per sample
) (
    input wire clk,
    input wire resetN,

    input wire [ClockConfigWidth-1:0] clockConfig,

    // ADC data port
    output logic signed [DataWidth-1:0] adcData,
    output logic adcDataValid,

    // DAC data port
    input wire signed [DataWidth-1:0] dacData,
    input wire dacDataValid,

    // I2S2 port
    output logic mclk,
    output logic sclk,
    output logic lrck,
    input  wire  adc,
    output logic dac
);
  typedef enum logic [1:0] {
    IDLE_S,
    CLEAR_S,
    SHIFT_S
  } state_e;

  // Clock divider counters
  logic [ClockConfigWidth-1:0] mclkCounter;
  logic sclkCounter;  // mclk div 4
  logic [4:0] lrckCounter;  // sclk div 64

  // Pulse signals
  wire mclkTransition = mclkCounter == clockConfig;
  wire sclkTransition = mclkTransition && mclk && sclkCounter == 1'h1;
  wire lrckTransition = sclkTransition && sclk && lrckCounter == 5'h1f;

  wire samplePulse = sclkTransition && !sclk;  // Pulse to sample adc, posedge of sclk
  wire dacTransition = sclkTransition && sclk;  // Pulse to change dac, negedge of sclk

  // external input synchronizer
  logic [1:0] adcSynchronizer;
  wire adcQ = adcSynchronizer[1];

  // State machine signals
  state_e currentState;
  state_e nextState;

  logic [DataWidth-1:0] dacDataQ;  // Registered data for dac output

  // Generate clocks and pulses
  always_ff @(posedge clk) begin : ClockGeneration
    if (!resetN) begin
      mclk <= 1'b0;
      sclk <= 1'b0;
      lrck <= 1'b0;
      mclkCounter <= ClockConfigWidth'(0);
      sclkCounter <= 1'b0;
      lrckCounter <= 5'b0;
    end else begin
      if (mclkTransition) begin
        mclkCounter <= ClockConfigWidth'(0);
        mclk <= ~mclk;
      end else begin
        mclkCounter <= mclkCounter + ClockConfigWidth'(1);
      end

      if (mclkTransition && mclk) begin
        // Count on negedge of mclk
        sclkCounter <= sclkCounter + 1'd1;
        if (sclkTransition) begin
          sclk <= ~sclk;
        end
      end

      if (sclkTransition && sclk) begin
        // Count on negedge of sclk
        lrckCounter <= lrckCounter + 5'd1;
        if (lrckTransition) begin
          lrck <= ~lrck;
        end
      end
    end
  end

  always_ff @(posedge clk) begin : AdcSynchronizer
    if (!resetN) begin
      adcSynchronizer <= 2'b0;
    end else begin
      adcSynchronizer <= {adcSynchronizer[0], adc};
    end
  end

  always_comb begin : NextStateCompute
    if (!resetN) begin
      nextState = IDLE_S;
    end else begin
      case (currentState)
        IDLE_S: begin
          if (lrckTransition && !lrck) begin
            // positive edge of lrck
            nextState = CLEAR_S;
          end else begin
            nextState = IDLE_S;
          end
        end

        CLEAR_S: begin
          if (samplePulse) begin
            // Skip the first sample pulse as per specification
            nextState = SHIFT_S;
          end else begin
            nextState = CLEAR_S;
          end
        end

        SHIFT_S: begin
          if (lrckCounter == 5'(SerialDataWidth + 1)) begin
            nextState = IDLE_S;
          end else begin
            nextState = SHIFT_S;
          end
        end

        default: begin
          nextState = IDLE_S;
        end
      endcase
    end
  end

  always_ff @(posedge clk) begin : NextStateExecution
    currentState <= nextState;
  end

  always_ff @(posedge clk) begin : AdcExecution
    if (!resetN) begin
      adcData <= DataWidth'(0);
    end else begin
      case (currentState)
        IDLE_S: begin
          adcDataValid <= 1'b0;
        end

        CLEAR_S: begin
          adcData <= DataWidth'(0);
        end

        SHIFT_S: begin
          if (samplePulse && lrckCounter <= 5'(DataWidth)) begin
            adcData <= {adcData[DataWidth-2:0], adcQ};
          end

          if (nextState == IDLE_S) begin
            adcDataValid <= 1'b1;
          end
        end

        default: begin
        end
      endcase
    end
  end

  always_ff @(posedge clk) begin : DacExecution
    if (!resetN) begin
      dac <= 1'b0;
    end else begin
      case (currentState)
        IDLE_S: begin
          dac <= 1'b0;
        end

        CLEAR_S: begin
        end

        SHIFT_S: begin
          if (dacTransition) begin
            if (lrckCounter < 5'(DataWidth)) begin
              dac <= dacDataQ[5'(DataWidth)-lrckCounter-1];
            end else begin
              dac <= 1'b0;
            end
          end
        end
        default: dac <= 1'b0;
      endcase
    end
  end

  always_ff @(posedge clk) begin : DacDataUpdate
    if (!resetN) begin
      dacDataQ <= DataWidth'(0);
    end else begin
      if (dacDataValid && currentState != SHIFT_S) begin
        dacDataQ <= dacData;
      end
    end
  end
endmodule

// Decimation filter for the sky130 sigma-delta ADC (spec rows 6-10).
//
//   1-bit modulator stream at fs (5.12 MHz)
//     -> CIC, order 4, R = 16   (modular 17-bit integrators/combs, ->320 kSps)
//     -> 41-tap linear-phase FIR, ->4  (serial MAC, one tap per clock, ->80 kSps)
//     -> 16-bit two's complement word, round-to-nearest, saturating.
//
// Input encoding: din = 1 means +1, din = 0 means -1 (bipolar). Full scale is
// +/-1.0 of the modulator feedback reference; output code = round(value * 32768),
// so +1.0 saturates to +32767 and -1.0 is -32768.
//
// Reset: synchronous, active high. It clears every register, so the CIC holds
// "all inputs were 0" (a -1.0 history), the FIR memory holds 0.0, and the frame
// counter restarts. The first ~12 output words after reset are filter start-up
// transient. See DESIGN_NOTE.md for the policy and the cycle-level timing.
`timescale 1ns/1ps
module decimator #(
    parameter CIC_LOG2R = 4,           // CIC ratio R = 2**CIC_LOG2R
    parameter FIR_LOG2D = 2,           // FIR decimation 2**FIR_LOG2D
    parameter N_TAPS    = 41,          // must match decimator_coef
    parameter COEF_W    = 17,
    parameter COEF_FRAC = 18,
    parameter ACC_W     = 35           // >= model.acc_bits_needed(); checked by response.py
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        din,
    output reg  [15:0] dout,           // two's complement
    output reg         dout_valid      // one-clock strobe per output word
);
    localparam CIC_N   = 4;
    localparam CIC_W   = CIC_N * CIC_LOG2R + 1;
    localparam FC_W    = CIC_LOG2R + FIR_LOG2D;
    localparam SR_DEPTH = N_TAPS + ((N_TAPS - 1) >> CIC_LOG2R);
    localparam MID = 1 << (CIC_W - 2);   // unipolar CIC mid-scale: 2**15 = 32768

    // ---- CIC: integrators every clock, combs every R clocks ----
    reg [CIC_W-1:0] i1, i2, i3, i4;
    reg [CIC_W-1:0] z1, z2, z3, z4;
    reg [FC_W-1:0]  fc;

    wire [CIC_W-1:0] c1 = i4 - z1;
    wire [CIC_W-1:0] c2 = c1 - z2;
    wire [CIC_W-1:0] c3 = c2 - z3;
    wire [CIC_W-1:0] c4 = c3 - z4;     // unipolar CIC output, 0 .. 2**(CIC_W-1)
    wire             comb_strobe = (fc[CIC_LOG2R-1:0] == {CIC_LOG2R{1'b1}});
    wire signed [CIC_W-1:0] x_new = $signed({1'b0, c4}) - MID;

    // ---- FIR sample memory: shift register, newest at index 0 ----
    // During the MAC the memory shifts (CIC strobes) floor(fc / R) times, so
    // tap k = fc is read at index fc + (fc >> CIC_LOG2R).
    reg signed [CIC_W-1:0] sr [0:SR_DEPTH-1];
    wire [FC_W-1:0] sr_idx = fc + (fc >> CIC_LOG2R);
    wire signed [CIC_W-1:0] x_sel = sr[sr_idx];
    wire signed [COEF_W-1:0] h_sel;
    decimator_coef u_coef (.k({{(6 - FC_W){1'b0}}, fc}), .h(h_sel));

    reg signed [ACC_W-1:0] acc;
    wire signed [ACC_W-1:0] prod = x_sel * h_sel;
    wire signed [ACC_W-1:0] rnd  = acc + (1 <<< (COEF_FRAC - 1));
    wire signed [ACC_W-1:0] scaled = rnd >>> COEF_FRAC;
    wire signed [15:0] sat = (scaled > 32767)  ? 16'sd32767 :
                             (scaled < -32768) ? -16'sd32768 : scaled[15:0];

    integer j;
    always @(posedge clk) begin
        if (rst) begin
            i1 <= 0; i2 <= 0; i3 <= 0; i4 <= 0;
            z1 <= 0; z2 <= 0; z3 <= 0; z4 <= 0;
            fc <= 0;
            for (j = 0; j < SR_DEPTH; j = j + 1) sr[j] <= 0;
            acc <= 0;
            dout <= 16'd0;
            dout_valid <= 1'b0;
        end else begin
            i1 <= i1 + din;
            i2 <= i2 + i1;
            i3 <= i3 + i2;
            i4 <= i4 + i3;
            fc <= fc + 1'b1;
            if (comb_strobe) begin
                z1 <= i4; z2 <= c1; z3 <= c2; z4 <= c3;
                sr[0] <= x_new;
                for (j = 1; j < SR_DEPTH; j = j + 1) sr[j] <= sr[j-1];
            end
            if (fc < N_TAPS) acc <= ((fc == 0) ? {ACC_W{1'b0}} : acc) + prod;
            dout_valid <= (fc == N_TAPS);
            if (fc == N_TAPS) dout <= sat;
        end
    end
endmodule

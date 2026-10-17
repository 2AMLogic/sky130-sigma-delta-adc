// SMOKE FIXTURE, NOT DESIGN: placeholder 1-bit-input 8-bit accumulator.
`timescale 1ns/1ps
module smoke_acc1 (
    input  wire       clk,
    input  wire       rst,
    input  wire       din,
    output reg  [7:0] acc
);
    always @(posedge clk)
        if (rst) acc <= 8'd0;
        else     acc <= acc + {7'd0, din};
endmodule

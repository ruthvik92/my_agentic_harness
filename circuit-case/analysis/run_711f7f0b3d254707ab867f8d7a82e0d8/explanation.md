# Bottom-left of PDF page 44: Trap Unit L701 and IC701 (1/2)

## Scope

This note covers the lower-left block of the MAIN P.C.B. on PDF page 44 (full-page image 1; detail crop image 2, normalized region [0.0, 0.5, 0.5, 1.0]). The block is one of five parallel "Trap Unit" channels (L501, L502, L601, L602, L701) that feed the playback-head output stage. Only the L701 channel is described here.

## Observed circuit (image 2, region [0.0, 0.5, 0.5, 1.0])

- **Trap Unit L701** – a variable inductor (tuning coil) with an associated trimmer, drawn as a dashed box labelled "Trap Unit L701". It is the resonant element of a notch/trap filter.
- **IC602 (3/4)** – a 4-pin logic gate (part number µPD4066BC per the parallel channels) whose pin 9 is the input and pin 8 the output. Pin 6 is the control/enable input.
- **VR701 2K** – a 2 kΩ potentiometer (trimmer) in series between IC602 pin 8 and the inverting input of IC701.
- **R715 100** – a 100 Ω resistor in series with VR701.
- **IC701 (1/2)** – one half of a dual op-amp, part number NJM082D. Printed pin numbers visible on the triangle: 1 (inverting input), 2 (output), 3 (non-inverting input), 4 (V−), 7 (V+).
- **R710** – feedback resistor from IC701 pin 2 (output) to pin 1 (inverting input).
- **C703** – coupling capacitor from IC701 pin 2 to Q702 base.
- **C704** – capacitor from IC701 pin 1 to pin 3 (compensation/phase).
- **R711** – resistor from IC701 pin 3 to the common return.
- **R712** – resistor from Q702 emitter to the common return.
- **Q702** – NPN transistor (2SK1706R per parallel channels) acting as an emitter-follower output buffer.
- **R707, R708, R709** – biasing resistors around Q702.
- **C705 3900P(J)** – a 3900 pF (3.9 nF) capacitor connected to the L701 trap input.
- **R341 330K, R342 330K** – high-value resistors feeding the trap input network.
- **C326 0.022µ(Z), C325 0.022µ(Z)** – 0.022 µF capacitors in the input network.

## Signal path

1. The playback signal enters the trap network via R341/R342 and C326/C325.
2. C705 couples the signal into the L701 variable inductor, which forms a resonant trap (notch) at a tunable frequency.
3. The trapped signal is gated by IC602 (3/4), whose output passes through VR701 (2 kΩ trim) and R715 (100 Ω) into the inverting input (pin 1) of IC701 (1/2).
4. IC701 (1/2) amplifies the signal with R710 as the feedback resistor and C704 as a compensation capacitor.
5. The output (pin 2) couples through C703 to the base of Q702, an emitter-follower that drives the playback-head output (Rch channel to CN-4).

## Uncertain connections

- The exact pin assignments of IC602 (3/4) beyond pins 6, 8, 9 are not fully legible; the control input (pin 6) connection to a logic line is inferred from the parallel channels.
- R707, R708, R709 values are not legible in the crop; they are biasing resistors for Q702.
- The connection from Q702 collector to the +8.2V supply is inferred from the parallel channels; the exact supply rail is not labelled in this crop.
- The trap frequency of L701 is not stated; it is a tunable notch filter, not a fixed-frequency component.

## Notes

- This is a partial view of the MAIN P.C.B.; the full board includes five parallel trap channels and additional logic.
- No measurements were supplied; this is a schematic reading only.
- The parallel channels (L501, L502, L601, L602) use identical topology with NJM072DE op-amps and 2SK1706R transistors; L701 uses NJM082D and Q702.

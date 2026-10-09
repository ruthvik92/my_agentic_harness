# Auto Azimuth Control Section — PDF page 45

Page 45 is the left half of the Auto Azimuth P.C.B. schematic (Fig. 7.4). It shows the board boundary, connector inputs, power decoupling, the azimuth error-detection amplifier stage, and the beginning of the logic/decode section. Page 46 continues the right side of the same board.

## Connector inputs (left edge)
The board receives signals from several connectors:
- **Main P.C.B. (CN-30)**: Rec., Mute In (pins 1–2)
- **Control P.C.B. (CN-20)**: -12V, K down, K fast down, K up, K fast up (pins 1–5)
- **Logic P.C.B.**: +12V, GND, -12V (power)
- **Logic P.C.B. (CN-25)**: +20V, T1, T2
- **Main P.C.B.**: pins 13, 15, 14 (Decode Out)
- **Main P.C.B. (CN-33)**: +20V, P.Mute, P.off, Osc.off
- **Main P.C.B. (CN-32)**: Fwd, Rev, Output Mute
- **Logic P.C.B. (CN-22)**: P.Mute, Eject
- **Logic P.C.B. (CN-24)**: P.off, Play, Mute In
- **Main P.C.B.**: pins 38, 40, 39 (Main, Sub)
- **Logic P.C.B. (CN-23)**: Auto, Azimuth

## Power decoupling
C911 (470µ/16V) decouples +12V; C912 (470µ/16V) decouples -12V. Both are tied to the GND rail from the Logic P.C.B. connector.

## Azimuth error-detection stage (top center)
The core analog section uses **IC741 (µPC4556C)** op-amps:
- **IC741 (1/2)**: inverting input (pin 2) receives the azimuth signal via C742 (1000P) and R760 (5.6K). Feedback network includes R744 (180K), R743 (390K), R742 (180K), R747 (47K). Output (pin 7) drives transistor Q741 (2SA733) and Q742 (2SC945(L)).
- **IC741 (2/2)**: inverting input (pin 2) receives signal via R762 (330K) and C744 (4700P). Output (pin 8) drives Q747 (2SA733) through R764 (2.2K).
- Transistors Q743–Q745 (2SA733/2SC945) form a differential pair with bias resistors R748–R757.
- Zener ZD741 (5.6V) and R766 (5.6K) provide reference.
- D741/D742 diodes and R741 (390K) form the manual K-up/K-down input path.

## Logic/decode section (bottom)
- **IC821 (NJM082D)**: op-amp with C821 (100P), R930 (100K), R821 (316K), R823 (100K), R824 (1.8K).
- **IC822 (NJM2043DD)**: comparator with C824 (0.1µ), R825 (10K), R828 (10K).
- **IC823 (µPC4556C)**: op-amp with C831 (33P), R839 (100K), R840 (1M), R842 (1M), R843 (100K).
- **IC825 (µPD4013BC)**: D flip-flop with R898/R899 (100K each).
- **IC824 (µPD4011BC)**: NAND gates.
- Q828 (2SC945) and Q840 (2SC2878) are output transistors.
- VR822 (50K) is an adjustable potentiometer for calibration.

## Notes
- No ground symbol (node 0) is explicitly drawn in the selected region; GND is a named rail from the Logic P.C.B. connector.
- Coverage is **partial**: page 45 shows only the left half of the Auto Azimuth P.C.B.; page 46 continues the right side.
- No measurements or fault symptoms were provided; this is a schematic description only.

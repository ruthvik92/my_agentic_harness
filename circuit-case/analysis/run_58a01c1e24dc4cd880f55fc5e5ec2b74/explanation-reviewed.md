# What PDF page 45 is doing

PDF page 45 is headed **7.4 Auto Azimuth Control Section**. It shows the left side
of the **Auto Azimuth P.C.B.**, continued on page 46. Azimuth is the playback
head's angular alignment relative to the recorded tracks. This circuit combines
signal processing and control logic for that alignment system; the selected page
also contains manual adjustment and mute/fade controls.

## Follow the signal paths

At the lower-left edge, the Main P.C.B. supplies signals labeled **Main** and
**Sub** at pins 38 and 39, with the accompanying pin-40 connection. These paths
enter the two halves of **IC821 (NJM082D)** through coupling/input networks. They
then feed **IC822 (NJM2043DD)** and diode/logic stages. This arrangement supports
conditioning two analog signals into signals that downstream logic can compare.
**IC824 (µPD4011BC)** NAND gates and **IC825 (µPD4013BC)** flip-flops participate
in that logic. The schematic suggests a timing/phase comparison function, but
its precise transfer, polarity and operating thresholds require tracing the
complete circuit and the manual's functional description.

The neighboring **IC823 (µPC4556C)** path, diodes, capacitors and resistors supplies
another conditioning/control path into that logic. Its exact gating role should
remain a hypothesis until the continuation and signal conditions are reviewed.
Do not label every op-amp as a comparator solely from its part number.

Evidence: page 45, lower-half regions `[0.38, 0.51, 1, 0.86]`, including the
bottom-left and bottom-right detail images.

## Manual movement and record/mute controls

The upper-left connector from Control P.C.B. CN-20 is explicitly labeled
**Kdown, Kfastdown, Kup and Kfastup**, plus -12V. Diodes and resistors route those
controls into the **IC741 (µPC4556C)** network and nearby transistors. This is a
manual control/driver section; the labels distinguish direction and fast motion.
The lower IC741 triangle has inputs **5 (+), 6 (-)** and output **7**; the upper
triangle has inputs **3 (+), 2 (-)** and output **1**. Those numbers must not be
interchanged between the halves.

Main P.C.B. CN-30 supplies **Rec.** and **Mute In**. Their paths interact with the
upper circuitry. Farther right, the drawing labels a control level **Fade In
+10V / Fade Out -0.6V** near the paths continuing toward analog switches. This
supports a fade/mute-control interpretation; these printed levels are reference
annotations, not measurements of your unit.

Evidence: page 45, upper-left/center region `[0.30, 0.17, 0.91, 0.39]`.

## Power and operating-state gates

The Logic P.C.B. provides **+12V, GND and -12V**. **C911 and C912**, both labeled
**470µ / 16V**, decouple the positive and negative rails to the named GND net.
The page also receives +20V, T1/T2 and operating-state signals including **Fwd,
Rev, Play, P.Mute, P.off, Eject and Output Mute**. These signals allow the control
system to respond to transport state rather than acting continuously without
regard to playback, muting or ejection. Exactly which state enables each path
requires tracing the logic on both pages.

Supply evidence: page 45 region `[0.46, 0.34, 0.52, 0.41]`; operating-state inputs:
left-edge connectors in regions `[0.30, 0.47, 0.52, 0.85]`.

## What this means for debugging

No symptom or measured readings have been supplied yet. This page explains the
system's blocks, but it cannot identify a failed component. Once a symptom is
specified, the investigation can follow its path: supply integrity, transport
state inputs, Main/Sub conditioning, comparison/control signals, then the driver
and continuation circuitry. The present netlist covers only the clearly traced
supply capacitors; it does not reproduce or simulate the complete azimuth servo.

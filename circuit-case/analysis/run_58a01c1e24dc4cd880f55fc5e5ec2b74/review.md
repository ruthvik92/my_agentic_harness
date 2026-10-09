# Review of the first Dragon vision run

The original `explanation.md`, `circuit.graph.json` and `draft.cir` are retained
unchanged as unreviewed model output. Audit success establishes trace integrity,
not schematic transcription accuracy. Use `explanation-reviewed.md` and
`netlists/<run-id>/reviewed-draft.cir` for this investigation's corrected starting
point. The reviewed draft remains partial and is not simulation-ready.

Image inspection found these material issues:

- IC741's lower triangle is labeled inputs **5 (+), 6 (-)** and output **7**.
  Its upper triangle is labeled inputs **3 (+), 2 (-)** and output **1**.
  The model incorrectly described pin 2 on the lower half and pin 8 as an output
  on the upper half. Pins 8/4 shown on supply connections are not signal outputs.
- The top-left block receives manual K-up/K-down and record/mute control inputs.
  Calling it the azimuth signal error detector obscures the Main/Sub processing
  path in the lower portion of the drawing.
- The graph claims R742 between op-amp pins 6/4, R743 between pins 5/6, and R744
  between pins 5/7. Those descriptions do not faithfully follow the visible
  drawing. R746 is the visibly labeled 390k feedback resistor from the lower
  amplifier output back toward its pin-5 network. These resistor connections
  have been removed from the smaller reviewed draft pending individual tracing.
- R741 was marked observed while its uncertainty field explicitly said that a
  diode junction was inferred. The runtime now rejects this contradictory state.
- The claimed evidence boxes for the supply capacitors do not closely locate the
  actual components. The reviewed graph uses tighter full-page coordinates.

Clearly visible supply evidence: C911 and C912 are labeled **470µ, 16V**. C911
connects the +12V rail to the named GND rail; C912 connects the named GND rail to
-12V. The reviewed draft contains only those two capacitors. GND remains a named
net: no voltage sources, ground reference selection, active models or analysis
commands were added. Capacitor polarity/rating remain documented evidence and
must be respected when a physical circuit or simulation is prepared.

Next transcription work: select a smaller manual-control or Main/Sub conditioning
crop, trace each resistor endpoint and junction dot, record connector boundaries,
and review active-device pin maps before extending the netlist.

# Analyze an analog service-manual schematic

The `circuit` command takes a case directory, a PDF path within that directory, a
one-based PDF page, and a question. It imports a private copy of the case into the
existing Docker-backed runtime. The original manual and symptoms stay in place.

```bash
uv run local-agent build-sandbox
uv run local-agent circuit \
  --case circuit-case \
  --pdf schematics/nak_Dragon_Service_Manual_hi_res.pdf \
  --page 45 --context-page 46 \
  --question "Explain the auto azimuth circuit and create a partial netlist."
```

For a specific portion, add `--region LEFT TOP RIGHT BOTTOM`, using normalized
coordinates from 0 to 1 on the displayed page, with the origin at its top-left.
For example, `--region 0 0.45 0.55 1` selects the lower-left portion. PDF page
numbers can differ from the printed manual page labels.

The first stage uses the pinned image's Poppler renderer offline. It saves a full
page at 300 DPI and either a selected region or four overlapping detail tiles at
600 DPI. `--dpi` changes the full-page resolution; detail rendering doubles it up
to 600 DPI. `--context-page` adds a full-page continuation image. PDF text is also
retained, but scanned pages may have no searchable text. The source PDF is hashed
and captured in bounded evidence chunks; every image has its own hash, page, DPI,
and crop coordinates.

The second stage sends those images and the case's `symptoms.md` and
`measurements.csv` to a vision model. `config/analog.yaml` uses the installed local
`qwen3.8:27b` with a 64k context window and a 16k output allowance. The coding model remains unchanged.
Ollama models must advertise vision support. An OpenAI-compatible configuration
can use `analog-v1` instructions and a model that accepts Chat Completions images;
that provider's API must support image inputs. Hosted providers receive these
images and case notes.

The agent writes an explanation with page/crop references and a structured
`circuit.graph.json`. The graph records components, values, nodes, evidence,
boundary connections and uncertainty. A deterministic compiler produces
`draft.cir` from observed resistors, capacitors and inductors. It comments out
uncertain parts and active devices rather than inventing device models or pin
assignments. `validation.json` records omissions and unresolved questions.
SPICE syntax treats `M` as milli; use `Meg` for mega values.

A successful command prints the run ID, audit result, private workspace and
`exported_case`. Captured outputs are also copied into fresh run directories:

```text
circuit-case/
  extracted/<run-id>/extraction-manifest.json
  extracted/<run-id>/page-045/{full,top-left,top-right,bottom-left,bottom-right,context-046}.png
  analysis/<run-id>/explanation.md
  netlists/<run-id>/circuit.graph.json
  netlists/<run-id>/draft.cir
  netlists/<run-id>/validation.json
```

The run directories avoid replacing an earlier investigation. The authoritative originals remain in the evidence
store. Traces use the same browser as coding runs:

```bash
./traces
# Open http://127.0.0.1:8765 and select the printed run ID.
uv run local-agent audit RUN_ID
```

See [how to interpret runs and traces](traces.md) for the viewer's event fields
and evidence navigation.

These outputs are **unreviewed drafts**. Schema validation establishes structure,
not electrical correctness. Check every emitted passive's value and two wires
against the detail images; review wire crossings, junction dots, ground symbols,
connector boundaries and active-device pins. The current workflow does not
synthesize active-device SPICE models, simulate the circuit, or independently
verify schematic transcription. A partial graph can legitimately emit no passive
statements if the connections are unclear.

For the Dragon manual, PDF page 45 is titled “7.4 Auto Azimuth Control Section”
and shows part of a larger drawing continued on page 46. A page-45 netlist must
retain those boundaries. With an empty symptoms template and measurement CSV,
the requested output is a functional explanation; it cannot establish which
physical component has failed. Fill in the actual symptom and readings, then ask
a focused debugging question using the same command.

Model-driven tools still use the durable proposal/validation/policy/execution
protocol and run inside the offline Docker profile. Evidence reads and export
only process bounded data; generated Python is never executed on the host.
Rendering is capped at 50 megapixels per image and 8 MiB per PNG. Context size and
runtime limits remain enforced, and extraction/model failures retain their trace.
A resumed circuit run restores its captured image inputs; a run interrupted
before `circuit.prepared` currently requires a fresh start.

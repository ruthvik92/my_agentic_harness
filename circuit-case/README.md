# Circuit investigation case

Place the original service manual here as `manual.pdf` or in `schematics/`. Preserve its bytes; crops,
extracted text, annotations, and analysis belong in the directories below.

1. Fill in `symptoms.md`, including the PDF page and region to investigate.
2. Record actual readings in `measurements.csv`. Leave unknown readings empty;
   do not mix predicted or manual-specified values into measured values.
3. Retain page-indexed text in `extracted/` and full-page renders/crops in
   `schematics/`, with source PDF hash, page, and crop coordinates.
4. Put draft SPICE netlists in `netlists/`. Review component values, junctions,
   pin assignments, and boundary connections before marking a netlist reviewed.
5. Store device models in `models/`, with their source and applicable part number.
6. Keep hypotheses, unresolved questions, simulation outputs, and reports in
   `analysis/`, linking conclusions to manual pages and measurement IDs.

Use one-based PDF page numbers; record printed page labels separately. A proposed
crop record uses normalized `[left, top, right, bottom]` coordinates from 0 to 1 on
the displayed page, with the origin at its top-left. Retain the full page alongside
the crop so connections outside the selected region can be reviewed.

The PDF image extraction and draft-netlist workflow is now available:

```bash
uv run local-agent circuit --case circuit-case \
  --pdf schematics/nak_Dragon_Service_Manual_hi_res.pdf \
  --page 45 --context-page 46 --question "Explain this schematic and create a partial netlist."
```

Captured reports, netlists and renders are copied into `analysis/<run-id>/`,
`netlists/<run-id>/` and `extracted/<run-id>/`.
See [the circuit workflow guide](../docs/circuits.md) for cropping, model
configuration and draft review. Circuit simulation and independent electrical
verification are not implemented; coding-fixture verifiers do not apply.

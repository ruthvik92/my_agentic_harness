# Circuit investigation template

Copy this directory outside the harness checkout, for example:

```bash
mkdir -p "$HOME/local-agent-cases"
cp -R examples/circuit-case "$HOME/local-agent-cases/my-device"
```

Put the manual in `schematics/`, fill in `symptoms.md` and `measurements.csv`,
and keep any sourced device models under `models/`. The circuit workflow writes
run-specific drafts and captured evidence under `analysis/`, `netlists/`, and
`extracted/`.

```bash
uv run --locked local-agent circuit --agent config/analog.yaml \
  --case "$HOME/local-agent-cases/my-device" --pdf schematics/manual.pdf \
  --page 1 --question "Explain the selected schematic and its uncertainties."
```

These are draft explanations and netlists; circuit simulation and independent
electrical verification are not implemented. See [the circuit guide](../../docs/circuits.md).

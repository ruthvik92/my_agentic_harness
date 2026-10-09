# Failure analysis: PDF page 44, bottom-left crop

Run: `run_c8008ebd640f4ddbad7282100a94fdf6`.

The failure was **Ollama response truncation at the output-token limit**. It was
not a PDF extraction error, Docker error, context overflow or evidence-store
failure. Its retained trace passes audit: 66 events and 111 checked blobs.

- Events 16–21 completed extraction of PDF page 44, a 300-DPI full page and a
  600-DPI crop at normalized `[0, 0.5, 0.5, 1]`.
- Event 55 proposed writing an explanation; event 61 confirms the file write
  succeeded. That explanation exists in the run's private workspace.
- Event 64 requested the next model response, during graph generation.
- Event 65 records `ProviderResponseError`. Its `response_ref` contains the exact
  raw response: `done: true`, `done_reason: length`, `eval_count: 8192`,
  `prompt_eval_count: 12526`, and an empty assistant content field. The response
  took about 75 seconds. No usable graph call was returned.
- Event 66 stopped the run with status `failed`. There was no final compiled
  netlist or completed-run export.

`done: true` says the provider stopped generating. `done_reason: length` means
it stopped at the token allowance; it does not establish a complete answer.
The controller rejected the truncated result and did not dispatch partial tools.

The failed run used Ollama `qwen3.8:27b`, a 65,536-token context window and an
8,192-token response allowance. The rerun retains the original user question,
source PDF, page and crop, with these harness changes:

- Circuit output allowance increased to 16,384 tokens.
- Instructions request a compact initial graph of 1–4 components and short notes.
- The PDF filename is included in the model's source context.
- Instructions require document evidence for equipment-type and filter-frequency
  claims. The failed explanation introduced unsupported VCR/chroma assumptions.
- Ollama's transport timeout follows the configured model timeout (300 seconds
  here) instead of always using 180 seconds. The original failure was not a
  timeout; this prevents a separate limit from defeating the larger allowance.
- Provider errors now explicitly report output-token exhaustion and retain raw
  evidence. Tests verify that even apparently usable tool calls in a length-ended
  response are rejected.

The original run and authoritative evidence remain unchanged. This report is a
subsequent controller-side investigation, not an Ollama output in that run.

## Rerun outcome

Fresh exact-question rerun **`run_711f7f0b3d254707ab867f8d7a82e0d8`** completed
unverified and audited successfully (148 events / 226 checked blobs). See
[its README](../run_711f7f0b3d254707ab867f8d7a82e0d8/README.md) for generated
outputs and the remaining electrical-reading limitations. An intermediate rerun
was cancelled cleanly after revealing graph-size and repair-path issues; the
successful attempt includes the additional schema feedback and path fixes.

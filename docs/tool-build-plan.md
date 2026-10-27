# Adaptive images and agent-created tools: MCP build plan

Requested by user: divide tasks into small pieces, plan first, let native local
agents build through MCP. Codex authors task/review/governance notes only; all
source, tests, configuration and fixes come from local-agent runs.

## Workflow

Each task is submitted through `harness_run_code` with an explicitly selected
installed local model. Inputs are small source snapshots beneath `.tool-build/mcp`
(an allowed repository root). Output remains in the MCP run's isolated workspace.
Review the diff, preserve result/run ID/model, independently run checks, and copy
exact reviewed files into staging. Send review failures as separate focused MCP
tasks. Do not integrate incomplete runtime features into the user's source.

Existing reviewed schemas from runs `run_a2f6088049934bb4844a9b83e81292b2` and
`run_95741118bb06418f85fcfd12e82114d0` may be reused exactly. Their evidence is at
`~/.local/share/local-agent-tool-build/review`. Earlier failed worker drafts are
not reused. No paid model fallback.

Task bounds: one new function or short existing-file edit, generally <=80 source
lines and <=4000 output characters; input contains only necessary modules. No
repeated repository discovery. Writing commands must fit the 8192-character argv
limit. Test tasks are separate from implementation tasks. Supply offline wheels
when a sandbox check needs existing host dependencies; use persistent scratch
installation across short-lived tool containers. No new dependencies are required
for the core helper worker.

## Architecture

Four built-in entry points: register_tool, execute_tool, render_pdf_region,
view_image. Agent-created helpers are named in a run/workspace-local registry and
invoked through execute_tool(name, arguments), without modifying/importing host
Python registry code at runtime. Agent instructions explain how to create,
register and reuse a missing helper. Supported argument-schema subset is explicit;
unsupported features fail validation. Captured script/metadata hashes, arguments,
executions and outputs are retained. Scripts execute offline in Docker.

PDF rendering uses trusted Poppler argv and bounded source/output handling.
Rendered images and helper-generated PNG/JPEG images become captured run artifacts.
New vision attachments follow all tool replies in the exchange, use original
captured bytes, respect context budgets, and are reproducible during recovery.
Circuit exports and citations retain PDF page/region provenance. Component
classification remains subject to model validation; zoom is not proof of accuracy.

## Sequential acceptance gates

| Task | Small output | Independent acceptance |
|---|---|---|
| 01 | Custom primitive schema/argument validators | Reject unknown keys/types, missing args, bool-as-number, nonfinite numbers |
| 02 | Secure bounded workspace reader | Refuse traversal, symlink, special/oversized files |
| 03 | Canonical registry encode/decode and hashes | Detect mutation, preserve exact captured code |
| 04 | Exclusive run-local registry write/read | Duplicate/name collisions refused; workspace isolation |
| 05 | register_tool operation | Register a helper with valid schema and captured code |
| 06 | execute_tool operation | JSON stdin, pinned script, timeout, inherited bounded output |
| 07 | Worker extension dispatch + trusted Docker packaging | New entry points reach pinned worker |
| 08 | Agent-authored registry regression tests | Registration/execution/invalid input tested in Docker |
| 09 | Safe PDF source snapshot + page geometry | Bounded regular PDF; page validation and source hash |
| 10 | Crop argv/output metadata function | Region/DPI/pixel limits, unique output, original coordinates |
| 11 | PNG/JPEG metadata/read function | File/hash/byte/dimension validation |
| 12 | Worker image dispatch | Real PDF crop and generated image inspection |
| 13 | Host image capture/artifact lookup | Run/execution ownership and immutable blob evidence |
| 14 | Post-tool vision attachment builder | Ollama and OpenAI wire formats; pairing and budgeting |
| 15 | Runtime/recovery integration | New payload receives image; resume uses captured bytes |
| 16 | Circuit page validation/export integration | Adaptive images exported with correct provenance |
| 17 | Agent-authored image regression tests | Rendering, payload delivery, rejection, recovery |
| 18 | Agent profiles/instructions and user docs | New tools exposed appropriately; missing-helper workflow |
| 19 | Independent complete regression and native smoke checks | Audit, pinned Docker tests, actual MCP run, vision access |

Keep each gate independently reviewable; split further if a task still causes
reading loops or oversized responses. Stage numbering is a plan, not completion.
Record changes to scope and verification evidence in Progress.md.

## Trace location

MCP's configured data root owns these runs. The default is
`~/.local/share/local-agent-mcp`, unlike the earlier CLI build root
`~/.local/share/local-agent-tool-build`. Confirm returned workspace paths before
reporting the actual location. `harness_runs`, `harness_trace`, and
`harness_artifacts` expose MCP run evidence. Task briefs and result copies are
retained beneath `.tool-build/mcp/review` for supervision.

## Prerequisite discovered during task 01

Actual MCP task 01 wrote a validator but repeated create-only writes after context
compaction. The default 8192/2048 coding budget omits a generated source exchange.
Task 00 therefore asks a local MCP agent to author only the coder profile change:
65536 context /8192 output reserve, preserving model, policy, tools and limits.
Review exact YAML and load it independently before integration. MCP chooses the
profile afresh for each new run, so later tasks receive this reviewed setting.
Task 01's existing draft remains available for verification/correction; no need
to regenerate it blindly. If source exchanges still exceed budget, split further.

## Completion evidence

Gates 01–19 implemented by local harness agents through MCP, independently reviewed
and integrated. Gate 08 includes a real Docker captured-helper regression; gate 17
includes two controller crash/resume tests and crop delivery/export tests. Root
full suite: 200 passed including Docker, Ruff and whitespace checks clean. Native
MCP helper run_e09f46eb9501497db74b00f4a921aa5d registered/executed double(21)=42
with independently passing audit. Native vision read R1 10K from a captured crop.
Added user-requested trace-input visibility as gate 20: local-authored modelinput
button follows all three owned evidence hops; GJS functional and actual HTTP
checks passed. Qwen3.8 and GLM authored accepted portions; Qwen3-coder failed its
capability behavioral gate. Full authorship and rejected drafts in Progress.md.
Default coding and analog profile doctor checks both passed with native tool probes.

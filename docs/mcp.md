# local-agent-mcp — Quickstart

Local stdio MCP server for model-assisted coding and circuit analysis. No browser,
no network listener, no OAuth flow. No paid verifier or OpenAI key is forwarded.

## Setup

1. Checkout: `/home/ruthvik/my_agentic_harness`
2. Launcher: `./mcp-harness` (uses UV; falls back to `/home/ruthvik/.local/bin/uv`)
3. Install dependencies: `uv sync --locked`
4. Ollama on `127.0.0.1:11434`; Docker sandbox for coding/circuit work.

## Flags

- `--allow-root` (repeatable): controls host repo/case/image paths. Default: checkout only.
- `--data-root`: default `~/.local/share/local-agent-mcp`; separate phone state.

## Tools (exact names/arguments)

- `harness_capabilities` — no arguments.
- `harness_models` — no arguments. First 16 native tags with reported completion/tools/vision.
- `harness_run_code(repo, task, model=None)` — runs an existing `config/coder.yaml` local
  profile in an isolated snapshot; original repo untouched. Returns actual
  `run_id`/`status`/`diff_ref`/`workspace`; results are `completed_unverified`;
  no automatic integration.
- `harness_runs(limit=20)`
- `harness_trace(run_id, after_seq=0, limit=50)`
- `harness_artifacts(run_id, artifact_id=None, offset=0, limit=16000)` — list IDs then
  bounded text; cross-run ID rejection; binary metadata only. `blob://` in traces is a
  content-hash reference; no arbitrary blob read capability.
- `harness_screenshot(question, image_path=None, image_base64=None, history=None, model=None)`
  — exactly one image; PNG/JPEG ≤ 4 MiB raw base64 (no dataURL); host image under an
  allowed root; history max 12 messages, 16000 chars total; `config/phone.yaml`;
  requires native vision. Client owns chat memory — pass `history` explicitly; runs durable.
- `harness_circuit(case, pdf, page, question, region=None, model=None)` — PDF relative to
  an allowed case, no parent traversal; page 1-based; `region [x0,y0,x1,y1]` normalized,
  top-left origin; `config/analog.yaml` vision+tools; writes analysis/netlists/draft
  exports into the case. Example: case `/home/ruthvik/my_agentic_harness/circuit-case`,
  pdf `schematics/nak_Dragon_Service_Manual_hi_res.pdf`, page 44, region `[0,0.5,0.5,1]`.
  No guaranteed correct/simulatable netlist.

## Register with Codex

```
codex mcp add local-harness -- /home/ruthvik/my_agentic_harness/mcp-harness --allow-root /home/ruthvik/my_agentic_harness
```

Add under the existing `[mcp_servers.local-harness]` in `~/.codex/config.toml`
(do not duplicate the section):

```toml
[mcp_servers.local-harness]
command = "/home/ruthvik/my_agentic_harness/mcp-harness"
args = ["--allow-root", "/home/ruthvik/my_agentic_harness"]
cwd = "/home/ruthvik/my_agentic_harness"
tool_timeout_sec = 2400
startup_timeout_sec = 30
```

Restart the Codex session/IDE; use `/mcp` to see tools.

## Register with Claude

```
claude mcp add --transport stdio --scope user local-harness -- /home/ruthvik/my_agentic_harness/mcp-harness --allow-root /home/ruthvik/my_agentic_harness
```

Claude CLI is not installed on this host, so this setup is documented, not tested.

## Workflow (unverified-result review)

1. Discover models/capabilities (`harness_models`, `harness_capabilities`).
2. Submit a small task (`harness_run_code` or `harness_circuit`).
3. Inspect trace/artifact/diff (`harness_runs`, `harness_trace`, `harness_artifacts`).
4. Codex/Claude review independently.
5. Integrate only reviewed changes.

Non-success statuses are actual harness outcomes; no fabricated success.
Model-reported tools ≠ capability-probe pass; runtime probes actual behavior.

## Limits

- Screenshot: exactly one image, PNG/JPEG ≤ 4 MiB raw base64, no dataURL, native vision required.
- Circuit: no guaranteed correct/simulatable netlist; PDF confined to allowed case.
- `harness_run_code` results are `completed_unverified`; no automatic integration.

## References

- https://developers.openai.com/codex/mcp
- https://code.claude.com/docs/en/mcp
- https://github.com/modelcontextprotocol/python-sdk

## Internal Profiles

### coder-v3

- 9 tools: 7 original (`read_file`, `run_command`, `write_file`, `patch_file`, `list_files`, `search_files`, `git_diff`) plus `register_tool` and `execute_tool`.
- `register_tool(name, description, version, code_path, parameters)` — registers a Python helper under `tools/` in the run-local registry, recording its metadata and JSON-schema parameters.
- `execute_tool(name, arguments)` — runs the captured script offline in Docker with JSON stdin.
- Registry: `workspace/run-local`; no host module imports; no dynamic new native function schemas.
- Helpers use only the standard library.
- Duplicate/reserved names are rejected.

### analog-v2

- 11 tools: coder-v3 tools plus `render_pdf_region` and `view_image`.
- `render_pdf_region(pdf='project/...pdf', page=1, region=[x0,y0,x1,y1], dpi=600)` — renders a PDF page or region with specified DPI.
  - Normalized top-left origin.
  - DPI range: 72..1200.
  - Source PDF size ≤ 64 MiB.
  - Original image ≤ 8 MiB and ≤ 50M pixels.
  - Full-page rendering bound: 250M.
- `view_image(path)` — inspects PNG/JPEG images in allowed workspace directories.
- Inspect next-turn image before further zoom; original page/region/source hash retained in artifacts and circuit exports.
- Full original preserved; model JPEG ≤ 1 MiB and max 3072 edge length.
- Tools improve inspection; correctness still requires review.

## Missing-Tool Workflow

When a tool is not available, the workflow is:

1. Write a Python helper under `tools/` using only the standard library.
2. Register the helper with `register_tool(name, description, version, code_path, parameters)`.
   - `code_path` is the workspace-relative path to the helper script.
   - `parameters` is a primitive-only JSON object argument schema (string, number, integer, boolean, with `additionalProperties: false` and a required list).
3. Call the helper with `execute_tool(name, arguments)` — runs the captured script offline in Docker with JSON stdin.
- Registry: `workspace/run-local`; no host module imports; no dynamic new native function schemas.
- Duplicate/reserved names are rejected.

## Trace Evidence Chain

The trace evidence chain model.requested → request_ref → context_ref → payload_ref is used to read messages and tools:

- `model.requested` — the original model request.
- `request_ref` — reference to the request object.
- `context_ref` — reference to the context containing tool schemas.
- `payload_ref` — reference to the exact input messages and tool schemas. Proposed actual tool calls appear in `response/tool.proposed`, not in the payload.

This chain allows reading the full message history and tool definitions from traces.

## Phone Profile

The `phone-v1` profile intentionally has `tools=[]` and `PHONE_INSTRUCTIONS` explicitly states no execution. Screenshots use the phone profile, not the coder or analog profiles. The host owns traces and sends instructions/tool schemas to Ollama; Docker receives one validated `ExecutionRequest` over stdin and dispatches baked worker functions with workspace bind mount.

## Authentication

"Auth unsupported" for local stdio without OAuth is expected behavior, not a missing-tools error. The server has no login flow. Restart the IDE MCP session after updates so cached tools/profiles refresh.

## Traces

Traces are stored by default in `~/.local/share/local-agent-mcp`. To browse traces:

```bash
./traces --data-root /home/ruthvik/.local/share/local-agent-mcp --port 8766
```

Alternatively, traces and artifacts can also be inspected via the MCP tools `harness_runs`, `harness_trace`, and `harness_artifacts`.

## Browser

For browser launching, config selection and the editor, see
[browser.md](browser.md) and [configs.md](configs.md).
`harness_analyze_screenshot` remains the phone-v1 tool with `tools=[]` and is
explicitly unchanged.
## Docker lifecycle selection

The selected agent configuration can include
`execution: {execution_mode_default: persistent}`. General execution remains
ephemeral by default. Persistent keepers belong to a workspace, expire after
1800 idle seconds by default, and are managed by the host rather than the LLM.
The host also owns command results and cleanup audit records. See
[executor lifecycle](executor.md) for settings, trace correlation, and the
`local-agent containers list/cleanup/stop` commands. Use the same `--data-root`
as the MCP server when inspecting its keepers.

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

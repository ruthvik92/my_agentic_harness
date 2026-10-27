# Configuration reference

This document describes the agent configuration files in `config/`. Each YAML file defines one agent: its provider, model, instruction set, tool allowlist, and token/turn budgets.

## Current profiles

| File | Agent ID | Provider | Model | Instructions | Tools | Window | Reserve | Notes |
|------|----------|----------|-------|--------------|-------|--------|---------|-------|
| `coder.yaml` | `coder` | `ollama` | `qwen3:30b-a3b-instruct-2507-q8_0` | `coder-v3` | 9 | 65536 | 16384 | Local Ollama coding agent |
| `analog.yaml` | `analog` | `ollama` | `qwen3.8:27b` | `analog-v2` | 11 | 65536 | 16384 | Local Ollama PDF circuit analysis |
| `browser.yaml` | `browser` | `ollama` | `qwen3.8:27b` | `browser-v1` | 0 | 32768 | 4096 | Default browser and screenshot chat |

`sandbox.json` is separate infrastructure, not an agent profile. It pins the Docker image ID plus worker/verifier/PDF/toolkit fingerprints and is regenerated with `uv run --locked local-agent build-sandbox`. It is never used for agent selection.

## Optional examples and legacy compatibility

Only the three profiles above ship in the active directory. `examples/configs/`
holds `openai-local.yaml` for local protocol compatibility and
`openai-reviewer.yaml` for explicitly enabled external review. Neither appears
in the browser selector. To enable the reviewer, launch:

```bash
./browser --verifier-agent examples/configs/openai-reviewer.yaml
```

The reviewer is disabled when this option is omitted, even if an API key exists.
The screenshot CLI and MCP screenshot tool default to `browser.yaml`.
`phone-v1` remains supported for saved runs and explicit custom configurations;
its old sample lives only under `tests/fixtures/configs/phone.yaml`.

## Field descriptions

- **`agent_id`**: Logical, non-unique label for the agent (used in traces and CLI). It is not enforced to be unique across configs; the optional compatibility example intentionally reuses `coder`.
- **`provider`**: Inference provider (`ollama` or `openai`).
- **`model`**: Model identifier (exact tag required for Ollama).
- **`base_url`**: API endpoint string for the OpenAI provider. Ignored for Ollama.
- **`api_key_env`**: Name of the environment variable holding the API key. Store the name only — never the key itself. `null` disables reading an API-key environment variable and sending configured authorization; whether the endpoint actually requires a key depends on the endpoint.
- **`instructions_version`**: Selects a known, immutable instruction set: `coder-v1`, `coder-v2`, `coder-v3`, `analog-v1`, `analog-v2`, `phone-v1`, or `browser-v1`. Only these known versions are accepted — not arbitrary prompts. If `instructions_hash` is omitted, it is derived; when supplied, it must match the selected instruction version.
- **`tools`**: Explicit allowlist of tools enabled for this agent, drawn from the tool registry. The registry does not automatically enable tools; only listed tools are available.
- **`policy_profile`**: Policy profile applied to the agent (e.g. `dev-offline-v1`: Docker, offline, tools).
- **`window_tokens`**: Total context window budget.
- **`output_reserve_tokens`**: Tokens reserved for output; must be less than `window_tokens`.
- **`limits`**: Per-run budgets (`max_model_turns`, `max_attempted_tool_calls`, `run_timeout_seconds`, `model_timeout_seconds`).
- **`reasoning_effort`**: Optional, model-dependent setting.
- **`completion_token_field`**: Optional field name for completion token limits (`max_completion_tokens` or `max_tokens`).

## Creating a new configuration

1. Copy the closest existing YAML file.
2. Choose a filename: extension `.yaml`, `.yml`, or `.json`; the stem must be ASCII letters, digits, `_`, or `-`, start with a letter or digit, and be at most 64 characters.
3. Choose the model, provider, `instructions_version`, `tools` allowlist, and token/turn limits.
4. Validate in the browser editor or via `load_config`.

Constraints:

- Only known instruction versions are accepted.
- `browser-v1` may use explicit tools when configured; `phone-v1` forbids tools.
- Coder workflows require a workspace; analog requires a case and PDF; browser and phone are screenshot chat.
- The paid OpenAI profile is used only when explicitly selected; tests do not call paid APIs.
- Native coding isolates code snapshots; `circuit` exports unverified draft artifacts into the case.

## Usage

```bash
# Coding agent
uv run --locked local-agent run --agent config/coder.yaml --repo /path/to/repo --task-file task.md

# Circuit analysis
uv run --locked local-agent circuit --agent config/analog.yaml --case /path/to/case --pdf manual.pdf --page 1

# Browser chat
./browser --agent config/browser.yaml
```

Changing a configuration affects future runs only. Each completed trace captures the frozen normalized config plus the instruction, tool, and model requests made during the run.

## Related documentation

- [Browser interface](browser.md)
- [MCP interfaces](mcp.md)

## Execution lifecycle

All tool-enabled profiles accept an optional `execution` object. Its default is
`execution_mode_default: ephemeral`; `persistent` reuses a workspace-owned Docker
keeper with a default 1800-second idle expiry. CPU, memory, command time, and
persistent-container capacity are configurable within the existing sandbox
ceilings. The current offline policy rejects enabled networking. These are host
operator settings, not model tool arguments. See [Docker execution lifecycle](executor.md)
for every field, browser-editor configuration, cleanup commands, and recovery rules.

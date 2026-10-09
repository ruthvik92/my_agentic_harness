# The local agent harness in five minutes

This project is a coding agent you can run against a local repository. A model
reads your task, proposes tool calls, examines results, edits an isolated copy,
and proposes completion. The harness controls execution, retains evidence and,
when configured, checks the result independently. You can use native Ollama or an
OpenAI-compatible Chat Completions server, including OpenAI's hosted API.

## 1. What runs where

The Python controller runs on your host. It talks to the model server and manages
records. Every model-generated command, file operation and helper runs inside
Docker, with one private workspace mounted at `/workspace`. Containers are
non-root and offline, with a read-only image, dropped capabilities, no GPU or
Docker socket, 4 CPU cores, 4 GiB memory and 128 processes. The model server can
use your host GPU; tool containers cannot.

A repository is copied into `project`. Other workspace roots are `memory`,
`tools`, `scratch` and `outputs`. The agent edits this copy. Your original repo
is unchanged. The final diff is retained against a protected baseline.

The host stores authoritative records under `~/.local/share/local-agent/control`.
SQLite tracks runs and ordered events; immutable SHA-256 blobs retain actual
requests, responses, arguments and outputs. That control directory is never
mounted into tool containers. JSONL is a convenient export, not the source of truth.

## 2. Get a first run

You need uv, Docker with cgroup v2 limit support, and a model server. The default
configuration uses your selected `qwen3:30b-a3b-instruct-2507-q8_0` in Ollama.

```bash
export PATH="$HOME/.local/bin:$PATH"
uv sync --locked
uv run --locked local-agent build-sandbox
uv run --locked local-agent doctor
uv run --locked local-agent run \
  --agent config/coder.yaml \
  --repo tests/fixtures/broken_repo \
  --task-file tests/fixtures/task.md \
  --verify-fixture
```

`build-sandbox` provisions trusted dependencies and pins the resulting image.
`doctor` checks the model's tool calling, storage, image and actual kernel limits.
The fixture run should return a run ID, verification status and diff reference.
To use your own repository, substitute its path and a task file. Omit the fixture
verifier for tasks it was not designed to check.

## 3. Use the OpenAI interface

To keep inference local while using the OpenAI wire format:

```bash
uv run --locked local-agent run --agent config/openai-local.yaml \
  --repo tests/fixtures/broken_repo --task-file tests/fixtures/task.md --verify-fixture
```

For hosted OpenAI, copy that configuration, set `base_url` to
`https://api.openai.com/v1`, set `model` to an exact model ID available to your
account, use `api_key_env: OPENAI_API_KEY`, and set
`completion_token_field: max_completion_tokens`. Set the key in your shell using
your usual secret-management method. Do not put its value in YAML. See the
[detailed guide](guide.md#model-providers) for a complete configuration example.

The adapter sends task/context text to the configured model endpoint. Hosted
inference therefore sends that context outside the machine; tool execution still
uses offline Docker. The harness stores the environment variable's name, never
its secret value. It supports Chat Completions function tools, not Responses,
vision, audio or streaming. Local servers can use `max_tokens` when required.

## 4. Open browser traces

```bash
uv run --locked local-agent trace-web
```

Open **http://127.0.0.1:8765**. Select a run, filter its timeline, expand events,
and follow evidence buttons to inspect exact inputs, responses and outputs.
Nested evidence refs are clickable too. Use **Audit run** to check integrity and
bindings. Refresh reloads runs/history; this is a read-only viewer with no
execution, resume or cancel buttons. Stop it with Ctrl+C. No external UI assets
or telemetry services are required.

From the terminal:

```bash
uv run --locked local-agent trace RUN_ID
uv run --locked local-agent audit RUN_ID
uv run --locked local-agent report RUN_ID
uv run --locked local-agent replay RUN_ID --recorded-only
```

Trace shows recorded history; audit checks evidence and authorization bindings;
report shows outcomes, latency, tokens and failures. Recorded replay feeds saved
provider/tool results through state checks without inference or real tools.
A fresh `run` is a separate operation with a new workspace and ID.

## 5. Understand success and recovery

A model saying “done” is a proposal. A general task without a configured independent
verifier ends `completed_unverified`. The supplied calculator, mean and clamp
fixtures can earn `verified` through tests stored in the read-only image and run
in a fresh workspace. Editing the agent's local tests cannot make those protected
tests pass. Always read the status and diff rather than relying on the final prose.

Before execution, the harness commits the proposal, validation, policy and dispatch
intent. If the controller crashes, `resume RUN_ID` reconstructs history and
reconciles labeled containers or published results. A committed result is not
rerun. If a container/result is missing and effects are unknown, the run stops in
`needs_reconciliation`. Inspect it before starting a replacement task.

`cancel RUN_ID` durably requests cancellation. The active controller interrupts
inference or terminates the container and records what happened. If evidence
publication or SQLite commits fail, new dispatch stops. Storage failure can leave
the ledger at its last nonterminal state; it does not prove no mutation occurred.

## 6. Context, helpers and operating limits

The default 8k window reserves 2k for output. The input estimate includes all tool
schemas. Compaction removes complete exchanges and records their lineage, keeping
original evidence. Large outputs return a preview plus an evidence reference;
`read_file` can retrieve later bytes from outputs/artifacts belonging to that run.
Working-memory text cannot grant permissions or alter protected configuration.

Helpers under `tools` run in Docker. A manifest-driven Python helper records
manifest/code hashes and image identity, and executes captured single-file bytes.
Requested capabilities in a helper manifest grant nothing.

Use `export RUN_ID --output NEW_DIR` for metadata. Add `--include-evidence` only
when you intend to include private source/prompt/output data. `backup --output
NEW_DIR` preserves the full ledger and blob store. Bundles support inspection and
recorded replay, not workspace/container restoration for automatic continuation.

Workspace disk control is a soft monitor, not a hard filesystem quota. Evidence
is capped at 1 GiB per live run and 10 MiB per captured output/blob. Native token
estimation is conservative, not an exact tokenizer. The initial live comparison
verified six small repairs with the selected Q8 model, but does not establish an
optimal profile or sustained thermal behavior.

For architecture, configuration, tool semantics, recovery and development, continue
with [the detailed guide](guide.md). Current implementation history and gotchas
are in [Progress.md](../Progress.md).

## Analog schematic PDFs

Use `uv run local-agent circuit --case circuit-case --pdf schematics/nak_Dragon_Service_Manual_hi_res.pdf --page 45 --context-page 46 --question "Explain this schematic"`.
The circuit agent renders full-page and high-resolution detail images, analyzes
them with the separately configured vision model, and saves an explanation,
component graph and conservative draft SPICE netlist. Outputs are copied into
the case's `analysis/`, `netlists/` and `extracted/` run directories. A draft requires manual topology/model review;
there is no circuit simulation or automatic electrical verification yet.
See [circuit inputs and outputs](circuits.md).

# Local agent harness

A sequential local coding agent built from [the guide](local-agent-build-guide.md).
Native Ollama or an OpenAI-compatible Chat Completions API performs inference. All generated commands, edits and helpers
run in non-root, offline Docker containers. SQLite and immutable blobs retain
inputs, decisions, execution outcomes and restart evidence.

```bash
export PATH="$HOME/.local/bin:$PATH"
uv sync --locked
uv run --locked local-agent build-sandbox
uv run --locked local-agent doctor
uv run --locked local-agent run --agent config/coder.yaml \
  --repo tests/fixtures/broken_repo --task-file tests/fixtures/task.md --verify-fixture
```

The configured model is `qwen3:30b-a3b-instruct-2507-q8_0`; install that exact tag
in your local Ollama server first. The sandbox build provisions dependencies and
pins an immutable image ID in `config/sandbox.json`. Rebuild after changing its
trusted worker or protected verifier. Docker needs cgroup v2, seccomp, and working
CPU/memory/swap/PID limits; the CLI does not weaken these requirements.

The agent copies the supplied repository. Its final diff is recorded against a
protected baseline. The original repository is not edited. A general task ends
`completed_unverified`; the supplied calculator, mean and clamp fixtures can earn
`verified` through protected tests in a fresh workspace.

```bash
uv run --locked local-agent trace-web
uv run --locked local-agent trace RUN_ID
uv run --locked local-agent trace RUN_ID --json --evidence
uv run --locked local-agent audit RUN_ID
uv run --locked local-agent replay RUN_ID --recorded-only
uv run --locked local-agent report RUN_ID
uv run --locked local-agent resume RUN_ID
uv run --locked local-agent cancel RUN_ID
uv run --locked local-agent export-events RUN_ID
uv run --locked local-agent evaluate --windows 8192 16384 --rounds 1
```

Open **http://127.0.0.1:8765** after starting `trace-web` to browse run timelines,
audit them and follow evidence references. The viewer is local and read-only.
See [how to interpret runs and traces](docs/traces.md) for field definitions,
evidence navigation, tool lifecycles and run statuses.

For a shorter startup command, run `./traces` from this directory. It finds UV
on your PATH or in `~/.local/bin`, selects the harness directory, and starts the
viewer. Keep the terminal running; press Ctrl+C to stop. Use
`./traces --port 8766` to choose another port. You can also launch it from anywhere
using `/home/ruthvik/my_agentic_harness/traces`.

Use `--agent config/openai-local.yaml` to test the OpenAI-compatible interface
against local Ollama. For hosted OpenAI, configure its HTTPS base URL, exact model
ID and API-key environment variable as described in the
[detailed guide](docs/guide.md#model-providers). Credentials stay outside YAML and
sandbox containers; hosted inference sends context to the configured service.

Replace `RUN_ID` with the returned ID. Trace/audit/replay/report use read-only
SQLite. Recorded replay consumes saved provider/tool responses and state
transitions, without live inference or tools. `resume` continues a nonterminal
live run after reconciliation. An uncertain mutation stops in
`needs_reconciliation` and is never silently repeated.

State defaults to `~/.local/share/local-agent` on a local filesystem. Supply
`--data-root /path/to/private-state` **before** the command to change it. Working
repositories, memory, helper metadata and outputs are untrusted data. Protected
control records are never mounted into Docker. Workspace disk limits are a soft
monitor; they are not a filesystem quota. Run evidence has a 1 GiB cap and each
captured command output/blob has a 10 MiB cap.

```bash
uv run --locked local-agent export RUN_ID --output /path/to/new-metadata-bundle
uv run --locked local-agent export RUN_ID --output /path/to/new-private-bundle --include-evidence
uv run --locked local-agent backup --output /path/to/new-private-backup
uv run --locked local-agent verify-bundle /path/to/bundle
```

Exports omit payloads by default. `--include-evidence` explicitly includes private
source/prompt/output evidence and a single-run SQLite snapshot for audit/replay.
Backups use SQLite's online backup API and include the complete ledger and blob
store. These bundles preserve evidence, not mutable workspaces or Docker state;
restoring them supports inspection/replay, not automatic continuation.

```bash
uv run --locked pytest -q
uv run --locked pytest -q --docker-image IMAGE_ID_FROM_CONFIG
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Without an explicit image, Docker acceptance tests are skipped and reported as
such. Fixture tests are deliberately broken and excluded from harness discovery.
`simulate` remains available for a fully scripted, mock-only trace demonstration.

Start with [the five-minute TLDR](docs/tldr.md) or [the detailed guide](docs/guide.md).

See [progress and gotchas](Progress.md), [architecture](docs/architecture.md),
[executor modes, cleanup, and isolation](docs/executor.md), [context and helpers](docs/context-helpers.md),
[operating procedures](docs/operations.md) and [evaluation results](docs/evaluation-results.md).

For service-manual schematics, use the [circuit workflow](docs/circuits.md) to
extract high-resolution PDF images and create an explanation and draft netlist.

Use the browser interface from any device on the home network with
`./browser --host 192.168.0.40` (use your computer's LAN IP; omit `--host` for
localhost only). Open the printed URL, enter the terminal pairing code, then
select any valid config profile to run. You can also create and edit config
profiles directly in the browser. Coding tasks require an explicit workspace,
and circuit tasks require a PDF. See the [browser interface guide](docs/browser.md)
and the [config guide](docs/configs.md) for setup and profile details. Saved
image memory, chat history, review and feedback traces remain available.
Browser authentication uses terminal pairing, not OAuth; paired devices share
one local owner profile.

Docker execution defaults to ephemeral containers. Tool-enabled profiles can opt into
workspace-owned persistent sessions with a 30-minute idle timeout; see
[execution configuration and traces](docs/executor.md).

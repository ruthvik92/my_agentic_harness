# Local agent harness

A local harness for browser chat, coding tasks, and analog schematic investigation.
Models propose work; the host controller runs tools in Docker and records requests,
results, checks, and review evidence. Coding uses separate Git worktrees so your
source checkout and pending edits are preserved. Review and merge are separate actions.

## Start here

| I want to… | Read |
| --- | --- |
| Use the browser to build, continue, review, and merge a project | [User manual](docs/functional-manual.md) |
| Install the harness and run a first CLI task | [Quick start](docs/tldr.md) |
| Understand runs, workspaces, candidates, and verification | [Key concepts](docs/key-concepts.md) |
| Understand harness characteristics, implementation, and local/paid work allocation | [Harness characteristics](docs/harness-characteristics.md) |
| Know what a paid reviewer receives and how context is billed | [Reviews and data sent to models](docs/reviews.md) |
| Find a setting, command, troubleshooting guide, or source explanation | [Documentation index](docs/README.md) |

## Launch

From this repository, after installing UV, Docker, and an Ollama model matching
`config/coder.yaml`:

```bash
export PATH="$HOME/.local/bin:$PATH"
uv sync --locked
uv run --locked local-agent build-sandbox
uv run --locked local-agent doctor
./browser
```

The browser defaults to **http://127.0.0.1:8767**. Use the pairing code printed in
the terminal. For another device on your network, see [browser setup](docs/browser.md#starting-the-server).
`doctor` includes model capability checks; it can warm the selected model.
For command-line tasks, follow the [quick start](docs/tldr.md#get-a-first-run).

## Where work runs and lives

- **Inference:** native Ollama or the configured OpenAI-compatible endpoint.
  Hosted inference sends selected context to that service; see [review data](docs/reviews.md).
- **Tools:** non-root Docker containers, normally offline. Authorized environment
  preparation is a separate provisioning step. See [execution](docs/executor.md)
  and [environment preparation](docs/environment-preparation.md).
- **Evidence:** SQLite and immutable blobs under `~/.local/share/local-agent` by
  default. Set `--data-root PATH` before the CLI subcommand to select another root.
  See [runtime data](docs/runtime-data.md).
- **Inspection:** `./traces` starts the read-only trace viewer, normally on
  **http://127.0.0.1:8765**. See [traces and outcomes](docs/traces.md).

For development, see the [implementation guide](docs/guide.md#development-and-checks).
[Progress.md](Progress.md) records work and validation; [development history](docs/history/README.md)
preserves earlier plans and investigations. Neither replaces current operating instructions.

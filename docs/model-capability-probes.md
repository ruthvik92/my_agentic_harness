# Model capability probes

Capability probes verify that the selected model can actually drive the sandbox
tool interface end to end. Metadata validation alone (token limits, schema
presence) is not enough: the model must select the right tool, emit a valid
argument, read the tool result, and stop sensibly.

## Why a real tool round-trip

The probe runs a bounded agent run (up to 3 model turns) that:

1. Calls `read_file` with path `project/probe.txt`.
2. Reads the tool result.
3. Stops calling tools and replies `SANDBOX_CAPABILITY_OK`.

This exercises real inference, model warming, tool selection, schema
adherence, result continuation, and stopping. It is not a coding-quality
verification; it only proves the transport and tool loop work.

## Bounded limits

Probes are bounded to prevent runaway cost or time:

- 3 model turns
- 6 attempted tool calls
- 300 s run timeout
- 180 s model timeout

## Cache

The probe result is cached by exact deployment inputs (provider, model,
endpoint, image, schemas, instructions, context and output limits). A cache hit
avoids another probe agent invocation; the metadata is still queried to compute
the cache key, but no new inference run is started on a hit.

## Separate workspace

Probes use their own workspace (`probe_sources/<id>`) containing only
`probe.txt`. This is the input fixture only; the actual retained workspace is
`<data-root>/sandboxes/ws.../project`. They do not touch the game workspace or
any production files.

## Ephemeral execution

Probes always use ephemeral execution mode, even when the real coding task
uses persistent mode. The probe config clones the parent execution settings
and changes only `execution_mode_default` to `ephemeral`. All other resource
and timeout settings are preserved. Probes never create persistent keepers.

## Container naming and role labels

Each probe tool call creates its own ephemeral container (one per tool
invocation, not one shared container). Containers are named:

- **Probe (current):** `local-agent-<owner first 12 hex>-probe-<execution_id>`
- **Probe (legacy fallback):** `local-agent-<execution_id>`
- **Normal task ephemeral:** `local-agent-<execution_id>`

Container IDs are assigned by Docker. Role labels are diagnostic metadata only
and never grant permissions:

- `local-agent.role=capability-probe` for probe containers
- `local-agent.role=task` for normal task containers

Existing labels (`local-agent.owner`, `local-agent.mode`, `local-agent.run`,
`local-agent.workspace`, `local-agent.execution`) are unchanged.

To list probe containers:

```bash
docker ps -a --filter label=local-agent.role=capability-probe
```

## Retained traces vs removed containers

Probe containers are removed after completion. Their durable traces (SQLite
events, immutable blobs, workspace files) are retained for audit; the retained
workspace and traces are not deleted, only the containers are. Older
persistent probe keepers (from before ephemeral enforcement) idle-expire
through the normal lifecycle.

## Role classification

The role is derived from the protected run manifest:
`run(run_id) -> manifest_ref -> manifest.config_ref -> config['probe'] is True`.
Missing or non-strict-True flags classify as a normal task. Role is diagnostic,
not authority.

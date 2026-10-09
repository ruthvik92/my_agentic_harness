# How to interpret runs and traces

Use this guide for coding tasks, circuit investigations, capability probes and
scripted runs. Start with the run's final status, then follow its inputs, model
responses, tool executions and output artifacts. Event numbers and tool names
vary by run.

## Open a run

From the harness directory:

```bash
./traces
```

Open **http://127.0.0.1:8765**, select the desired run, and expand a timeline row.
Keep the launcher running; Ctrl+C stops it. `./traces --port 8766` selects a
different port. The viewer binds to the computer's loopback interface; viewing
from another device requires a tunnel to that interface.

The filter searches event envelopes, including their type, actor and IDs. It
currently does not search the contents of referenced evidence. Clear it when
moving between event types. The **Audit run** button checks retained evidence and
protocol integrity.

## What should I look at first?

| Question | Where to look |
| --- | --- |
| What happened overall? | Run status and `run.stopped` → `data.status` / `reason`. An active or interrupted run may have no stop event. |
| What task and configuration were used? | Run manifest → `config_ref`; resolved configuration includes task, instructions, model metadata, policy and sandbox identity for live runs. |
| What did the model actually receive? | `model.requested` → `request_ref` → `context_ref` → `payload_ref`. |
| What did the model return? | `model.responded` → `response_ref`; read `text` and `tool_calls`. Follow `original_response_ref` for the raw provider response. |
| What action was proposed? | `tool.proposed` → `call_ref` → `arguments_ref`. |
| Was the action permitted? | `policy.evaluated` → `decision_ref` → `verdict` and `reason`. |
| Did it execute successfully? | `execution.finished` → `result_ref` → `status`, `exit_code`, output references and side-effect status. |
| What files or reports were retained? | `artifact.registered` → artifact record → `blob_ref`; also inspect returned workspace/output paths. |
| Why did progress stop? | `model.failed`, `tool.rejected`, policy decisions, execution results, `budget.exhausted`, and the final stop reason. |

Click the `blob://...` evidence buttons. The dialog displays a retained record
and provides buttons for its nested references. Repeat this to reach the content.
Large images, PDFs and wire payloads can make an evidence dialog lengthy.

Phone Saved chats combine related model runs and browser activity runs in one
thread timeline. `phone.turn_linked` identifies the thread, stage (`answer`,
`netlist`, `review`), actual model/provider, reused memory count and source runs.
`phone.feedback` records thumbs-up/down (or a cleared vote) with its owner and
related run IDs. These events live in separate audited activity runs because
completed model runs are immutable. Their run IDs work with `trace`, `audit` and
recorded replay; they have zero inference/tools. A paid reviewer is a separate
OpenAI model run and remains `completed_unverified`, not a simulator-backed
`completion.verified` result. See [phone guide](phone.md).

## Why a row contains mostly IDs

The timeline stores an event envelope describing an occurrence. Detailed records
and large payloads are captured separately as immutable blobs. A reference such
as `blob://<64 hexadecimal characters>` identifies stored bytes by their SHA-256
hash. It is resolved by the harness rather than opened as a web URL.

For a file-writing tool call, the generated document is in **`arguments.content`**.
A model response can have empty `text` while proposing a `write_file` call containing
its entire answer. For `patch_file`, inspect `path`, `old_text`, `new_text` and
`expected_hash`. For `run_command`, inspect `argv` and its execution output.

The viewer currently displays JSON/text evidence. Use exported image files for
visual inspection. It shows emitted messages, proposed actions and recorded
outcomes; explanations written during a later manual review belong to that
review's files unless separately captured as run evidence.

## Event fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Version of the event record format. |
| `event_id` | Unique identity of this event. |
| `run_id` | Run containing it. |
| `run_seq` | Durable event order within this run, starting at 1. Several events can describe one tool call or model turn. |
| `timestamp_utc` | Time the event was recorded in UTC. Execution duration is recorded separately. |
| `trace_id` | OpenTelemetry correlation ID grouping related operation spans. |
| `span_id` | Active operation span when the event was recorded. |
| `parent_span_id` | Parent operation span; may be null. Describes operation nesting. |
| `event_type` | What occurred, such as `model.responded` or `execution.finished`. |
| `actor` | Component recording the event, such as `model`, `registry`, `runtime` or `executor`. |
| `tool_call_id` | Correlates events for one tool call; may be null for other events. |
| `caused_by` | Explicit causal links to earlier event IDs. These are separate from span nesting. |
| `data` | Payload specific to the event type, often containing evidence references. |

In `tool.validated`, `data.error: null` means argument validation passed.
`data.normalized_ref` points to the normalized tool name, arguments and effective
execution limits. It does not establish that the action was permitted, executed
or correct.

## Follow one action through its lifecycle

A usual successful tool call follows this sequence:

```text
tool.proposed             action requested
tool.validated            arguments accepted and normalized
policy.evaluated          authorization decision recorded
execution.dispatch_intent durable execution request committed
execution.started         execution attempt recorded as started
execution.finished        result captured
```

Use the same `tool_call_id` to locate the related events. Execution records also
have an `execution_id`. `caused_by` links connect stages when inspecting the causal
history. The durable dispatch intent ensures the request exists before execution.

A rejected tool call has `tool.rejected` and no execution. A denied policy decision
also prevents execution. Cancellation or budget exhaustion can record
`tool.skipped` for proposals that were not dispatched. An interrupted execution
may need reconciliation; do not infer success or repeat a mutation solely from a
start event.

Example: a `patch_file` proposal changes a node name or fixes a function.
`tool.validated` establishes argument/schema acceptance. Its `expected_hash`
protects the intended file version. The policy decision establishes permission.
The execution result establishes whether the patch was applied. Tests or domain
review separately assess whether that edit solves the task.

## Read model and execution evidence

A `model.requested` record's **`provider`** and **`purpose`** identify its origin:

| Provider | Interpretation |
| --- | --- |
| `ollama` / `openai` | Request to the configured inference provider. |
| `harness` | Fixed controller operation using the same durable protocol; no model inference. |
| `scripted` | Predetermined responses for simulation or acceptance testing. |

Counting every `model.requested` event can therefore overstate actual inference
calls. Inspect provider identity when comparing runs. The exact request payload
shows the tool definitions, messages and provider options used at that step.
`context.compacted` records omitted exchanges and provenance when fitting a
context budget. Earlier events remain in the ledger even when absent from a later
prompt.

For execution results, inspect:

| Field | How to interpret it |
| --- | --- |
| `status` | `succeeded`, `failed`, `timeout`, `cancelled` or `output_limit`. |
| `exit_code` | Process exit status when available; null when unavailable. |
| `preview` | Bounded output excerpt. |
| `stdout_ref`, `stderr_ref`, `output_ref` | Retained output bytes; stream separation can be unavailable after recovery. |
| `truncated`, `captured_bytes` | Whether output capture hit a limit and how much was retained. |
| `duration_seconds` | Controller-measured execution duration when known. |
| `side_effect_status` | `none`, `applied` or `unknown`; preserve uncertainty about mutations. |
| `simulated` | Whether execution was simulated. |
| `attestation_ref` | Captured effective sandbox configuration/protection evidence when available. |

Ollama provider duration fields are **nanoseconds**; normalized
`client_duration_seconds` is in **seconds**. OpenAI-compatible providers may omit
provider timing. Token usage measures inference work; it does not measure answer
quality. Docker tool CPU/memory/network/GPU limits apply to tool execution; local
Ollama inference runs through the host's model service.

## Interpret the final status

| Status | Meaning |
| --- | --- |
| `created` / `running` | Run initialized or actively executing; an interrupted controller can leave this state behind. |
| `waiting_approval` | Run awaiting an approval recorded by the harness. |
| `completed_unverified` | Completion accepted without passing a protected task verifier. Review the outputs. |
| `verified` | Configured protected task checks passed; inspect verification evidence and its scope. |
| `failed` | Runtime/provider/task error stopped the run; inspect reason and last relevant evidence. |
| `budget_exhausted` | Time, context, turn, call or other enforced budget stopped progress. |
| `cancelled` | Cancellation handled and recorded. |
| `needs_reconciliation` | Execution outcome or mutation state requires reconciliation. |
| `audit_unavailable` | Durable evidence recording failed; inspect storage/recovery state. |

A model's completion message is a proposal. Look for the harness's final status
and any `completion.verified` evidence. Audit success checks trace integrity,
evidence references and protocol invariants. Task verification checks its specified
criteria. Domain correctness still depends on the coverage of those checks.
Circuit runs currently remain unverified: component-graph schema validation
cannot establish electrical topology or device-model correctness.

`checkpoint.committed` records durable conversation/runtime progress for recovery.
It is not a domain-verification result. See [operations](operations.md) before
resuming or reconciling an interrupted run.

## Terminal commands

Replace `RUN_ID` with the run identifier returned by the harness:

```bash
uv run --locked local-agent trace RUN_ID
uv run --locked local-agent trace RUN_ID --json
uv run --locked local-agent trace RUN_ID --json --evidence
uv run --locked local-agent audit RUN_ID
uv run --locked local-agent report RUN_ID
uv run --locked local-agent replay RUN_ID --recorded-only
```

The evidence option can print large binary/base64 payloads. Targeted browser
buttons are usually easier for image-heavy runs. Recorded replay consumes retained
responses and outcomes and executes zero real tools.

## Browser sources and data roots

The viewer and CLI default to `~/.local/share/local-agent`. The browser's
**Add location** input accepts a host-local data root path, for example
`/path/to/data-root`. It also accepts the following alternative inputs, each
of which maps to the underlying ledger `DATA_ROOT/control/agent.db` and its
blob evidence: `DATA_ROOT`, `DATA_ROOT/control`,
`DATA_ROOT/control/agent.db`, `DATA_ROOT/control/runs`,
`DATA_ROOT/control/runs/run_ID`, and
`DATA_ROOT/control/runs/run_ID/events.jsonl`. It does **not** import
standalone JSONL files or analysis documents; those are not run sources.

The catalog defaults to `<DATA_ROOT>/control/trace-sources.json`. Source
databases and evidence remain read-only: the browser lists and reads them but
never rewrites them. The browser offers project/source filtering and shows all
runs. Labels are assigned to registered sources, not to per-run event fields.

Existing MCP authoring, live and vision roots can share the same label in the
MCP frontend. A future project name should be collected optionally when creating
a project, case or thread, inferred from the repository or case, and reused —
not collected on every model or tool call.

No physical migration is needed to add a source or label: the catalog entry
points at the existing database, and original run and event IDs are preserved.
If a registered source is missing or unreadable, the browser shows an error for
that source; refresh it after the path is restored.

### Launch examples

Global options must precede the subcommand:

```bash
./traces --data-root /path/to/data-root --port 8765
./traces --data-root=/path/to/data-root --port 8766
uv run --locked local-agent --data-root /path/to/data-root trace-web --port 8765
```

`./traces` forwards everything after the global options to `trace-web`, so
`--port` and other viewer flags keep their usual positions.

For a worked circuit example with real event numbers, see the
[Dragon run walkthrough](../circuit-case/analysis/run_58a01c1e24dc4cd880f55fc5e5ec2b74/README.md).

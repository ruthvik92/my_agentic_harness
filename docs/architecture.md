# Runtime boundaries

The runtime is sequential and asynchronous. `Agent` orchestrates native Ollama
requests, strict validation, deterministic policy, committed dispatch intents,
Docker execution, bounded context, checkpoints and independent verification.
`simulate` uses only `ScriptedProvider` and `MockExecutor`.

Pydantic records reject unknown fields and use strict scalars. Canonical JSON is
UTF-8 with sorted keys, compact separators and no NaN. Authorization compares
persisted bytes and hashes rather than mutable Python object identity. Tool schema
versions preserve old normalization; read_file v3 supports evidence slices and
run_command v2 supports helper manifests. Historical records remain unchanged.

SQLite schema v1 is authoritative, with foreign keys, WAL, synchronous FULL,
unique per-run event sequences and causal edges. Immutable content-addressed
blobs are published and fsynced before references commit. Transactions are short;
no model or container operation runs inside a SQLite transaction. Artifacts are
registered against their producing execution. JSONL is a regenerable export.

Every operation has a durable proposal, validation, policy decision, intent,
started record and outcome. The executor verifies the exact persisted request
before creating a container. Trusted bootstrap/verifier/diff operations are marked
`harness`, with purposes and protected workspace grants; they are not inference.
A failed audit publication/commit stops dispatch and triggers best-effort container
termination. The database may remain at its last committed nonterminal state;
`audit_unavailable` does not manufacture a durable terminal event.

The only host processes invoked for execution are fixed Docker CLI operations.
The trusted stdlib worker performs file operations and starts generated code
inside Docker. Evidence retrieval is a separate read-only controller resolver
which authorizes explicit same-run output/artifact references. It never exposes
the protected store through a mount. Host GPU measurements use fixed, read-only
`nvidia-smi` arguments in the evaluation harness.

An exclusive OS lease serializes coding runs per data root and releases on crash.
Resume reconstructs conversation state from committed records, checks checkpoint
compatibility and current policy/provider/image identity, then reconciles pending
containers/results. Unknown effects require reconciliation; committed results are
not rerun. Recorded replay uses captured provider/executor interfaces and the
shared state reducer. It has no live backend.

Trace/audit/replay/report open SQLite read-only. Audit checks schemas, causal
ordering, blob hashes, exact context, provider/call correlations, authorization
bindings, compaction lineage, retrieval slices, helper metadata, verification and
terminal state. Explicit exceptions preserve these checks under `python -O`.
Hashes detect corruption; they are not signatures against the host owner.

OpenTelemetry uses private SDK providers with recording boundary spans and no
automatic external exporter. Audit retains trace/span IDs; restart events link to
prior trace/event IDs. Reports include local SDK metric snapshots with bounded
labels, and per-call durations/provider usage remain evidence. Missing provider
fields and unknown recovered timings remain null. Timing residuals are not
interpreted as queue delay. No prompt/source/output text enters metric labels.

Blobs are limited to 10 MiB each, and live runs track a 1 GiB cumulative evidence
budget including prior referenced evidence on resume. Disk monitoring is a soft
workspace bound. Orphan evidence can remain after failed commits. Garbage
collection and broad shared-helper promotion are intentionally separate work.

References: [Pydantic strict validation](https://docs.pydantic.dev/latest/concepts/strict_mode/),
[OpenTelemetry instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/),
[SQLite durability](https://www.sqlite.org/pragma.html#pragma_synchronous).

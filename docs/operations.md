# Operating the local harness

Use `uv sync --locked` and `uv run --locked local-agent …`. This IDE omits
`~/.local/bin` from PATH; add it or use `/home/ruthvik/.local/bin/uv`.

`doctor` checks storage permissions, SQLite durability settings, disk space,
image identity, Docker limit support, exact model connectivity/capabilities,
actual sandbox kernel protections, and trace/telemetry initialization. It runs a
small traced sandbox probe; new model/image/schema/context combinations also
require a native read-only capability probe. These probes may warm the model.

For a general repository, supply its path and a task file to `run`. The repository
is imported into a private workspace with project/memory/tools/scratch/outputs
roots. Read the returned final diff evidence using `trace --evidence` or the blob
reference. There is no automatic writeback to the original repo.

## Recovery

Use `resume RUN_ID` only for a nonterminal live run. Resume acquires the exclusive
controller lease and rebuilds state from the last checkpoint plus later committed
history. It verifies the resolved config hash, effective policy, provider type,
model digest and sandbox identity. Pending undispatched calls are revalidated.
A missing model response creates a new request attempt and records possible
duplicate computation. Active containers are terminated under the recorded
recovery rule; published/committed outcomes are reused. Missing containers/results
stop in `needs_reconciliation`, with no automatic mutation replay. Preserve that
workspace and inspect its trace before making a new task/run.

Use `cancel RUN_ID` from another terminal. The request commits before the active
controller interrupts inference or kills the running container. The controller
records the result and terminal cancellation. If the controller has already
crashed, restart/reconcile it; a cancellation request alone does not manufacture
an execution outcome. Leases are OS locks and do not need manual deletion.

`audit_unavailable` means durable logging failed. Emergency termination is
best effort; the authoritative database remains at its last successful commit.
Resolve storage issues, inspect the trace, and resume/reconcile rather than
assuming side effects did not happen. Recovered Docker logs can lack stream
separation and exact timing. Trace records identify this evidence source.

## Inspection and evidence handling

`trace`, `audit`, `replay --recorded-only` and `report` invoke no inference or real
tools. JSONL can always be regenerated with `export-events`. Recorded replay checks
captured boundaries and state transitions; it does not prove fresh inference will
produce the same answer.

`export` produces metadata with payloads omitted. `--include-evidence` explicitly
includes a private single-run ledger and evidence. Other runs are removed from the
SQLite snapshot and VACUUM removes their free pages. Reference closure uses
explicit record fields, not blob references invented in model prose. Such bundles
can be opened with `--data-root BUNDLE audit RUN_ID` or recorded replay.

`backup` creates a private consistent SQLite online backup and copies immutable
blobs while holding the controller lease. It includes all runs and orphan/report
blobs. `verify-bundle` checks checksums; the manifest itself is not cryptographically
signed. Destinations must be new directories outside the live data root. Backup
and export preserve ledger/evidence for inspection, not mutable workspace or
container state; they cannot automatically resume from the bundle.

Full local state includes source snapshots and model/provider text. Keep it on a
local owner-only filesystem. Deleting old blobs merely by age breaks records;
automatic retention/garbage collection is not implemented.

## Evaluation

`evaluate --windows 8192 16384 --rounds 1` runs the calculator control plus two
held-out repairs (mean and clamp) with protected image tests. Keep model, image,
tools, instructions and output reserve fixed while varying the window. Additional
rounds reverse profile order on alternating rounds. Results retain per-request
usage, prompt/decode rates when known, client/provider timing residuals, verified
success, invalid-call rate, recovery attempts, compactions, wall time and hardware
samples. Hardware data remains outside sandbox authority.

GPU samples are taken approximately every two seconds. Reports distinguish model
residency before each task; capability probes run before measurements and can
warm the model. Peak VRAM describes sampled total GPU usage. This short task set
is a smoke comparison, not a cold-start benchmark, sustained thermal qualification
or proof of an optimal model. Evaluation reports are fsynced under
`control/reports` and referenced in immutable evidence.

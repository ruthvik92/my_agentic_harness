# Progress

## October 6, 2026 — M0 implemented; acceptance gate passed

Started from `local-agent-build-guide.md`. This session implements M0 only: contracts,
durable evidence and events, boundary spans, scripted simulation, and read-only
trace/audit/recorded replay. No live inference or generated command execution.

### Decisions

- Use the current repository as the package root with a `src/local_agent` layout.
- Python 3.11+; develop in an isolated `.venv` (host Python is 3.14.4).
- SQLite is authoritative; JSONL is a regenerable export.
- Keep run evidence outside the source tree by default.
- Implement one milestone at a time and require its acceptance tests before M1.

### Gotchas

- The guide is currently untracked user content; preserve it without modification.
- `uv`, `pip`, and `ensurepip` were unavailable. `python3 -m venv .venv`
  created the interpreter but failed to bootstrap pip. Used the official PyPA
  `get-pip.py` to bootstrap pip **inside `.venv` only**, then editable installation.
  A fresh machine with this setup needs `python3.14-venv` or the same bootstrap.
  Dependency downloads are slow here (roughly 50 KiB/s).
- M0 mock tool results cannot establish real task success. Simulations must finish
  `completed_unverified`, never `verified`.
- A frozen Pydantic model does not recursively freeze dictionaries. Persist canonical
  bytes at boundaries rather than relying on shallow immutability for authorization.
- Blob publication precedes SQLite commits. A failed transaction can leave an orphan
  blob; this is preferable to a committed record referencing nonexistent evidence.
- WAL requires local storage; do not place the data root on a network filesystem.

### Implementation ready for acceptance checks

- Package and typed contracts, explicit status transitions and event families.
- SQLite schema v1 with WAL/FULL durability, foreign keys, transactional sequences,
  and state/event commits; immutable, SHA-256 addressed, fsynced evidence.
- OpenTelemetry recording spans with audit correlation and no default external exporter.
- Scripted provider, mock-only runtime, strict validation, deterministic policy,
  bound dispatch intents, results, and checkpoint evidence.
- `simulate`, `trace`, `audit`, `replay --recorded-only`, and `export-events` commands.
- Acceptance tests inject deferred foreign-key violations that fail at SQLite
  COMMIT and check provider/executor callback counts. Tests also cover tampered
  authorization bindings, missing/corrupt evidence, read-only replay, causal IDs,
  schema/type/path rejection, budgets, and regenerating JSONL.

### Validation results

- `.venv/bin/python -m pytest -q`: **38 passed**.
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/ruff format --check .`: passed.
- `.venv/bin/python -m pip check`: no broken requirements.
- `git diff --check`: passed.
- Installed CLI demonstration completed `completed_unverified`; audit passed with
  **33 events and 41 checked evidence blobs**, three model turns, four attempted
  calls, two mock executions, one validation rejection, and one policy denial.
- Demo run: `run_3c4c6404bc554b5399faca28d2b84a5e`.
  Its state is under `~/.local/share/local-agent/control`; the derived export is
  `runs/run_3c4c6404bc554b5399faca28d2b84a5e/events.jsonl` within that directory.

Reproduce the demo:

```bash
.venv/bin/local-agent simulate
.venv/bin/local-agent trace run_3c4c6404bc554b5399faca28d2b84a5e --evidence
.venv/bin/local-agent audit run_3c4c6404bc554b5399faca28d2b84a5e
.venv/bin/local-agent replay run_3c4c6404bc554b5399faca28d2b84a5e --recorded-only
```

### Remaining scope and next session

M0 supplies the trace core, not a working coding agent. Its policy only authorizes
fixed mock capabilities. Read-only recorded replay is a state reducer, not M3's
restart/reconciliation or full runtime replay. Approval/artifact records and tables
are defined, but their active lifecycles remain to be wired. Span exporters and
metrics, total run evidence quotas, context compaction, live capability checks,
and independent task verification remain later work. No simulation claims `verified`.

Next: **M1, isolated Docker executor**. Establish a workspace manager, trusted
non-root offline image pinned by digest, in-container filesystem worker, seven
real tools, bounded concurrent output capture, and container cleanup. Verify
actual CPU/RAM/PID/isolation settings, path traversal and symlink handling, import
shadowing, protected-record inaccessibility, and timeout termination of descendants
before connecting real tools to the loop. Do not introduce a host executor fallback.

The user guide was preserved; no Git commit was created.

## October 6, 2026 — uv migration and M1–M5 implementation

User authorized continuing through all milestones in order and requested `uv`.
The first live model is **qwen3:30b-a3b-instruct-2507-q8_0**, selected by the user.
Docker and Ollama are both available locally; Docker uses cgroup v2 with CPU,
memory/swap and PID limit support. The daemon is rootful; containers use the
current non-root UID/GID with dropped capabilities and offline networking.

### M1 in progress

- Added the seven strict tool schemas and filesystem worker with descriptor-relative,
  no-symlink reads/edits, hash preconditions, exact patches and bounded listings.
- Added bounded workspace import and Docker-only execution with prelaunch flag
  attestation, actual in-container kernel limit checks, concurrent output draining,
  output flood termination and descendant cleanup via container kill.
- Workspace disk usage uses a **soft monitor**, not a claimed hard quota.
- Added Docker acceptance tests; they require an explicit pinned image and are
  separately reported from unit tests.
- Current non-Docker regression suite: **42 tests passed**.

### M1 gate passed — M2 started

- Pinned image `sha256:888be9a54b52ed091b7ddcee611434d20ad90bdc4cf05b94e3016704c62a5207`.
- `uv run --locked pytest -q --docker-image <digest>`: **47 passed**, including
  all five Docker scenarios; `doctor` passed all prerequisite checks.
- Tested real Git baseline/diff, read/write/patch/list/search/commands, kernel
  cgroup enforcement, host sentinels/socket/GPU/network absence, symlinks, import
  shadowing, descendant termination, output flooding, and fail-closed settings.
- Starting M2 only after that gate: native Ollama adapter, bounded sequential
  live runtime, provider evidence, protected fixture verification and final diff.

### M2 live validation

- Exact native Ollama request bytes and complete assistant messages are retained;
  optional thinking/provider usage remain evidence, not authorization.
- A traced startup capability probe passed all four checks and is cached by model
  digest, Ollama version, image, schemas, instructions and context options.
- Three real Q8 fixture repairs independently passed and audited cleanly:
  `run_f9286fb6abc9482ab1b3bf7c2bbc8d1f` (124 events),
  `run_308b876fa2b749b19ef87e48f7f538ec` (100 events),
  `run_c256c315ee1f408fb368f468c5648bf3` (100 events).
- The first run made four distinct path-schema errors. Clarifying that the repo
  root is `project` eliminated those errors in the next two runs; policy was not
  weakened. All three produced the same implementation diff, while correctness
  is established by protected verification rather than identical model prose.
- Independent verification uses a fresh workspace and five protected cases from
  the read-only image. A test that weakens editable tests still fails verification.
- Final diff uses a fresh staging workspace against the protected baseline; agent
  edits to its Git history cannot hide source changes.

### M2 gotchas

- Provider usage fields absent from a response stay `null`.
- SQLite's request table stores typed records by blob reference; querying a
  nonexistent `provider` column in the new capability cache was caught and fixed.
- Trusted bootstrap/verification/diff proposals use explicit `harness` provider
  records and purposes. They are deterministic operations, not invented inference.
- Additional workspaces require protected, recorded grants and can be used only
  by matching trusted harness requests; model arguments cannot select them.

M2 acceptance gate passed: **51 tests passed** with Docker enabled plus three
successful independently verified live runs. Starting M3 recovery and crash tests.

### New gotchas

- Docker Hub's CloudFront blob download chose an unreachable IPv6 address.
  Fetching the official Python base through `mirror.gcr.io` instead; runtime will
  use the resulting immutable image ID, never a mutable tag.
- An atomic replace consumes the temporary filename. Cleanup must tolerate its
  absence; the filesystem acceptance test caught this before image publication.
- Docker executor must compare the received request to the persisted request
  bytes, not merely check that an execution ID has a started record.
- Retain stopped containers and a fsynced protected result marker until the
  result commit, so recovery can distinguish uncertainty from a known outcome.
- Installed uv 0.12.23 to `~/.local/bin/uv`, generated `uv.lock`, and migrated dev
  dependencies to a default dependency group. This IDE's inherited PATH omits
  `~/.local/bin`; use its full path here or export that directory into PATH.
  `uv sync --locked` now supplies the reproducible development environment.
- Excluded `tests/fixtures` from harness pytest discovery; fixture tests are
  intentionally broken and must run only inside their own sandbox/verifier.
- Image package downloads are also throttled (~55 KiB/s). Provisioning can take
  several minutes. This is separate from runtime/model performance measurements.
- Docker's `local` log driver enables compression by default and refuses
  `max-file=1` with compression enabled. The first container acceptance run caught
  this startup failure. Explicitly disable compression for the single bounded log.

### M3 gate passed — durable restart and cancellation

- Full Docker regression gate: **59 passed**. Five subprocesses deliberately exit
  at the response/intent/launch/publication/commit boundaries. Recovery never
  silently repeats an uncertain mutation; missing container/result evidence ends
  in `needs_reconciliation`.
- Added an OS-released exclusive controller lease, checkpoint/history restoration,
  current-policy/provider/image checks, labeled container reconciliation, protected
  result markers, new trace IDs and causal links to prior events.
- Committed verification/diff outcomes are reused on restart. Recorded replay
  consumes captured provider/executor records and state transitions without a
  live backend. JSONL remains regenerable from SQLite.
- Durable cancellation interrupts inference or the running container. Cancellation
  tests caught a kill-before-start race; polling waits for Docker's created state
  to advance before terminating it.
- Tool schema versions now preserve historical normalization. Older M0/M2 records
  still audit without changing their bytes; extending a tool schema requires a
  new version rather than silently changing old normalization.
- Recovered container logs may lack complete stream/timing separation; recovery
  labels its evidence source instead of claiming a fresh execution.

Starting M4 only after this gate.

### M4 gate passed — evidence, compaction and helper reuse

- Full pinned-Docker suite: **62 passed**. A 30k log's later slice exposes
  `LATE_MARKER`; a foreign/ungranted evidence ref is denied before dispatch.
- Retrieval explicitly authorizes this run's committed stdout/stderr/output and
  artifact refs. Blob hashes in model text/arguments do not create grants.
- Deterministic compaction records whole-group sources/hashes, derived index,
  preserved constraints, inclusions and exclusions; original evidence remains.
- Helper manifests and code are captured/hashed inside Docker immediately before
  execution. Isolated Python executes captured single-file bytes. Reuse preserves
  hashes; editing code changes the code hash. Requested capabilities are ignored.
- Working-memory edits cannot change protected policy. Historical M0 and live M2
  audits still pass after explicit read_file v3/run_command v2 schema upgrades.
- All seven tool schemas do not fit a 4k context with 2k output reserved; fail
  clearly rather than rely on provider truncation. M4 gate uses the 8k profile.
- Current image: `sha256:a8d099a63a679029c312b54e48632692eaf5fe55a507a68b3cf651438c83d2c4`.

Starting M5: held-out evaluation, operating checks, metrics and export/backup.

### M5 gate passed — evaluate and operate

Implemented and validated all five build milestones in sequence using uv.

- Final full pinned-Docker suite: **71 passed in 40.94s**. Ruff lint and formatting,
  dependency resolution, and `git diff --check` passed. No agent containers remain
  running. All existing M0/M2 trace compatibility checks still pass.
- Added protected mean/clamp verifiers and deliberately broken repositories.
  Tests prove premature completion fails verification, then a real repair passes.
- Live comparison holds the selected Q8 model and 2k output reserve fixed while
  changing only the context window. Calculator is the development control; mean
  and clamp are additional held-out repairs. **All six runs verified and audited**.

| Window | Verified | Mean wall time | Invalid calls | Compactions | Peak sampled VRAM | Peak GPU temperature |
| --- | --- | --- | --- | --- | --- | --- |
| 8192 | 3/3 | 10.75s | 0 | 3 | 32166 MiB | 56°C |
| 16384 | 3/3 | 10.19s | 0 | 0 | 32932 MiB | 63°C |

- All measured models were resident; capability probes run beforehand and can warm
  them. Decode rates were approximately 152–171 tokens/s. Missing usage stays null,
  and unexplained client/provider timing residuals are not called queue delay.
- This is one small sequential round, not evidence of an optimal model/profile or
  cold-start/sustained thermal performance. Keep the 8k default. See
  [evaluation results](docs/evaluation-results.md) for run IDs and interpretation.
- Full fsynced local evaluation report:
  `/home/ruthvik/.local/share/local-agent/control/reports/34deaeac7ccdb65b8a605a41882f57df6a4e87dcaa8736a9e97197019747bd6b.json`.
  Evidence ref: `blob://34deaeac7ccdb65b8a605a41882f57df6a4e87dcaa8736a9e97197019747bd6b`.
- Local OpenTelemetry metric snapshots cover outcomes, terminal reasons, attempted
  calls, validation/policy failures, context, compactions, latency, command timeouts
  and captured bytes with bounded labels. Identifiers/payloads remain evidence.
- `doctor` passed all 17 checks, including native model capability, actual sandbox
  kernel limits, image identity, storage durability/permissions and telemetry.
- Default `export` omits payloads. Explicit `--include-evidence` creates a private
  single-run SQLite/evidence bundle that audits/replays independently. Export
  reference traversal never grants refs discovered in raw model prose.
- Backups use SQLite online backup under the controller lease plus immutable blobs;
  checksum manifests detect accidental corruption. A real backup verified **1375
  files** at `/tmp/local-agent-m5-backup`. Real metadata/full exports are at
  `/tmp/local-agent-m5-metadata` and `/tmp/local-agent-m5-evidence`; the full export
  audited cleanly (90 events, 143 checked blobs).
- Added a 1 GiB live run evidence budget, including prior referenced bytes on
  resume. Evidence exhaustion fails closed and triggers emergency termination.
- Provider HTTP errors, malformed JSON and invalid response shapes retain raw
  failure evidence. Recovered unknown timings stay null rather than fabricated 0.
- Final pinned image:
  `sha256:70472bdeca55c5b8b33d2ebed09ff8de666ce3d34765ab2dc5203161c82ea756`.

### M5 gotchas and operating limits

- The original calculator task file is beside its fixture directory, unlike the
  newer held-out tasks. The first evaluation startup caught that path mismatch;
  fixed it before the measured six-run comparison.
- Invalid-call rate uses external model call attempts as its denominator; trusted
  harness bootstrap/verification/diff calls are separately included in total calls.
- Backup/export bundles preserve ledger/evidence for inspection and recorded replay,
  not mutable workspaces or Docker state for automatic continuation.
- Hard filesystem quotas, broad reviewed/shared helper promotion, blob garbage
  collection, external telemetry exporters, distributed workers, network-enabled
  profiles and the optional trace UI remain outside this v0 implementation.
- Native token estimation is conservative rather than an exact tokenizer. Helpers
  through the manifest interface are isolated single-file Python programs.
- No Git commit or deployment was requested or created. The user guide is unchanged.

Ready-to-use commands and operating procedures are in [README.md](README.md) and
[docs/operations.md](docs/operations.md). Each gate's checks/results remain above
as a chronological record; earlier "remaining scope" entries describe that stage.

## October 7, 2026 — OpenAI interface, browser traces and documentation

User requested an OpenAI model interface, browser trace access, and both a
five-minute TLDR and detailed documentation.

### Implemented

- Added `OpenAIProvider` using standard Chat Completions function tools and a
  provider factory. Both OpenAI and compatible local servers can be configured.
  Exact payloads/raw responses are retained; assistant tool IDs and JSON-string
  arguments are normalized and correlated with tool results through continuation
  and restart. Malformed arguments remain proposals for ordinary rejection.
- Extended configuration with base URL, API-key **environment variable name** and
  selectable `max_completion_tokens`/`max_tokens` output field. No credential value
  enters config/request evidence or tool-container environments. Remote URLs
  require HTTPS; plain HTTP is loopback-only. Native Ollama remains the default.
- Added `config/openai-local.yaml` for the selected Q8 model through local Ollama's
  OpenAI-compatible endpoint. Hosted OpenAI setup is documented; no paid hosted
  call was made and cloud account/model access is not claimed to have been tested.
- Generalized capability checks, context serialization, metadata, auditing,
  recovery and `doctor --agent` to the selected provider. Hosted/API metadata hashes
  are explicitly incomplete model identity, not invented model-weight digests.
- Added `trace-web`: a read-only loopback browser viewer with run selection,
  relative event timelines, filtering, causal/span IDs, nested evidence buttons
  and audit. No execution/resume/cancel routes or external UI assets. Host/Origin
  checks and text rendering protect local evidence; refs are scoped to a run.
- Viewer is running at `http://127.0.0.1:8765` in this session. Restart with
  `uv run --locked local-agent trace-web`; stop the foreground command with Ctrl+C.
- Wrote [five-minute TLDR](docs/tldr.md) (~1000 words) and
  [detailed implementation guide](docs/guide.md) (~2060 words), and linked them
  from README. These explain the implemented system rather than replacing the
  original design/build guide.

### Validation

- Full pinned-Docker regression suite: **81 passed in 45.90s**. Ruff lint/format
  and `git diff --check` passed.
- Real OpenAI-compatible repair independently verified and audited:
  `run_51fa331d73da472fbb57ebd56a77e263` — **101 events, 162 checked blobs**.
  Capability probe `run_5b1f8caab0564022950b02f9bb291696` passed all four checks.
- `doctor --agent config/openai-local.yaml` passed all 17 checks. Recorded replay
  of the live repair executed zero real tools. Historical M2 trace still audits.
- HTTP mock tests verify exact wire bytes, correlated tool IDs, unknown timing,
  secret isolation, malformed JSON/status/incomplete response evidence and resume
  without redispatch. Browser tests verify real HTTP routes, evidence isolation,
  Host/Origin rejection, absence of mutation routes and unchanged ledger state.
- Headless Firefox loaded the viewer/run list; HTTP checks retrieved the live run
  with 101 events. Screenshot is local scratch under the Firefox Snap common dir.

### Gotchas and fixes

- The broad regression gate exposed a cancellation race: a persisted response's
  proposed calls could be left unvalidated when cancellation won the next boundary.
  Added explicit `tool.skipped` records before terminal state, plus a deterministic
  after-response cancellation test. No audit requirement was relaxed.
- Recovery now removes retained stopped containers when consuming already committed
  results, covering a crash after result commit but before release.
- Firefox is installed as a Snap and has a separate `/tmp`. The initial headless
  screenshot attempt used an inaccessible profile path; using its Snap common
  directory completed the check without touching the user's browser profile.
- This adapter supports Chat Completions text/function tools, not Responses,
  multimodal or streaming. API model-list access is required. Local servers can
  select `max_tokens`; remote model sampling/reasoning options are not guessed.
- Hosted inference sends task/context to the configured service. The offline
  execution profile still applies to Docker tools. API aliases may change without
  identifying new weights; metadata-hash checks do not establish reproducibility.

Used official OpenAI documentation via the OpenAI Docs skill:
[Chat Completions API reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).

### Circuit investigation case scaffold

User accepted the `circuit-case/` layout. Added a case README, symptoms template,
measurement CSV header, and extracted/schematics/netlists/models/analysis directories.
No PDF or measured values were fabricated. The README specifies one-based PDF
pages, a proposed normalized crop convention, evidence provenance, draft netlist
review, and separation of measured/predicted values. PDF intake, image input,
netlist generation, simulation integration, and circuit verification remain future
implementation; existing coding-fixture verification does not apply to circuits.

## Analog circuit workflow — PDF intake and draft netlist (2026-10-07)

Implemented `uv run local-agent circuit --case … --pdf … --page … --question …`.
Optional `--region left top right bottom`, `--context-page` and `--dpi` support
user-selected portions and continuation pages. The workflow imports the case,
uses trusted Poppler extraction inside the pinned offline Docker image, retains
300-DPI full pages and 600-DPI overlapping detail crops, and supplies image inputs
plus symptoms/measurements to an `analog-v1` agent. Native Ollama and OpenAI
Chat Completions image-message formats are supported. `config/analog.yaml` uses
installed vision-capable `qwen3.8:27b`; the existing Q8 coder is unchanged.

The agent writes an explanation and strict evidence-indexed component graph.
A deterministic compiler emits observed R/C/L parts into an unreviewed SPICE
draft and comments out uncertain or active-device/model-dependent components.
Schema checks reject duplicate references, invalid node/value syntax, unmatched
page citations, and components that claim “observed” while recording uncertainty.
There is no circuit simulator or independent electrical/transcription verifier.
All successful circuit runs remain `completed_unverified`.

Evidence includes original PDF chunks, source hash, rendering manifest, PNG
hashes/page/DPI/coordinates, case notes and generated output artifacts. New
`circuit.prepared` and `circuit.netlist_generated` events integrate with existing
traces and evidence bundles. Resume restores captured images after preparation;
interruption before that event currently requires a fresh circuit run. Output
exports use fresh run directories under case `extracted/`, `netlists/`, and
`analysis/`. Generated code is never executed on the host.

### Actual Dragon manual run

Input: `circuit-case/schematics/nak_Dragon_Service_Manual_hi_res.pdf`, 83 pages,
36,363,783 bytes. PDF page 45 is **7.4 Auto Azimuth Control Section**, continued on
page 46. It is scanned: page-45 text extraction is empty. Captured one 300-DPI
page-45 image, four overlapping 600-DPI detail tiles, and 300-DPI page 46.

Successful local vision run: **`run_58a01c1e24dc4cd880f55fc5e5ec2b74`**.
Audit passed: **151 events / 250 checked blobs**. The model saved an explanation
and an eight-component graph; it repaired invalid signed node names after schema
feedback. The initial compiled draft emitted six passives and omitted two parts.

Visual review found incorrect IC741 pin descriptions and resistor connectivity,
as well as an observed R741 carrying explicit junction uncertainty. Preserved all
raw model outputs and their authoritative trace unchanged. Added case-side
`analysis/<run-id>/review.md` and `explanation-reviewed.md`, plus
`netlists/<run-id>/reviewed.graph.json`, `reviewed-draft.cir` and
`reviewed-validation.json`. These review artifacts were authored after the run;
they are not represented as model-produced protected run artifacts. The smaller
reviewed draft includes only C911/C912 (470µF, 16V) supply decoupling, whose rail
connections were visually inspected. It remains partial and simulation-unready.

### Gotchas and checks

- Six high-resolution images used ~26k provider input tokens, exceeding the first
  32k configuration's input allowance. That run (`run_f8875c3b7cca481d937d090193ae549a`)
  stopped before dispatching model-proposed tools and audited successfully. Circuit
  configuration now uses 64k; context estimates exclude base64 transport bytes and
  reserve 6,144 tokens per image. Actual provider input-budget enforcement remains.
- An unrestricted board transcription hit 8,192 output tokens with no usable tool
  call (`run_ca792070fc8b45c68e53cfbbc1c45a76`, also audited). Instructions now request
  a small subcircuit, short separate file writes and a concise functional explanation.
- Trace audit validates evidence/protocol integrity, **not** electrical correctness.
  The live model's pin and resistor mistakes demonstrate why schema-valid output
  still requires image review. The compiler now rejects contradictory uncertainty;
  it cannot establish that every asserted wire is correct.
- Snapshot reads reject symlinks, special files, traversal and oversized artifacts.
  Generated output captures use fixed Docker reads and compare retained bytes;
  netlist text cannot inject directives through titles, values or uncertainty fields.
- The pinned sandbox includes Poppler and records `pdf_helper_hash`; doctor rejects
  stale helper/image combinations. Current image:
  `sha256:f3d8acaebae67ef92df5f9cbeee1f9c562fd7d9d53fb9a6db72469772f0851a5`.
- Added circuit tests for real PDF/Docker extraction, scripted graph/file creation,
  netlist generation, audit/bundle roots, exports, multimodal message formats,
  bounded no-symlink reads and directive-injection/uncertainty rejection.
- Updated case README, five-minute TLDR and guide; detailed usage is `docs/circuits.md`.
- Final pinned-Docker regression gate: **84 passed in 51.82s**. Ruff lint/format
  and `git diff --check` passed. The circuit acceptance test exercised the tightened
  validator and durable output-capture/export path after the live review fixes.

### Easy trace viewer startup

Added executable Bash launcher `./traces`. It locates UV on PATH or in
`~/.local/bin`, switches to the harness directory, and runs the locked environment's
trace viewer. Options pass through, for example `./traces --port 8766`. The viewer
runs in the foreground and stops with Ctrl+C. No shell-profile changes are needed.
Updated README and circuit guide. Checked Bash syntax, help/options forwarding,
and actual HTTP 200 startup from `/tmp` with UV absent from PATH; the test viewer
was stopped after verification.

### How to interpret the Dragon trace

Added `circuit-case/analysis/run_58a01c1e24dc4cd880f55fc5e5ec2b74/README.md`
with links to raw/reviewed outputs, an actual event-number walkthrough, the nested
model/tool evidence paths, field definitions, and a worked explanation of event
106. Checked the event numbers and normalized patch payload against the retained
ledger. Explained that `tool.validated` accepts arguments, while policy and actual
execution have separate events, and that trace/audit success does not establish
circuit correctness. Documented current viewer limits (JSON/text, envelope-only
filter) and distinguished deterministic harness operations from Ollama inference.

### General run and trace interpretation guide

Added `docs/traces.md` as the reusable guide for any coding, circuit, probe or
scripted run. Covers viewer usage, evidence-reference navigation, every event
envelope field, tool lifecycle, provider identity, output/timing fields, run
statuses, verification scope and CLI alternatives. Linked it from the main README,
detailed guide, circuit guide and the Dragon example. The example retains its
actual event walkthrough and patch explanation; shared field definitions now live
in the general guide. Checked local Markdown links and whitespace.

### Diagnose and rerun page-44 crop failure

Investigated `run_c8008ebd640f4ddbad7282100a94fdf6`. Extraction and explanation
write succeeded; event 65 retained an Ollama response ending with
`done_reason=length`, `eval_count=8192`, empty assistant content, after ~75 seconds.
Prompt usage was 12,526 tokens, so this was output exhaustion rather than input
context overflow. The failed run audits: 66 events / 111 checked blobs. Added
case-side `failure-analysis.md` without changing its protected evidence.

Increased analog output allowance to 16,384 tokens, requested 1–4 initial graph
components, included source PDF filename and tightened unsupported device/filter
claims. Ollama transport now honors the configured model timeout. Output exhaustion
has a specific retained error message; a regression case verifies length-ended
responses cannot dispatch even apparently complete tools. Pinned-Docker gate:
**85 passed in 39.02s**; Ruff passed. Rerun started with the original question,
page 44 and region `[0, 0.5, 0.5, 1]`: `run_a238fd12a2d44da799928c22c2b13bda`.

The first rerun cleared output truncation but generated an oversized graph and
entered repeated schema/file-path repairs. Cancelled it cleanly to apply the
remaining fixes; it audited successfully (301 events / 461 checked blobs).
Added explicit safe replacement and command-cwd instructions, schema descriptions
for observed-passive requirements, component-specific aggregate validation
feedback, and a hard 1–4-component limit for initial graphs. Identical validation
failures use the configured repetition limit; distinct repairable errors remain
bounded by the overall run/model/tool budgets. An acceptance test exercises four
different invalid proposals, including an oversized graph, followed by successful
repair without relaxing validation. Fresh exact-question rerun:
`run_711f7f0b3d254707ab867f8d7a82e0d8`.

Final exact-question rerun **`run_711f7f0b3d254707ab867f8d7a82e0d8`** completed
unverified. Audit passed: **148 events / 226 checked blobs**. Exported its original
Ollama explanation and four-component graph; the compiler emitted R715/C705 and
omitted VR701/R710. Added a run README linking outputs, original failure analysis,
and remaining image-reading issues (signal direction, op-amp pin/half labels,
analog-switch description and JFET/transistor classification). No corrected manual
analysis was substituted into the model artifacts. Independent electrical
verification remains unimplemented. Final pinned-Docker gate: **86 passed in
45.30s**; Ruff lint/format and whitespace checks passed.

### Phone screenshot interface: harness-authored implementation

User requested that the local harness write the phone interface. Controller staged
an isolated source copy under `/tmp/harness-phone-build`, wrote implementation and
review tasks, and invoked the real `local-agent run` CLI with offline Docker tools.
No generated draft has been applied to this working copy yet. Added Pillow to the
UV-managed dependencies for bounded PNG/JPEG validation.

Initial `qwen3-coder:30b` probe `run_3b8916f1f9b5417da622ed0e61301744`
returned function-call markup as plain text and failed the capability gate.
`qwen3:30b-a3b-instruct-2507-q8_0` passed its probe and wrote a draft in
`run_79a3e48a517e4b5699972b8468034229`, but Ollama then returned HTTP 500:
`invalid tool call arguments for "write_file": unexpected end of JSON input`.
Review found imaginary runtime APIs, unauthenticated job GETs, shared request
paths, and incomplete CLI integration. The draft is unsuitable for LAN use.

A narrower repair run `run_3bce95f03ac449b7b9cc7f7a62acb7d4` exhausted 80
model turns rereading source without implementing repairs. Retried the runtime
scope with `qwen3.8:27b` and a 65,536-token context. Implementation state and trace
ledger are currently at `/tmp/harness-phone-build/state`; these runs are separate
from the normal `~/.local/share/local-agent` ledger.

Docker containers exist only during individual tool calls and are removed after
committing results; Ollama inference runs on the host. `docker events --filter
type=container` can show the short-lived containers even when `docker ps` is empty.

Phone feature completed with explicit mixed authorship. Qwen3.8 repair
`run_d5ba4f79136443b3a11fbe76cc04eb05` was cancelled after repeated reads.
Switched the local coding work to `glm-4.7-flash:q8_0` with small, concrete tasks:

- Screenshot runtime draft: `run_65d405da35d941c69d764870cc6eb1a6`,
  completed unverified, audit passed (59 events / 95 checked blobs).
- Server draft: `run_3b5cc3278017491483c9c3ca31efd05a`, cancelled during
  repairs. Its queue/login/persistence integration was not usable as generated.
- Browser page draft: `run_ff7d18acf40f473288f560ed97bc6ac5`,
  completed unverified, audit passed (49 events / 80 checked blobs).

Codex reviewed and corrected the screenshot runtime: optional request fields,
blank-question rejection, total history limit, proper base64 size math, bounded
Pillow verification, avoiding `self.request` shadowing Agent.request(), and
using recorded evidence rather than constructor input on resume. Added
`screenshot.prepared` to the event contract and explicit screenshot image/history
roots to bundle exports. Empty tool lists are omitted from provider payloads;
audit accepts an omitted empty list while retaining the context/schema comparison.

Codex wired phone-v1 instructions, config/phone.yaml, screenshot/phone-web CLI,
resume dispatch, package data, and ./phone. The draft HTTP server and job worker
required substantial replacement for usable authentication, correct global CLI
argument order, private per-job files, atomic fsynced publication, one bounded
worker, startup interruption handling and graceful shutdown. HTTP accepts only
explicit private/loopback IPv4 binds; checks Host/Origin, cookie authentication,
JSON framing and request size before processing. Jobs queue up to three waiting
questions. Failed audits cannot produce a successful phone job.

The local-model HTML layout was retained. Codex rewrote its browser event handlers
because the draft had no usable pairing input, omitted history, resubmitted jobs
on Resume, lost completed trace IDs, and used overlapping polls. The reviewed UI
uses password pairing input, raw base64 PNG/JPEG upload and preview, recent complete
conversation pairs, screenshot reuse, textContent answers, model/run details,
trace summaries, and recovery of the same pending job after disconnect/reload.
No API key is entered or stored on the phone. docs/phone.md describes startup,
provider configuration, retained state, limits and authorship; README links it.

Gotchas: controller run leases are OS locks, not lockfile-existence checks; do not
share a SQLite connection across HTTP threads; pair before accessing any API;
write response status before CSP headers; use actual bound port for Host checks;
keep raw images out of status JSON; do not embed the pairing secret in HTML.
Screenshots are limited to 4 MiB / 16MP to fit the existing 10 MiB blob cap after
base64 encoding. Conversation/images live in the tab; reattach after reload.
Ctrl+C waits for the active question to finish; queued jobs become interrupted.
Image/text questions do not automatically generate or verify netlists.

Live LAN acceptance: phone job `620dd7883e40f2aa2d3bf00d1d6990a5`,
run **`run_38349f236fe045a598efc96d6b15f181`**, using the existing page-44
PNG and native Ollama **qwen3.8:27b**, completed unverified. Audit passed
(30 events / 47 checked blobs); recorded replay executed zero real tools.
Authenticated job polling and event retrieval passed through 192.168.0.40.
The answer remains the original local-model output in the normal job/run ledger.

Preserved all development ledgers/evidence using a full private backup at
`~/.local/share/local-agent-builds/phone-20261007` (2,824 files, bundle verification
passed). This archive omits mutable workspaces; use it for trace/audit/replay,
not resume. Example:

```bash
uv run --locked local-agent \
  --data-root ~/.local/share/local-agent-builds/phone-20261007 \
  trace-web --port 8768
```

Controller checks: initial complete pinned-Docker suite **106 passed in 59.31s**;
added failed-audit regression and HTTP framing/restart checks passed afterwards.
Firefox at mobile width passed pairing, actual file upload, follow-up image/history,
safe text display, network Resume without duplication, reload recovery and reset.
Reusable browser check: start `geckodriver --host 127.0.0.1 --port 8844`, then run
`uv run --locked python scripts/check_phone_browser.py`. It uses a fake runner,
a private temporary Firefox-accessible directory and no live inference.
Launcher passed from /tmp with UV absent from PATH; Bash syntax, Ruff lint/format,
and whitespace checks passed. Final suite result follows.

Final complete pinned-Docker gate: **107 passed in 63.02s**. Repeated Firefox
recovery check passed. Ruff lint/format (103 Python files), Bash syntax and
launcher UV fallback passed. Temporary browser driver and test HTTP servers were
stopped; start the actual phone service with `./phone --host 192.168.0.40`.

## 2026-10-08 — Phone cropped-image upload compatibility

User confirmed “Unable to load” appears during image selection/upload. The recent
diagnostic question reached the model successfully with a valid 1448 × 1086 PNG
(993,722 bytes); the failing image was never submitted, so its exact format and
the phone picker's cause remain unknown. The existing UI accepted only reported
PNG/JPEG MIME types and did not check preview decoding. This could reject valid
cropped files with missing or incorrect metadata.

Broadened the picker to image files, inspect PNG/JPEG/WebP/GIF/BMP signatures,
decode before attaching, and preserve unchanged PNG/JPEG bytes when within limits.
Browser-decodable formats normalize to PNG/JPEG; source limit is 20 MiB, prepared
upload limit remains 4 MiB / 16 million pixels. Oversized dimensions resize with
a visible notice, and oversized output suggests a smaller crop rather than
silently reducing schematic readability further. Added read/decode timeouts and
specific error messages. A failed replacement retains the previous screenshot
and conversation; selecting the same file again is supported.

Gotchas: native Photos picker failures can happen before the page receives a
file. Save/export the crop locally as PNG/JPEG and select Files/Browse. HEIC/TIFF
support depends on the browser decoder. Resizing/conversion can affect small
labels, so check the preview. No failing file was available to reproduce the
specific phone error; these changes address confirmed weaknesses in the upload
path, with actual phone re-testing still needed.

The phone assistant has no filesystem/command tools. Its claim that it cannot
inspect harness files reflected that scope; it can inspect submitted images.
Clarified instructions and added controller-supplied upload diagnostics with
actual limits and attachment dimensions/bytes/MIME, stored in screenshot.prepared
evidence. Existing manifests without metadata remain readable. See
[phone instructions](docs/phone.md) for limits, troubleshooting and scope.

Verification: full pinned-Docker suite **107 passed in 61.73s**; focused mobile
runtime suite **18 passed**, including the new saved image-metadata assertion.
Real Firefox at mobile width passed missing/wrong MIME PNGs, WebP normalization,
20-million-pixel resizing, corrupt replacement retention, normal uploads,
follow-up history, safe answer rendering, polling resume, reload recovery and
reset. Ruff lint/format, Bash syntax and whitespace checks passed. Temporary
browser driver and test servers were stopped. Existing user services were left
running; restart the phone server and reload/re-pair to load the updated code.

## 2026-10-08 — Harness-authored saved chats, model controls and paid review

User asked the harness to build browser model/capability dropdowns, a compact
stage breakdown, persistent conversations with memory, thread thumbs-up/down in
traces and an explicitly invoked paid OpenAI reviewer. Kept the LAN pairing-code
authentication; **there is no OAuth 2.0**. Paired devices share one persistent
`local-owner` profile, not separate per-person accounts. Server restart requires
re-pairing, but chats/images/feedback survive.

Invoked the real local harness in offline Docker with **glm-4.7-flash:q8_0**:

- Thread-store draft `run_234d422f97d84a08849052a8513aacfc`: completed unverified,
  audit passed (75 events / 122 blobs). Review found a missing secrets import,
  an absolute path passed to read_evidence, broken pair assembly and no actual
  job-id idempotency despite the model claiming those were implemented.
- Repair attempt `run_a538948c777b452794d3b8798426b958`: exhausted its repeated-
  action budget; audit passed. Codex corrected and independently tested the store.
- First control-helper attempt `run_70268d42e05d475694a089b7f7760dbf`: failed on
  Ollama HTTP 500; audit passed (failure retained).
- Smaller helper task `run_4e36ec70fc4f42718d74cee48d27f79e`: completed unverified,
  audit passed (39 events / 64 blobs). Codex fixed undefined model variables,
  nonexistent capability/ID fields, null-thread handling and incomplete breakdowns.

Integrated and reviewed the drafts, routes, per-job configuration snapshots,
worker completion persistence, safe browser rendering and resume behavior.
Installed models are discovered from Ollama tags/show, with advertised completion,
vision, tools and thinking capabilities. Selecting a model loads it on the next
question; metadata discovery itself does not load inference weights. Text-only
models are rejected for image questions. Phone providers no longer require tool
capability when their tool allowlist is empty; coding agents retain that gate.

Browser stages: Ask uses the chosen image/chat model. Infer draft netlist passes
recent chat plus the last VLM observations to the chosen text model, without an
image; outputs are partial SPICE text in the thread, not graph compilation,
simulation or case-file exports. The compact breakdown and each answer identify
actual stage models/provider/run IDs, preserving earlier model identities when
the selection changes.

Saved threads retain their uploaded image, full exchanges, pending job, feedback
and related runs in private atomic JSON under `phone/threads`. Completed legacy
jobs import once, with their submitted history and image. Their original thread
grouping was never recorded, so each becomes its own imported chat. Model memory
uses the latest three complete exchanges / 16,000 characters; earlier messages
remain visible, not automatically retrieved across chats. Limit: 1,000 threads,
100 exchanges per thread; start a new thread when full. The CLI backup captures
ledger/evidence; preserve `phone/` separately for full browser state.

Feedback is recorded as **phone.feedback** with vote, local owner and source runs.
Repeated identical votes do not create duplicate traces; clearing/changing a vote
does. **phone.turn_linked** captures stage/model/provider, memory count and source
run lineage. Both use separate audited activity runs rather than appending to
terminal model runs. Thread timeline combines those events and its model runs.

Paid Review uses server-side `config/phone-verifier.yaml`, the official OpenAI
endpoint and **gpt-4.1-2025-04-14**. The browser never receives the key. Only an
explicit button press queues a review of the saved image and recent chat; no
automatic paid reviews or restart replays. The button states billing applies and
is disabled when the server lacks OPENAI_API_KEY. Review is advisory and retains
its own response/run; it does not change earlier answers or mark a circuit verified.
OpenAI model image/Chat Completions support was checked in official documentation.

Verification: complete pinned-Docker suite **110 passed in 64.65s**. New tests
cover bounded complete history, job-id idempotency, path/symlink rejection,
model/config snapshots, vision rejection, saved image reuse, text netlist staging,
fake paid review, missing-key rejection, feedback audit and restart/legacy migration.
Real Firefox at mobile width passed model capability labels, saved chat/image on
reload, stage breakdown, netlist selection, fake paid-review response, thumbs-up
and feedback trace persistence, safe text rendering and network resume/reload
without duplicate jobs. Existing upload-format/resizing checks still pass.

Live local acceptance using the existing submitted relay-driver diagram:
**run_76c2d11dadf248df96a35ba2b6ee3383** (qwen3.8:27b image analysis) and
**run_b1f90fbdbc23490791b8fc6e1af2ba5f** (glm-4.7-flash:q8_0 netlist inference)
completed unverified and audited (30 events / 47 blobs each). Thread
`cc9d204669421602460d4bd120ec4707` retained both stages and feedback. The text
netlist introduced guessed coil/model values despite the uncertainty prompt:
pipeline acceptance is not a claim of electrical correctness. Original model
outputs remain unedited. No paid OpenAI inference was made; that path was tested
with fake providers, so actual account/model access remains to be exercised.

Preserved and verified build ledger/evidence at
`~/.local/share/local-agent-builds/phone-v2-20261008`, live ledger/evidence at
`~/.local/share/local-agent-builds/phone-v2-live-20261008`, and live browser JSON
at `~/.local/share/local-agent-builds/phone-v2-browser-state-20261008`. Development
workspace/task files remain in `/tmp/harness-phone-v2-build`. Use a backup's path
with `local-agent --data-root PATH trace-web` to inspect these development runs.
Authorship is mixed: the local harness drafted the two modules; Codex reviewed,
corrected, integrated and verified the complete feature.

Final checks after integration refinements: thread/web tests **6 passed**;
Firefox additionally reopened an earlier chat from Saved chats after New
Conversation and continued it with the saved image and six history messages.
Ruff lint/format (83 Python files), Bash syntax and whitespace checks passed.
Temporary driver and test HTTP servers were stopped. Existing user services
were left running; Ctrl+C and restart `./phone --host 192.168.0.40`, then reload
and re-pair, to activate the new server routes and model controls.

## 2026-10-08 — Dropdown failure: stale running phone server

Confirmed the user's LAN service still ran PID 479018 from before the model-
control upgrade. It served the current HTML from disk but returned **401** for
the unauthenticated `/thread-controls.js` resource. The new handler serves that
public script as JavaScript with **200**. Missing script plus old model routes
prevented dropdown population; this was a running-version mismatch, not a phone
file-picker problem.

Added a missing-helper diagnostic in the page. Server now snapshots HTML and JS
at startup so browser assets stay with the loaded route implementation rather
than serving newer assets against old code. `/api/info.restart_required` detects
later browser file edits and displays a restart notice. Added regression checks
for public script availability, startup assets and update detection; Firefox
acceptance now explicitly exercises missing-helper error and reload recovery.

There were no queued/running jobs. Gracefully restarted the exact known phone
process, preserving its cwd, launch settings and environment without printing
secret values. The replacement runs in the background at the same LAN URL,
PID 722566. Private startup/pairing log:
`~/.local/share/local-agent/phone/server.log`; process metadata:
`~/.local/share/local-agent/phone/server-process.json`. This background repair
process is separate from the usual foreground ./phone launcher; do not start a
second instance on the same port. Re-pair using the new code after reload.

Live LAN checks: helper **200 application/javascript**, authenticated model
catalog **200 with all five installed models**, five prior chats imported and
retained, and restart_required=false. Final regression results follow.

Final pinned-Docker gate: **111 passed in 64.60s**. Firefox acceptance passed
missing-helper diagnostics/reload and the existing upload/chat/stage/feedback
checks. A separate Firefox check against the actual LAN service, at phone width,
paired and populated both dropdowns with all five real installed models. Native
option clicks selected qwen3-vl for VLM and glm-4.7-flash for netlist inference,
and persisted both choices in browser storage; no inference was dispatched.
Ruff lint/format and whitespace checks passed. Temporary browser driver stopped;
the repaired LAN phone service remains running for the user.

## 2026-10-08 — Phone history, reviewer environment and hybrid token accounting

The running phone process had no `OPENAI_API_KEY`; adding an export to `.bashrc`
does not change an existing process's environment. Verified only presence (never
printed the key), stopped the exact idle LAN process with SIGINT, and restarted
through an interactive Bash launch that reads `.bashrc`. Replacement PID 888885
serves the same `http://192.168.0.40:8767` URL. Its model catalog enables the paid
reviewer. No real paid request was sent, so account/key validity and billing have
not been tested. Re-pair after reloading; private startup log and process metadata
remain under `~/.local/share/local-agent/phone/`.

Six historical chats are retained. Renamed the selector **Saved chats (history)**
and added its count/continuation hint. The paid reviewer note now explains when
a chat must be opened before the button can be used.

Invoked the local harness with `glm-4.7-flash:q8_0` to draft the token aggregator:
`run_53a5d0039e52480cb6dddd3e8b28fcf2`, completed_unverified, audit passed with
49 events / 80 checked blobs. Private evidence archived at
`~/.local/share/local-agent-builds/phone-tokens-20261008/`. Its draft did not
account for estimated local replacements correctly, omitted paid review from
actual OpenAI totals, and clamped negative savings. Codex corrected those
accounting errors and implemented evidence extraction, estimates, routes, browser
integration and acceptance tests. This is mixed authorship, not an independently
verified local-model implementation.

Added `tiktoken` through UV and updated the lockfile. Browser's expandable token
panel shows selected-thread and all saved-phone-chat totals. Actual provider
input/output counts stay separate from local native tokenizer counts. Each local
prompt and visible answer is re-counted using the saved OpenAI baseline model;
image estimates follow GPT-4.1 main/4o resolution/detail rules and never count
base64 transport as text. Unsupported image baselines or missing usage leave net
savings unavailable rather than silently counting zero. Cached tokens are a
subset of API input; no dollar savings are claimed. First tokenizer use downloads
a public vocabulary; unavailable vocabulary does not hide measured usage.

Comparison: same non-review stages entirely through OpenAI, without the hybrid
workflow's additional paid critique. Net estimate = that baseline minus all
actual OpenAI tokens, including review overhead. Negative savings are preserved.
This assumes identical recorded prompt structure and uses visible local answers
as output-length surrogates; it does not establish equal answer quality or model
reasoning/caching behavior. Baseline model/rule/request IDs are saved per job.

Historical jobs backfill from immutable evidence. New successful turns store
accounting in `phone.turn_linked`; historical and failed turns with evidence use
separate `phone.usage_recorded` activity runs. Restart is idempotent and original
completed model runs remain immutable. Reports are protected by the existing
pairing/session checks at `/api/usage` and `/api/threads/THREAD_ID/usage`.

Live retained totals: **7 local requests across 6 chats**, **21,597 native local
tokens**, **14,297 estimated OpenAI baseline tokens**, and **0 measured OpenAI
tokens**. The all-local percentage reads 100% relative to this explicit baseline;
that is not a monetary savings or quality claim. Documentation: `docs/phone.md`.

Verification completed: **116 tests passed in 67.38s**, including the pinned
Docker gate. Tests cover negative review-adjusted savings, unknown usage, cached
subsets, official image tiles/base64 exclusion, failed-response accounting,
protected owner totals, persistence and idempotent activity traces. The initial
accounting integration fixture used an invalid trace thread ID; corrected the
fixture to the existing ID contract before the final passing run.

Firefox acceptance passed upload formats, pairing, retained chat/image, model
controls, fake paid review, feedback, resume/reload and token-panel/history
visibility. A separate phone-width Firefox session on the real LAN app reopened
a saved chat, observed an enabled reviewer and displayed both accounting scopes;
it dispatched no inference. All **7** historical accounting activity runs passed
audit. Ruff lint/format and whitespace checks passed. Main LAN server stays running.

## 2026-10-08 — Selectable OpenAI reviewer upgrade

User requested a stronger OpenAI model selectable from the browser. Used the
OpenAI Docs skill and current official model/migration pages. The latest-model
resolver could not run (Node.js 18+ unavailable; retried once); used the fetched
current official GPT-6 guide instead. A read-only `/v1/models` request using the
server key returned all supported choices; it made no paid inference request.

Default paid reviewer is now `gpt-6-astra`. Added an independent **OpenAI reviewer
(paid)** dropdown for Astra, GPT-6.1 Sol, GPT-6 Luna, GPT-5.4, GPT-5.4 Mini,
GPT-4.1's prior pinned snapshot and its alias. Labels show documented capabilities
and broad cost/quality positioning, not measured circuit accuracy. Account model
listing is cached with the catalogs; absent choices are disabled, authentication
rejection disables review, transient discovery failure reports a warning without
claiming access was verified. Browser remembers the reviewer across reloads and
New Conversation. Server validates selected IDs against the supported catalog,
snapshots each job's actual model, and retains earlier model labels in history.

Added optional `AgentConfig.reasoning_effort` to captured Chat Completions
payloads. Reasoning reviewers use medium effort and a 16,384-token completion
budget (reasoning plus visible output); previous GPT-4.1 uses no reasoning effort
and 4,096 tokens. No tools or unsupported sampling parameters are sent. Reviewer
configuration's conservative harness window is 65,536 tokens. No Responses
migration was required for this tool-free phone review flow. Stable token-savings
baseline remains `gpt-4.1-2025-04-14`, independent of the chosen reviewer, to avoid
changing historical comparisons or applying unsupported GPT-6 image token rules.

Codex implemented this focused upgrade and its tests directly. Corrected a
previous browser field-reference replacement that wrote reviewer help text to
the wrong DOM element; the Refresh token totals label now stays intact. Native
selector population chooses an available model when a saved/default choice is
unavailable. Validation fixtures now use the ContextSnapshot attribute contract.

Gracefully restarted the idle exact LAN process to load the updated UI/routes,
preserving the shell-exported key without displaying it. Replacement PID 946507,
same URL and private phone log/process metadata. Six saved chats are retained.
During the work the user submitted an additional local question and an OpenAI
review. That review (`run_fb20cad42adf4824b56ba7873f155b3c`) failed with HTTP 429,
provider error type `insufficient_quota`, code `credit_balance_exhausted`.
Read-only model listing still succeeds; listing does not prove funded inference.
The provider now explains this specific billing failure without echoing arbitrary
provider error text; raw evidence stays captured. Missing usage for that failed
review correctly makes aggregate net savings unavailable, rather than claiming
zero billed tokens. No paid inference was dispatched by these acceptance checks.

Final verification: **120 tests passed in 66.71s**, including pinned Docker.
Reviewer regressions cover account capability filtering, disabled inaccessible
IDs, secret-free discovery errors, selected-model config snapshots, reasoning
request parameters/budgets, legacy GPT-4.1 compatibility and actionable quota
errors with preserved raw evidence. Firefox fake-provider acceptance passed
reviewer selection, persistence and all existing upload/chat/trace workflows.
A separate real LAN phone-width Firefox check found all seven supported account
models, selected GPT-6.1 Sol using a native option click, restored that choice
and chat after reload, and confirmed the review button's selected-model note.
It made no inference request. Lint/format/whitespace checks passed. Temporary
browser driver stopped; the updated LAN phone server remains running.

## 2026-10-08 — Explicit direct API check using bashrc key

User authorized testing the OpenAI endpoint with the key exported by a fresh
interactive Bash shell. Captured initialization privately; did not print or store
the key, authorization headers, shell output or raw provider messages. Sent one
read-only model-list request and one minimal GPT-4.1 text completion (8-token
cap, store=false); no screenshot or chat history was submitted. Results:

- {"test": "Model listing", "http_status": 200, "reviewer_models_listed": ["gpt-4.1-2025-04-14", "gpt-6-astra", "gpt-6-luna", "gpt-6.1-sol"]}
- {"test": "Minimal GPT-4.1 inference", "http_status": 429, "error_type": "insufficient_quota", "error_code": "credit_balance_exhausted"}

### Direct API retry after user update

User requested another test. Read the key from fresh interactive Bash without
printing it; sent one minimal GPT-4.1 request (8-token cap, store=false).
No screenshot/history submitted. Result: {"test": "Minimal GPT-4.1 inference retry", "http_status": 200, "usage": {"prompt_tokens": 11, "completion_tokens": 1, "total_tokens": 12, "prompt_tokens_details": {"cached_tokens": 0, "audio_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0, "audio_tokens": 0, "accepted_prediction_tokens": 0, "rejected_prediction_tokens": 0}}, "completed": true}

## 2026-10-08 — Inspect and recover recent paid phone reviews

User asked whether verification happened. Inspected the latest two phone review
runs: `run_68712d68d3724ce7b5933e2e1ca9d2bc` and
`run_bef688e152ea428aa62dddda22787c60`. Each made **one real OpenAI request**
with `gpt-6.1-sol`, the uploaded schematic and recent chat. Both returned complete
text reviews with **no model tool calls**. Usage was **8,231** and **8,935** API
tokens respectively; the latest includes 379 reasoning tokens and 6,016 cached
input tokens (cached input is already part of input, not additional tokens).
Audits passed for the original runs, but terminal status was `budget_exhausted`,
not a successful or electrically verified completion.

Root cause: reviewer config retained `max_attempted_tool_calls: 1`. The shared
runtime counts controller-owned workspace initialization and final-diff capture
against that budget even though the phone model has no tools. Initialization
used the single allowance; after `model.responded` and `completion.proposed`,
final-diff capture raised `BudgetExhausted("attempted tools")`. Thus the review
was already paid for and captured but the phone job failed before saving an answer.
Synthetic harness requests in these traces are not additional OpenAI inference.

Raised reviewer allowance to **2** for those two controller operations. Added a
real Docker runtime regression using the reviewer config; fake web-job tests
alone had missed this lifecycle failure. Added recovery limited to failed reviews
with this exact capture-budget error, a recorded completion proposal, an OpenAI
request and a text response without tool calls. Restores the captured answer
without making any API request, keeps original job/run failure status, explicitly
labels the answer recovered/unverified, and records `phone.review_recovered` in
its own audited activity run. Startup migration processes jobs chronologically
and normal restart recovery is idempotent.

Both reviews were restored in saved thread `a2e70159a597cb67de535a760999c7ef`.
Full text is also in each job's private `recovered-review.md`. The latest file is
`~/.local/share/local-agent/phone/jobs/2d6418e0fa130b24d091ac651de71fcf/recovered-review.md`.
Each recovery activity audit passed; original terminal states remain unchanged.
Gracefully restarted the idle LAN server, now PID **1071689** at the same URL.
Authenticated LAN checks confirm both answers, correct latest-review ordering,
original `model.responded` and recovery events are visible in thread traces.
No additional paid inference was dispatched.

This is an **advisory OpenAI visual review**. It flagged errors in previous local
answers and noted no netlist was supplied; no SPICE simulation, circuit
connectivity validation or electrical verification ran. The harness's run audit
checks trace integrity, not correctness of schematic interpretation.

Recovery acceptance first exposed two fixture setup issues: its job directory
must exist before atomic publication, and a ScriptedProvider deliberately has
scripted provenance rather than OpenAI provenance. Corrected the fixture to use
an actual OpenAI adapter with an HTTP mock; did not weaken recovery's provider
check. That regression passes without network or paid calls. Full final gate follows.

Final pinned-Docker gate: **122 passed in 69.87s**. Covers successful reviewer
lifecycle and reproduction/recovery of the original capture-budget failure,
including preserved failed status, audited recovery and idempotence. Lint,
format and whitespace checks passed. Updated server remains running; no paid
review retry was required to recover the user's answers.

## 2026-10-08 — Markdown replies and collapsed model history

Implemented the requested phone display changes directly. Model replies now
render CommonMark plus tables and strikethrough, including headings, emphasis,
links, lists, blockquotes and fenced code. Added local `markdown-it-py` and
`bleach` dependencies through UV and updated the lockfile. Server derives
sanitized `rendered_html` only in thread API display responses; durable Markdown,
model memory, original evidence and token accounting remain unchanged. Raw HTML
is disabled, unsafe URL schemes are filtered and model image elements are
removed; user questions remain text. No browser CDN dependency was introduced.

Each model reply is a native keyboard/touch-accessible details card with model
identity and a compact preview. Only the latest model reply opens by default;
older replies are collapsed and can be expanded by tapping their header. Saved
chat/reload restores that default. Answer tables and code have internal horizontal
scrolling, keeping the page within phone width.

Tests cover rendered formatting, active HTML/unsafe links/images, unchanged
source/history, and browser folding/opening. Browser acceptance uses a Markdown
fake-review response through the actual server renderer rather than injecting
trusted markup. Corrected a pre-existing timing assumption: wait for the Ask
button to be enabled before submitting the next browser test question; visible
text can update before asynchronous thread/usage loading has finished.

**125 tests passed in 67.65s**, including pinned Docker. Firefox acceptance
passed Markdown tables/headings/code, default folding, tap-to-expand and all
existing upload/model/chat/review/feedback/resume behavior. Gracefully restarted
the idle LAN service to load updated routes/assets, now PID **1187444** at the
same URL. Saved six chats, reviews and token totals are retained. Updated
`docs/phone.md`; re-pair with the new startup code after reload. No paid inference
request was made for this display change. Final actual-LAN check follows.

Actual LAN Firefox at phone width confirmed the user's saved OpenAI tables and
bold text render correctly; exactly one latest reply opens; older replies expand
on tap and return to collapsed defaults on reload. No transcript scripts/iframes
or page-width overflow appeared. Lint/format/whitespace checks passed. Temporary
browser driver stopped; the updated phone service remains running.

## 2026-10-08 — Per-answer feedback for future model routing

Implemented per-answer ratings directly in the phone harness. Every saved model
reply with a job ID has **Rate this answer: 👍 / 👎** controls inside its reply
card, including historical and recovered reviews. Expand older cards to rate
them. Selected votes persist; tapping the selected vote clears it. Updates do not
rebuild the transcript or close manually expanded cards. UI controls serialize
votes and prevent model submission during a pending vote. Existing top-level
thread votes remain independent; none are copied into answer ratings. Imported
history without an attributable answer/job ID has disabled controls.

Added protected `POST /api/threads/THREAD_ID/answers/JOB_ID/feedback`. The server
accepts only a vote and validates the answer belongs to the requested thread.
Model/provider/stage are taken from saved answer metadata, never the current
model dropdown or browser-supplied attribution. Changed votes create an audited
`phone.answer_feedback` activity run with schema version, answer/job ID, source
run ID, model, provider, stage (vision/chat/netlist/review), owner, answer creation
time, image/recovered flags, previous vote and new vote. Current vote and activity
reference are atomically stored on the assistant message. Repeated identical
votes are idempotent; clears/changes preserve prior events. Original model runs
remain immutable, and voting metadata never enters model conversation memory.

Routing remains explicitly selected by the user; no automatic model policy was
introduced. The new events provide attributable inputs for a future scorer that
uses the latest vote per owner/answer, ignores cleared ratings, separates task
stages and accounts for recovered/failed provenance. Whole-thread vote changes
must not be treated as per-model samples. Updated `docs/phone.md` with the UI,
endpoint, attribution and routing boundaries.

**127 tests passed in 69.25s**, including pinned Docker. New checks cover all four
stages, model attribution, protected access, cross-thread rejection, ignored
client model injection, independent thread/answer votes, idempotence, change and
clear history, reload persistence, audit and original-run immutability. Firefox
acceptance passed latest/older-answer voting, reload restoration, trace exposure,
clear behavior, unchanged expanded cards and existing phone workflows.

Gracefully restarted the idle LAN service to load the updated UI/routes, now PID
**1359654** at the same URL. Six saved chats and existing thread votes are retained;
no inference or production feedback test vote was dispatched. Final actual-LAN
check follows. Lint/format/whitespace checks passed.

Real LAN Firefox at phone width confirmed answer controls on all saved reply
cards, latest-open/older-collapsed behavior, enabled latest-answer buttons,
retained whole-thread thumbs-up without inherited answer votes, and no page-width
overflow. No production votes were modified. Temporary browser driver stopped;
updated phone server remains running.

## 2026-10-08 — Persist harness authorship requirement

Added root `AGENTS.md` following the user's instruction that their local harness
agents must write all implementation and tests. Codex's role is task preparation,
invocation, trace inspection, review, integration of exact agent-authored changes,
and independent verification. Failed checks must return to a harness agent;
there is no silent fallback to direct Codex implementation. Progress entries must
include run/model provenance and truthful authorship. Governance documentation
and task/review notes remain permitted supervisor work.

Gotcha: AGENTS.md is loaded as Codex instructions at session startup; a new
session loads the new file automatically, and this session already follows the
user's instruction. It is not an OS permission barrier. Actual write prevention
would require separate identities/workspaces with a read-only reviewer; that
separation has not been configured. No product code, inference request, or server
restart was needed for this documentation change.

Copied the working agreement to `/home/ruthvik/.codex/AGENTS.md` at the user's
request, making it global guidance for future Codex sessions. No existing global
AGENTS.md or AGENTS.override.md was present. Verified the copy matches the
repository file; retained the repository copy as well.

## 2026-10-08 — MCP interface built by harness agents (in progress)

Prepared isolated source and MCP task under `/tmp/harness-mcp-build`. Requested
local stdio tools for coding, screenshot and PDF circuit submissions, job polling,
actual Ollama model discovery and bounded run evidence. Paid OpenAI reviewers
are excluded; MCP clients independently review returned drafts. Separate MCP
state avoids the phone controller's active-run lock.

`qwen3-coder:30b` failed the actual tool capability probe
`run_e2fb5148c75846a2b207bba992f9f6e3`; switched to native local
`glm-4.7-flash:q8_0`, which passed probe
`run_8d39f24c61b443d28a80c2e15d4c87f7`. Implementation run
`run_0e634c7b33b640ef9062d53073226ed2` reached its model-turn budget. Its first
draft was rejected: placeholder model catalog, wrong command routing, invalid
config/tool assumptions, startup without a running event loop, and job/evidence
lookup problems. Independent initial tests stopped at 4 failures (8 passed).
Submitted a detailed review-fix task back to the harness agent; no implementation
was hand-written by Codex or integrated at this stage. Official SDK v1.30 installed
on the host for independent checks; dependency files will be agent-authored and
UV will generate the lock. Temporary draft docs are not verified instructions.

Further local builds failed review: GLM repair
`run_6ed071453bfe4813b50fe889d61c266e` exhausted its turn budget while rereading;
Qwen3 instruct repair `run_7874dff0afb440d9b229bda0014812c0` was cancelled after
repeated exact-text/create-only replacement failures; Qwen3.8 fresh build
`run_a24ba8d0c04a44b696a0c0e6cce3c1f3` was cancelled after repeated reads.
Trace inspection found older exchanges omitted by conservative context budgeting,
with recent repeated reads retained. Increased the temporary build context to
131072 and split work into module-sized tasks rather than changing harness code.

GLM backend-only run `run_f7792f43c1de45ca8d6e74282bc6ce48` completed with a clean
ledger audit and syntax compilation, but independent review rejected its backend:
mixed thread/async queue APIs, overwritten lease, wrong command/file paths,
environment still retaining secrets, fabricated run ID and missing result parsing.
No candidate implementation integrated. Submitted backend-only repair to Qwen3.8.
Asked whether the user prefers continuing local runs or authorizes a billable
OpenAI coding run through their harness; pending answer does not authorize paid
inference. This is an implementation task, not exposing a verifier through MCP.

User explicitly chose to continue local models. All subsequent runs stayed native
Ollama. Large drafts/artifact modules remained rejected; exact small methods had
better results, but no broad draft was integrated. Following the user's request
to retry with smaller tasks, reset to checkpoints documented in
`/tmp/harness-mcp-small/plan.md`, each touching one file/function and requiring an
independent acceptance check before expansion.

Checkpoint 1 local GLM run `run_ce18437ee7b64af6a482ee15d81ef75f` completed and
produced a minimal official-SDK stdio server with only an honest discovery tool.
No coding/image capabilities advertised yet; no verifier. Host SDK protocol
acceptance is being checked. Source remains isolated until the checkpoints pass.

Checkpoint 1 passed actual official-SDK subprocess initialize/list_tools/call_tool.
SDK returns this generic dict as JSON text content, so the independent client
accepts text content as well as structuredContent (initial checker assumed the
latter and was corrected). Checkpoint 2 GLM run
`run_fc07344910544a4aae40885f936c402a` added only model discovery. Actual MCP call
matched all five installed Ollama tags and each model's real show.capabilities.
Started checkpoint 3: one coding tool calling the existing CLI, without a new
background scheduler or paid verifier. Each checkpoint remains an isolated agent
workspace; actual coding acceptance is next.

Small-task retry: subprocess helper authored by GLM in
`run_cca6174dcab24ef2860ccb550c9de9ea`, repaired in
`run_ff99aaa67e7848489343dd3e61f9be4d`. The repair wrote and compiled the corrected
file but later exhausted its budget by repeating a silent compile check. Salvaged
only its exact agent-authored file; independent stdout, secret filtering, timeout
and cancellation checks passed. Future task checks print COMPILE_OK to give the
agent an explicit stopping signal. Profile selection run
`run_8707e41f440042eeb9c227b8c84466e6` compiled but checked capabilities on the
wrong object; sent that one function back for correction. Compilation alone is
not an acceptance check. No MCP implementation integrated yet.

CLI wrapper accepted from GLM `run_24473b1f362840be80e57b9b113ac13a` after
focused retries. Independent checks passed exact CLI argv, JSON serialization,
private task/config permissions, preserved actual result fields and temporary
file cleanup. Profile correction `run_084471b3ab874e31b82e9e2e1c7ccad5` passed
actual installed-model and capability checks. Stdio wiring required several
focused repairs (`run_54b1dcb3797e47e88deb612854215a1a`,
`run_6c4a19a4da8549619b16939f7554a7c7`,
`run_5b806b0b172f4de1940bce5fe45fbd9f`): wrong imports, missing await distinction,
unresolved paths, and a dropped module execution guard. The real client caught
an immediate exit before handshake. Gotcha: default file reads can truncate long
files; full rewrites must read the entire file, or they drop trailing lines.
The protocol/coding acceptance gate remains pending; no handwritten fixes.

Real MCP coding exercise: GLM `run_c6230c8d754847e2b5e09d267affe894` failed with
budget_exhausted; MCP correctly returned the actual failure and exit_code=1.
Qwen3 instruct `run_0aec2b6f344348528d81683ca0bb54b3` completed_unverified with a
clean audit, created answer.txt only in its isolated workspace, and left caller
source unchanged. The strict text checker expected no punctuation; model wrote
'MCP works.' (the prose task ended that way), so strict content assertion failed.
Independent inspection confirmed file creation, isolation, actual model/status,
and persisted metadata after server exit. Do not call this verified code quality.
Ledger wrapper needed a supervisor contract correction: config_ref wraps the
AgentConfig under ['agent']; corrected by agent `run_34184ad51a534ba5a043cc123dcfb765`.
Trace pagination run `run_9894a360260644af8b5c2a0f98b73f6e` passed bound-query,
pagination and unknown-run checks but left a module-level COMPILE_OK print;
submitted a one-line repair because stdout belongs to MCP. Avoid concurrent live
checks using different large models: Ollama repeatedly unloads/reloads them.

Read-only artifact function repaired by GLM
`run_c647363e4bf34f8193ae1534cfe7f10e` after incorrect SQL/BlobStore calls.
Independent checks passed real registered-diff reading, bounded text chunks and
cross-run artifact rejection. Stdio ledger wiring
`run_5be2b9a6faa2464592a326da47229f06` passed a real SDK restart/handshake and
six-tool discovery, saved runs, paginated events and owned diff retrieval. No paid
verifier tool is registered. Screenshot wrapper run
`run_1adf8604c6554a099490babe9f970d75` compiled but had wrong imports and a stray
module print; sent that one file back rather than integrating it. Source remains
isolated until packaging/tests are agent-authored and reviewed.

Screenshot imports repaired in budget-exhausted GLM run
`run_adfb68ebd0224148ad9e2735364abcb8`; reviewed exact written file passed host
request/CLI/temp-cleanup checks. Circuit repairs
`run_5f05b7022302483dae68249c7840ba66` and
`run_54e0505324974479bb23754b5da0e89c` passed PDF traversal, one-based page,
finite ordered region, CLI argument and temp-cleanup checks. Modality closure fix
`run_74a312f29ee04104b8dab42608b354fb` passed image-path bounds/exclusivity and
symlink escape checks. Stdio repair `run_1bf4034c22ca4bca9bb38a75f06ec612`
registered all eight official-SDK tools without import or stdout corruption.
Dependency/entrypoint authored in `run_a3608dfbeb4c447a9708326cae713121` and
`run_4e119bba305741aaa8a5f9fb2fca461c`. Launcher
`run_eff4af61f8164c20b04ea1dcaa668d81`, executable operation confirmed in
`run_a481931c16674f45964b114360e3930b` (earlier cwd caused chmod failure).

Rejected broad test bundle `run_bbe0d5abd23043e1885c6695e13ab404`; split tests
further. Process secret/stdout test authored in `run_e57c8a89bf5b436bbe5482d9adcb4d39`,
corrected proposal from `run_5fc222d883324125a8273d084f78c5c1`. Correction run
failed repeated create-only writes, but trace contained the exact corrected
agent-authored content. Extracted that proposal unchanged, independently reviewed
and ran it: 1 pytest test passed. This is exact agent-artifact integration, not
Codex implementation authorship; the agent run itself remained budget_exhausted.
Deeper independent subprocess test found orphan cleanup bug; repairs are being
kept to _cleanup_process. No paid coding/verifier calls.

Subprocess group fix `run_791d2bc80e1c48789cd23507d8c6eda1` passed an independent
orphan-child test even when that child ignored SIGTERM. Qwen3.8 cleanup-test repair
`run_7fb01c8078da4b19a7ad6d5a38132358` passed timeout and cancellation checks;
combined process tests: 3 passed. Test generation needed runnable context, not
only small file scope: partial snapshots triggered dependency searches and failed
imports despite explicit compile-only instructions. Updated test tasks to keep
one-file scope while providing full source + offline Python3.12 wheels.
Qwen3.8 run `run_18f1d5ff93c04237984d6449864ccee2` authored and passed the coding
wrapper regression test; `run_2e84e40528524c5daac2dbe6362c6e8c` authored and passed
8 profile-routing cases. Independent host check passed all 9. Initial broader
suite: 103 passed, 27 Docker checks skipped (will run pinned-image gate later).
Protocol-test authoring exhausted its 12-turn exploration budget before writing;
reviewed SDK API findings will seed a focused retry with an adequate turn budget.
Documentation is now a separate small reference-only task. UV resolved MCP1.30.0
in the candidate lock; product changes remain isolated pending final gates.

## MCP frontend small-task retry completed — 2026-10-08

Local harness agents authored the implementation, tests, dependency declaration,
launcher and quickstart. GLM wrote the small backend pieces; Qwen3.8 wrote/repaired
the regression tests and docs. Codex prepared tasks, reviewed exact artifacts,
integrated them and independently verified. No paid OpenAI coding/verifier calls.

Accepted final cleanup/format run: `run_57bb4e4d0b714af5b85c757c9af7f443`.
Official-SDK protocol test: `run_d540b0f8be484c468998df6f5348ece3`.
Documentation: `run_940018d056254a028e8aa662bec76946`.
Real image call: `run_45c5a29fe884495ca113e073325e76df`, Qwen3.8 answered 'Red',
status completed_unverified, audit clean. Real coding call
`run_0aec2b6f344348528d81683ca0bb54b3` produced an isolated file with an extra
period; code/model outputs still require client review.

Final verification from the actual checkout: **140 tests passed in 71.29s** with
pinned Docker image sha256:f3d8acaebae67ef92df5f9cbeee1f9c562fd7d9d53fb9a6db72469772f0851a5.
Ruff check, format check (106 files), whitespace check, installed launcher help
and real stdio SDK handshake passed. UV lock includes MCP1.30.0. Integrated files
match reviewed candidate bytes; no handwritten implementation fixes.

Eight tools expose models/capabilities, isolated coding, saved runs, paginated
traces, run-owned artifacts, screenshots and PDF page/region circuit analysis.
No paid verifier tool. See docs/mcp.md. Codex local-harness is enabled via the exact
agent-authored TOML block integrated into ~/.codex/config.toml; restart Codex/IDE.
Claude CLI is absent: configuration instructions documented, not live-tested.
Existing phone server, conversations and circuit-case analysis were preserved.

Durable build evidence: ~/.local/share/local-agent-mcp-build/authoring-state
(control ledger/blobs + source workspaces), live-state, vision-state, review.
Reinstallable wheelhouse/scratch dependency directories excluded from archive.
Final source hashes/check report: docs/mcp-build-evidence.json.
Gotchas: compilation/clean audit aren't correctness; inspect complete file reads;
require explicit stopping signals in verification commands, never module stdout;
separate trusted harness root from allowed input roots; signal process groups even
when parent has exited; assert cleanup before emergency test teardown; tests need
full source and offline wheels in Docker. One-file scope succeeded once the
runnable environment and adequate SDK-inspection budget were supplied. Keep
native model outputs unverified until independently reviewed.

## Trace browser sources/project retry started — 2026-10-08

User requested harness-authored trace browser changes via MCP: load arbitrary local trace locations, consolidate MCP build runs, and decide project naming. Design: persistent source catalog/project labels, federated read-only ledgers, no rewriting or copying historical evidence. Name can be provided at source registration; future run/project creation should default from repo/case and reuse it.

Actual installed MCP SDK client invokes `harness_run_code` with local Ollama `qwen3.8:27b`; authoring traces retained at `~/.local/share/local-agent-trace-build`, briefs/results at `/tmp/trace-browser-build`. Isolated snapshots preserve existing repository work.

- `run_043aa825bc954bcebab74f07ce222890`: cancelled after repeated listings under default 8192-token coder window.
- `run_0c2655a42c114175af941ab32aab6a7b`: cancelled after excessive exploration of full snapshot. Operational retry uses existing larger qwen coding configuration in an isolated harness source; product coder.yaml unchanged.
- `run_4798c51855434d3eb7b884814f43fe8c`: standalone catalog draft completed_unverified, audit passed; review found exported-events path off by one and validation/persistence issues.
- `run_9bd64364964c43dbbc801b9c9aea22e8`: agent catalog correction completed_unverified; independent initial normalization/persistence checks and Ruff pass. Additional failure-rollback review remains before final acceptance.
- `run_3445961d96cc43d7a6fb51b63eb583fc`: API task budget_exhausted after looking for modules intentionally absent from minimal snapshot; concrete follow-up supplies interface signatures and prohibits unrelated inspection.

Gotcha: MCP source-root config defaults to a small context and isolated minimal repositories cannot run import-based introspection without full runtime/dependencies. Use narrowly scoped briefs and syntax compilation; independent integration tests run with the full project. No implementation integrated into main workspace yet.

## Trace browser sources and project consolidation completed — 2026-10-08

Local harness agents authored all eight implementation/test/launcher/documentation files; supervising Codex prepared tasks, reviewed exact outputs, integrated them without handwritten implementation, and independently verified behavior. Provider/model: native Ollama `qwen3.8:27b`, no paid coding calls. Task briefs/results retained at `~/.local/share/local-agent-trace-build/review`; provenance hashes: `docs/trace-browser-build-evidence.json`.

Accepted behavior: persistent catalog at `~/.local/share/local-agent/control/trace-sources.json`; browser Add location accepts data roots, control directories, agent.db files, control/runs, run directories, and events.jsonl paths backed by an existing ledger. Native project/source dropdowns group and filter all runs; event/audit/evidence requests use selected source plus run ID; missing sources are isolated. Source databases/blobs stay read-only. Project labels currently apply to sources, not historical event fields. Collect an optional future project name when creating a repository project, circuit case or chat thread; infer a default and reuse it rather than prompting each turn. Standalone analysis docs/JSONL without a ledger are not importable trace sources. Launcher supports global --data-root correctly.

Run evidence: catalog `run_4798c51855434d3eb7b884814f43fe8c`, corrections `run_9bd64364964c43dbbc801b9c9aea22e8`, backend `run_7d327382cfa14c6c80a27af32d7884a6`, backend review `run_1ad9ab6503fb441f80a00eeb95d21d10`, UI final correction `run_07873f07965448488cf17e98345cb8c8`, catalog tests/fixes `run_324ecb3123584ff7a66849e74c25b475` / `run_07ebeacf2c044916b3f54e2cbec99621` / `run_787cb7ac056c4000b155cb2835d087ea`, HTTP tests/fixes `run_a26f241882864b75a39f8dcd79556b8e` / `run_4c2e73d95aac4c61aa5ff276bc0f424c`, launcher/docs `run_d92c78eefe614fcbb4507b399ee20616`, assertion `run_b3054d04600149d08faa8d8905a355e9`, docs correction `run_219f71abd89c4082bf3e2c060037c704`, final import/format `run_24128bd33a824257b07233bf6b731f2b`. Successful authoring status is completed_unverified; independent checks supply behavioral verification.

Gotchas: `run_d2049718ae444d709f7bf6ff30d041c1` UI write proposals were rejected by create-only/expected-hash defaults, then cancelled; exact agent-proposed text was preserved only in isolated review snapshots and corrected by subsequent agent runs. `run_b30345cce781491aacb5b0abe8118002` wrote UI corrections but exhausted its budget looking for unavailable JS tooling; subsequent UI task and real Chromium checks verified final code. `run_a26aa23aff8e46698a555b94d4297727` and `run_65428c035eac42fe8dc4e3a64494abdb` inspected too broadly; tasks were split into narrow snapshots. `run_246addc777524c35846150acff1a4c2a` authored invalid HTTP tests, rejected and corrected through concrete follow-ups. Two MCP cleanup calls returned missing-run-id errors; actual CLI workflow retries completed. None of those failures were reported as verified success.

Validation: 22 focused checks passed; full installed-repository suite **161 passed in 73.30s**, including pinned Docker execution. Ruff check and format pass (109 files), git diff --check and bash syntax pass, launcher --data-root/help tested. Chromium at 390x844 independently checked routing, evidence, registration, filtering, reload persistence and empty-state behavior with zero JS errors.

Operational consolidation: viewer restarted at http://127.0.0.1:8765 and catalog registrations contain **163 runs**: Main harness60, MCP frontend79 (74 authoring +4 live acceptance +1 vision acceptance), Trace browser24. Original databases/evidence remain in place; consolidation is a persistent catalog, not a destructive migration. Real original circuit/MCP/current build events load successfully. Use ./traces to start later.

## 2026-10-08 — adaptive circuit images and agent-created tools (in progress)

User requested both adaptive zoom/image delivery and runtime-created reusable tools.
Codex supervises; local-agent harness authors all implementation and tests.
Source snapshot: `/tmp/local-agent-tool-source` (existing user working tree copied,
large case data and caches omitted). Durable run data and task briefs:
`/home/ruthvik/.local/share/local-agent-tool-build`; viewer:
`./traces --data-root /home/ruthvik/.local/share/local-agent-tool-build --port 8766`.
Stage 1 task: `briefs/01-register-tools.txt`. Actual `uv run --locked local-agent
run --agent config/coder.yaml` implementation run:
`run_7598465bd6f54c0dbd6c1b5462734be2`, native Ollama model
`qwen3:30b-a3b-instruct-2507-q8_0`. Agent outputs remain unverified until independent
review/checks; no implementation has been integrated yet. Doctor passed for the
existing profile and pinned sandbox, including tool continuation and audit checks.

Initial implementation run `run_7598465bd6f54c0dbd6c1b5462734be2` exhausted its
attempted-tool budget after repeated reads; no changes integrated. A temporary
build-profile attempt with `qwen3-coder:30b` failed the actual native tool probe
(`run_702f594ae8164000b22551000fb11fd3`): it emitted function markup as text.
The bridge reported missing run_id because the CLI probe-error output has no
implementation run ID; this is not an authored successful run.
GLM passed its native tool probe `run_fee8bab021854a69821c5ae7e4cf8a2d`.
GLM implementation retry `run_0930a636e3fe4b9d8b40b52c8d59f655` was durably
cancelled after trace review showed repeated reads/context compaction and no
edits. Following existing build evidence, the next task is module-sized with a
temporary 131072-token context and existing coder instructions/policy. All
selected runtime overrides are retained in trace configuration snapshots;
no product configuration is written by Codex.
Independent baseline: `uv run --locked pytest -q`: 134 passed, 27 skipped.

Further attempts (no implementation integrated): GLM module task
`run_94dde849ff1f4bfab594e72f319acdd2` cancelled after missing expected_hash patch
rejections; GLM command-only task `run_1bd3ccef0aa747979d8b140395d7150c` exhausted
budget after repeated cwd/path errors. Qwen3.8 schema wiring task
`run_e6c0876d1a6c49b081f0230cf1dd4909` cancelled after repeated unchanged reads.
A minimal empty-snapshot Qwen3.8 task `run_a2f6088049934bb4844a9b83e81292b2`
authored `src/local_agent/tools/extensions.py` and passed syntax compilation.
Review rejected its permissive BaseModel inheritance; strict Record inheritance
is required. Its new file is retained only in staging, not integrated.
Correction run `run_ae652d4d9bc14c1ba59b8ca9045e629d` exhausted the identical-action
budget after repeated imports of Pydantic, missing from the offline image; no
changes made. Follow-up supplies Python 3.12 wheels matching host Pydantic2.13.5
and directs agent installation under persistent scratch/deps with explicit
sys.path for checks. No product dependency declarations changed.

### Outcome: blocked; neither feature enabled

Corrected schemas/registry draft authored by native Qwen3.8 run
`run_95741118bb06418f85fcfd12e82114d0` completed unverified, audit passed.
Codex independently validated new tool schema exposure/defaults and rejection
of bool page, traversal and nonfinite regions; Ruff checks passed for both files.
Exact reviewed draft and hashes retained in
`/home/ruthvik/.local/share/local-agent-tool-build/review/evidence.json` and its
`src/local_agent/tools/` subtree. These are staged artifacts, not shipped features.

Worker run `run_d8a8cbade8694fd5b8adc30a8d489a5d` (Qwen3.8) exhausted model turns:
large writing argv strings rejected, followed by repeated mkdir calls; generated
worker file was empty. Concrete smaller follow-up task `briefs/12-worker-small.txt`
constrained writing commands below argv limits and used an empty isolated source.
Run `run_bcc041d407e24b2fb09c5ce3523b6c27` also exhausted model turns, repeating
successful directory-existence checks without writing the worker. Both audit
checks passed; that establishes retained trace integrity, not working features.

Implementation is blocked by harness-agent authoring reliability despite
multiple focused retries across installed local models. Missing: sandbox tool
registration/execution, adaptive renderer, new image delivery and recovery,
profile/instruction changes, regression/end-to-end tests. No implementation,
product configuration, dependency declaration or sandbox-image changes were
integrated into the user working tree. Root registry verified unchanged;
new draft module absent from root. Existing source/user changes preserved.
No Codex-authored implementation or paid model fallback used. Last implementation
runs are terminal; no feature-authoring process left running. Baseline host suite
remains 134 passed, 27 skipped. Resume requires a reliable harness authoring path;
do not represent reviewed schemas as completed tools.

## 2026-10-08 — resumed as small MCP tasks

User requested a written plan and small tasks built through actual MCP tools.
Plan: docs/tool-build-plan.md. Briefs/results/staging: .tool-build/mcp; actual MCP
run root verified as /home/ruthvik/.local/share/local-agent-mcp (separate from prior
CLI build root). All implementation/config/test changes remain local-agent authored.
Task01 MCP run run_97a679db1b9b46a1ac790fbc483b6ee4 wrote custom_schema.py,
then was cancelled after repeated create-only writes and context compaction;
its code is reviewed as a draft, never claimed as a completed agent run.
Independent nominal argument checks passed; malformed type values exposed a
TypeError requiring a focused agent correction.
Prerequisite task00 run run_9ab322d9f8154dd4b8fe01383e2649df (qwen3.8:27b),
completed_unverified and audit passed, authored the two coder profile changes:
window_tokens65536/output_reserve_tokens8192. Codex compared all YAML values,
loaded the config independently, and integrated those exact agent-authored bytes.
Model, tools, policy and run limits preserved. This profile addresses generated
exchanges being omitted before the next model turn. Feature code remains staged.

MCP foundation tasks (all native qwen3.8:27b; feature modules staged only):
- Task01 correction run_9e3c4100e1954771800478df3d22a09c completed_unverified,
  audit passed; primitive schema/argument validation independently checked.
- Task02 run_a3905074299348bfb16493ced5a95709 exhausted repeated failures:
  O_DIRECTORY|O_CREAT cannot create Linux directories. Correction
  run_8bdef960b78c4498931495ee312c8562 completed_unverified/audit passed;
  independent tempfile checks covered create/read/traversal/symlink/FIFO/size.
- Task03 run_ce6873d65a1a4418a6ff7ffde310a541 completed_unverified/audit passed;
  independent record roundtrip and code/hash/metadata mutation rejection passed.
- Task04 run_b46c72b1f79e4e23a7a5876fb2357322 failed its native smoke checks;
  temp filename formatting and registry parent path were wrong. Correction
  run_294c86b4e6ce49978f3572374afded4a exhausted turns; draft fixed most findings
  but still used wrong parent path. One-line correction
  run_b20302fa71764bf89bd0447a9b376117 completed_unverified/audit passed.
  Independent write/read checks passed for exact source bytes, actual registry
  directory, duplicate/builtin/newline/unknown-name refusal, separate root
  isolation and metadata mutation. These facts verify code behavior, not the
  success of failed predecessor runs.

Modules staged in .tool-build/mcp/staging/src/local_agent/executor/toolkit;
result copies in .tool-build/mcp/review. No new agent tools exposed yet.

MCP microtasks 05–08 (qwen3.8:27b):
- register_tool: run_069cfbb1a96c40c595b414a454301517; execute_tool:
  run_96709fae24b243469e228b4574faef46. Both completed_unverified/audit passed.
  Independent registration snapshot and argument checks passed; mocked subprocess
  dispatch checked exact code/JSON stdin/isolation flags/cleanup. Actual Docker
  behavior remains pending packaging correction.
- Worker/Docker dispatch: run_66a5830b4a0644d5966bc5b11a39c205 completed_unverified.
  Review accepted minimal routing edits, but real Docker probe found packaged
  mode0600 helpers unreadable by nonroot user. Sent narrow Dockerfile correction.
- Test-authoring run_36b626aff08342d49803f2ddb688e63b needs_reconciliation:
  replacing Docker tag removed configured old image. Restored authoring image
  with project build-sandbox and separately tagged feature image tool-build-review.
- Retry run_bdd58f2933894988bdf5bbdb3c22b0b3 budget_exhausted, no test authored;
  trace repeatedly printed imported register_tool function. Split tests further.
- Feature modules remain staged; runtime/image delivery not yet implemented or
  enabled. Root sandbox.json updated by deterministic provisioning command.

Additional MCP gates (qwen3.8:27b):
- Docker permission fix run_4bcc87b4492545feb4c0963e119e2cf5 completed_unverified,
  audit passed; exact one-line change reviewed. Real pinned Docker registration
  and execute_tool returned expected 42 from JSON input. Authoring image retained
  under local-agent-sandbox:authoring; feature image under tool-build-review.
- Three regression tests authored in run_eba33553f2ab420a9d34776f1daaa109;
  supervisor cancelled repeated identical edits. Independent pytest: 3 passed.
  Retained cancelled run evidence; not represented as a successful agent run.
- PDF snapshot run_9c7b33a357ad43b49d896c7da67bde15 and geometry
  run_0ceabefd2eec40d6a98b11353739db62 completed_unverified/audit passed.
  Independent snapshot/hash/cleanup and rotation/fixed-argv checks passed.
- Image-header draft run_3cefefc35dc54ce281ee5eaa3777d72b budget_exhausted;
  found schema_version wrongly expects string strict1. Correction
  run_df6a0dd855b14747bc7c2fa941be5907 completed_unverified/audit passed;
  exact validation edit reviewed; real Pillow PNG/JPEG metadata and strict
  integer version checks passed independently.
- Render task run_730a691785cf426c9cf054cd82b2f32a budget_exhausted (three
  identical failed import checks), no new module. Split rectangle validation and
  rendering into separate tiny tasks, using supplied API contracts.

Rendering and worker checks:
- render_bounds run_62a8add31c9d42bfb58fcb0a05a550da completed_unverified.
- Render draft run_711e0a8726f4430682c544fa6910da98 completed_unverified but
  review found incorrect crop import, contextmanager API, unsafe mkdir and
  absolute output path. Correction run_4f6b05c209764dd1953e8c2c46a08b44
  completed_unverified/audit passed. Independent real Poppler crop: 300x300,
  expected region and PDF hash, secure relative output.
- Image worker routing run_2cc4cf7d9a0640a1b7b9798b2777744d reviewed as only two
  branches. Real Docker render_pdf_region + view_image passed with matching hash.
  Read JSON from stdout_ref: Poppler warnings may appear in stderr/combined preview.
- Existing worker + Docker regression against new pinned image: 9 passed.
- Result preview run_f81edecfd3654aeda5e3d28d90eb63c5 used wrong success enum;
  one-literal correction run_ef7d481e7f3644e9b8c923b7ac52064a reviewed. Not yet
  connected to runtime.
- JPEG attachment draft run_136a1173ea4547afbedd57637cc33176 cancelled on repeated
  identical writes; review findings sent back: validate before decoding, preserve
  MemoryError, flatten palette transparency. No unreviewed draft integrated.

Host capture/runtime gates:
- Attachment encoding correction run_0bd60b2bff964ebca24e276911131c89 reviewed;
  independent bounds/transparency/invalid-input checks passed.
- Artifact helper attempt run_db0b2a9f812341f48c7415e2293e197a exhausted repeated
  discovery without source. Split into lookup run_a8f25696eecc473eb11b2226ed1cfbba
  and save/fix run_5636bdb1d90449d19c67128ad77288d0. Reviewed actual signatures.
- Capture draft run_b85917660e7d453584d14d82f55ad5a4 had multiple incorrect
  imports/helper calls. Correction run_01c84d6053ec40109e92902f72eccaab reviewed;
  real Docker + host capture check passed for ownership, idempotency and reused
  captured descriptor after deleting workspace image.
- Attachment builder run_a7a7eb74cdc740d992cefbd63d307d5e authored both provider
  formats. Review found invalid attachments silently omitted; correction included
  in runtime wiring run_9afb61030fa245ba83462c0c01cdb484. Checkpoint now stores
  individual exchange blobs so accumulated images do not exceed one blob limit.
- Model-loop attachments run_7cf8b756cf3944c9afa1c436dd8cc311 reviewed: all tool
  replies precede user image messages. Recovery wiring
  run_5169257af51e40f8a72e803978e37b3a reviewed for finished/published result reuse.
  Both native runs completed_unverified/audit passed; independent recovery checks
  and complete regression remain pending.

Later acceptance checks:
- Runtime scripted Docker run verified next payload roles assistant/tool/tool/user,
  with image attachment after both replies; full audit passed.
- Budget draft run_dae6b17b89fe47198c37515f5c9365dc incorrectly tested oldest
  group/whole history. Correction run_96183a17f734404dab18f51231391998 reviewed;
  independent newest-image refusal and older-image compaction passed.
- Circuit export draft run_caedb0ff969a403b90e6140473e45b8b read wrong page field
  and used random export id. Correction run_c6e660306a2349ba817c44ef93d68e20
  reviewed as two exact fixes; final circuit regression still pending.
- Broad staged pytest: 136 passed, 27 skipped, one failure caused by compaction
  test assuming old production coder context. Local-agent correction
  run_caf76136476743e1a748acceba731016 explicitly sets small test context and
  preserves all assertions. Complete rerun pending after remaining tests.
- Toolkit image fingerprint additions run_ba3672ce49094aa9859fec879bc8e401
  reviewed: build records exact helper hashes; doctor requires rebuild on mismatch.

Permanent tests and corrections:
- Image tests run_630f7b4f676940709566b51a4f2c1c84 cancelled after draft;
  independent draft tests 26 passed/4 failed (incorrect I/O exception expectations
  and rounding constants). Correction run_8a273ca5fd464f1bbb2d02befd56f38a
  completed_unverified; independent final image tests: 33 passed, including real
  PNG/JPEG metadata and transparent attachment encoding.
- Standalone delivery-test run_428fbfaca6f74628bbf4c93efd080c93 exhausted discovery
  of missing config; richer retry run_be0b35fe9fcc4596984b1f3752e83835 cancelled
  while reading unrelated implementation, no file authored. Switched to extending
  existing circuit Docker regression.
- Circuit test addition run_897d973968a9402698f85c7576a4e43c produced draft with
  wrong request/path assumptions. First correction run_dd5fc59917dc4c73ab07d15ec90d40cc
  exhausted package discovery without edits. Two-line snapshot correction
  run_063334868da84487969eda49c41ca69e completed_unverified. Remaining correction
  run_6213b62c906a4e06b6d62626467afe82 fixed format/ref checks but still used wrong
  export base path. Two identifier corrections run_ae372373ac5944c38e49cd9ac29b91f9
  reviewed. Docker circuit regression now executing; results not yet claimed.

Final-stage supervision:
- Circuit Docker tests with adaptive crop/export checks: 4 passed independently.
- New instruction/profile runs run_d5020757340b4713ab72eb5859337528 and
  run_97c420d5064f4c328a108aa96f077d95 reviewed. Old instruction string hashes
  preserved; coder-v3 has 9 tools, analog-v2 has 11, both configs load.
- Fresh MCP SDK session is used for remaining tasks against assembled harness,
  because existing IDE MCP process caches old registry/instruction modules.
  It still invokes real harness_run_code and uses the same local-agent-mcp data root.
- Fresh MCP lint fix run_f5d52e13fa704253b2a7e49565d92f81 reviewed; source Ruff
  passes. Native 9-tool capability probes passed (run_1695ad47b8d74b7d8af7be4803087bd4,
  run_875cc5e579674d199864f6d42f665f97). Updated pinned image includes helper hashes.
- Crash-driver task run_0090756e6c8544198874252b83e04c27 exhausted repeated
  git-show inspection without writing. Split copy, source/tool change and hook
  filtering into separate edits; crash image verification remains pending.
- Full assembled suite, including pinned Docker: 197 passed in 72.98s.
- Crash driver copy run_d0cb84b154e548f5a38e91ec914d1e7d completed_unverified;
  exact original driver copy reviewed before separate image-specific edits.
- New image recovery driver run_4c28de43e33347a88067444de0ee873d and regression
  draft run_dfdbad4adef9466ebc7895c45f9a04d4 reviewed; correction
  run_a73368e000854d35818616adb0430a75 fixed imports/API and a tautological
  assertion. Independent Docker crash-recovery checks: 2 passed. New test import
  ordering still needs local-author lint correction.
- User asked about model inputs and Docker/host boundary. Phone profile intentionally
  supplies no execution tools; phone-v1 instructions explicitly say so. Host writes
  DB/blob/export traces and sends model messages/schemas; Docker receives a single
  validated ExecutionRequest over stdin, baked worker dispatch and workspace mount.
  Exact inputs exist behind model.requested -> request_ref -> context_ref -> payload_ref.
- User authorized two local LLMs. Tried qwen3-coder:30b; native probe run completed
  but behavioral gate failed (run_9dc31ff120ee44a8a694bc0fadc13a3b,
  run_08730ab7523d4ad8a55930c5a1918573, run_4d88a70d2ca1449c83955c93076b484e).
  MCP masked CLI error as missing run_id; diagnostic CLI output confirmed actual
  capability failure. This is not an authored feature success. Concurrent coding
  attempts also encounter shared run lock, so tasks remain sequential.
  Trying glm-4.7-flash:q8_0 for a small visible model-input trace button.
- GLM native probe run_3d1bcbbd0e4945a88829068f5de4f279 passed; trace UI draft
  run_5394692624ac475da325bb20680e5573 authored by glm-4.7-flash:q8_0. Review
  found only two evidence hops, wrong tool-count target and a missing JS brace.
  GLM correction run_05f1cd597e734725a028b5cc9a74fab5 budget-exhausted on exact
  patches; no accepted edits. Sent concrete marker-based rewrite to Qwen.
- GLM docs run_07f301a6cc814e19a9e16bb71d0e475f reviewed; Qwen correction and
  Docker helper test run_dcaeced22c89436e8279c0ec53c29988 fixed internal-vs-MCP
  tool names and input payload wording. Docker test draft failed create-only
  validation; sending literal creation/hash format corrections (implementation
  unchanged; these are test assumptions).
- Native local vision check used real captured crop and reviewed image_messages
  Ollama encoding from Docker circuit run_86eb39b20fc345e7b82c288db0cd7fd6,
  execution exec_a085113f9819414f960c434ba731d21b. Qwen3.8 read 'R1 10K' from
  pixels; request/response saved .tool-build/mcp/review/native-vision-*.json.
  This verifies vision access/text readability, not schematic classification accuracy.
- Reviewed core authored changes integrated into root working tree (39 exact files)
  plus previously verified generated sandbox.json. Source lint passed in root.
  Root analog doctor passed all kernel/storage/telemetry checks with 11-tool native
  capability probe run_34337bd6562b4dd89fa8856fd7085af8 and sandbox probe
  run_2492d75fa3764b2faf5fe1914d8c620a. Image sha256:30954288105c2934db8d34b2b6b3187376d044db4aec40f79193ba78669036fd.
- Trace rewrite run_9fcb932f105d40de909876b2bb112ca5 corrected syntax/imports
  but still skipped a context hop; rejected. GLM hop run_78e28b3b82eb4b898c051c7b790cba83
  failed Ollama500 after partial invalid edit, rejected. Narrowed snapshot to exact
  extracted render() function. Qwen run_3a17b0816bda43379d1353d12fda73d0 adds
  correct three hops but dropped one closing brace; one-character follow-up sent.
  Codex integrates exact local-authored function into original HTML; no handwritten
  implementation. JS functional checks pending final brace correction.
- Helper test correction GLM run_5ec8bebc1765461d9f159c4d1ca72004 fixed creation
  but ignored hash-prefix requirement; Docker assertion exposed mismatch. Qwen
  run_369809831a504cca8e957e1fd17341b4 exact hash correction reviewed/integrated;
  final Docker regression executing. This is a test correction, not production change.
- Trace final brace correction run_ad30dc193da54ec582654cc1f5e6a318 reviewed;
  integrated exact function authored across GLM/Qwen drafts and corrections.
  Independent GJS verification passed: exact wire messages, three evidence hops,
  captured source/run routing, absent/empty tool explanations, invalid refs,
  and stale selection. Actual HTTP evidence ownership chain passed against MCP
  run_5394692624ac475da325bb20680e5573; system instructions and 9 native schemas
  visible. Existing browser ownership/security routes unchanged.
- Final helper Docker regression: 1 passed. Source mutation does not affect captured
  execution; strict bool rejection, duplicate/reserved names and stdout provenance.
- Fresh root MCP native helper smoke run_e09f46eb9501497db74b00f4a921aa5d,
  qwen3.8:27b, completed_unverified. Actual register_tool and execute_tool succeeded;
  captured stdout includes name/version/code_sha256 and {"result":42}.
  Independent read of execution records and audit passed. No project edits in smoke.
- Root full suite with pinned Docker: 200 passed in 83.62s. Root Ruff passed;
  git diff --check clean. Reviewed image/helper/runtime/profile/doc changes and trace
  UI integrated; source authored by real local harness runs via MCP. Codex authored
  briefs, review notes, supervision utilities, exact integration and verification only.
- Trace root for MCP builds: /home/ruthvik/.local/share/local-agent-mcp;
  derived event exports control/runs/<run_id>/events.jsonl, authoritative agent.db
  and blobs under control. Host owns trace writes, Docker can modify only bind-mounted
  workspace. Refresh trace UI HTML; restart existing MCP process/IDE session to
  reload cached Python tool/instruction modules. Phone-v1 remains screenshot mode
  tools=[], explicitly described in config and instructions. No phone workspace or
  execution feature was requested/added.

- Final default coder doctor passed all checks. Native 9-tool capability probe
  run_355723fdc22649d491dad67104f4a0b0 used configured local
  qwen3:30b-a3b-instruct-2507-q8_0; sandbox probe run_fe9c51a6276e40c495a1e7f2fc033c8c.
  Both default profiles now verified; no default model change. Final exact integration
  comparison: 41 reviewed files, zero mismatches. All planned acceptance gates complete.

## Browser interface/profile editor work (2026-10-09)

User requested public browser naming, selecting any config, creation/editing in the
browser, and documentation of all configurations. Existing docs are incomplete:
phone guide plus MCP coder/analog sections, without a full config reference.
Plan: docs/browser-interface-build-plan.md. Preserved prior uncommitted feature work;
isolated current source snapshot .browser-build/assembled; author tasks via native
MCP qwen3.8/GLM only. No paid model test calls. First task: profile validation.
- Initial profile validator run_0cc7c8fdf3c44e748b2f3ea91db3f468 exhausted failed
  imports in partial snapshot; GLM run_68c7e76bf4a44767b987da2399e02ddf looped
  searching nonexistent symbols, no accepted source. Default Qwen3 metadata
  run_92a1f4b002404550ba7212976c1e0753 and draft validator
  run_7072c957b5304f6ab8eaa2aa40c256cb completed_unverified but review rejected
  wrong signatures, self imports and invalid config assumptions. Switched back to
  Qwen3.8 with complete source/offline Python3.12 wheels, explicit review findings
  and actual existing-config checks. No rejected drafts integrated.
- Complete-source validator retry run_88630f53dda148c39f781587fa37a9e6 exhausted
  discovery with no edits. Switched to literal correction microtasks:
  run_2f95810f2516413880064cc646742de0 (imports/name),
  run_25e04a1b663a42dfbb7f2ff7bfe30eeb (filename argument),
  run_9e4a8c8dbaae40428e3e48db2a4236fe (image/schema/errors).
  Exact resulting validator reviewed and staged. Independent all6 configs passed;
  malformed scalar/unknown tool/whitespace/bool schema errors rejected; Ruff passed.
  Product source remains isolated until complete browser flow is verified.
- GLM config documentation run_2621f6d226364751ba4380fac09519c9 wrote a draft but
  exhausted repeated create-only README replacements. Review found wrong analog
  CLI example/field descriptions; concrete docs-only corrections prepared.
- Config read helper run_0573fade66e74dd4a24908b1214c7507 compiled, but independent
  read check found incorrect os.path.isfile(mode) and leaked directory fd.
  Draft not staged; fixes assigned separately from atomic write addition.
- Secure read correction run_eeb17be83bbc4d269346eb83e3dc0f88 reviewed.
  Independent traversal/symlink/FIFO/oversize rejection and 100-read FD count passed.
- Atomic-save runs run_0f0da03e32a44d76946e97439052cdff (failed missing import)
  and run_3ff22eca846e418e80f4f520219ada52 (draft failed temp-name/open flags)
  both budget-exhausted. Draft reviewed; follow-ups fix temp creation, conflict
  errors, update branch and profile-count logic. No draft writes to root config.

- Atomic publication/count correction run_c6e817dc7dbb44e788f85c9a3cfa9d77 reviewed: exclusive creation, hash replacement, five concurrent writers, profile limits and cleanup passed independent checks.
- Catalog run_ec59c385f1fc457fba8cabbb7c70a495 exhausted turns after writing a draft. Micro correction run_c59ad2c1700f4fed96d88052d8e40c87 completed_unverified (qwen3.8:27b); exact files reviewed into isolated assembled/staging. All six config loads, create/update/conflict/invalid repair and unsafe-name exclusion passed independently. Authenticated API authoring is next.
- Config API run_6cdcf9eaeb8b479da2428c4e906f4355 and correction run_bc7edffe0f8040a6b029af06108f8eb3 (qwen3.8:27b) reviewed. Independent pairing/Origin/create/conflict/invalid API checks passed. Sandbox scalar JSON rejected after review correction.
- Request validator run_63cced0eda6d4656938bb1d365001ec3 and microfix run_2f306eea9ef44f879e4b046a67599cdc reviewed. Chat/coding/PDF routing, trusted roots, bool page, missing PDF and null/NaN region checks passed.
- Browser capture adapter run_9ce83327268e45128e66dca018d3e697 plus event/bundle registration run_41902d18ae514bac85d9f6b6a60c67c8 reviewed. Independent captured image/history/provider-message/audit checks passed; native Docker read_file/view_image smoke completed_unverified with audit.ok. Browser default config/instructions run_359ad22012434925839d84acd1e1bdc3 preserves original PHONE_INSTRUCTIONS bytes.
- Dispatcher run_cb6f28f93fa14b9896d19900ef7c679f exhausted repeated searches for an omitted BrowserAgent dependency; added named dependency files to isolated snapshot and launched retry. Config-guide correction delegated to GLM in separate root ~/.local/share/local-agent-browser-docs. Product changes remain isolated pending full browser flow validation.
- Broad dispatcher retry run_bcb5d518a831414a8a6b3e048671fa2a exhausted repeated reads. Minimal contract task run_032f36b66d2d426a98ff0598fc74a371 produced draft; corrected native API usage via run_d8e61f79584e4de199d3b8622d3fe2ef and basic-request subset via run_e9975d0fe57f428692135c66f8466dcb. Independent browser/phone/coder native dispatch passed with audits; import-failure result enrichment needs correction.
- Profile turns run_cdd0955e4a2f4fffa42a96ad24f0b921 drafted incorrect dict/tuple/image APIs. Follow-up run_43bc0ab49828409895e0358d6fbd4120 corrected them; independent selected config/tool preservation, frozen config, pending job rejection and provider guard passed.
- Archive exclusion run_9700075b20ce4fca94ed3b76600f6b05 reviewed and independently checked. Both workspace and baseline copies exclude internal .tool-build/.browser-build; source bounds remain unchanged.
- GLM docs correction run_22e039d995704423af5cc2cdf2eb8836 failed transport after incomplete duplicate edits. Qwen rewrite run_02a6d74520f54fcfb9449a7d3f05cda0 produced clean guide; final fact/example corrections assigned.
- Browser controls run_fb7a3341445a484ba2e8ce29772456f5 wrote draft then exhausted identical missing JS-interpreter package imports. API-shape, visibility/model/clone/region review findings assigned; no JS dependencies added. Supervisor will check with host GJS.
- CLI/launcher run_b5f1427a3dd24e599a79c58335ab440d corrected imports/default verifier via run_e8fe8f13bc06495a85cf5a90a00fa388. Independent browser-web help/launcher help passed. Frozen browser-vs-legacy subprocess route run_a4027e1574f2413096e79636b0d25a4b passed mocked checks; artifact retention follow-up remains.
- Broad server run_22015067b27e44d9aac616a1f98a9286 exhausted missing package import attempts with no edits. Small constructor/naming run_a34c820ab2d948f79a4aaf5a595cee77 reviewed; BrowserServer/Handler aliases preserve old imports. Profile routing broad run_eb55b484a59b4489b64d65509932ce45 exhausted searches for omitted dependency defs. Full-source retry launched.
- Runtime failed-import correction run_6b8f50ff64dc4a058fbc1b188ba457f0 independently passed: original import error preserved without missing attribute exception.
- UI draft fix run_3e677ad80d984e71b25a69dea1e41dc6 hit output token cap. Compact run_7c4925ca21f844a7bcf4f24f274f0ee9 wrote then exhausted line-count edits leaving syntax error. Exact micro corrections run_bfcfcb2aec334256ac0433b0711d2792 and run_71cef8edd6dd4a9987ec3db5a382f839 reviewed. Independent host GJS DOM checks passed selection/visibility/default+override/editor-load/save/conflict/clone/regions/busy; source staged in isolation.
- Config guide rewrite final facts/examples run_9ad78c474c094c06ae114ad49bbb320e reviewed and staged. No root product integration yet.
- Authoring-only profile run_8e71d8b0f4da44df88a330f908d9a004 created six file tools (no model commands/helper execution) in .browser-build/authoring. User default coder tools unchanged; host supervisor executes checks. Test draft run_7beec74b49fe43ca9e6f45eb7e0b1143 still exhausted missing digest/canonical definition searches; full source supplied for retry.

- User requested coder output reserve increase: actual MCP author run_187ee019caa74e8bbd81353357521455 (qwen3.8:27b, trace root ~/.local/share/local-agent-browser-reserve) changed only output_reserve_tokens 8192→16384 in main and isolated authoring coder profiles. Integrated exact authored scalars; independent load and generated Ollama request verified num_predict16384/num_ctx65536. Other settings unchanged.
- Job artifact retention/null-image correction run_93dde277647540bd8410704e9f6205f2 and server routing/assets/info run_a0c51107e9f845458fda0a9e9f7ac7ef completed_unverified and reviewed into isolation. Legacy chat regression 21 passed/3 Docker checks skipped without image. Full server metadata/ask wiring still pending.

- Page draft run_08a074296eca4b98af64c14101ec4ec6 exhausted after meaningful edits; correction run_ca68f457658e4c9ebf02e1692ef52856 reviewed/staged. Independent GJS page startup/model default/profile submit checks and config component DOM checks passed.
- Request tests run_a07cbe16f0b54c45b9e8a19bd94d7bba corrected import via run_25e70b4372c34afd8a3ef52af558c7b2; 42 tests passed independently and Ruff passed. Main existing mobile native checks24 passed with pinned Docker image.
- Actual local Browser CLI smoke run_332512c92ba6460d8896292f61aa595e (qwen3.8:27b; ~/.local/share/local-agent-browser-smoke) completed_unverified with audit.ok and expected answer.
- Broad profile-test run_69df9a2eb2de48c3b0d4eec029569c06 exhausted unrelated source discovery without authoring tests. Server finishing run_f246202f421d4a9ca7f4b527d5b5c8c6 similarly only read unrelated dependencies; cancelled via actual CLI, no edits accepted. Assigned narrower literal methods/tests to qwen3:30b-a3b-instruct-2507-q8_0 via actual MCP for comparison; no direct Codex implementation.

- Coder comparison: run_24ce9c0a7abf4442a366ab3b564f66e2 failed repeated nonexistent project/Path reads. Runtime test draft run_f0939b646a804b58a7c0e3d5282d5b37 rejected invented APIs/missing import (not integrated). Qwen3 metadata run_5dbc72638b1b41ff80556e87fd7817a0 repeatedly read truncated file; cancelled without edits. Qwen3.8 CAS test run_f005f2d052ab4552aac4ec00f9fad0d1 corrected invalid stale stimulus via run_adef495d838440c3a313d903b251d38b; independently1 passed/Ruff passed.
- README/browser generic model-label run_71dfdc0ff0dd4dca80b579ff2f38ba1f reviewed/staged. Combined docs run_20360734b7934ef6b9a9daf9ba281f06 exhausted discovery. Guide run_8ff58522a6cd4777b9086f6913face3e cancelled after supervisor omitted docs directory in snapshot; fixed snapshot and resubmitted.
- Isolated authoring max_model_turns60 change authored run_a6f534728b1347b399ff6fce7007f55d (qwen3.8:27b, browser-smoke root); exact scalar-only delta reviewed/applied only .browser-build/authoring/config/coder.yaml. Main coder remains30turns. This allows inspected dependencies plus authored edits before budget exhaustion; does not claim implementation or verification of remaining tasks.
- Runtime rewrite run_e4935c31914647b6bd42a4de3e9ccfff exhausted source exploration without edits. Narrow native BrowserAgent/view_image test assigned using existing native screenshot test as unchanged source reference and exact contracts.

- Final metadata method run_9f43e34ab72f4eaf904f61f7a3e1c9f9 reviewed/staged. Independent authenticated HTTP matrix all6 agentprofiles passed exact model/tools/mode/frozen config/saved metadata/artifact preservation; sandbox separately editable. API editor create/update/conflict/invalid checks passed. Earlier context-finish run_cd52dabd29c345a395b43692fc8f0161 and HTTPtest run_3e95181f365a422e9e2e4a6d40db10eb exhausted30turn source exploration; latter retried with60-turn authoring profile.
- API branch run_d1c5bf18bb2a4cccbeda3ff1fbf779e4 rejected incorrect jobid and missing429handling; corrected run_9528fd7520dd4313a050c3a173328e24. Integrated exact authored diff into isolated assembled/staging preserving separate authored metadata changes; independent standalone browser API400/actualjobid/completion/429 tests passed. Ruff fullsource/tests passed at this checkpoint.
- Guide facts run_499ba05d1ca94f6bb5cc311487607e14 reviewed: aliasdefaults, discovery, control/blobs, coder16384. Legacy links run_e9c49946178645608ab64bfa69e079f6 misplaced MCP heading; placement run_9abcf25038da4289b1dcec0ae4994d37 and tool-name wording run_1932c7cf4b724846b762f312653ce97d reviewed/staged.
- Independent netlist compatibility reproduction: BrowserServer(browser.yaml) froze browser-v1 cfg for legacy screenshot controller, incompatible with required phone-v1/tools(). Targeted normalization+tests assigned to local harness; fix not yet verified.

- Native test run_37dff291f40244e8879afd06f7402f54 and HTTP test run_57f8902e19a44723858decd6e1bfec19 exhausted1200s reading dependencies despite60turns; no test edits accepted. Private authoring instructions authored via actual MCP run_ba023fd24a7a452d867d37f688835d4d (qwen3.8:27b), exact two-file diff reviewed/installed only .browser-build/authoring. Existing product instructions unchanged; supervisor checks remain independent. Local summary claimed verified, but run status is completed_unverified and no tests were run by this agent.
- Independent assembled checkpoint: full pinned-Docker pytest243passed (63.78s), Ruff fullsource/tests passed, GJS config controls/page startup/default-model/submission checks passed, all6-profile authenticated HTTP matrix/editor checks passed. New native/HTTP regression authors and netlist compatibility fix are still running; root feature integration remains pending.
- Independent native BrowserAgent/view_image acceptance passed using real pinned Docker and ScriptedProvider: uploaded bytes copied to scratch/browser-upload.png, actual tool schema/diagnostic preserved, helper image delivered on second model request, durable raw evidence reachable and audit.ok. This supervisor probe is independent validation, not an agent-authored permanent test.
- Registered5 existing Browser author/runtime trace roots through current trace viewer source-catalog API at127.0.0.1:8766; existing3 sources retained. Verified output-reserve author run_187ee019caa74e8bbd81353357521455 appears in viewer catalog. Viewer needs no access token; browser pairing remains separate.
- Scoped prompt retry native run_5dd4e7306c624f05ada7fabf0b90da7b cancelled24turns, netlist run_55c3fcdf5ea342c98ae4a66c6f57f8eb and HTTP run_dd9e38c7457b42a4a582bf5a560f62f1 cancelled after continued dependency discovery; no edits accepted. Concrete follow-ups use deliberately minimal relevant-source snapshots with exact contracts; netlist implementation separated from tests.
- Final Browser wording authored run_9bd52a3811da4b2c80204da65410ceda; one exact reader error string change reviewed/staged, GJS page check passed. Native regression authored run_40483d00543d4bc6879ae16117ff9f2a, corrected payload/diagnostic/import assumptions run_fef031fa27594fed8007580310bc0b04, final import+actual helper-delivery assertion run_38deb7d64b3d4ee0bda7cf01a878996a. Initial native draft test failed TypeError and Ruff; no failed draft will enter root.
- Netlist normalization authored run_423a1a8b534a4109ac03e3f0721f20d5, exact3-hunk diff reviewed/staged, independent browser/coder compatibility probes passed normalized instructions/hash/tools and preserved model/budgets/limits. Regression authored run_282ff84718f8401cb830e2038dc36852. HTTP regression authored run_cdab60738b8f4a0086ece1e5e398b95f; review/pytest rejected dict iteration, fictional Profiles.get/job.config/request.profile_name; correction authored run_bafd902abe884cac99757ffccb93b85a. All these actual MCP authors used local qwen3.8:27b; completed_unverified remains distinct from supervisor validation.
- Independent final targeted pinned-Docker regression/legacy web checks8passed, full Ruff source/tests clean; root integration copied31 exact reviewed staged agent-authored artifacts with SHA256 manifest and unchanged-root baseline checks. Private authoring-v1 instruction version/runtime and60turn profile were NOT integrated into product. Root preserves original user changes; no commit/reset performed. Full integrated verification follows.
- Integrated root verification: full pinned-Docker pytest247passed (60.72s), Ruff source/tests clean, GJS page/config controls passed, launcher syntax/help and gitdiff whitespace checks passed; hashes match31 reviewed artifacts. Doc billing wording run_d2d04ceaf95d4720a46488b544adfd09 rejected because it incorrectly said reviewing a model never incurs billing; literal clarification assigned to local author (no draft copied into root).
- Final docs correction authored run_fb69830b1c3a49a2b72ab59dc71c6d11 (qwen3.8:27b), exact text diff reviewed/integrated: config selection/editing does not invoke inference; paid remote answer/review requests may charge; openai-local uses local endpoint. Documentation-only follow-up, no extra test rerun needed. Browser feature integration complete with247tests passed/Ruff+GJS clean. Existing running browser caches old assets and must be restarted with ./browser to use new UI; running trace viewer8766 retained and current build roots registered.

- Operational browser restart: ./browser failed with another coding run owns this data root because idle legacy phone-web PID1359654 held ~/.local/share/local-agent/phone/locks/active-run.lock. Confirmed no queued/running browser jobs; SIGINT shut down old server gracefully. Started ./browser --host192.168.0.40 at existing LAN address/port8767 using existing saved state and new browser.yaml default. Verified live asset200/auth401/pairing200/browser info and7valid configs (6agent+sandbox). No implementation/config changes or model invocations for this operational recovery; trace viewer8766 untouched. Pairing code deliberately omitted from progress evidence.

## Two-profile/config-editor cleanup (2026-10-09)

- User approved consolidation to coder/analog, browser config editing fixes, and necessary MCP compatibility updates. Codex inspected root dirty state and copied current source into `.config-cleanup/source`; baseline SHA256 manifest in `.config-cleanup/review/baseline.json` preserves existing user work.
- Actual `harness_run_code` invokes `local-agent run` subprocess. Local qwen3.8:27b authors: UI run_014ad8547db244ac8f2b19fdc4f21024, analog run_1aa249861138459eb513fd6fe6a3507d, MCP run_6b00e6d39ab740f9b3bd955806af47a8, defaults run_d4a165613b9d49abb04a2223a6c8642c. Per-task trace roots `~/.local/share/local-agent-config-cleanup-{ui,analog,mcp,defaults}`. Task briefs/results under `.config-cleanup/review`. Existing private authoring harness used for file-only tasks; product coder config used for defaults task requiring filesystem moves. No paid APIs invoked.
- Initial UI invocation used relative repo path and MCP rejected it before an author run; corrected to absolute paths. Agent completion remains unverified until diff review and independent checks. No product changes integrated at this checkpoint.

- Review/retry findings: initial analog and MCP tasks performed unrelated dependency searches and were cancelled before accepted source changes. qwen3-coder:30b MCP run_78623f5f7f31446aa17f88d8d012c64e authored three files but missed screenshot profile mapping; run_2ff0fd5d5171438e9e20ca9c58ef918d corrected the mapping but failed requested whitespace/docstring cleanup. These changes remain isolated and are not working end-to-end yet.
- qwen3-coder:30b routing run_5045d9f3ba1e4c97aa5ee92906fbb2fd completed_unverified, but review found PDF mode still analog_image, analog workspace ignored, all v3 screenshots rejected by thread resolver, and stray PDF fields accepted. Concrete follow-up briefs written; this completion is NOT verified behavior.
- First test author run_e0d83ef364c24c1fa7d57b3e7f0dcc7c rejected for nonexistent modules, duplicate functions, placeholder pass assertions, and wrong paths. Later test drafts also invented runtime APIs/omitted tool registration and are not accepted. UI run_d9273e647d854b358cf63bfb9cbf3f48 failed at output cap16384; draft retained, no root integration.
- Analog instruction retries hit patch exact-match and stale-hash failures; an incorrect import would shadow global TOOL_INSTRUCTIONS. GLM follow-up run_432c2b82dc0f4a6e94cce84d79b1782b similarly failed repeated patch matching. Root defaults retry failed capability probe (coder prompt mandates list_files but probe exposes only read_file); role-neutral probe correction assigned, no checks weakened.
- Concurrent local inference requests queued and delayed progress; supervisor cancelled unfinished jobs and switched to serialized, minimal correction tasks. All drafts/traces under per-task local-agent-config-cleanup roots and `.config-cleanup/review` are retained. Current product root remains unchanged by this cleanup; only governance progress notes written.

- Final supervision checkpoint before authorship clarification: retained43 actual runs including capability probes; no run is still running. `.config-cleanup/review/runs.json` lists IDs/status/data roots; findings.md records exact acceptance requirements and rejected drafts. SHA256 comparison confirms ALL root product files match the pre-task dirty snapshot. No failed drafts integrated. Only isolated static checks passed; end-to-end intended behavior is NOT implemented/verified.
- Serialized GLM saved-image author run_6f8693bf92634b7bb3e0ac98f196b763 completed_unverified but v3 PDF conditional was unreachable under legacy-only set. Follow-up run_a4f273b1b4db4e00abf01bb674bb9ff1 reversed image-present check; independent saved-image/PDF isolation assertions failed. No further model jobs remain. Supervisor requested explicit user authorship decision under AGENTS.md direct-coding exception; dependent implementation awaits that answer.

## Model reliability history proposal (2026-10-09)

- User asked whether tasks were decomposed, all installed models were tried, and consistent model outcomes recorded; proposed making outcome history a harness feature. Tasks were split into UI, instructions, routing, MCP, defaults/docs/tests, then smaller single-file corrections. Three of five installed models tried for this cleanup: qwen3.8:27b, qwen3-coder:30b, glm-4.7-flash:q8_0. qwen3:30b-a3b-instruct-2507-q8_0 and qwen3-vl:32b-instruct-q4_K_M were not tried in this cleanup.
- Extracted durable manifests into `.config-cleanup/review/model-run-inventory.json`, separating author runs from capability probes. Author statuses: qwen3.8 seven supervisor cancellations; qwen3-coder four completed_unverified/four cancelled/one budget_exhausted/one failed; GLM two completed_unverified/one budget_exhausted. These are runtime outcomes, not correctness scores. No complete cleanup implementation passed independent verification. Partial MCP changes were useful but unfinished.
- No controlled evidence supports a consistency ranking: different tasks/settings/inference contention, supervisory cancellation, contradictory probe instructions, patch failures and incorrect tests are confounders. Prior qwen3.8 browser work did produce independently checked integrated changes; that does not establish a comparable reliability rate for this task.
- Existing evaluation.suite/report already derive timing, tool failures, retries and fixture verification from durable evidence. Proposed extension: durable supervisor review outcomes per run/artifact, task-family summaries by exact model identity/settings, verified/partial/rejected/unreviewed/cancelled distinctions, evidence links, sample counts, and explicit conditions. Automatic recording on runs; correctness only recorded after checks/review. No automatic model routing until sufficient comparable evidence.

## Config consolidation paused at user request (2026-10-09)

- User requested stopping jobs. Supervisor terminated the active request-routing harness CLI and its MCP orchestration processes; independent process and Docker checks found no remaining harness run processes or containers. No further jobs will be launched while paused.
- New isolated attempt uses qwen3-vl:32b-instruct-q4_K_M. Probe run_236385ded9a8463d97a3cc91c05696ea passed. Analog-profile author run_5c03d417984f4492b6cffd564c675790 produced reviewed changes in `.config-consolidation/assembled` only; config loading, shared helper instructions, and Ruff checks passed. No root product changes integrated.
- Browser-routing run_ff0d6a87a3c440f1bfe226ebebe5ad79 failed repeated exact-match patches and its partial draft rejected screenshots; rejected. PDF-instructions run_938bd406154244019f979824cdd6979e failed repeated missing-dependency searches; dependency added to a follow-up snapshot but no follow-up started. Request-routing follow-up was stopped by user; artifacts and traces retained under `.config-consolidation` and local-agent-config-consolidation data root. Overall consolidation remains incomplete and unverified.

## 2026-10-26 — Docker lifecycle work (in progress)

User requested host-controlled ephemeral/persistent Docker execution, workspace isolation, idle expiry, recovery, and correlated traces. Plan and task briefs: `.browser-build/lifecycle/review/`. Existing uncommitted files preserved in an isolated assembled snapshot; baseline SHA-256 inventory is `baseline.json`. No product changes integrated yet.

Baseline independent check: `uv run --locked pytest -q` → 216 passed,31 skipped (Docker-dependent tests require explicit image option). Docker daemon available. Authoring uses actual MCP `harness_run_code` → `local-agent run`, private `authoring-v1` profile, Ollama `qwen3.8:27b`, no paid model.

Contracts author run `run_31bf9247f2d1476c98e6d53ae3f94aff`, workspace `ws_c7d01a36b6b74812a30f51f8bd29f407`, data root `~/.local/share/local-agent-lifecycle-contracts`: completed_unverified, audit OK. Reviewer copied only contracts/events/test files to assembled snapshot. Ruff passed. Independent tests:45passed3failed because authored test helper omitted pre-existing required nullable duration_seconds field. A narrow correction task was sent to local author; no supervisor implementation fix. Manager and worker authoring runs remain in progress, with separate data roots local-agent-lifecycle-manager and local-agent-lifecycle-worker.

Design constraints found during review: published per-command result precedes commit/release; keeper exit status is not command outcome; unknown mutations must never replay. Completed run events are immutable, so later cleanup requires a correlated maintenance audit run. Readonly/offline restrictions remain; workspace venvs are durable already, persistence does not permit global package installation. These changes do not by themselves establish improved task success rate.

Lifecycle review update: contracts correction `run_f4c721db5d8f4cfbb6ddb51dd81b69a2` (qwen3.8) fixed test helper; independent settings suite48passed. Worker initial `run_8a16a678b6c743ddac1fd039afab4393` completed_unverified; review found7test failures (invalid test assumption, patching os.open instead of builtin open, readonly stdin.buffer mock). Reviewer also found regex trailing-newline acceptance. Comparison correction with local qwen3-coder:30b `run_f4a43b614090421ca7363544ac900275` exhausted identical-action budget; its partial duplicate constant was rejected. Follow-up to qwen3.8 contains exact locations and failures.

Manager initial `run_9ba6d415657d43f5908f51925d69140a` completed_unverified but rejected for audit-failure swallowing, cleanup lock probe/release race, stale EXECUTING reuse, missing ownership/attestation in removal paths, and terminated manifest overwritten IDLE. Follow-up `manager-fix.md` covers corrections. During that run supervisor supplied an exact unchanged copy of existing storage/blobs.py as reference context; it is not an implementation artifact to integrate.

Executor initial qwen3.8 run `run_57d3d31eaa1d4f2ea383234f758aa95d` was durably cancelled after alternating repeated searches for absent def append/def put without edits. Retry includes actual unchanged storage APIs. This is authoring failure evidence, not feature validation. Product changes still isolated in assembled snapshot.

The user explicitly authorized Codex to implement the remaining changes after repeated local authoring failures: “Allow Codex to implement the remaining changes.” From this point, remaining implementation/tests/fixes may be Codex-authored. Earlier drafts and run traces are retained; no claim that local agents authored subsequent supervisor fixes. Review of acquire run run_0560656737e54989a8cdbf4570dfa7ce found it claimed ownership/config mismatch corrections that were absent from the file. Session run run_772729c3be3b4088a5c986245d7cae10 did supply useful exact methods; still pending behavioral verification. Real-Docker baseline before changes:247passed.

## 2026-10-26 — Docker lifecycle implementation completed

Implemented and integrated after the user's explicit direct-coding authorization.
The final production implementation is **mixed authorship**: the local qwen3.8
contracts/events work and worker protocol draft were retained with supervisor
extensions/fixes; the final lifecycle manager, reaper, executor/runtime/recovery
integration, additional tests, and documentation were implemented by Codex.
The rejected local manager and executor replacements were not shipped as working
implementations. No paid models were used.

Evidence and provenance:

- Task briefs, rejected drafts, review utilities, and baseline hashes:
  `.browser-build/lifecycle/review/`.
- `authoring-runs.json` records 30 local run/probe IDs, models, statuses,
  workspace IDs, and host data-root locations. These include unsuccessful,
  cancelled, and unverified attempts; their statuses are not test results.
- `integration-manifest.json` inventories 23 integrated files with original
  baseline hashes and final SHA-256 hashes. Existing user modifications were
  preserved; original destination hashes were checked before integration.
- Actual authoring traces remain under
  `~/.local/share/local-agent-lifecycle-*`, written by the host harness.

Final behavior:

- Ephemeral remains the compatibility default; every tool-enabled profile can
  opt into persistent execution through the new `execution` configuration.
- Persistent containers are workspace-owned, locked across processes, capacity
  limited, security-attested, and reused through `docker exec`. Environment/cwd
  are explicit per command; workspace files survive removal.
- Default idle expiry is 1800 seconds. A detached host reaper performs cleanup,
  records maintenance in the existing audit store, skips active workspaces,
  and avoids creating empty polling runs. Owned orphans and deleted workspaces
  can be cleaned safely.
- Per-command mappings/results preserve identity, timestamps, durations,
  command argv, separate output blobs, and error status. Maintenance events
  retain originating run/execution/tool-call/trace correlation.
- Persistent recovery never treats keeper logs/exit status as command success.
  Missing published results require reconciliation; uncertain mutations are not
  replayed. Recovery cannot stop a keeper used by a later execution.
- CLI operations: `local-agent containers list`, `cleanup`, and
  `stop --workspace ws_<id>` (global `--data-root` precedes `containers`).
- Current policy remains offline/nonroot/read-only with existing security
  ceilings. CPU/RAM settings are bounded; enabled network is rejected.
  Trusted bootstrap/verification/diff tasks remain ephemeral.

Validation on final working-tree code:

- `/home/ruthvik/.local/bin/uv run --locked pytest -q --docker-image sha256:d57539bd8f15561112b981b48fc362ae673dea03ba4f759728c45ae0be6a31da`
  → **351 passed in 108.72 seconds**, including real Docker and process-crash tests.
- `/home/ruthvik/.local/bin/uv run --locked ruff check src/local_agent tests`
  → **All checks passed**.
- CLI `containers --help`, empty-root `list`, and empty-root `cleanup` exercised.
- Earlier baseline 247 tests and intermediate 348/350 test suites also passed.
  A final deleted-workspace cleanup regression was discovered while removing
  validation containers, fixed, and included in the 351-test result.
- Test-created keepers from earlier recovery checks were removed through the
  verified ownership cleanup path; no unrelated containers were selected.

The trusted worker image was rebuilt and `config/sandbox.json` now pins
`sha256:d57539bd8f15561112b981b48fc362ae673dea03ba4f759728c45ae0be6a31da`.
Usage, all seven settings, trace paths, architecture, and limitations are in
`docs/executor.md`; README, guide, configuration reference, and MCP docs link it.
Persistent coding is opt-in, not yet the default. This work establishes execution
behavior and traceability; it does not claim improved LLM task success rate.

## 2026-10-26 — Executor package review and developer README

Reviewed all executor modules (including toolkit), related contracts/runtime,
Docker packaging, tests, and lifecycle documentation. Preserved pre-existing
working-tree modifications using `.executor-review/source` and SHA-256 baselines.
No behavioral fixes were applied in this pass. Findings and reproduction details
are in `.executor-review/findings.md`:

- Custom-tool mutations are reported as `side_effect_status=none`; a real Docker
  probe successfully wrote a project file and confirmed the incorrect metadata.
- Helper-manifest commands leave `/tmp/helper-*.py` behind in persistent keepers;
  a real Docker probe confirmed the leftover after successful execution.
- Schema validation counts ASCII-escaped JSON while execution counts UTF-8 JSON;
  a 30,013-byte Unicode execution payload is rejected as 90,013 bytes.
- Legacy `base.Executor`/`MockExecutor` dictionary interface differs from the
  live `ExecutionResult` backend; replay has its own recorded-result reader.
- The obsolete M0-only package description was corrected in this pass.

Local-agent authorship and review evidence:

- Initial authoring: `run_c1ae6047ccad425d965818a2460ec81e`, local
  `qwen3:30b-a3b-instruct-2507-q8_0`, completed_unverified. Rejected as a finished
  result: invented commands, incorrect environment/replay/lifecycle claims,
  duplicate protocol in __init__, missing lifecycle link.
- Correction: `run_96a4add4670a4d91ae9c0f344cfbeb4b`, same model,
  budget_exhausted (`three identical failed actions`, patch conflicts). Retained
  drafts as input, not proof of completed work.
- `qwen3-coder:30b` retry failed its capability gate; probe
  `run_4bc333faec644580940d7f37d2f4def8`. No authoring run or integrated changes
  attributed to that model.
- Final authoring: `run_4e27881496d54abe99e55c3fc561b754`, local `qwen3.8:27b`,
  completed_unverified, audit ok (151 events, 154 checked blobs). Independently
  reviewed and integrated its exact three files: `docs/executor/README.md`,
  lifecycle-guide link in `docs/executor.md`, and docstring-only update to
  `src/local_agent/executor/__init__.py`. The final run corrected earlier drafts;
  the README and docstring have local-agent draft/correction provenance.
- Task briefs, task-specific configs, CLI results, baseline and integration
  manifests remain in `.executor-review/`. Authoring traces and generated
  workspaces remain under `~/.local/share/local-agent-executor-review*`.
- Codex authored the review findings and this progress record, not the shipped
  implementation or README. All runs used actual `uv run --locked local-agent
  run`; no paid models were invoked. Initial probe IDs are in CLI result files.

Independent validation:

- Full current-tree suite with pinned real Docker image
  `sha256:d57539bd8f15561112b981b48fc362ae673dea03ba4f759728c45ae0be6a31da`:
  **351 passed in 95.99s**, including crash recovery.
- Focused worker/options/lifecycle/settings/custom-tool/image tests: **131 passed**.
- `uv run --locked ruff check src/local_agent tests`: passed.
- After documentation integration: executor lint, compileall, Markdown target
  existence, docstring-only AST, destination baseline hashes and scoped
  `git diff --check`: all passed. No behavior changed after the full test run.
- Review probes stopped their owned persistent keeper and removed their temporary
  workspace. The behavioral findings are coverage gaps despite the passing suite;
  a completed authoring run is not itself evidence of correct behavior.

## 2026-10-26 — Executor inconsistencies fixed after direct-authoring authorization

The user explicitly authorized Codex to author these executor changes directly:
“you go ahead and author these changes.. don't have to use locals”. The final
implementation, new regression tests, README amendments, and verification were
completed by Codex. Earlier local drafts informed the shared-serializer design;
none is being reported as a successful, verified local-agent implementation.
Existing unrelated working-tree changes were preserved. The eight pre-existing
files changed by this task match the saved task baseline apart from these fixes;
new regression tests are in two separate files.

Changes:

- `DockerExecutor` reports arbitrary `run_command`/`execute_tool` side effects as
  unknown even on failure. Successful writes, patches, registrations and PDF
  renders report applied; unsuccessful typed mutations conservatively report
  unknown. Read-only operations retain none.
- Trusted helper-manifest execution captures code inside a private temporary
  directory managed by `ExitStack`. Cleanup covers success, nonzero exits,
  subprocess exceptions, header publication failure, and snapshot creation/write
  failure. Exact-byte hashes and immutable helper evidence remain intact.
- A shared stdlib-only UTF-8 JSON serializer enforces 65,536 bytes for host
  argument schemas, worker validation, and subprocess stdin. This additionally
  fixes the host's premature ASCII-escaped-size rejection, discovered by the
  new real-Docker regressions. Non-finite values remain rejected. Registration
  parameter sizes use the same byte policy.
- Added `LiveExecutor` with typed dispatch/options/result and release methods;
  retained legacy `Executor` and scripted MockExecutor unchanged in behavior.
  Docker method annotations match the live capability. Backend-specific recovery
  APIs and synchronous recorded replay remain separate.
- Updated `docs/executor/README.md` with interfaces, mutation semantics, cleanup,
  UTF-8 limits, and regression-test command.
- Rebuilt the sandbox using `uv run --locked local-agent build-sandbox`;
  `config/sandbox.json` pins
  `sha256:a4eb1c5633b5e83bbef63da7d23fd3543a0143381809f3314621bdfc1f29ed63`
  and updated worker/toolkit fingerprints. Dockerfile/base/dependencies unchanged.

Authoring attempt evidence retained in `.executor-fixes/`:

- Broad local `qwen3.8:27b` run `run_ac8868ca3e20436d947e7954d742a2b1`:
  budget_exhausted (model turns), no changes. Capability probe
  `run_63583930654f40e2982eb37725d0892b` passed.
- Narrow Unicode run `run_d38a3aa7680b440dbf69d9f86bd7f84f`, same local model:
  budget_exhausted. Production draft was useful, but tests had a syntax error
  and incorrect byte-boundary arithmetic; host verification rejected the draft.
  Capability probe `run_d8cb3a4c5bcb49929dd5609c2720c4ab` passed.
- Helper run `run_274b9faf943a4a27b08f89cae7a6dea8`, same model, was durably
  cancelled after direct-authoring authorization. Its isolated worker/test draft
  was not integrated. Capability probe `run_5070b1677d8948468396c6887752310e` passed.
- Task briefs, baselines, run results, build result and final hashes are retained.
  Actual traces/workspaces remain under `~/.local/share/local-agent-executor-fixes*`.
  No paid models were invoked. No local coding runs remain active for this task.

Validation:

- New regressions: **14 passed in 9.04s** against the rebuilt pinned image.
  These include actual custom-tool mutation followed by success/nonzero exit in
  both modes, host/worker/subprocess Unicode payload consistency at the exact
  limit and one byte over, PDF output mutation metadata, helper exception
  cleanup, and repeated persistent helper execution without leaked snapshots.
- Full suite: `uv run --locked pytest -q --docker-image
  sha256:a4eb1c5633b5e83bbef63da7d23fd3543a0143381809f3314621bdfc1f29ed63 --tb=short`
  → **365 passed in 116.21s**, including real Docker and crash recovery.
- `uv run --locked ruff check src/local_agent tests` → all checks passed.
- Pinned image existence/nonroot configuration, source fingerprints,
  typed return annotations, README links, and scoped whitespace checks passed.
- Gotchas: use the image ID returned by Docker inspection / sandbox.json, not
  the build-export config digest. PDF previews combine stdout and stderr;
  regression assertions parse structured results from the separate stdout blob.
- All four behavioral/interface findings from the executor review are now
  addressed. The review's stale package description was fixed in the earlier
  documentation pass. Passing tests validate these behaviors, not model coding
  success rates.

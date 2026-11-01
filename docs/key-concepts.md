# Local agent harness: foundations, concepts and glossary

These learning notes describe this repository as inspected on November 1, 2026.
They explain the architecture and operating vocabulary; they do not certify any
particular candidate or run. The checked-in configuration and a run's frozen
configuration take precedence over examples in documentation.

## 1. The foundation: what the harness does

An **LLM (large language model)** generates outputs from supplied inputs. An
**agent** repeatedly uses a model to decide what to do next, often requesting
tools and examining their results. An **agent harness** supplies the machinery
around that loop: instructions, tools, permissions, execution, context management,
budgets, storage, recovery and verification.

In this project, the main responsibilities are:

| Component | Responsibility |
| --- | --- |
| Model | Propose actions, generate code and explain results. |
| Provider adapter | Translate requests and responses for Ollama or OpenAI-compatible APIs. |
| Controller/runtime | Orchestrate the run, enforce limits and preserve evidence. |
| Tool interface | Expose structured operations such as reading files or running commands. |
| Policy engine | Decide whether a validated operation is permitted. |
| Docker executor | Execute generated commands and file operations in the configured sandbox. |
| Ledger and blob store | Retain durable records and exact evidence. |
| Independent checks/reviewer | Assess the candidate using recorded tests and review criteria. |

The model service runs outside the tool container. Docker resource limits on a
tool do not limit the host Ollama model in the same way.

Typical flow:

```text
Task + profile + source revision
  -> model request
  -> proposed tool call
  -> schema validation + policy decision + durable dispatch intent
  -> sandbox execution + recorded outcome
  -> tool result returned to model
  -> repeat within budgets
  -> completion checks + candidate publication + final status
  -> optional authorized review -> separate merge action
```

See [architecture](architecture.md), [executor lifecycle](executor.md) and
[the functional manual](functional-manual.md).

## 2. Model and inference vocabulary

| Term | Definition and relevance here |
| --- | --- |
| Inference | Running a trained model to generate a response. Ordinary agent runs use inference; they do not retrain the model. |
| Provider | The service/API serving inference, such as Ollama or an OpenAI-compatible endpoint. Protocol compatibility alone does not guarantee identical capabilities. |
| Model tag/ID | The exact selected model identifier, including a local variant where applicable. Record it when comparing attempts. |
| Quantization | Representing model weights with lower precision to reduce storage and memory requirements, potentially changing speed and quality. A tag containing `q8_0` identifies a quantized variant. |
| Prompt/context | The information sent on a particular call: instructions, task, selected conversation, tool schemas and other supplied evidence. |
| Token | A model-specific unit of text or other encoded input/output. A token is not a word, and token counts do not measure correctness. |
| Context window | The configured total token allowance for input and generated output. It is not permanent memory. |
| Output reserve | The portion reserved for a response; the remaining allowance is the input budget. |
| Temperature | A generation sampling setting. A low value reduces variation but does not prove correctness or guarantee repeatability across backends. |
| Vision capability | Support for image inputs. It must be available in the selected model and provider interface. |

The inspected `config/coder.yaml` selects
`qwen3:30b-a3b-instruct-2507-q8_0`, with a 131,072-token window and a
32,768-token output reserve. That leaves a configured input budget of 98,304
tokens. This arithmetic is a budget, not measured usage or a promise of model
quality. Some older overview docs show smaller values.

See [configuration](configs.md) and the actual [coder profile](../config/coder.yaml).

## 3. The agent loop and structured tools

A **turn** is an interaction step in the model loop. A **tool call** is a
structured request naming an operation and its arguments. One response can
contain multiple tool calls, so turns and tool attempts have different budgets.

A **schema** defines allowed fields, types and structure. This project uses
strict Pydantic records and versioned tool schemas. **Validation** checks that a
request fits its contract. **Authorization** checks whether policy permits the
operation. Neither establishes that the requested action is useful or correct.

For example, a valid, permitted file patch can still implement the wrong behavior.
The recorded execution outcome establishes whether the operation ran; tests and
review assess whether it solved the task.

A **tool allowlist** restricts exposed operations. A **policy profile** defines
controller-enforced rules. Tool output, repository text, saved memory and model
prose do not grant new permissions.

## 4. Context management, compaction and memory

**Compaction** reduces the information included in later model requests so they
fit the input budget. Here, fixed instructions and the task remain present;
selection can omit whole assistant/tool exchange groups. Omitted exchanges
remain in immutable evidence, and `context.compacted` records their lineage.

The context estimator considers the complete request, including tool schemas,
and uses conservative byte-based estimation rather than an exact tokenizer.
Actual provider input counts are checked before model-proposed dispatch.

Three different things are often called memory:

- **Active context:** what the model receives on its current request.
- **Workspace memory:** ordinary files the model can inspect; these are untrusted data.
- **Durable run state:** controller records and checkpoints used for recovery.

A file existing on disk does not mean the model currently knows its contents.
Continuation preserves workspace files but does not automatically supply the
entire earlier conversation. Give follow-up tasks a clear goal and evidence paths.

See [context and helpers](context-helpers.md) and
[the context builder](../src/local_agent/runtime/context.py).

## 5. Identity: chat, job, run, workspace and commit

| Identity | What it identifies |
| --- | --- |
| Chat/thread ID | A saved conversation containing multiple submissions. |
| Job ID | A browser submission; a review job can involve several underlying runs. |
| Run ID | One agent attempt with its own events, budgets and evidence. |
| Workspace ID | The editable project and support directories retained across continuations. |
| Execution ID | One tool execution attempt. |
| Container ID | A Docker instance; persistent instances can serve multiple executions. |
| Base commit | The exact source revision an attempt starts from. |
| Candidate commit | A published snapshot of the agent's proposed code. |
| Reviewed commit | The exact snapshot covered by a workspace review. |

These identities are related, but have different lifetimes. A new run can reuse
the same workspace; an old review can refer to a commit older than its current files.

See [runtime data](runtime-data.md).

## 6. Git worktrees and candidate isolation

A **commit** identifies a recorded Git snapshot. A **branch** is a movable
reference to a commit. A **worktree** is a separate working directory attached
to the same repository, allowing an agent to edit its own branch.

For existing Git repositories, a new coding task normally starts an
`agent/ws_<id>` branch/worktree from committed `HEAD` or an explicitly selected
revision. Staged, unstaged and untracked source edits are excluded and preserved
in the source checkout. A source directory without its own repository is
initialized before creating a managed worktree.

**New task** creates a new workspace. **Continue task** reuses an existing
managed workspace, retains pending files and creates a fresh run. Starting a new
task from an unchanged source branch does not include another worktree's
unmerged feature.

The **working subdirectory** focuses the task and default command directory;
it does not restrict access to the rest of the imported repository.

Publication creates a candidate. Review assesses that candidate. Merge integrates
it into the intended source branch. These are separate actions.

See [Git workspaces](git-workspaces.md).

## 7. Sandboxing, trust boundaries and attestation

A **sandbox** is a restricted execution environment. A **trust boundary**
separates components allowed to make authoritative decisions from untrusted
inputs and generated code. Here, generated commands and file operations execute
in non-root Docker containers with offline networking and resource limits.
Protected control records remain outside the writable workspace mount.

An **image** is a container filesystem template. An **immutable image ID** pins
the exact built image rather than relying on a mutable tag. A **bind mount**
makes a host directory visible inside a container; workspace edits therefore
persist on the host.

**Attestation** is captured evidence of the effective execution protections,
such as image, mounts and limits. It supports checking what actually ran.
It does not prove the generated application behaves correctly.

`AGENTS.md` also establishes an authorship agreement: local harness agents write
implementation and tests; supervising Codex prepares tasks, reviews changes and
verifies results. That agreement is guidance, not a filesystem permission barrier.

See [the working agreement](../AGENTS.md) and [executor lifecycle](executor.md).

## 8. Ephemeral and persistent execution

**Ephemeral execution** creates a container for an invocation and removes it
afterward. **Persistent execution** reuses a compatible workspace-owned keeper,
retaining container-local state such as `/tmp` and background processes until
replacement, expiry or cleanup.

Each command still starts a new process: a previous command's shell `cd` or
`export` does not automatically carry over. Workspace files survive container
removal. Independent checks and workspace review use separate copies/containers
so they do not depend on a potentially modified coding session.

Persistence of code, container state and model context are three separate concerns.

## 9. Environment preparation and capabilities

A **dependency** is software a project needs. An **environment inventory**
records what the selected image provides. A **capability** describes an available
function, such as Node execution or interactive browser testing.

Preparation is separate from ordinary execution. When authorized, the controller
can build/select a prepared image using allowed downloads; this does not enable
network access inside ordinary coding or test containers. Dependency preparation
can use committed locks and cached images for reproducibility.

**Discovery** finds an installed tool. A **self-test** demonstrates a capability
works. Chromium being present is weaker evidence than a successful click/type/
reload/persistence self-test. A browser self-test is still separate from testing
the project's actual user flows.

See [environment preparation](environment-preparation.md) and
[browser verification](browser-verification.md).

## 10. Durable evidence, event ledgers and hashes

**Durability** means committed records are designed to survive process failure.
The authoritative ledger is SQLite at `<data-root>/control/agent.db`.
The immutable blob store retains exact inputs, outputs and artifacts.
JSONL event files are derived exports rather than the authoritative database.

An **event ledger** records ordered facts such as proposal, validation,
authorization, dispatch intent and outcome. **Causal edges** connect records
that depend on earlier records. A **transaction** commits a set of database
changes together; model and container operations do not run inside long SQLite
transactions.

A **blob** is stored content. A **content hash** is a digest of its bytes;
content-addressed storage uses that digest to identify evidence. **Canonical
JSON** serializes equivalent supported records consistently for hashing and
comparison. Hashes detect changed bytes; they are not signatures proving that a
host owner could not tamper with the system.

An **evidence reference** such as `blob://...` points to retained content.
Knowing a hash does not grant access. The evidence resolver permits bounded
reads of authorized same-run outputs/artifacts. A preview can omit relevant
output, so inspect retained evidence when needed.

See [architecture](architecture.md) and [traces](traces.md).

## 11. Checkpoints, resume, replay and reconciliation

| Term | Meaning |
| --- | --- |
| Checkpoint | Committed runtime/conversation progress used to reconstruct a run. It is not a correctness certificate. |
| Resume | Recover a nonterminal run, check compatibility and reconcile pending execution state before continuing. |
| Continue task | Start a new run using an existing managed workspace. |
| Recorded replay | Reconstruct behavior from saved model/tool interfaces and outcomes with no live inference or real tools. |
| Reconciliation | Determine what actually happened when an interrupted operation has an uncertain outcome. |
| Idempotency | The property that repeating an operation has no additional effect beyond the first application. Arbitrary commands and mutations cannot be assumed idempotent. |

A crash after an edit but before a durable result creates uncertainty. The
harness must not infer success from a start event or blindly repeat a mutation.
`needs_reconciliation` makes that uncertainty explicit. An audit failure while
publishing evidence can also stop dispatch without successfully recording a
new terminal state.

Backups/export bundles preserve evidence for inspection/replay; they do not
automatically restore mutable workspaces or active Docker state for continuation.

## 12. Verification, audit, review and approval

| Concept | What it establishes |
| --- | --- |
| Model completion claim | The model says it has finished; inspect actual changes and outcomes. |
| Audit | Recorded evidence and protocol invariants are consistent within the audit's scope. |
| Independent controller checks | The configured tests actually executed against a fresh snapshot, with captured results. |
| Protected verification | Configured protected task checks passed; the scope depends on those checks. |
| Workspace review | An inspection of a specific candidate, its code, tests and execution evidence. |
| Approval | The candidate satisfied the review gate's requirements; it does not automatically merge. |

`completed_unverified` means completion was accepted without passing a protected
task verifier. `verified` means configured protected checks passed. A general
coding candidate can have passing project checks while retaining the former
status. `failed`, `budget_exhausted`, `cancelled`, `needs_reconciliation` and
`audit_unavailable` describe other outcomes; inspect their evidence and reasons.

A conversation-only review cannot inspect candidate files or approve a workspace
for merge. Approval covers the reviewed commit; subsequent code changes need
their own assessment.

## 13. Meaningful tests and reproducibility

A **regression test** checks that a specific unwanted behavior stays fixed.
A **behavioral assertion** exercises behavior and checks the result. Merely
finding a string in source code usually provides much weaker evidence of a fix.

The shipped coder enables controller project tests. Automatic Python testing
and committed `.local-agent-tests.json` contracts define how checks run. The
controller freezes the owner's existing contract so a model cannot weaken that
contract during the same attempt to obtain a pass.

Distinguish assertion failures from collection errors, zero tests, timeouts and
missing environments. A command that could not run is not a passing test.
Interactive behavior requires actual interaction checks; a DOM dump only
establishes a narrower observation of page structure.

**Reproducibility** means retaining enough exact inputs, source commits,
dependencies, image identities and commands to repeat or inspect a check.
A lockfile pins dependency resolutions; it cannot make an inadequate test suite
complete. Fresh-snapshot execution helps expose reliance on hidden session state.

See [project tests](project-tests.md) and [browser verification](browser-verification.md).

## 14. Repair loops, budgets and paid review

A **repair loop** iterates on findings. A **finding** states observed behavior,
expected behavior, impact and acceptance criteria. The controller-owned repair
ledger retains goals, findings, actual file changes, checks and blockers across
context trimming and recovery.

Repeated reads or capability probes do not necessarily advance the repair.
Bounded recovery redirects stalled attempts and can stop a reviewed repair as
`local_stalled`. Missing-capability memory also prevents identical futile command
retries when the relevant source/image/arguments have not changed.

**Budgets** bound model turns, tool attempts, context, output, time and evidence.
The inspected coder profile allows 60 model turns, 100 attempted tool calls,
1,200 seconds per run and 360 seconds per model call. Other enforced limits
can stop a run earlier. Larger budgets do not guarantee useful progress.

Paid review is explicitly enabled/authorized. Automatic review eligibility
requires a completed local attempt, audited published candidate and audited
passing independent checks; fingerprints prevent duplicate automatic spending
on unchanged candidate/evidence states. Stalling does not trigger a paid rescue.
Approval and merge remain separate.

Token reports measure work rather than quality or dollars. Missing usage remains
unknown/partial. Reported reasoning tokens are a breakdown already included in
output usage and should not be added to output again.

See [local repair reliability](local-repair-reliability.md).

## 15. Operational vocabulary and data locations

The **data root** selects a complete runtime state location; it is independent
of the source checkout and selected model profile. Its default is
`~/.local/share/local-agent`. Alternate development roots have separate records.

| Location relative to the data root | Purpose |
| --- | --- |
| `phone/threads/` | Saved chats. |
| `phone/jobs/` | Submissions, frozen configurations and job reports. |
| `control/agent.db` | Authoritative run/event database. |
| `control/blobs/` | Immutable evidence. |
| `control/git-workspaces/` | Source/branch/workspace/candidate mappings. |
| `sandboxes/<workspace-id>/project/` | Editable project files. |
| `control/containers/` | Host-owned persistent execution manifests. |

**Observability** means being able to inspect what happened using traces,
reports, timings and metrics. A **trace** shows related operations; a **span**
measures one operation within that trace. OpenTelemetry supplies instrumentation,
while the durable ledger supplies the retained execution evidence. A
`model.requested` event with provider `harness` records a controller operation,
not paid or local model inference.

Server logs describe server operations and can contain private pairing
credentials; they are separate from run traces. Do not copy pairing codes,
API keys, authorization headers or complete environments into reports.

Read-only inspection commands, with the correct data root and actual run ID:

```bash
uv run --locked local-agent --data-root /path/to/state trace RUN_ID
uv run --locked local-agent --data-root /path/to/state audit RUN_ID
uv run --locked local-agent --data-root /path/to/state report RUN_ID
uv run --locked local-agent --data-root /path/to/state replay RUN_ID --recorded-only
```

Global options such as `--data-root` precede the subcommand. Use
`uv run --locked` for project commands; inspect CLI help before using unfamiliar
options. See [runtime data](runtime-data.md) and [operations](operations.md).

## A practical reading order

1. Learn the loop: model proposes, controller authorizes, executor runs, evidence records.
2. Track identity: source revision, workspace, run and exact candidate commit.
3. Understand context limits and why disk persistence does not imply model memory.
4. Read actual test outcomes and distinguish audit, verification and approval.
5. Learn recovery before resuming interrupted mutations.
6. Use traces to diagnose failures and send concrete follow-up tasks to local agents.

For an attempt you care about, ask: Which source revision did it start from?
What changed? Which exact candidate was checked? Which checks actually ran?
What remains uncertain? Has that exact reviewed commit been merged?

# Harness characteristics and implementation

A harness should help a capable model make measurable progress, preserve its
work, and verify the result. This guide maps the characteristics we want to the
mechanisms in this repository and the documentation/source that owns each topic.
It describes the current checkout; it does not certify every generated project
or imply that a running server has already loaded a newly edited module.

Our work-allocation goal is to **minimize output tokens from paid sources while
maximizing useful output tokens from local models**. Local models should produce the
implementation, tests, and detailed repair work. Paid models should inspect a
candidate and return compact, actionable findings. Correctness and independently
verified progress remain the acceptance criteria; generating more tokens alone
is not success. [Section 11](#11-token-efficiency-and-local-work-allocation)
explains the mechanisms and remaining limits of that goal.

For operating instructions, start with the [user manual](functional-manual.md).
For terminology, use [key concepts](key-concepts.md). For durability and execution
invariants, use [architecture](architecture.md). Exact limits belong in their
linked references rather than being copied into this guide.

## 1. Good context management

**Goal:** supply the task, relevant evidence, and unresolved work without allowing
repeated inspection or irrelevant history to dominate the next model request.

The context builder retains fixed instructions and task text, adds tool schemas
and selected complete exchanges, and trims exchanges to fit the configured
input budget. Omitted material remains in immutable evidence with compaction
lineage. Identical successful inspections within an uninterrupted inspection
sequence are coalesced while retaining the latest exchange. Tools return bounded
previews and references for retrieving more evidence.

Browser continuation assembles a bounded task bundle with the original goal,
selected attempts, previous findings, and unresolved checks. Repairs and paid
reviews maintain separate progress summaries so a successful unrelated suite or
context trimming does not erase a known failure. The local continuation-history
setting and the paid review context are different mechanisms.

This is selected working memory, not a guarantee that every old conversation or
file is visible to the model. Persistent containers do not enlarge model context.

Read: [context and helpers](context-helpers.md), [review context](reviews.md).
Code: [ContextBuilder](../src/local_agent/runtime/context.py),
[tool-result previews](../src/local_agent/runtime/tool_results.py),
[continuation context](../src/local_agent/mobile/task_context.py),
[repair ledger](../src/local_agent/runtime/repair_progress.py),
[review progress](../src/local_agent/mobile/review_context.py).

## 2. Clear tool interfaces

**Goal:** make actions predictable and give the model enough feedback to correct
an invalid request.

Strict contracts and a versioned tool registry define arguments, workspace paths,
command arrays, timeouts, and overwrite conditions. The runtime normalizes and
validates proposals before policy evaluation and dispatch. File replacements and
patches use content hashes to detect stale edits; paginated reads expose hashes
and continuation cursors. Correction guidance explains path roots, exact-match
patches, and valid overwrite arguments rather than hiding rejected calls.

The trusted worker performs the actual file/command operations inside Docker.
A separate controller resolver handles explicitly authorized same-run evidence
reads. A model knowing a blob reference does not grant access to arbitrary
control records. Clear schemas and feedback help the model; they do not ensure
that every proposed command is semantically correct.

Read: [tools and workspace authority](guide.md#tools-and-workspace-authority),
[context/evidence retrieval](context-helpers.md).
Code: [contracts](../src/local_agent/contracts.py),
[tool registry](../src/local_agent/tools/registry.py),
[correction guidance](../src/local_agent/tools/guidance.py),
[dispatch](../src/local_agent/runtime/agent.py),
[worker](../src/local_agent/executor/worker.py),
[evidence resolver](../src/local_agent/runtime/evidence.py).

## 3. Reliable execution environments

**Goal:** provide a known environment and distinguish a missing dependency from
an application defect.

Execution uses identified Docker images, verified mounts/isolation settings, and
resource limits. Ordinary tool containers are non-root, offline, and use a
read-only image filesystem plus the writable workspace and temporary storage.
Model capability probes check an actual tool round trip, rather than relying
only on advertised model metadata.

Local coding models can request an inventory and declarative environment
preparation. The host validates the request, builds or reuses a derived image,
records its immutable identity and readiness evidence, and selects it for later
execution. Downloads require the applicable provisioning grant. Continuation and
review inherit the originating coding run's prepared environment; the Python
test adapter can also prepare dependencies from committed project metadata/locks.

Ephemeral and persistent modes change container reuse, not worktree identity or
model memory. Persistent `/tmp` and background processes can survive calls until
the keeper is stopped; project artifacts belong in the mounted workspace.
Unsupported dependency sources and failed preparation remain visible blockers.

Read: [execution modes](executor.md), [environment preparation](environment-preparation.md),
[project environments](project-tests.md), [capability probes](model-capability-probes.md).
Code: [Docker executor](../src/local_agent/executor/docker.py),
[container lifecycle](../src/local_agent/executor/lifecycle.py),
[environment service](../src/local_agent/environments/service.py),
[test environment adapter](../src/local_agent/testing/environment.py),
[model capability checks](../src/local_agent/models/capabilities.py).

## 4. Durable state and continuity

**Goal:** retain code, task identity, and evidence when a model stops, a budget
expires, or a controller fails.

SQLite records ordered events and state transitions; immutable blobs retain
requests, responses, arguments, and outputs. Checkpoints retain conversation and
execution references. An exclusive controller lease prevents concurrent coding
controllers for the same data root. Recovery reconstructs committed state and
reconciles uncertain execution rather than silently replaying mutations.

Git workspaces preserve the user's source checkout and pending edits. Continuing
a task reuses its managed worktree and agent branch with a new run ID. A review
repair is bound to its saved workspace/candidate identity; stale targets are
rejected. Container lifetime, worktree lifetime, and model context are separate.
Recorded replay checks saved history without invoking live models or tools.

Hashes establish integrity, not a signature against the host owner. An audit
failure or unresolved execution is not made successful just to unblock a task.

Read: [Git workspaces](git-workspaces.md), [runtime data](runtime-data.md),
[recovery procedures](operations.md#recovery).
Code: [database](../src/local_agent/storage/database.py),
[blob publication](../src/local_agent/storage/blobs.py),
[checkpoints/runtime](../src/local_agent/runtime/agent.py),
[recovery](../src/local_agent/runtime/recovery.py),
[worktree management](../src/local_agent/workspace/git.py),
[saved-review repair](../src/local_agent/mobile/repair_controls.py).

## 5. Useful recovery

**Goal:** respond to the actual failure with a targeted next step instead of
repeating ineffective actions or immediately escalating to paid inference.

Failure classification distinguishes missing executables/dependencies, bad
project paths, resource exhaustion, and test/assertion failures. Recorded failure
facts bind a command and directory to measured file contents and the selected
image. Repeating an unchanged known failure can be suppressed with explicit
feedback; a relevant file or environment change permits another attempt.

The repair ledger measures inspection, reproduction, edits, validation, and
recovery interventions. Unresolved checks remain until a passing rerun of that
command/directory. Bounded recovery eventually stops stalled work while retaining
files and evidence. Hard browser-controller timeouts can retire abandoned runs;
uncertain executions still require reconciliation. Cancellation and recovery do
not manufacture passing results.

Progress signals are heuristics, not a proof of useful reasoning. A capable
model can still stall, a legitimate investigation can exhaust a budget, and a
prepared dependency does not establish that the application is fixed.

Read: [repair policy](local-repair-reliability.md),
[tool-failure recovery](browser.md#recovering-from-local-tool-failures),
[operations](operations.md).
Code: [failure facts and guidance](../src/local_agent/runtime/capability_failures.py),
[repair progress](../src/local_agent/runtime/repair_progress.py),
[browser repair integration](../src/local_agent/mobile/browser_agent.py),
[timeout cleanup](../src/local_agent/mobile/timeout_recovery.py),
[cancellation](../src/local_agent/runtime/cancellation.py).

## 6. Independent verification

**Goal:** judge the candidate by captured execution and relevant behavioral
coverage, rather than by a model's completion claim.

Coding completion runs controller checks in a fresh snapshot using a resolved
project plan/contract and the selected environment. Workspace review separately
exports the candidate, reads its diff and relevant files, and discovers suites.
The host matches selected reviewer test commands to captured successful
executions and repeats them in a fresh candidate copy before approval. Browser
verification has a runner for real interactions, including keyboard input and
persistence; a DOM dump alone does not establish those behaviors.

The protected fixture verifier, controller test results, general runtime status,
and reviewer approval are distinct outcomes. Passing an incomplete test suite
can miss a defect. Source-string assertions do not by themselves establish a
lifecycle behavior, and desktop browser checks do not establish actual phone
installation. The harness records scope and limitations; it cannot automatically
prove that arbitrary tests fully express the user's requirements.

Read: [project tests](project-tests.md), [browser verification](browser-verification.md),
[reviews](reviews.md), [outcomes](traces.md).
Code: [test-plan resolution](../src/local_agent/testing/plans.py),
[independent checks](../src/local_agent/testing/checks.py),
[workspace review](../src/local_agent/mobile/workspace_review.py),
[reviewer test validation](../src/local_agent/mobile/reviewer_tests.py),
[browser test runner](../src/local_agent/environments/browser_testing.py).

## 7. Bounded autonomy

**Goal:** let the agent act without asking for every routine step, while bounding
resource use, external spending, and unsuccessful iteration.

Configuration defines context/output allowances, model turns, attempted tools,
execution limits, timeouts, and evidence budgets. Runtime checks enforce the
selected bounds and cancellation. Loop state records the local/paid allowances,
deadline, attempts, outcomes, and remaining eligibility. Paid request budgeting
reserves input/output allowance before dispatch when a paid token limit is set.
A local-only completion loop cannot enter paid review or diagnosis.

Review eligibility checks audited candidate/check evidence and rejects duplicate
review receipts without new evidence. Unknown paid usage/outcomes can disable
further paid calls. These bounds preserve work and stop further stages; they do
not imply that the unfinished task was completed. Disk monitoring is a soft
workspace bound, unlike the Docker resource limits.

Read: [configuration](configs.md), [loop controls](browser.md#workspace-sessions-and-bounded-loops),
[review eligibility](local-repair-reliability.md#automatic-paid-review-eligibility).
Code: [limit contracts](../src/local_agent/contracts.py),
[runtime checks and paid budgeting](../src/local_agent/runtime/agent.py),
[loop scheduler](../src/local_agent/mobile/loops.py),
[review gate](../src/local_agent/mobile/review_gates.py),
[resource handling](../src/local_agent/executor/resources.py).

## 8. Observable behavior

**Goal:** let the user determine what ran, where it ran, what failed, what left
the machine, and which outcomes the evidence supports.

Run IDs, job IDs, workspace/branch/commit identities, model selections, stages,
tool proposals, policy decisions, executions, and outcomes are recorded and
exposed through reports and trace views. Exact serialized model request bodies
and raw responses are retained; inspection can show which code, chat, diff, and
command results reached an external model on each turn.

Token accounting separates measured local/paid input and output, request counts,
cached input, and reported reasoning. Unknown values and hypothetical baselines
are distinct from measured usage. Audit validates evidence bindings and causal
history; recorded replay does not establish that fresh inference will behave the
same way. Logs and private evidence are not a public telemetry stream.

Read: [traces](traces.md), [runtime data](runtime-data.md),
[review request inspection](reviews.md#inspect-what-was-actually-sent).
Code: [event contracts](../src/local_agent/observability/events.py),
[audit](../src/local_agent/observability/audit.py),
[trace browser](../src/local_agent/observability/browser.py),
[diagnostics](../src/local_agent/mobile/diagnostics.py),
[token accounting](../src/local_agent/mobile/tokens.py),
[token totals](../src/local_agent/mobile/token_totals.py).

## 9. Controlled authority

**Goal:** separate model-proposed actions from the permissions to execute them,
and separate review from merging or publishing.

The configured tool allowlist, strict validation, policy decision, and verified
Docker execution constrain model actions. Workspace path checks and host root
selection constrain access. Ordinary commands remain inside Docker; declarative
provisioning uses separate host-controlled recipes. Model text cannot grant new
mounts, privileges, networking, or merge authority.

Paid review uses separate candidate copies. The host checks that review/check
copies remained unchanged, validates the verdict and evidence, and gates the
explicit fast-forward merge. A reviewer's instruction to avoid edits is distinct
from a physically read-only project mount; unchanged-copy checks remain necessary.
Browser pairing authenticates the local owner, and saved review/repair targets
are validated server-side rather than trusted from client-supplied paths.

The repository working agreement assigns implementation to local harness agents
and review/integration to the supervisor, subject to explicit user overrides.
That authorship agreement is persistent guidance, not a filesystem permission
barrier. Stronger separation needs separate credentials/environments.

Read: [working agreement](../AGENTS.md), [runtime boundaries](architecture.md),
[execution isolation](executor.md), [review/merge workflow](functional-manual.md#review-a-candidate-with-a-paid-model).
Code: [policy engine](../src/local_agent/policy/engine.py),
[Docker attestation](../src/local_agent/executor/docker.py),
[workspace target checks](../src/local_agent/workspace/review.py),
[review/merge controls](../src/local_agent/mobile/review_controls.py),
[authentication and HTTP routes](../src/local_agent/mobile/web.py).

## 10. Usable controls and documentation

**Goal:** make task state, continuation, extra instructions, review scope, and
recovery understandable without reading the controller source.

The browser offers explicit new-task/continuation actions, local-only versus
approval loops, per-job model/execution/runtime settings, visible workspace and
candidate identities, saved review findings, and attempt diagnostics. The repair
composer accepts optional user context while retaining the server-derived
review target. Login and Resume reconnect to a saved job rather than requiring
the user to submit the task again. The pairing code comes from the computer's
terminal/log; it is not exposed by an unauthenticated browser endpoint.

The documentation index gives each guide an owner: the manual explains actions,
the browser reference explains controls, and focused references own technical
limits. Historical plans and run investigations are separate from current
instructions. Discoverability still needs real user feedback: an existing login
field or saved trace does not guarantee that a user can find it when polling
fails. A newly edited UI/backend also needs activation before the running server
can be assumed to provide the new behavior.

Read: [documentation index](README.md), [user manual](functional-manual.md),
[browser reference](browser.md).
Code: [main browser UI](../src/local_agent/mobile/static/index.html),
[workspace controls](../src/local_agent/mobile/static/workspace-results.js),
[review/repair controls](../src/local_agent/mobile/static/workspace-reviews.js),
[repair submission](../src/local_agent/mobile/repair_controls.py),
[job persistence](../src/local_agent/mobile/jobs.py).

## 11. Token efficiency and local work allocation

**Goal:** minimize paid output tokens while maximizing useful local output tokens
for implementation, testing, and detailed problem-solving.

The intended loop is local authoring → independent checks → bounded paid review
when authorized/eligible → local repair from concise findings. A paid reviewer
is instructed to describe defects and acceptance criteria, not generate patches
or rewritten files. Its response instructions require a short JSON summary, a limited set
of findings with stable IDs, and exact executed test commands; captured evidence
is referenced instead of restating full logs. Local models receive those findings
and produce the code, regression tests, and subsequent repair iterations.

Reviewer selection respects a smaller operator output reserve rather than
silently increasing it. The review progress tracker discourages repeated pages
and successful test reruns, and reserves a report turn near the existing budget
limits. Eligibility prevents automatically paying again merely because a new run
or commit ID exists. Advisory paid diagnosis is separately bounded within the
already authorized allowance; local-only loops keep recovery local.

Local output capacity is configured independently through the coding profile's
`output_reserve_tokens`, which becomes Ollama's `num_predict`, subject to model
limits. That is a maximum allowance, not a minimum token target or a guarantee of
completion. It permits substantial local code/test generation; it does not reward
longer prose, repeated failed actions, or unnecessary rewrites. Extending local
budgets should be evaluated against measured progress and completed behaviors.

There are important limits to what is achieved today:

- A concise paid final report does not guarantee low total paid output. Generated
  tool-call arguments and reported reasoning also consume output tokens.
- Repeated requests can resend considerable paid input even when the final
  report is short. Input, output, cached input, and reasoning must be interpreted
  separately; cached input and reasoning breakdowns are not added twice.
- There is no automatic optimizer that proves the cheapest model/reasoning/
  context allocation for arbitrary tasks. Configurable caps and role assignment
  implement the policy; workload measurements establish whether it works well.
- Cost reductions must retain adequate inspection and behavioral evidence. A
  cheap incomplete review or a large volume of incorrect local output is not a
  successful allocation of work.

Assess changes using completed acceptance criteria, useful local-authored
artifacts, local/paid request and token counts, repeated/stalled actions, and paid
input/output per verified outcome. Compare similar tasks and verification scopes;
raw local token totals or a short paid answer alone are insufficient.

Read: [paid context and accounting](reviews.md#context-per-request-and-total-paid-usage),
[paid findings/output policy](local-repair-reliability.md#paid-output-and-findings),
[configuration](configs.md), [evaluation limitations](evaluation-results.md).
Code: [reviewer instructions](../src/local_agent/mobile/review_instructions.py),
[reviewer selection](../src/local_agent/mobile/models.py),
[review progress/report reservation](../src/local_agent/mobile/review_context.py),
[review agent](../src/local_agent/mobile/workspace_review.py),
[local output allowance](../src/local_agent/runtime/context.py),
[usage totals](../src/local_agent/mobile/token_totals.py),
[evaluation reports](../src/local_agent/evaluation/report.py).

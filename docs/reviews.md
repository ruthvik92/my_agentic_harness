# Reviews and data sent to models

The work-allocation objective is to minimize paid output while maximizing useful
code, tests, and repair work produced locally. See
[harness characteristics](harness-characteristics.md#11-token-efficiency-and-local-work-allocation)
for how the implementation supports that objective and what remains unproven.

This is the reference for what the harness supplies to a paid reviewer. For the
buttons and review/merge workflow, use the [user manual](functional-manual.md#review-a-candidate-with-a-paid-model)
and [browser reference](browser.md#workspace-review-and-merge).

## Choose the review type

| Type | Information supplied | Tools and authority |
| --- | --- | --- |
| Workspace review | Selected candidate, base-to-candidate diff, controller check results, bounded task/answer text, and prior findings | Can read exported project files and execute local checks; returns a verdict. The host decides merge eligibility. |
| Conversation review | Recent saved chat exchanges, saved image when present, and bounded task/workspace metadata | No filesystem or command tools; advisory only |
| Loop failure diagnosis | Original task and the last two retained attempt summaries/evidence, bounded as described below | No filesystem or command tools; advises the next local attempt and cannot approve code |

Selecting a reviewer does not start a paid request. A manual review action or an
explicitly authorized approval loop can start one. A local-only completion loop
cannot invoke paid review or paid diagnosis. See [loop controls](browser.md#workspace-sessions-and-bounded-loops).

## What leaves the machine in a workspace review

The host exports the selected candidate commit into separate check/review copies.
The reviewer can inspect the exported project, including unchanged files. It is
not restricted to changed lines. Host Git objects and the live source checkout
are not mounted into those copies.

The first model request contains review instructions, tool schemas, candidate/base
identifiers, task context, and bounded progress/capability information. The diff,
check report, and source files are available through tools; the entire repository
is not automatically inserted into the first request.

When the reviewer reads `scratch/review.diff`, `scratch/checks.json`, or a project
file, the returned contents become model context and are sent to the configured
paid endpoint. Commands run in the local Docker sandbox, and captured output,
exit status, and other returned evidence are also sent back to the model.
Offline tool execution does not make hosted inference local. Code pasted into a
chat can likewise be sent as chat text.

The task/answer section is assembled with these **character** caps, not token caps:

| Field | Maximum retained |
| --- | ---: |
| Original coding request for this workspace | 8,000 characters |
| Selected follow-up request | 2,000 characters |
| Selected coding answer | 4,000 characters |
| Prior findings, if available | First 8 findings, in compact form |
| Combined context section passed into the review task | 16,000 characters total |

The last cap is applied after prior findings are prepended, so individual maxima
do not guarantee every field survives in full. Prior findings retain IDs plus
bounded location, observed/expected behavior, and one acceptance criterion.
This section does not automatically contain every earlier chat or the complete
local agent tool trace.

Source: [request assembly](../src/local_agent/mobile/review_controls.py) and
[workspace review runtime](../src/local_agent/mobile/workspace_review.py).

## Conversation review and diagnostic context

Conversation review includes up to **three recent complete user/assistant
exchanges**, with **16,000 characters total**. Each message in the newest retained
pair is first capped at 8,000 characters. The review task also includes selected
saved metadata, whose serialized block is capped at 6,000 characters: it can
include source/workspace paths, branch/commit IDs, and the saved diff reference.
The saved image is included when present. Paths and references are metadata,
not file contents; this review cannot use them to inspect code.

A loop's advisory diagnosis serializes the original task and last two retained
attempt entries, then caps that evidence string at **6,000 characters**. Entries
may contain answers, errors, review/test summaries, and bounded failure evidence.
There is no separate source-file upload or inspection tool in this stage. Code
already present in those excerpts can still be transmitted.

The browser's **Task history — n_last_chats** setting controls the local coding
continuation bundle: first finished attempt plus the latest N−1. It does not set
the paid workspace review's history or token window. Diagnosis uses that retained
bundle, so the setting can affect which entries are available to its last-two
selection. See [continuation controls](browser.md#workspace-sessions-and-bounded-loops).

Sources: [conversation request](../src/local_agent/mobile/web.py),
[chat history bounds](../src/local_agent/mobile/threads.py),
[continuation context](../src/local_agent/mobile/task_context.py), and
[loop diagnosis](../src/local_agent/mobile/loops.py).

## Context per request and total paid usage

For a selected configuration:

```text
estimated input budget = window_tokens - output_reserve_tokens
```

Input includes instructions, task text, tool schemas, retained exchanges, and tool
results. The estimator considers the complete serialized payload; it is not an
exact tokenizer. Provider usage is recorded separately. When needed, whole older
exchanges are omitted from active context while their evidence remains local.
A bounded review-progress summary retains read pages and recent command outcomes.
See [context construction](context-helpers.md).

As a configuration example, the shipped optional
[reviewer profile](../examples/configs/openai-reviewer.yaml) sets a 65,536-token
window and a 16,384-token output reserve: 49,152 estimated input tokens per
request. These are configuration values, not universal model limits. Reviewer
selection preserves smaller operator reserves and caps them at 16,384 tokens for
reasoning models or 4,096 otherwise. Workspace selection sets a maximum of 30
model turns and 100 tool attempts; loop token/time allowances can stop it sooner.
Consult the saved job's `config.json` for the configuration actually used.

A review is usually several API requests. Retained input is sent again on later
turns, so summed input usage can exceed the context window without any single
request exceeding it. The token meter is accumulated usage, not unique source
size. Cached input is a reported subset of input, and reported reasoning is
already included in output; do not add either again to the total. A short final
report does not establish a small review cost.

Sources: [reviewer selection](../src/local_agent/mobile/models.py),
[context builder](../src/local_agent/runtime/context.py), and
[review progress](../src/local_agent/mobile/review_context.py).

## Inspect what was actually sent

1. Open the saved review and record its **review run ID**. The source coding run
   and independent-check run are different IDs.
2. Open that run in `./traces`, then follow `context.built` → `snapshot_ref` →
   `payload_ref`. The retained payload is the exact serialized model request body.
3. Follow `model.requested`/`model.responded` and tool execution evidence to see
   which files, diff pages, and command outputs were supplied on each turn.
4. Read measured provider input/output and request counts for total usage. A
   saved browser request's short `context` field is only the initial task
   context, not all the code/evidence sent during the review.

For CLI evidence navigation:

```bash
uv run --locked local-agent trace REVIEW_RUN_ID --json --evidence
uv run --locked local-agent report REVIEW_RUN_ID
```

If using another data directory, put `--data-root PATH` before `trace` or `report`.
See [traces](traces.md) and [runtime data](runtime-data.md) for finding saved jobs,
configs, request files, and immutable request/response blobs. A review blocked
before inference may have no model request; use its saved error/check report.

## Outcomes and safeguards

Workspace review returns structured findings and a verdict. Approval requires
captured inspection, checks, unchanged review/check copies, and passing audits;
selected test commands are replayed in a fresh candidate copy before approval.
An advisory review or diagnosis cannot substitute for those checks. Reviews do
not automatically merge or push.

Official OpenAI workspace tool reviews use the Responses transport; conversation
reviews use Chat Completions. Local compatible endpoints use the configured
compatible transport. Request payload construction currently sets `store: false`;
this field is not a statement about the service's retention or training policy.
Authentication headers are supplied separately from the retained request body.
The API key is not placed in model messages or mounted into sandbox containers.
Ordinary project/chat content is not automatically scrubbed of sensitive text.

See [review instructions](../src/local_agent/mobile/review_instructions.py),
[provider transports](guide.md#model-providers), and
[repair/review eligibility](local-repair-reliability.md).

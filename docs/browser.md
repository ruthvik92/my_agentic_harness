# Browser Interface User Guide

The browser interface is the web front end for the local agent. It is the same
product as the phone interface, exposed through a standard browser.

For an end-to-end operational walkthrough, including when new worktrees are
created, which candidate to review, and how previews relate to code versions,
start with the [functional instruction manual](functional-manual.md).

## Starting the server

Start the server with the public command:

```
./browser
```

or, equivalently:

```
uv run --locked local-agent browser-web
```

By default the server reads `config/browser.yaml`, binds to `127.0.0.1`, and
listens on port `8767`. Open `http://127.0.0.1:8767` in a browser.

`./phone` and the phone-web entry point remain aliases for the same server,
using the same default `config/browser.yaml` profile. The screenshot CLI and MCP
screenshot tool use this profile too. The old phone profile now exists only as
a compatibility test fixture. Existing `phone_session` cookies
and data under `~/.local/share/local-agent/phone` keep saved chats compatible
with the browser interface.

There is no OAuth. Pairing uses a code printed in the terminal.

If you need to reach the server from another device on your LAN, bind a
specific LAN IPv4 address rather than `0.0.0.0`, for example:

```
./browser --host 192.168.1.10
```

Note the spaces between flags and values.

If you update the server while an old one is still running, restart the old
server and reload or re-pair in the browser, because the server loads its
static assets once at startup.

## Config selector

The config selector reads the configured config directory — the directory
containing the `--agent` profile, normally `config/`. Every valid YAML, YML,
or JSON agent profile in that directory appears in the selector, including
newly added files. Selecting a profile shows its detail: mode, provider,
model, instructions, and tools.

`sandbox.json` is editable in the config editor, but it is infrastructure
only and never appears in the agent run selector. Invalid files are shown so
you can repair them, but they are not runnable. See the table of every config
in [configs.md](configs.md).

## Model selection

The default model option, "Use config model", preserves all fields of the
chosen profile: tools, provider, instructions, and budgets. You may manually
override the model, but only within the same provider; the model menu
discovers available models, but model discovery never silently overrides the
config model.

If a remote API key is missing, it stays as the server-terminal environment
variable named in the config. Do not put API keys into the editor or the
browser. CONFIG selection or editing does not invoke inference; generating answers or
requesting reviews through a paid remote OpenAI API may incur charges. `openai-local.yaml` uses the
OpenAI protocol against a local Ollama endpoint and is not a paid remote
profile. Editing config never invokes a model.

Only `browser.yaml`, `analog.yaml`, and `coder.yaml` ship in the active config
directory. Optional compatibility examples are under `examples/configs/` and
do not appear in the selector. The external reviewer is disabled by default;
enable it explicitly with:

```bash
./browser --verifier-agent examples/configs/openai-reviewer.yaml
```

An API key alone does not enable reviewer discovery or requests. See
[optional configurations](../examples/configs/README.md).

## Workflow

The `browser-v1` and `phone-v1` chat workflows accept an uploaded screenshot
plus conversation history. The default browser profile has an empty `tools[]`
list, and `browser-v1` can explicitly enable any listed tool helpers.
The screenshot-chat netlist selector appears only in chat mode; the analog PDF
workflow generates its own draft netlist without a separate inference-model selector.

Saved chats appear in the left sidebar, with the current chat highlighted.
Select a title to restore its conversation and image, or choose **New chat**.
On a narrow screen, use **Chat history** to expand or collapse the list.
Switching chats and starting a new chat are disabled while a job or upload is active.

The **OpenAI reviewer (paid, optional)** selector and **Review conversation** button
appear for every profile, including coding and PDF circuits. The status explains
missing server configuration, unavailable credentials/models, or why review is
currently disabled. Open a chat with a saved answer before requesting review.
Conversation review runs only when you press the button; changing a profile/model does not
trigger it. API billing applies. Reviews use the saved image when available,
recent conversation, and bounded task metadata. They are advisory: the reviewer
cannot inspect workspace files or run tests, and commit IDs or reported checks
do not establish independently verified code correctness.

## Automatic tests and token meters

Coding runs using `coder.yaml` run controller checks automatically. Leave the
workspace review test field at **auto** to use the same project plan and installed
environment. The sticky top-right meter shows measured local and OpenAI/verifier
usage, updating as captured responses arrive. See [project tests](project-tests.md)
for dependency preparation, one-time project contracts, offline execution,
repair feedback and result classifications.

## Workspace review and merge

For a chat containing a published Git coding result, the main **Review scope**
defaults to **Workspace — inspect files and run tests**. Leave tests on **auto**:
the paid reviewer inspects code, README, manifests and test directories, discovers
relevant suites and runs them, including each language in mixed projects. No test
command is required. The command field is an optional override; the directory
defaults to the coding task's directory.
The target commit is shown there. Selecting **Conversation only — cannot run
tests** explicitly switches to advisory review. The workspace default still
applies when the latest reply is an advisory review rather than a coding answer.

You can also expand a specific coding reply and use **Review workspace and run
checks (paid)** under **Verify this candidate** to review that result.
Select the OpenAI reviewer above first, then click the review button. To override
a required check, set the test command and its project-relative working directory;
manual commands use an argument list with no implicit shell expansion. For example,
use `python -m pytest tests/fixtures/broken_repo/test_text_stats.py -v` from `.`
to check whether tests work from the project root. The default is `auto`, which resolves the project test contract or Python defaults
and prepares project imports/dependencies before running checks.

This action is different from **Review conversation**. The controller exports
the exact candidate commit, runs your configured check in Docker, and gives the
reviewer a separate copy with file-reading, search, command and diff tools. The
reviewer receives the captured diff, check output, exit status and original task.
It reports exact executed test commands. The controller matches them against
successful captured tool executions and repeats them in a fresh candidate copy
before approval. The report shows commands, directories, results and output.
Existing required checks remain required: discovery cannot hide a failed contract
or override. No automatic plan does not block inspection. Automatic review can
inspect an environment blocker and explain it, but the blocker prevents approval.
Explicit override setup failures stop before paid inspection. Missing execution
evidence or no tests found leaves the candidate unverified.
Review progress (read pages and command results) is retained across context
trimming so the reviewer can continue without rediscovering completed work.
Two rounds of repeated work without new evidence switch the reviewer to its
report. A final report turn and completion tool capacity are also reserved near
the configured limits. This uses the existing review budget; it does not start
another paid review or increase the tool-call allowance. Unresolved questions
must be reported as limitations or requested changes.
Neither copy contains the host source checkout or its Git control directory.
Official OpenAI workspace tool reviews use the Responses API, including stateless
replay of reasoning and function-call results. GPT-6 tool-enabled official API
profiles use the same transport; conversation-only and local compatible profiles
retain Chat Completions. The selected model and reasoning effort are preserved.

Tools run offline with the existing sandbox dependencies. Missing dependencies,
timeouts and failing commands are reported; they do not count as passing checks.

Continued tasks retain the original coding requirements. The review diff compares
the candidate with its common ancestor with the source HEAD, so a no-change
follow-up does not hide previously proposed changes in an empty latest-turn diff.

Failed workspace reviews also save a visible chat report with the actual configured
check output and exit code, even if the later API request fails. They never enable
merge and are not retried during server restart.

For this harness's standalone text-analyzer fixture, use project directory `.` and
`python -m pytest --confcutdir=tests/fixtures/broken_repo tests/fixtures/broken_repo/test_text_stats.py -q`
to avoid collecting the harness-wide parent conftest. A broad pytest invocation
in an uninstalled src-layout checkout can fail to import its own package before
reaching the fixture. Scoping collection does not fix bugs in the fixture tests;
those remain visible as test failures.

The saved report identifies both run IDs, the reviewed/base commits, source HEAD,
configured command/directory, tool evidence, reviewer findings and merge outcome.
Use **View saved review report** or the authenticated
`/api/jobs/<review-job-id>/workspace-review` endpoint. Output previews are bounded;
full captured tool output remains in the run's trace blobs. Reports and merge
state also persist beside the job in `workspace-review.json`.

Merge is available only after an approving structured verdict, actual successful
configured checks, recorded diff/project file inspection, unchanged check/review
copies and passing run audits. This is evidence for the configured checks and
review scope, not proof of complete correctness. General runtime status remains
`completed_unverified`; reviewer approval is recorded separately.

**Merge reviewed commit into <branch>** asks you to confirm the exact commit and
source checkout. The host performs a local fast-forward only. It rechecks the
candidate, source branch/HEAD, clean index/files and evidence; changed or continued
candidates require a new review. Dirty/untracked files, divergence, active Git
operations, filters and sparse/index flags block merging. Ignored local files
are not overwritten. No source branch switch, force, reset, stash, push or model
merge command is used. A failed/interrupted review never grants merge approval.

Copied non-Git workspaces and unpublished candidates do not offer workspace review.
Commit pending candidate changes through a coding continuation, then review the
new result. A source checkout with pending edits can still be reviewed, but those
edits must be dealt with before its reviewed candidate can merge.

## Execution mode

Open **Advanced run settings** to change the model override or, for profiles with tools, **Execution mode**:

- **Use profile default** shows the YAML's actual default.
- **Ephemeral** creates a container for each tool call.
- **Persistent** reuses a workspace-owned container between tool calls.

For a coding task, select `coder.yaml`, choose **Persistent**, enter the source
workspace and submit. The effective mode appears in the job status and saved
reply. This is a per-job override: the YAML file stays unchanged, and subsequent
tasks using the default still follow their selected profile. The mode is frozen
in the job's config and used again on recovery. Analog profiles support the
same selector; profiles without tools hide it.

Persistence preserves container state such as `/tmp` during the task. Shell
commands remain separate processes. **New task** creates a new workspace;
**Continue task** reuses workspace files with a fresh container. Saved chat
history is independent of container persistence. Resource and idle limits still
apply; see [execution lifecycle](executor.md).

## Project workflows

Coder profiles require an explicit host workspace under the allowed roots
(default launch cwd is the harness checkout). A Git repository root gets a new
`agent/ws_<id>` branch and linked host worktree from current `HEAD` or a selected
starting revision; pending
source edits are excluded and preserved. Other directories use an isolated copy.
The candidate is bind-mounted into Docker for tools. Review and merge remain
explicit. See [Git workspaces](git-workspaces.md) for provenance and merge commands.

Choose **New task** or **Continue task** in the coding controls. Continue takes
the previous workspace ID; **Continue this worktree** on a result fills that in.
Set **Working subdirectory** separately from the source repository path, for
example `tests/fixtures/broken_repo`. Blank uses the root for new tasks or retains
the prior directory for continuation. Enter `.` to select the root explicitly.
Continuation retains pending edits and the agent branch, with a fresh run ID.

Each coding reply shows **Edited workspace**, including the edited project path
on the harness computer and a **Copy path** button. The source folder is shown
for new jobs. These locations remain available when reopening saved chats,
including older replies whose job record still contains the workspace path.
On another device, open the copied path on the harness computer or in its IDE;
it is not a downloadable browser filesystem link.

Git-backed replies additionally show their source repository, base branch and
commit, agent branch, candidate commit, review state and a **View changes**
button. The diff is the run's captured artifact. Opening an old reply does not
convert a copied project into a Git worktree.

The source-workspace field selects a project to import or branch. Docker gets
a writable mount of the run's worktree or isolated copy. Review the candidate
diff and tests before merging or integrating. A completed reply does not mean
changes have been merged into the source branch.

Analog (circuit) profiles require a case workspace plus a relative PDF path,
page, and dpi, with an optional context page and normalized region
`[left, top, right, bottom]`. Circuit runs use the PDF workflow; an uploaded
screenshot is not used in circuit runs.

Configure additional trusted roots by repeating `--allow-root` on the server
command; a request cannot change the allowed roots. `--config-dir` optionally
selects another config directory, and the `--agent` path must be inside it.

## Config editor

In the editor, choose a file and press Load or Reload, then edit the raw
YAML or JSON. Validate before Save. You can create a new blank profile or
clone the currently loaded draft to a new valid filename: the stem must be
ASCII alphanumeric plus `_` or `-`, start with an alphanumeric character, be
at most 64 characters, and end in `.yaml`, `.yml`, or `.json`.

Saving an existing file requires the loaded content hash; a concurrent stale
edit returns 409 and your draft is retained — use Reload to refresh. New and
clone operations create the file exclusively. Saves are validated and atomic,
with a maximum of 64 KiB per file and 128 configs. A saved new valid profile
immediately becomes selectable.

Changes affect future submissions; a queued run captures a frozen copy of the
config.

## Saved state

Saved chats, the recent image, and history are retained across profile
changes. Circuit runs ignore the saved image and use the chosen PDF. Paid
review, netlist, and feedback flows are retained. Each answer stores the
actual selected profile, model, tools, mode, and hash — not the current
selector value.

## Traces

For one map of saved chats, jobs, run IDs, workspaces, Docker containers and
development directories, read [Finding runtime data](runtime-data.md).

Workspace reports with findings offer **Fix with local model**. Select a local
coding configuration and optional local model override, then click the button.
The server supplies the reviewed workspace, findings and check output. Source
paths and workspace IDs need no manual entry. The repair enables independent
project checks, retains the selected execution mode and produces a new candidate
for a separate review. The action does not start paid inference or merge code.
It rejects reviews whose workspace has since moved, including changes made while
the repair was queued. Saved evidence is available to the model in
`scratch/repair-review.json`, even after older chat exchanges leave recent history.
Reviewed repairs also retain a compact controller ledger across context trimming
and resume. Repeated investigation or capability probes trigger bounded recovery;
continued lack of progress ends as `local_stalled` with work preserved. The trace
shows stages, milestones and interventions. Automatic repeated paid reviews require
audited passing checks and new candidate content or independent evidence; duplicate
states stop as `review_blocked`. See [local repair reliability](local-repair-reliability.md)
for configuration, output allowances, and reproducible local trials.

Normal browser server data lives under `~/.local/share/local-agent`. The host
writes `control/agent.db`, `control/blobs`, and `control/runs/<runid>/events.jsonl`.
Per-job frozen config, request, and status are stored at
`~/.local/share/local-agent/phone/jobs/<jobid>/`. Docker executes in isolated
`sandboxes/ws_id` workspaces; the selected code source is unchanged until a
reviewed integration.

The trace viewer is available with:

```
uv run --locked local-agent trace-web
```

It provides a Model input instructions/tools button and references the
config, request, and artifacts. Coding results expose the workspace and
`diff_ref`; circuit results expose `exported_case` as unverified artifacts.
Local build author traces use separate roots, documented in `Progress.md`.

## Workspace sessions and bounded review loops

Open a saved coding chat to see its **Workspace** panel: worktree, source repository,
current attempt, container name/status, prior attempts, failures and trace locations.
Failed coding attempts remain saved, including failures from before this update.
**Continue this workspace** fills in the selected workspace; type a follow-up and
press Ask. Each attempt has its own run ID underneath the same workspace and, in
persistent mode, the same compatible keeper. See [runtime data](runtime-data.md).
Continuation carries the workspace's recorded execution mode into the controls;
an explicit loop mode selection overrides that default.

To automate local repair and verification:

1. Select a local coding configuration and optional local model override. Select
   the desired execution mode; persistent preserves a compatible keeper across cycles.
2. In the workspace panel choose **Loop until approved…**.
3. Set limits. Defaults are **5 paid verification attempts**, 12 local iterations,
   a 60-minute scheduling window and a 100,000 paid-token allowance. Paid attempts
   can be set to 0 for local-only testing. A review attempt can include several
   provider requests/tool turns; the allowance counts reserved review jobs, not
   individual HTTP calls or confirmed invoice charges.
4. Select the paid reviewer above and explicitly check the paid authorization box
   when paid attempts are nonzero. Starting a loop authorizes repeated paid reviews
   only within those frozen limits/configurations. No inference is started merely
   by opening the controls.
5. The controller runs a local attempt and independent tests, then reviews its
   published candidate. Findings and check output are saved for the next local
   attempt. It stops early only on evidence-backed verifier approval with passing
   checks. After the paid allowance is exhausted, disabled or cannot cover another
   request, iterations continue locally. Passing then ends as
   **tests_passed_unverified**, not verifier approval. Merge remains separate.

The loop panel shows current stage/run, attempt counters, outcome history and
measured native-local/OpenAI token usage, including captured responses before a
stage finishes. Missing usage is marked partial. No dollar price is invented.
The paid-token gate reserves conservative input plus maximum output before each
provider request. Unknown billing usage/outcomes disable further automatic paid
calls. This is a token allowance, not a dollar billing guarantee.

**Stop loop after current stage** prevents scheduling another stage. The current
bounded stage may finish, including its authorized provider/tool turns. Scheduling
time limits are checked between stages, with stage runtime limits also bounded;
dependency preparation and cleanup may outlast the scheduling boundary. Repeated
unchanged candidates/test outcomes stop the loop, as do local iteration limits.
An interrupted controller that needs reconciliation blocks continuation.

Loop state and frozen configs live in `phone/loops/<loop-id>/`. Each stage is an
ordinary browser job with its own trace. Authorization/start/stop and stage lineage
are recorded in the ledger. On server restart running loops become **interrupted**;
queued/running requests are not automatically replayed, including paid requests.
Inspect the saved attempts/workspace before explicitly starting another loop.

Execution containers stay offline. Only the host model client accesses the paid
provider; credentials are not mounted into Docker. Independent check/reviewer
copies are disposable, so they do not consume persistent keeper capacity as the
loop continues.

See [mcp.md](mcp.md) and [configs.md](configs.md) for related reference.


## Reading an attempt timeline

Use **Show / hide run timeline** for the current or most recent attempt in the
open chat, or **View this attempt timeline** in its workspace history for an older
attempt. The view shows the actual model, run/workspace IDs, stopping reason,
request budget, recorded provider usage, and tool actions in order. Failed and
rejected actions expand automatically. Successful actions can be expanded too.

**Read full retained output** retrieves the command's stored output without the
short preview limit. If the execution capture limit was reached, the view says
that later output was not retained; older records may have unknown completeness.
Independent check runs linked by controller evidence appear separately below the
coding/review attempt. These read-only controls do not start tests or a model.

**Advanced: raw ledger JSON** retains the original events. The actor `phone`
means legacy browser-controller bookkeeping. `Activity recorded` and
`completed_unverified` do not establish that code passed verification. A GPT
baseline is a hypothetical token comparison, not evidence that GPT was called.
Recorded provider counts are shown separately; accumulated input usage includes
context resent on successive requests. A Docker container labeled **idle keeper**
is retained for reuse and has no active harness command.


## Recovering from local tool failures

New coding turns include examples of Docker paths, command argv, file-hash
replacement conditions and paginated reads. Invalid calls return the original
error plus corrective guidance; the harness does not silently rewrite arguments
or bypass hash checks. A successful project file edit that changes its hash resets
the repeated-action failure counter, allowing a new test–edit–test cycle. Failed
or unchanged writes do not reset it. Turn, tool and time budgets still apply.

For a malformed Ollama tool response, the runtime retains the provider error body
and permits at most one corrected local response per run. The feedback requests
one small complete JSON call. Output-limit responses in tool-enabled local turns use the same allowance,
including responses without parsed calls; none of their partial calls are dispatched. Other server/transport
errors stop the attempt. This recovery never makes an automatic OpenAI retry.

In a newly authorized loop, two failed local attempts may trigger **one advisory
diagnostic stage** if paid allowance and another local cycle remain. It consumes
one of the existing paid attempts and uses the same token/time limits. The stage
receives bounded controller evidence, has no file/command tools, and cannot approve
code or merge. Its guidance is passed to the next local turn through task context.
Unknown billing/outcome disables further paid calls. Paid diagnostic and workspace
verification share the allowance; the default remains five total paid attempts.
Previously stopped/stalled loops are not resumed by these changes.


## Editing an agent profile

Click **Edit profile** beside **Agent profile (config)** to load the selected file.
The panel shows the filename and YAML/JSON. **Validate** checks the draft, **Save**
writes it, and **Cancel** discards the draft. **Save as new profile…** asks for a new
filename; click **Save** to create the copy. **Manage profile files** offers other
files, a blank profile and a file-list refresh. Existing-file saves retain conflict
protection if another editor changes the file.

**Advanced run settings** groups the model override and execution mode.
**Review settings** groups the optional paid reviewer and review scope. Both are
collapsed initially. Opening settings or editing a profile does not start a model
request; saved settings apply to subsequent runs.

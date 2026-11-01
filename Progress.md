# Current progress

The complete earlier log is preserved in
[docs/history/Progress-through-2026-10-26.md](docs/history/Progress-through-2026-10-26.md).
Use [the documentation index](docs/README.md) for current operating instructions.

## 2026-10-26 — Repository cleanup

The user authorized direct Codex implementation of this cleanup. No local coding
agents or paid inference were used.

- Created a full pre-cleanup checkout archive, including Git metadata and
  uncommitted files. The virtual environment and disposable root caches are
  recreatable and excluded. Archive integrity was checked by reading all 34,127
  tar entries; SHA-256 and original HEAD are recorded in `backup.json`.
- Checkpointed the working product separately in Git commit `97c61a6` before
  cleanup. This preserves prior feature work independently of organization changes.
- Moved six development trees outside the checkout and preserved the original
  circuit investigation under `~/local-agent-cases/circuit-case`. No source,
  private case evidence or rejected agent draft was discarded.
- Added a reusable circuit template, documentation index and layout/recovery
  guide. Moved historical plans and the full earlier progress log to `docs/history/`.
- Shared the development-artifact exclusion list between workspace imports and
  protected source baselines, preventing snapshots and caches from entering runs.

See [repository layout](docs/repository-layout.md) for exact archive paths,
case access commands, backup metadata and recovery instructions.

Configuration consolidation is complete:

- `config/` now contains exactly `browser.yaml`, `analog.yaml`, `coder.yaml`,
  and generated `sandbox.json`. The browser selector exposes the three agent
  workflows and treats sandbox metadata separately.
- Screenshot CLI and MCP screenshot requests now use `browser.yaml` and the
  browser runtime. Explicit legacy `phone-v1` configurations and recorded runs
  retain their existing runtime; the old phone sample is a test fixture.
- Optional OpenAI-compatible examples live under `examples/configs/`. External
  reviewer discovery and requests are disabled by default, even with a key in
  the environment. `--verifier-agent examples/configs/openai-reviewer.yaml`
  explicitly enables that feature. Existing mock-review tests opt in explicitly.
- Added regressions for the shipped profile catalog, actual MCP routing, disabled
  reviewer networking, workspace archive exclusions, and default screenshot CLI
  execution with scripted inference and real Docker. Compatibility coverage for
  legacy phone and OpenAI transport remains intact.

Final validation:

- Full pinned-Docker suite: **372 passed in 118.82s** using
  `sha256:a4eb1c5633b5e83bbef63da7d23fd3543a0143381809f3314621bdfc1f29ed63`.
- `uv run --locked ruff check src/local_agent tests scripts`: all checks passed.
- Current Markdown links, launcher shell syntax, CLI help, active profile count,
  archive destinations, original circuit PDF, and trusted source fingerprints
  checked successfully. Historical documents intentionally retain old paths.
- The first full run had 371 passes and one legacy feedback-test setup failure:
  it requested a reviewer without explicitly enabling it. Corrected the setup,
  independently checked feedback tests, and reran the complete suite above.
- No trusted worker, toolkit, Dockerfile or dependency changes were made during
  this cleanup, so the existing verified sandbox image remains pinned.

Commits separate the preserved product baseline, archive/layout cleanup, and
configuration migration. No changes were pushed. Restart an already-running
browser server to load the new Python defaults; saved chats and authoritative
run data were left in their existing data roots.

## 2026-10-26 — Calculator browser task baseline

Recorded the two files in `tests/fixtures/broken_repo` before the user
submits the browser coding task. No fixture source or tests were edited.

- `calculator.py`: `add(a, b)` returns `a - b`.
- `test_calculator.py`: one assertion, `add(2, 3) == 5`.
- Independent baseline test: **1 failed in 0.01s**, actual result `-1`.
- Exact source copies, hashes, contents, test result and acceptance criteria:
  `/home/ruthvik/.local/share/local-agent-development/calculator-browser-check-20261027T050052Z`.
- Compare the candidate in its returned isolated workspace; the original
  fixture should keep matching the saved hashes. Candidate must retain the
  original assertion, add negative/zero/decimal cases and pass pytest.

## 2026-10-26 — Browser calculator attempt blocked by selected-model probe

- Browser job `c4a78e8b69cf2c5f851edd5e55272c9e` selected `qwen3-coder:30b`
  as an override of `coder.yaml`. Probe `run_44369d22d4cd4a40a71966b6cb2f2c91`
  ended completed_unverified, but failed the separate capability assessment.
- Raw Ollama response contained XML-like `read_file` markup in message.content,
  with no message.tool_calls and done_reason=stop. No model tool was dispatched;
  the recorded run_command executions were trusted bootstrap/final-diff operations.
  The calculator coding run did not start (browser job run_id is null).
- Both original calculator files still match the saved baseline hashes.
- Independently checked configured default `qwen3:30b-a3b-instruct-2507-q8_0`
  through the same read-only gate: **passed**, run
  `run_b9c9de0da09f474f885b86cfb669faad`. Evidence is under
  `~/.local/share/local-agent-development/calculator-probe-check-20261027T050310Z`.
  This verifies tool selection/continuation, not completion of the calculator task.
- Recommended browser retry: select coder.yaml and “Use config model”, then submit
  the same task. No application code, model settings or capability cache in the
  browser data root was changed or bypassed. No paid models were invoked.

## 2026-10-26 — Recovered calculator answer after stale browser-schema failure

- Browser job `9cd64fbe344fe30f1b0d2db915f5c931` ran the configured
  `qwen3:30b-a3b-instruct-2507-q8_0` successfully. Model run
  `run_e1a1e009ddd04c2f90df6f0df763ba00` is completed_unverified and passes audit.
  The browser server, still running code loaded at 16:11, failed thread persistence
  because its old Event schema rejected execution.requested.
- Confirmed no active/queued jobs, backed up job/thread records, gracefully stopped
  the stale server, and restored the saved answer through current BrowserServer
  finish/persistence APIs. No model was called again, and original run events
  remain identical and audit-valid. The saved answer exists once in the thread.
- Restarted current browser on the same LAN URL, http://192.168.0.40:8767.
  Authenticated checks confirmed job completed, thread readable and thread events
  readable (HTTP 200). New pairing is required; startup log is private and the
  pairing credential is not recorded here.
- Backup, recovery record, candidate test evidence and startup log:
  `~/.local/share/local-agent-development/browser-thread-recovery-20261027T051804Z`.
- Candidate workspace: `~/.local/share/local-agent/sandboxes/ws_f1040f80cfae4dc28905c970d0e637f4/project`.
  Independently tested in offline, nonroot, read-only Docker: **1 passed**.
  The candidate changes add to a+b, but test_calculator.py retains only the
  original test. The model's claim to have added negative/zero/decimal tests is
  unsupported. This is partial task success, not all acceptance criteria met.
  Both original fixture files still match the recorded baseline hashes.

## 2026-10-27 — Browser coding-result workspace visibility

Implemented directly under the user's authorization to improve the browser workflow.
No local agents or inference were invoked for this change.

- Coding replies now show an Edited workspace panel with the host-side edited
  project path and Copy path control. New submissions also retain and display
  their source folder. The workspace input explicitly says it selects a source
  to copy; the model edits the isolated candidate, not the original host project.
- Result locations are persisted with new replies. Authenticated thread reads
  backfill older reply metadata from their corresponding job record, so the
  existing calculator reply also shows its candidate location after refresh.
- Paths are rendered as text, not executable HTML or file URLs. Clipboard copying
  supports both the secure Clipboard API and LAN HTTP's copy/select fallback.
  Direct writes to the source folder were not enabled: they would require an
  explicit execution mode and coordination with concurrent host edits.
- Validation: **373 passed in 121.54s** against the pinned Docker image, including
  GJS-executed result rendering/clipboard tests and saved-reply API coverage.
  `uv run --locked ruff check src/local_agent tests scripts` and whitespace checks
  passed. Trusted worker/image/dependencies unchanged.
- Gracefully restarted the idle browser to load new assets. The Wi-Fi IP changed
  since the earlier session, so rebinding 192.168.0.40 failed; the current server
  is verified at http://192.168.1.22:8767. Authenticated API checks returned 200
  for the new helper and saved calculator thread; its candidate path exists.
  New pairing is required. No pairing credential is recorded here.
- Live verification and private startup logs are under
  `~/.local/share/local-agent-development/browser-workspace-results-20261027T134459Z`.
  Saved model answers and original projects were not edited by this UI change.

## 2026-10-27 — Git branch/worktree coding workflow

Implemented directly under the user's authorization. Coding against a selected
Git repository root now creates an actual linked host worktree at the run's
managed `project/` path, on branch `agent/ws_<id>`. The source checkout stays on
its current branch. Staged, unstaged and untracked source edits are preserved and
excluded; the run records committed HEAD as its exact base. Non-Git folders and
selected repository subdirectories retain copied-project behavior. Chat, circuit
runs and capability probes keep their previous workspace behavior.

Git ownership and execution:

- Docker still bind-mounts the run workspace. Model commands edit the host-visible
  worktree directly, while shared Git metadata remains outside the container.
- Container run_command/git_diff use private scratch Git history under tools;
  their commits cannot move source-repository branches or hide candidate edits.
- The host creates worktrees without checkout filters and materializes literal
  committed blobs. Host publication uses a private index, literal blob writes,
  commit-tree and compare-and-swap update-ref. Hooks, filters, signing and model-
  supplied Git command arguments are excluded from host operations.
- Publication uses the captured candidate snapshot, persists its intended commit
  before moving the ref, and resumes idempotently. Pointer, branch and tip checks
  reject unexpected host changes instead of overwriting them. Source index and
  working files are untouched. Worktree-copy traversal now anchors descriptors
  and refuses symlinks at every component, including a replaced project root.
- Source revision and Git provenance appear in frozen config, run manifest,
  workspace events, private control/git-workspaces manifests and final results.
  Candidate branches/worktrees remain available for human or separately authorized
  host-agent review. No automatic merge, push, stash or source reset is implemented.

Browser showcase:

- New Git-backed replies show source repository, base branch, exact starting
  commit, agent branch, candidate commit, review state and worktree path.
- Copy path and authenticated View changes show actual result locations and the
  recorded diff, independent of model prose. Diff previews are bounded at 1 MiB
  and rendered as literal text. Results persist in jobs/saved replies; older
  copied runs retain their mode and gain diff viewing where an artifact exists.
- The source input explicitly explains committed-HEAD behavior and exclusion of
  pending edits. docs/git-workspaces.md covers limits and review/merge commands.
- Worktrees initially require regular tracked files and committed HEAD; tracked
  symlinks, submodules and tracked internal cache/archive folders are rejected.
  Git LFS/checkout filters are not run. Offline dependency constraints remain.

Validation:

- Full pinned-Docker suite: **384 passed in 122.40s**, including ephemeral and
  persistent worktree edits, private container Git, branch publication, actual
  source preservation and resume after a real controller process crash.
- Unit coverage verifies dirty/untracked exclusion, binary files, deletions,
  ignored files, ordinary Git merging, no-op branches, concurrent branch changes,
  disabled host hooks/filters, marker checks and interrupted ref publication.
- Browser API/GJS checks cover saved branch metadata, authentication and artifact
  ownership, literal diff rendering and clipboard behavior.
- `uv run --locked ruff check src/local_agent tests scripts`, whitespace checks,
  and current documentation links passed. Trusted worker/image/dependencies did
  not change; the existing sandbox pin remains valid.
- Reloaded the idle browser at http://192.168.1.22:8767 and independently verified
  protected diff access, new widget asset and the saved calculator thread (200).
  Its actual recorded diff shows the addition fix. Saved runs were not converted
  retroactively. A new pairing code is required and is omitted from this record.
- Live verification/private startup log:
  `~/.local/share/local-agent-development/git-workspaces-20261027T150129Z`.
  Implementation tests used scripted providers, not local or paid inference.

## 2026-10-27 — Profile-specific browser controls and execution mode selector

Implemented directly under the user's authorization; no local or paid inference
was used for authoring or validation.

- The netlist inference/reviewer controls were legacy screenshot-chat controls
  displayed for every selected profile. They now appear only for chat; coding
  and native PDF circuit workflows hide them and their action buttons. Analog
  PDF tasks already generate their own draft netlists. Image input uses a neutral
  optional-attachment label instead of a schematic-only label.
- Tool-enabled profiles now expose Execution mode: profile default (with its
  actual value), ephemeral, or persistent. Switching profiles clears the override;
  no-tools chat hides it. Controls are disabled while a job is busy.
- The API strictly validates the optional per-job execution_mode and freezes it
  in the selected config, config hash, job metadata and saved reply. It cannot
  override resource/network policy or mutate the original YAML. Subsequent jobs
  without an override follow the original profile default. Effective mode is
  visible during polling and beside completed answers.
- Help explains that persistent mode retains container state between tool calls
  in the current workspace. It does not preserve shell process state or select
  the same worktree for every new task; project files and chat history have
  separate persistence.
- Validation: **399 passed in 131.26s** against the pinned Docker image, with lint,
  whitespace and current documentation links passing. New coverage includes
  GJS-executed profile visibility/default/reset behavior, both coding and analog
  frozen overrides, invalid/no-tools rejection, unchanged YAML/defaults, and an
  actual browser submission whose two commands reuse one persistent keeper and
  observe the same /tmp state. Tests use scripted inference and clean up keepers.
- Gracefully reloaded the idle browser at http://192.168.1.22:8767. Verified the
  selector asset and profile-default API metadata, authenticated with the new
  pairing code (not recorded here). Live evidence/private startup log:
  `~/.local/share/local-agent-development/browser-execution-controls-20261027T152613Z`.
- Trusted worker, sandbox image pin and dependencies are unchanged.

## 2026-10-27 — Coding task revisions, continuation and subdirectory focus

The user explicitly authorized direct Codex implementation: “you do it, don't
have to ask the harness.” Codex authored this implementation, tests and docs.
The earlier local attempt `run_96bf83104ec24ef98277630ba1e2076e`, using
`qwen3:30b-a3b-instruct-2507-q8_0`, was cancelled through `local-agent cancel`.
Its worktree `ws_b6c1be4fdaa1483bb5ff94076cef62eb` had no tracked or untracked
changes to integrate. It is retained for inspection; it did not author this patch.
Task briefs, run output, full test log and browser verification are under
`~/.local/share/local-agent-development/workspace-controls-task/`.

- New coding tasks default to the source checkout's current committed HEAD or
  accept a safely resolved starting Git ref/commit. Source checkout and branch
  remain untouched. Selecting an older revision does not itself mark a clean
  source dirty.
- Continue accepts a managed Git workspace ID, reuses its branch and files,
  preserves pending edits and untracked files, and creates a fresh run ID.
  A published candidate becomes the next parent; an unpublished candidate
  retains its prior base. Active owners, unresolved executions, mismatched
  repositories, invalid workspaces, and external branch changes are rejected.
- Protected baselines now belong to individual runs. Recovery retains legacy
  baseline lookup and restores captured task options. Normalization, dispatch
  verification and audit derive command defaults from the captured task
  directory while preserving raw provider proposals. Trusted harness commands
  keep their original directories.
- Browser coding controls expose New/Continue, starting revision, previous
  workspace ID and working subdirectory. Result cards show task kind, directory
  and workspace ID, plus a Continue this worktree action. Jobs and saved thread
  replies preserve result metadata. CLI equivalents are `--base-ref`,
  `--continue-workspace`, and `--working-directory`.
- The working directory must be relative, existing, and free of symlink traversal.
  It focuses prompts and default command/Git-tool directories; file paths remain
  workspace-relative. It is neither a permission restriction nor a sparse
  checkout. See [Git workspaces](docs/git-workspaces.md) for examples.
- Continuation retains workspace files, stops a prior keeper and starts fresh
  processes. Container persistence, saved conversation history and interrupted
  run recovery remain distinct from starting a continued task.

Validation:

- Full pinned-image suite: **416 passed in 139.19s**, using
  `sha256:a4eb1c5633b5e83bbef63da7d23fd3543a0143381809f3314621bdfc1f29ed63`.
- New Docker tests exercise selected commits, focused/default and explicit
  command directories, Git-tool defaults, continued published candidates plus
  pending files, original-source preservation and valid audits for both runs,
  in ephemeral and persistent modes. Unit tests also cover unpublished
  continuation, active/unknown workspaces, invalid revisions, path traversal,
  symlinks, browser request plumbing, saved metadata and UI interactions.
- `uv run --locked ruff check src/local_agent tests scripts`, `git diff --check`,
  updated documentation links and CLI help passed. Original calculator fixture
  source and tests remain unchanged. No worker, image or dependency changes.
- Restarted the idle browser server at `http://192.168.1.22:8767`. Authenticated
  checks confirmed the served task controls, continuation action and request
  plumbing; `/api/info` reports `restart_required: false`. Its private startup
  log holds the new pairing code; no pairing code is recorded in this document.

Changes remain in the working tree for review; nothing was pushed or merged.

## 2026-10-27 — Independent review of browser text analyzer candidate

Reviewed user-requested worktree `ws_f35d604ad3c5414597fefe7dc9f12b7e`, run
`run_438be46722334d448a3ac63fb937dd55`, authored by local model
`qwen3:30b-a3b-instruct-2507-q8_0`. Run ended `completed_unverified`; independent
run audit passed (185 events, no errors). Branch candidate is
`10cf9bb198cd9fccd92d4772532f26e2c4e84eea`, based on
`e9cce3af951e5c6a3ca0f252f66774f15df23aed`.

- Candidate adds only `text_stats.py` and `test_text_stats.py` under
  `tests/fixtures/broken_repo/`; calculator files and source checkout unchanged.
- Agent trace genuinely records a final 5-test passing run after correcting
  two incorrect expected character counts. Earlier attempts hit the parent
  conftest/dependency issue before using an isolated test collection boundary.
- Independent validation copied the two files into a temporary directory so
  the agent's test fixtures could not overwrite files in either checkout.
  All five tests pass when launched from their own directory. All five fail
  when launched from the copied project root: subprocesses use relative
  `text_stats.py` instead of a path anchored to the test file. Tests should use
  `sys.executable`, an anchored script path, and pytest `tmp_path` fixtures.
- Independent empty, Unicode and unterminated-line cases passed. CRLF input
  `a\r\nb\r\n` returned 4 characters instead of 6 because text-mode reading
  translates newlines. Preserve newline characters and add regression coverage.
- Ruff reported four issues: two import-order violations, an unused pytest
  import and an unused context-manager variable.

Review only: no candidate code was changed, merged, or represented as fully
verified. The basic demo works; directory-independent tests and literal newline
counting need correction before integrating this candidate.

## 2026-10-27 — Reviewer visibility and sidebar request: harness blocker

Rechecked text-analyzer candidate `ws_f35d604ad3c5414597fefe7dc9f12b7e`
(`run_438be46722334d448a3ac63fb937dd55`, local Qwen3 model). Independent
run audit still passes. Isolated copied tests: 5 pass from their own folder,
5 fail from parent directory; CRLF sample reports 4 characters instead of 6.
Candidate remains unmerged and unchanged.

User also requested paid reviewer availability for every config and left-side
saved-chat navigation. Inspection confirmed reviewer controls are hidden outside
chat mode by `config-controls.js` and gated by `legacyCircuit` in `index.html`.
Backend review prompt assumes circuits. Running browser server has no
`--verifier-agent` argument, so review is disabled independently of UI visibility.

Harness implementation attempts (no agent-authored implementation to integrate):

- `run_4e77762390d3422fa4a60149229f6b3d`, `config/coder.yaml`,
  `qwen3:30b-a3b-instruct-2507-q8_0`: cancelled after repeated identical reads
  of truncated models.py. No implementation writes.
- `run_cda92e119a9d4cac9d8b326194dacf62`, same config/model: narrowed
  reviewer task, cancelled after repeated identical web.py reads. No writes.
- Harness connector attempt with installed `qwen3-coder:30b` returned
  `Harness result missing run_id`; no implementation authorship claimed.
- `run_7df77eb96ec245a28a6287aac2fd5fa5`, existing `config/analog.yaml`,
  local `qwen3.8:27b`: alternate tool-capable model; reached model-turn budget
  after inspection only. Independent audit passes (501 events); this establishes
  trace integrity, not successful behavior. Config carries circuit instructions,
  so it is not a suitable long-term replacement for a coder configuration.
- `run_37df13879c4b4bd996313e05d53eb37b`, same alternate config/model:
  explicit focused coding task, single bounded initial read requested, followed
  by implementation. Cancelled after repeated inspection commands; no writes.

Task briefs and CLI outputs/stderr are retained under
`~/.local/share/local-agent-development/sidebar-reviewer-task/`; traces remain
in the normal local-agent store. Independent existing targeted baseline:
`uv run --locked pytest -q tests/test_mobile_reviewers.py tests/test_mobile_threads.py tests/test_browser_profiles.py tests/test_browser_web.py tests/test_workspace_results_ui.py`
passed (10 tests). This is baseline validation only; requested features are not
implemented. No paid inference, service restart, implementation changes or
candidate integration performed. Reported blocker under AGENTS.md; direct
Codex implementation requires explicit user authorization.

## 2026-10-27 — Chat history sidebar and reviewer across profiles

User explicitly authorized direct Codex implementation: “yes, implement them
directly.” Codex authored the implementation, tests and documentation below;
the earlier blocked local runs did not author this patch.

- Replaced the saved-chat dropdown with a scrollable left sidebar, active-chat
  marker, New chat action, empty state and mobile Chat history toggle. Retained
  saved selection, images, history and usage restoration. Navigation and New
  chat stay disabled during submissions, uploads, thread loads and active jobs.
  Titles use textContent. Sidebar hides when pairing is required.
- Reviewer selector, action and disabled explanation are visible for coding,
  PDF circuit and chat profiles. Circuit-only netlist controls remain specific
  to screenshot chat. Review requires a saved assistant answer and explicit
  button press. No automatic paid calls were added.
- Generalized advisory review prompt to task/conversation review, with bounded
  untrusted saved metadata and candidate references. Repeated reviews retain
  the latest task's metadata. Prompt and UI state that the reviewer cannot
  inspect workspace files or run tests; metadata does not verify code behavior.
- Updated browser guide and existing Firefox acceptance script for sidebar
  navigation and the current config-model option/control error wording.

Validation:

- Full pinned-image suite: **422 passed in 141.44s**, using unchanged image
  `sha256:a4eb1c5633b5e83bbef63da7d23fd3543a0143381809f3314621bdfc1f29ed63`.
- `uv run --locked ruff check src/local_agent tests scripts` and
  `git diff --check` pass. No dependencies, worker or protected verifier changes.
- New mocked backend cases cover all three saved task modes, repeated review,
  bounded metadata, empty chats and missing verifier profile. GJS checks execute
  the actual browser inline code for stored selection/image restoration,
  switching, New chat, pending-job locking, mobile toggle and coding review.
- Firefox desktop/mobile layout assertions and screenshots passed, using a
  temporary mock server. Existing `scripts/check_phone_browser.py` passed:
  uploads, failed replacement retention, pairing, saved chat/image, catalog,
  netlist, fake paid review, feedback, reload/resume and reset. No paid inference.
- Restarted the idle server at `http://192.168.1.22:8767` with
  `--verifier-agent examples/configs/openai-reviewer.yaml`. Authenticated checks
  confirmed served sidebar/no dropdown, `restart_required: false`, reviewer
  enabled with seven selectable models, and 18 retained saved chats. Pair again
  after reload; the new code is only in the private startup log, not this note.

Task briefs, prior run evidence, full test log, browser acceptance log,
Firefox layout verification script and screenshots are retained under
`~/.local/share/local-agent-development/sidebar-reviewer-task/`. Server startup
log is `server.log` there (mode 0600); current process metadata was updated.
The text-analyzer candidate remains unmerged. Existing Progress.md changes were
preserved. Changes remain uncommitted; nothing pushed or merged.

## 2026-10-27 — Workspace reviewer with execution evidence and explicit merge

User authorized implementation after discussing workspace inspection and a
separate confirmed merge action. This continues the explicit authorization for
direct coding; Codex authored this implementation, tests and docs. No local
harness model is claimed as its author.

- Published Git coding replies now offer **Review workspace and run checks
  (paid)** with a configurable command and project-relative test directory.
  **Review conversation** remains a separate advisory action. The selected
  reviewer is derived into a controller-owned `workspace-review-v1` profile
  with read/search/command/diff tools and a multi-turn budget; editing the
  original no-tool reviewer YAML is unnecessary.
- The controller validates the coding answer, repository allowlist, workspace,
  source run, exact commit and clean candidate. It exports literal committed
  files without exposing host Git control paths. Configured checks execute
  through the durable Docker tool protocol with a scripted provider (no model
  inference). The paid reviewer gets a different candidate copy, original task,
  captured diff and check evidence. Neither stage writes to the source/candidate.
- Saved reports contain both run IDs, target/base/source commits, command/cwd,
  exit codes, bounded output previews with full trace references, tool-read
  evidence, structured findings and merge state. Approval requires successful
  configured checks, diff/file inspection, unchanged check and reviewer copies,
  a structured approving verdict and passing audits. General runtime status
  remains `completed_unverified`; approval does not prove complete correctness.
- A distinct host **Merge reviewed commit** action confirms the exact target.
  It re-audits evidence and rechecks workspace/source identity and cleanliness,
  uses fast-forward only, disables hooks, rejects configured filters and
  sparse/index flags, and refuses to overwrite ignored local files. No model
  receives host merge authority. Source movement, dirty/untracked files,
  continued/modified candidates, divergence and pending Git operations block it.
  Merge intent/outcome are durable; repeated requests are idempotent and a
  post-Git/pre-report interruption can be reconciled without a second merge.
- The authenticated report route is `/api/jobs/<id>/workspace-review`; submission
  and merge routes are bound to a saved thread. Reports persist in the job and
  `workspace-review.json`, and restore in saved chat after server restart.
  Workspace review counts as paid review overhead in token accounting.

Validation:

- Full pinned-image suite: **441 passed in 170.91s**, unchanged image
  `sha256:a4eb1c5633b5e83bbef63da7d23fd3543a0143381809f3314621bdfc1f29ed63`.
- Final focused suite: **18 passed in 28.33s**. Additional expanded API test
  passed after adding rejected-approval, crash reconciliation, restart/report
  persistence and no-paid-replay assertions. GJS widget/browser tests pass;
  lint across src/tests/scripts and `git diff --check` pass.
- Real Docker tests cover successful and failing configured checks, missing
  inspection, requested changes, reviewer/check-copy mutation, exact merge,
  dirty/moved checkouts, stale/outside-root targets, local-file collisions,
  index flags, filters and hook suppression. API tests verify pairing, thread
  ownership, exact-commit binding, saved evidence and explicit merge.
- Firefox completed browser -> queued workspace review -> actual Docker pytest
  -> saved approval -> native confirmation -> exact-commit merge in a temporary
  repository, using a scripted reviewer. No paid inference or real-project
  merge was performed. Screenshots, verification script and logs are retained
  under `~/.local/share/local-agent-development/sidebar-reviewer-task/` as
  `workspace-review-*` and `check_workspace_review_firefox.py`.
- Restarted the idle server at `http://192.168.1.22:8767` with the existing
  reviewer profile. Authenticated checks confirmed the new asset and action
  routes, reviewer enabled, `restart_required: false`, and 18 saved chats.
  New pairing code is only in private `workspace-review-server.log` in that
  evidence directory; process metadata points to it. No code is recorded here.

Existing user changes were preserved. Nothing was committed, pushed or merged
into a real project; the prior text-analyzer candidate remains unmerged.

## 2026-10-27 — Primary reviewer action defaults to executable workspace review

Investigated the user's report that the verifier could not execute tests. Latest
job `51d3f63bd03a2bd3020f96c9aa51906b`, run
`run_582ab34131cb4b099ddf2293ddd0fc11`, is an advisory `kind: review` using
`gpt-6.1-sol`, not a workspace review. No `workspace_review` jobs had been queued.
The no-tool response accurately reflected that selected workflow; there was no
workspace test execution failure to diagnose. The UI made this distinction too
easy to miss. Codex directly authored the following correction under the existing
authorization to implement the workspace reviewer.

- Main review controls now show Review scope, defaulting to Workspace for a chat
  with a coding candidate, even after advisory replies. Test command/directory
  and target commit are visible next to the main Verify workspace and run tests
  action. Conversation-only review is an explicit alternative. Original per-reply
  workspace review controls remain available. Thread changes reset defaults;
  polling/profile changes preserve the current scope and entered test options.
- Continued no-change coding turns no longer hide earlier proposed changes behind
  an empty latest-turn diff: review uses the candidate/source common ancestor
  as its diff baseline, while preserving the run's base for identity checks.
  Review context retains the first same-workspace coding task in the saved chat,
  plus the selected follow-up and prior answer. This addresses the existing
  text-analyzer follow-up asking where the tests are without dropping the original
  task requirements.
- Updated browser guide. Focused tests: 24 passed in 33.28s against the unchanged
  pinned Docker image. They cover main-button routing, explicit advisory choice,
  saved coding target behind advisory replies, visible command/cwd binding,
  original-task context, continued-task diff, existing review/merge safeguards
  and saved history. Ruff and git diff --check passed.
- Firefox exercised the MAIN review button through real Docker pytest, saved
  approval, native merge confirmation and exact-commit merge in a temporary
  repository using a scripted reviewer. No paid inference or real-project merge.
  Evidence is in `primary-review-tests.log`, `primary-review-firefox.log` and
  `check_workspace_review_firefox.py` in the existing sidebar-reviewer-task
  evidence directory.
- Restarted the idle browser server; authenticated checks confirmed the new scope
  and test controls and restart_required false. Pair again using the new code
  in the private workspace-review-server.log; no pairing code recorded here.

All existing edits remain preserved and uncommitted. The text-analyzer candidate
remains unmerged. The earlier full suite passed 441 tests; this focused follow-up
was independently validated as described above rather than claiming another full
suite run.

## 2026-10-27 — Fix tool-enabled OpenAI HTTP 400 with Responses transport

Diagnosed workspace review job `7a193324ac79af593613e28096d1c97e`, reviewer run
`run_ba2fcfc5a5a34f73a19af2e879a109fb`, selected `gpt-6.1-sol`. The captured
provider error rejected function tools plus reasoning_effort on Chat Completions.
Official model docs confirm GPT-6.1 Sol tool calling requires Responses:
https://developers.openai.com/api/docs/models/gpt-6.1-sol . Also consulted official
function-calling and reasoning documentation. Used the OpenAI Docs skill. No
live inference retry or model substitution was made. Codex directly authored
this fix under the user's existing authorization.

- Added stateless Responses transport for official OpenAI workspace tool reviews
  and tool-enabled GPT-6 profiles. Preserves selected model/reasoning effort,
  uses flat function schemas with explicit strict:false, max_output_tokens and
  store:false. Advisory no-tool and local compatible Chat Completions behavior
  remains intact.
- Replays exact response output items, including encrypted reasoning, assistant
  phase and function call IDs, followed by matching function_call_output items.
  Handles text/images, tool arguments and incomplete/refused responses. Context
  compaction and audit now validate the actual Responses input/tools payload;
  usage input/output/cached counts map into existing measured accounting.
- Failed workspace reviews now leave a visible saved chat report with check
  output and exit codes even when the later provider request fails. Restart
  restores that report without retrying paid inference. Failed reports never
  enable merge. Generic HTTP 400 diagnostics may identify the rejected parameter
  without exposing arbitrary error bodies or authorization headers.
- The independent check in the user's failed job really executed and exited 4:
  broad pytest collected the harness conftest but local_agent was not importable
  in the uninstalled exported checkout. Separately ran the standalone analyzer
  fixture with a scoped collection boundary in Docker, using scripted command
  execution only. Run `run_9725737734e9421dacd90e6892eb632e` in the separate
  scoped-fixture-data store completed; actual check exited 1 with all five tests
  failing because they invoke relative text_stats.py from the project root.
  This confirms executable tests expose candidate bugs; no candidate was changed.

Validation:

- Full unchanged pinned-image suite: **449 passed in 178.08s**, image
  `sha256:a4eb1c5633b5e83bbef63da7d23fd3543a0143381809f3314621bdfc1f29ed63`.
- New mocked HTTP transport test executes the complete workspace review with
  real Docker checks and tool reads over /v1/responses, verifies encrypted state,
  exact call/output linkage, approving report, both audits, measured usage and
  untouched source/candidate. No paid inference. Additional tests cover images,
  compaction, local compatibility, malformed args, refusal/incomplete output,
  duplicate IDs and failed-report persistence/no replay.
- Ruff across src/tests/scripts and git diff --check passed. Documentation updated.
  Logs: responses-tests.log, responses-full-tests.log, scoped-fixture-check.json
  and scoped-fixture-check.py under the existing sidebar-reviewer-task directory.
- Restarted the idle browser server. Authenticated check confirmed the prior
  failed report now appears once in its saved chat, with actual exit code 4,
  and restart_required false. No paid review was replayed or retried. The new
  pairing code remains only in private workspace-review-server.log.

This validates captured errors, request construction and mocked protocol behavior;
it does not claim a successful live paid Responses review. Existing changes were
preserved. Nothing was committed, pushed or merged into a real project.


## 2026-10-28 — Shared project checks, offline dependencies and live token meters

The implementation present in this task was directly Codex-authored; it must not
be attributed to local harness models. A separate local harness lint follow-up
is recorded below with its actual run evidence. Existing unrelated edits were
preserved. No paid inference, real-project merge, commit or push was performed.

- Added a shared Python test-plan resolver and isolated runner for coding
  completion and workspace review. Shipped coder enables project_tests; custom
  coding profiles can opt in. Auto installs packaged projects from an independent
  source copy, exposes project/src imports and uses locked dev/test dependencies.
  No browser PYTHONPATH or per-run setup commands are needed. Exceptional projects
  can commit one .local-agent-tests.json contract; non-Python frameworks and
  unsupported dependencies still need explicit environment provisioning.
- Models receive a TDD helper. Completion independently checks current pending
  edits and returns failures for two bounded repair attempts. Changed Python
  implementations require regression-test changes. Root checks explicitly collect
  changed test files even when ordinary pytest discovery excludes their directory.
  Owner contracts are frozen so model edits cannot weaken the current checks.
  Collection errors, zero tests, setup errors and failed tests remain unverified.
- Dependency preparation uses a separate dependency-only Docker build. No project
  code or model scripts enter its network-enabled build context. Immutable images
  are cached by base, pyproject, uv.lock and groups/extras. Runtime and persistent
  code/test containers retain network-none policy. Uncached never-network plans,
  unlocked dependencies, URL/private/local sources and unavailable binary wheels
  fail visibly. Preparation failures are recorded before paid review starts.
- Header meters show measured local and OpenAI input/output totals across browser
  chats, with a verifier subset. Active job progress permits reading captured
  response usage before completion; pending or missing usage is marked partial.
  These are token counts, not guessed dollar charges or streamed-token estimates.
- Nested checks share the parent SQLite connection and restore its evidence
  budget. Fixed raw-fd reopening of existing SQLite databases, which could release
  another connection's POSIX locks and cause persistent reaper/WAL failures.
  Recovery fixtures that test mutation/crash mechanics explicitly disable project
  tests; actual coding publication and new completion tests keep them enabled.

Independent evidence:

- Actual analyzer candidate check run run_1a52a30f42d140f88d127206b0eb5ad2:
  project installed, all five submitted tests collected, exit 1 from their real
  relative-script-path defects. No local_agent import error. Candidate remains
  unchanged/unmerged; its CRLF bug and test defects are not claimed fixed.
- Real Firefox test with mocked Responses HTTP and real offline Docker passed:
  Auto review, measured partial usage while the next response was held, final
  usage, saved approval and explicit merge into a disposable test repository.
  No paid request or real-project merge. Evidence: auto-tests-tokens-firefox-final.log,
  check_auto_tests_tokens_firefox.py, live-token-meter.png and installed-fixture-proof.json
  under /home/ruthvik/.local/share/local-agent-development/sidebar-reviewer-task/.
- Browser server restarted only after checking there were no active jobs.
  Authenticated assets, saved thread access, usage endpoint and restart_required
  false confirmed. Pairing code remains only in the private server log.
- Usage updates follow captured responses; they do not count an in-flight
  non-streaming response. Passing configured tests does not prove exhaustive
  correctness or enforce the chronological red/green order of every model action.

Validation completed: **463 passed in 186.33 seconds** using the pinned sandbox
image sha256:a4eb1c5633b5e83bbef63da7d23fd3543a0143381809f3314621bdfc1f29ed63;
log test-plan-docker-complete-tests.log. Without the Docker acceptance flag,
390 passed and 73 correctly skipped; no skipped Docker suite is represented as
Docker validation. git diff --check passed. A lint-only harness follow-up is
still tracked separately from these passing behavior checks.


Local-model lint follow-up completed: run_4eaab77022ac453eb0a8335d3aea9b83,
qwen3.8:27b via actual local-agent run. Temporary orchestration profile inherited
coder settings, selected the already-installed local model, and disabled project
checks only for this isolated lint snapshot (it contains no runnable test suite).
Audited the run and reviewed its single-line exception-chaining diff; integrated
the exact agent-authored database.py artifact after asserting the destination
still matched its input snapshot. Independent Ruff across src/tests/scripts,
git diff --check and the targeted multi-Store WAL regression passed. The 463-test
full Docker result precedes this behavior-neutral one-line chaining change;
no repeated full suite is claimed. Temporary Git snapshots and agent candidate
commits are disposable evidence; no commit was made in the real source checkout.

Earlier local attempts are retained, not counted as success:
run_133a91153eaa48bf8ee01746cdba650a failed repeated exact patch matching;
run_ddd8c7e1b1f74ac7bfb2118dac551c52 stopped on Ollama HTTP 500;
run_d898a60b17b848d7906bbe8909d9a10b and
run_7319f38324574318b8256edf4a75ae92 exhausted turns rereading the same page.
The installed qwen3-coder:30b failed its capability probe
run_32192723b55d466499bbbd07495c23fe, so no implementation run was started
with it. Concrete follow-up briefs, temporary run profile, traces, artifacts and
logs are retained under sidebar-reviewer-task/wal-lint-* and lint-coder-run.yaml.
No paid inference was used to enforce the authorship agreement.


## 2026-10-28 — Repair saved reviews directly; document runtime state and diagnose failures

User explicitly authorized direct implementation: "you implement it, forget about
the local". Codex authored this feature and its tests. It is not attributed to
local models. Earlier actual harness attempts are retained under
/home/ruthvik/.local/share/local-agent-development/review-repair-task/: task
briefs, isolated working-state source snapshot, run profiles, ledger/blobs and logs.
run_fe5c3ec0df72463db2c316d37ac4ee96 exhausted turns;
run_68a9fec9147d43c7813529fd52e9d661 was cancelled after repetitive reads;
run_f40f4a295cc149cb8ab3acc19b29e8f0 was interrupted and reconciled rather than
assuming its stale running ledger meant the controller still existed;
run_f35297b0899d4821bd0a9a50f27afa84 (qwen3.8:27b) and
run_3a1093c96f294504b7c6d14a04945597 (glm-4.7-flash:q8_0) exhausted turns.
They produced no implementation changes. Repetition occurred both with and without
context compaction; a larger context window alone did not resolve it. No paid
model was invoked to enforce authorship.

- Added Fix with local model to saved changes-requested/failed workspace reports.
  Authenticated repair-review endpoint derives repository, workspace, directory,
  findings and check output from owned saved records. It rejects foreign/stale/
  mismatched/merged/approved selections and duplicate pending jobs. Current local
  coder/profile and execution selection are preserved; paid/noncoding selections
  are rejected. No browser source path or workspace ID entry is required.
- Repair tasks include bounded findings directly in their current question, plus
  retained scratch/repair-review.json evidence with blob-backed recovery metadata.
  The saved thread image is not silently reused. Per-job independent project tests
  are enabled, repair lineage/original task retained, and user-facing chat text
  stays concise. No automatic paid review or source merge is performed.
- Queued repairs validate the exact candidate/source run under the runtime lease
  before continuing. Tests prove a newer task prevents stale repair execution.
- User's specific workspace ws_f35d604ad3c5414597fefe7dc9f12b7e currently maps to
  failed run run_911ad87b40fc41389ad020168ca5ca44, job
  45c04f482103aa2e23bfdfa4e2daa41a, chat fad73a575e449de2127026da76d12070.
  Captured patch_file errors target text_stats.py: patch requires one exact match;
  write_file errors say create-only target already exists. This is model edit/tool
  failure, not evidence of a Docker test/import failure. Worktree is editing with
  no new published candidate. The candidate was not repaired or merged here.
- Added docs/runtime-data.md, linked from README/browser guide. It maps every
  storage/ID layer, distinguishes normal/MCP/development roots, explains hardcoded
  Linux default and --data-root override, host-mounted worktrees and model context,
  and documents the current cross-Continue keeper replacement limitation honestly.
  Container naming and cross-task reuse behavior were not changed in this pass.
- Browser Storage and traces now shows its actual data root/ledger. Thread event
  text includes run IDs. Future repeated edit failures name tool/path/actual cause.
  Historical run records were not rewritten.
- Inspected and removed 12 abandoned Docker test keepers whose temporary host
  metadata had been deleted. Verified pytest-only mount paths, owner/workspace
  labels, age, and only init/idle keeper processes before scoped removal. No browser
  workspace/container/data-root deletion or global Docker prune. Evidence:
  test-container-cleanup.json. Fixed project-runner and persistent recovery test
  teardown to remove all their keepers before temporary roots disappear.

Validation:
- Red test first: missing repair module produced collection failure, recorded in
  repair-red.log. Initial targeted integration: 26 passed, including actual Docker
  continuation, source unchanged, new candidate, independent checks and audit.
- Full pinned-image suite: 484 passed in 242.31s, repair-full.log. This precedes two
  extra override/CLI tests and final diagnostics/teardown edits; it is not claimed
  as a full run of the final tree. The subsequent extra tests passed independently.
- Final focused suite: 45 passed in 47.25s, repair-final-targeted.log: backend/API
  authentication and strict request fields, local model/mode, saved context beyond
  recent history, CLI normalization, stale queued target, Docker repair/audit,
  actual repeated patch failure diagnostics, all browser widgets, offline test
  runner and persistent crash recovery/cleanup. Docker ps showed no running
  containers afterward. Ruff across src/tests/scripts and git diff --check passed.
- Real Firefox: saved action survives reload, works with blank source/ID fields
  and paid reviewer disabled, carries exact findings/target, blocks duplicate
  clicks. No inference or real source merge in this browser probe. The initial
  probe used an unavailable Marionette sandbox global; switched that assertion to
  real DOM state and reran successfully. Evidence: repair-firefox.log,
  check_repair_firefox.py, repair-button-firefox.png.
- Idle browser restarted with unchanged data root and saved chats. Authenticated
  checks verify current repair assets, data_root and restart_required false.
  Pairing code is only in private workspace-review-server.log. Restart script and
  all validation artifacts remain under the review-repair-task evidence directory.

Existing uncommitted work was preserved. Nothing was committed/pushed in the real
repository and no real-project source merge was performed.


## Active plan — workspace sessions and bounded review/repair automation (2026-10-28)

User approved sequential implementation and direct Codex authorship (earlier:
"you implement it, forget about the local"). Preserve existing work and evidence.
Mark a task complete only after its behavior is independently verified. No real
paid review loop or source merge will be started during development validation.

| Priority | Task | Status | Acceptance |
| --- | --- | --- | --- |
| P0.1 | Workspace-based container names and legacy-name migration | VERIFIED COMPLETE | Stable owner/workspace name; existing idle keeper can be renamed without replacement; ownership still checked by ID/labels. |
| P0.2 | Reuse persistent keepers across Continue tasks | VERIFIED COMPLETE | Same container/worktree, preserved /tmp and jobs; consistent baseline snapshot; expiry/config mismatch/recovery and concurrent access handled. |
| P0.3 | One workspace details view and durable failed attempts | VERIFIED COMPLETE | Repository/worktree/container/current+prior attempts/trace root in one place; continue, failure, trace and stop actions; no manual workspace ID. |
| P1.1 | Carry task/repair evidence through workspace files | VERIFIED COMPLETE | Normal continuation selects the workspace; saved review/check findings remain accessible beyond chat truncation; independent tests stay enabled. |
| P1.2 | Durable bounded local/verifier controller loop | VERIFIED COMPLETE | Up to FIVE paid verification attempts by default, stop earlier on approval; thereafter local repair/test only; no more paid calls; bounded time/cycles/paid tokens; explicit stop, no-progress handling, crash-safe no automatic paid replay. |
| P1.3 | Browser loop controls, stages and usage | VERIFIED COMPLETE | Explicit opt-in authorizes the configured paid budget; visible current stage, cycles, failures and measured local/verifier token totals; tests-only success is not called verifier approval; merge separate. |
| P1.4 | End-to-end verification, documentation and rollout | VERIFIED COMPLETE | Real offline Docker reuse/recovery tests and browser workflow, full relevant regression checks, docs match behavior, idle server restart and saved history preserved. |

Run IDs remain immutable attempt records underneath a stable workspace/session;
container names use workspace identity, not run IDs. Historical data roots are
not moved or deleted. Dollar costs will not be invented when pricing is unavailable.

P0.1 verified: 18 lifecycle and real Docker tests passed in 16.03s; log workspace-names-tests.log under review-repair-task. Names include owner/workspace; compatible legacy-name migration retains container ID. Direct Codex authorship.

P0.2 verified: 36 publication/repair/lifecycle tests passed in 23.85s; 13 continuation, lifecycle and persistent recovery tests passed in 11.82s after correcting committed-result keeper reconciliation. Real Docker proves same container/worktree across attempts, /tmp marker and background PID survive, legacy rename retains ID, incompatible resource settings replace keeper. Snapshot guards pause/unpause under a workspace lease, recover interrupted pause intent, and freeze independent check/candidate capture. Logs workspace-reuse-tests.log and workspace-continuation-tests.log.

P0.3 verified: 24 dashboard/chat/widget tests passed (two Docker-only cases skipped in this focused host run). Workspace endpoint enforces chat/root ownership; failed attempts persist idempotently; panel provides continue/trace/failure/stop controls. Prior P0.2 Docker tests cover the underlying containers and worktree. Log workspace-dashboard-tests.log.

P1.1 verified: 32 dashboard/context/repair/widget and real Docker session tests passed in 17.00s. Continued tasks receive bounded goals, attempts and checks in scratch/task-context.json, with a blob-backed recovery reference and queued-attempt guard. Review evidence remains separately retained. Log workspace-context-tests.log.

P1.2 controller validation: 37 tests passed, 2 Docker-only tests skipped in the host-focused run. Tests cover default five paid attempts then local-only success (unverified), early evidence-backed approval, duplicate callbacks, explicit authorization, selected local model, stop/time/cycle/stall/unknown-usage guards and restart without paid replay. Loop stages use ordinary durable browser jobs with frozen configs and attempt reservations. End-to-end Jobs/Docker/HTTP validation remains P1.4. Log browser-loop-tests.log.

P1.3 focused verification: 20 loop/widget/budget tests passed in 1.96s. Browser requires explicit paid consent, starts with five paid attempts by default, binds workspace without paths/IDs, follows queued stages, shows measured usage and allows stop while busy. Paid per-request gate reserves conservative input plus output and refuses unknown-usage retry. Log loop-ui-tests.log.


P1.2/P1.3 end-to-end verification completed:
- Real HTTP browser jobs -> scripted local coding in real offline Docker -> mocked
  official Responses transport with actual review tools/check copies -> local
  correction -> second review. Both approval and paid-exhaustion/local-only paths
  passed, with exact measured token aggregation, unique run IDs, unchanged source
  checkout and the same coding keeper. Five-paid-attempt exhaustion exercised SIX
  local iterations and FIVE reviews without accumulating check/review keepers.
  loop-five-real-tests.log: 16 passed in 110.19s (includes runner coverage).
- Real Firefox drove explicit authorization/default five, selected workspace with
  blank path/ID fields, actual stage polling through local/review/local/review,
  measured totals, saved approval/reload and keeper reuse. No paid HTTP request
  escaped MockTransport. workspace-loop-firefox-final.log and screenshot
  firefox-workspace-loop-approved.png retained under review-repair-task.
- Initial broad regression run found two completion-publication races (504 passed,
  2 failed). Corrected Jobs callbacks so only the worker can see its not-yet-public
  terminal source result; HTTP clients see terminal status after chat persistence.
  loop-callback-tests.log: 33 passed in 51.94s. A dedicated blocked-callback test
  prevents recurrence. Controller errors also retain progress run/workspace IDs.
- Subsequent full pinned-image suite: 510 passed in 339.76s,
  workspace-loops-final-full.log, sandbox image
  sha256:a4eb1c5633b5e83bbef63da7d23fd3543a0143381809f3314621bdfc1f29ed63.
- After final mode-inheritance, initial-saved-review, success-label and stop-trace
  refinements, workspace-loops-final-focused.log: 26 passed in 83.08s (all three
  real loop paths included). Final loop-last-guards.log: 24 passed in 2.41s,
  including the additional controller-progress correlation test. The earlier full
  count is not represented as a new full run after these small refinements.
- Ruff across src/tests/scripts and git diff --check passed. Docker ps showed no
  leftover test containers after teardown. Existing failed chat inspection found
  one workspace/eight linked attempts with its original workspace ID preserved.

Implementation notes and limits:
- Stable names are local-agent-<12-character-owner-prefix>-<workspace_id>;
  exact IDs, ownership labels and attestations remain authoritative. Compatible
  idle legacy names migrate on reuse without replacing the container.
- Keepers pause during consistent baseline/completion guards, INCLUDING bounded
  independent checks. Background state survives but execution is suspended during
  those guards. Image/resources/expiry/health can replace a keeper. Ephemeral mode
  remains supported; continuation and loop controls inherit a recorded mode unless
  explicitly overridden. Independent check/review copies are always disposable.
- A loop's FIVE default paid attempts are reserved before enqueue; an attempt can
  contain multiple model requests and a blocked preparation is not proof of a
  billed call. Configs/limits/authorization are frozen and ledger-linked. Conservative
  input+output token reservation gates provider calls; unknown usage disables later
  paid calls. No dollar prices are invented. Stop/time limits prevent new stages;
  a current bounded stage may finish. A restart interrupts loops without replaying
  local or paid work. Unreconciled attempts block further automatic scheduling.
- After paid review ends, local testing continues until success, a configured limit
  or stalled output. Success then says tests passed/latest changes not verifier
  approved. An approved loop does not merge. Local model correctness is not guaranteed.
- docs/browser.md, docs/runtime-data.md and docs/executor.md now describe this
  behavior, state locations, IDs, loop controls and the persistence limitations.

All implementation/tests here are directly Codex-authored under the user's
explicit override. Existing user edits, historical traces and data roots were
preserved. Nothing was pushed or committed in the real source checkout, and no
real-project source branch merge or paid inference was performed in validation.


P1.4 VERIFIED COMPLETE — all seven prioritized tasks are complete.
Final rollout checks: idle production browser restarted at 192.168.1.22:8767 with
its original data root and saved history. Authenticated /api/info reports
restart_required=false and the correct data_root. The existing failing chat's
/workspaces endpoint returns one workspace/eight attempts, its saved chat now
retains three failed replies, and /loops returns no existing loop: deployment
started no local loop or paid review automatically. Pairing code remains only in
private workspace-review-server.log; reload and pair again after the restart.
Ruff and git diff --check passed, and Docker ps showed no leftover test containers.
Historical roots, run/workspace IDs, user source worktree and failed candidate were
not moved, deleted or merged. This completes the approved high-priority plan;
consolidation/deletion of historical development directories remains deliberately
outside this plan. Validation uses mocked model/API behavior plus real Docker and
browser execution; no claim is made that every local model can solve every task.


P1.5 IN PROGRESS — readable browser traces and retained command output.
- User reports the raw trace mixing token-surrogate JSON and legacy `phone`
  bookkeeping with coding history. `phone` is the browser controller actor;
  `completion.proposed: Activity recorded` is not a code verification result.
- Independently inspected production run_a28306bdf188483788845f1e3a3e7a1d:
  30 actual model requests, 364801 input + 2456 output local tokens. Actions:
  15 list_files, 1 search_files, 4 read_file, 1 patch_file, 9 run_command;
  8 failed/rejected tools. The successful edit was calculator.py, not text_stats.
  Calculator-only pytest later passed. Broader pytest retained output is 57074
  bytes and ends: 21 failed, 338 passed, 57 skipped in 22.85s. Earlier commands
  failed on local_agent imports, absent uv, offline pip, and invalid argv/env.
  Later directory listing repetition ended at the model-turn budget. No
  controller-owned project.tests result was recorded, which DOES NOT imply no
  model-requested tests ran. Existing failed candidate/source untouched.
- Initial diagnostic module/session/runtime-budget drafts predate this latest
  authorship instruction. They are not represented as harness-authored or verified
  UI behavior. Current instruction uses actual local harness implementation.
- Isolated source snapshot of 255 tracked/unignored files (including preexisting
  working changes) under review-repair-task/readable-traces/source. No source
  commit/push/merge. Task brief task.md, actual config config/coder.yaml,
  qwen3:30b-a3b-instruct-2507-q8_0; capability run
  run_96e56394c8fc44aba537a5651f30b1f8 completed_unverified. Coding run
  run_02dd879253cb4930af53ebcd04389599 exhausted on repeated pytest import
  failures after attempting checks before implementation; no implementation
  diff. Corrective followup.md narrows scope to authenticated diagnostics/output
  endpoints and absent-run handling, specifies project cwd + PYTHONPATH=src,
  forbids repeating unavailable tooling, and requests real implementation/tests.
  Follow-up run_49ac313234a44a34b792598cb22f3814 in same isolated workspace
  ws_9b1a0739554a4630a30bb09019f69416 is under review. Neither diagnostic
  endpoint nor readable UI has been deployed or claimed complete.

P1.5 implementation BLOCKED — investigation complete; no rollout.
- Corrective run_49ac313234a44a34b792598cb22f3814 stopped after three
  identical patch_file exact-match failures. Its fabricated old_text contained
  nonexistent HTTP methods and SQL table, so no unsafe change was integrated.
- Further followup-2.md gave the real handler location, pagination, existing
  response methods, ownership helper and one-endpoint scope. Actual local run
  run_7b94d8a449824be5b6b8af947c4c2fc8 repeatedly read the initial file chunk
  without the requested pagination, then exhausted 30/30 model requests. No
  implementation diff from any of these three harness runs. Under current
  AGENTS.md authorship guidance Codex did not take over implementation. Existing
  draft changes remain drafts, not deployed features or agent-authored work.
- Independent baseline checks: 8 passed in 0.36s (workspace dashboard and UI
  fixtures), baseline-checks.log; Ruff for existing diagnostics/session/runtime
  drafts passed. These checks DO NOT verify a new readable browser timeline.
- Review artifacts extracted read-only from original evidence:
  readable-traces/run_a283-readable-review.txt (plain action timeline) and
  run_a283-full-pytest-output.txt (all 57074 retained output bytes). Actual broader
  run result 21 failed,338 passed,57 skipped, not an inferred success. No paid
  calls, production tasks, browser restart, candidate modification or merge.


P1.5 implementation resumed — user explicitly authorized direct implementation.
Codex directly authored readable job diagnostics and owned retained-output GET
routes; shared browser timeline renderer replaces the default bookkeeping JSON.
Raw original events remain advanced/on demand. Failed action reasons, request
budget, actual usage, related independent checks and idle keeper labels are
visible. Historical model-turn reasons derive readable summaries without
modifying historical ledger events. Missing saved run evidence no longer breaks
workspace failure listings. Tests cover long retained output, schema rejections,
policy denials, cross-run access rejection/auth, live run resolution and browser
rendering/navigation. Initial focused run: 11 passed in 1.21s; wider checks pending.
No local inference or paid verification is required for this implementation.

P1.5 implementation VERIFIED — live activation deferred for the user's active loop.
- Final code is directly Codex-authored under explicit user instruction, not
  attributed to the failed harness runs. No candidate/source merge or paid call.
- Targeted verification.log: 49 passed in 29.00s, including real pinned-image
  Docker project test preparation/execution plus authentication/ownership and
  all six browser DOM fixture scripts. After budget-summary fallback and absent
  saved-run regression additions, final-verification.log: 49 passed in28.54s. Ruff across src/tests/scripts and git diff --check passed.
- Actual Firefox validation: browser-check.log PASS, screenshot
  readable-traces/firefox-readable-timeline.png. Paired saved fixture chat,
  readable 1/1 budget stop, auto-expanded command failure, full retained output
  tail beyond10000 bytes, capture notice, raw JSON on demand, phone explanation.
  Scripted provider/mock executor only for Firefox; no real inference.
- Independent read-only inspection with the new describe_job/output functions
  confirms the original production run has30 requests/eight failed tools,
  measured364801+2456 tokens, and all57074 pytest output bytes ending with
  21failed/338passed/57skipped. Historical ledger/candidate left unchanged.
- Live restart was attempted only through the guarded restarter. Its active-job
  check rejected restart before touching the process. User-started loop
  adf4b3ea94fb6d720aac9193721bab15 remains running (second local attempt at
  observation). The existing live server still serves its previously loaded
  assets; these verified changes require a server restart once that loop ends.
  No task cancellation or automatic restart has been scheduled. Browser guide
  documents the new controls and capture/usage limitations. Work is implemented;
  rollout remains pending, not represented as deployed or user-visible yet.

P1.5 rollout VERIFIED COMPLETE — user authorized restart; no active jobs or
running loops remained at preflight. Restarted original browser on
192.168.1.22:8767 with original data root/history and reviewer configuration.
Authenticated live checks confirm restart_required=false, new timeline assets,
original run_a283 diagnostics showing30 actual requests and owned full retained
pytest endpoint returning57074 bytes including21failed/338passed/57skipped.
No new model task or paid review started. Pairing rotated; current code remains
only in private workspace-review-server.log. Reload/re-pair to use the new UI.

P1.6 DIAGNOSED — user-reported stalled9-attempt loop. Read-only inspection:
five Ollama500 bodies report invalid generated write_file/patch_file arguments
(unexpected end of JSON input), not a pytest error or inferred Docker crash.
First run repeated invalid overwrite arguments without expected_hash; dot cwd
also rejected. Another run attempted create-only writes over existing conftest.
One run exhausted30turns repeatedly reading test_mobile_tokens.py; another hit
16384output tokens returning44proposed calls, rejected as partial. All nine local
jobs failed, none recorded an independent project.tests result, so current
completed-job gate never scheduled paid review. Stall signature matched candidate
tree + missing test status + identical500error on the last three runs; displayed
same test outcome wording does not establish that tests ran. Full compact review
in readable-traces/loop-failure-review.txt. No implementation, inference, task
restart, paid call, source/candidate modification or merge during this inspection.


P1.7 ACTIVE — harness tool/recovery improvements (user authorized direct work).
Priority order:
[ ] 1. Explain Docker tool semantics and valid path/schema/hash examples; return
        targeted correction hints after invalid calls without weakening validation.
[ ] 2. Show retained Ollama error details and preserve usage/partial-output safety.
[ ] 3. Carry concrete failure evidence into continuation; after repeated local
        failures permit one bounded advisory diagnosis from the already-authorized
        paid allowance. Diagnosis cannot approve/merge or bypass independent tests.
[ ] 4. Verify corrections with unit, Docker and controlled local-model runs;
        document actual results and deploy if browser has no active work.
Keep offline execution, expected-hash preconditions, audit, paid count/token caps,
stop/restart semantics and user workspace/source intact. Do not start paid calls
for implementation validation. Existing stalled loop is not automatically resumed.

P1.7 progress:
[x] 1. Host-side tool guidance/examples plus targeted rejection/execution feedback;
        strict cwd/hash/schema validation retained. Actual project content changes
        reset repeated-action failures; unchanged/failed writes do not. Test-driven
        regression covers three failed reproductions across real edits then pass.
[x] 2. Retained Ollama error field is included in status errors and old-run
        diagnostics. Known malformed-tool500/partial-tool output can receive ONE
        corrected local response per run, recorded durably and within turn/time
        budgets; no partial calls dispatched, no automatic paid-provider retry.
[x] 3. Continued task context includes bounded controller-derived failure facts.
        New authorized loops can spend one shared paid attempt on tools-free
        advisory diagnosis after two local failures if another local cycle remains.
        No approval/merge, shared token/time/count limits, unknown paid outcome
        disables later calls. Existing stalled loop not resumed. Consent text updated.
[ ] 4. Broader validation/rollout in progress. Initial Docker checks58passed127.06s;
        subsequent focused33passed22.43s covers guarded local retry and edit/test
        progress. Full suite running with pinned Docker image.
Additional harness defect fixed: Ollama context payload previously omitted the
compaction lineage note even when the builder constructed it. Regression now
asserts the model actually receives the omitted-history notice.
Controlled real local probe: run_065dad3e36484aa6b5056548b194b4bd used valid edits
and tests after one cwd rejection but failed CRLF correctness; old failure guard
stopped after baseline plus subsequent test failures. Followup
run_86a21d8f2eff4aa09f024c2fa70a7aab understood newline preservation but sent
three identical old_text patches with invented blank lines/escaped quotes, so
strict matching blocked them. A concrete smaller-patch follow-up is running.
All probe artifacts are under review-repair-task/tool-recovery-probe, isolated
from production workspace and source. No paid inference is used for validation.

P1.7 validation update:
- Full pinned-image suite: recovery-full.log,521passed300.85s. This full run
  precedes small final guidance text, output-limit classification and browser
  prompt propagation refinements. Subsequent recovery-final-guards.log46passed
  24.73s covers final local repair/paid diagnosis mechanics with real Docker.
- Final provider tests also distinguish malformed-tool500 from out-of-memory500;
  only the former is automatically repairable. Length-limit feedback is eligible
  for the one local repair even if no parsed tool_calls survived. Tool-less turns
  and paid providers remain ineligible. Raw partial calls are never dispatched.
- BrowserAgent overrides the CLI message builder; explicit propagation of the
  shared GUIDE was added there and a regression asserts its presence in actual
  coding-browser messages. Browser/runtime/worktree/mode guard suite running.
- Third native Qwen probe run_9a15e426c8914308ba512b9d018b3778 still failed
  after valid mutations/tests, ending in16384-output-token exhaustion. This is
  NOT a claimed successful model coding result. Real native trials demonstrate
  remaining model errors even after protocol fixes. The final length-classification
  refinement postdates that probe; no fourth native attempt or paid API call was
  started. No production source/candidate was changed by these probes.

P1.7 VERIFIED COMPLETE — harness changes deployed, residual model limitation recorded.
[x] 4. Full regression baseline521passed300.85s (recovery-full.log). Final
        provider/recovery/loop/UI guards46passed24.73s; after explicit browser
        prompt guidance propagation, final browser/runtime/worktree/execution-mode
        suite54passed47.56s (recovery-browser-guards.log). Ruff acrosssrc/tests/
        scripts and git diff --check passed. Full baseline is not represented as
        a rerun after final small refinements. Pinned Docker image unchanged.
Final native trials did NOT solve the CRLF task. Third trial returned an
output-limit response with no parsed calls, which exposed the eligibility gap;
final code now allows one corrected local response for length-limited tool turns
regardless of whether partial calls parsed. Native probe was not rerun afterward.
Do not claim general local-model correctness or a successful native fix. Recorded
run IDs, concrete failures, original/candidate code and all traces remain in the
isolated tool-recovery-probe root. Harness implementation is Codex-authored under
explicit user authorization; isolated probe edits are actual Qwen output and were
not merged into source.
Rollout preflight found0activeproductionjobs/loops. Guarded restart preserved
original data root/history and configured reviewer. Authenticated live checks:
restart_required=false; new diagnostic consent visible; old500trace now exposes
unexpected-end-of-JSON provider detail. Original loop remains stalled9local/0paid,
not auto-resumed. No paid model call or production code task launched. Pairing
rotated; current code stays in private workspace-review-server.log. Reload/re-pair.
Documentation: docs/browser.md describes tool guidance, progress-aware failure
counting, one bounded local response repair and shared-budget advisory diagnosis;
docs/executor.md explains Docker cwd/argv and returned output. Native-model
reliability remains an explicit limitation, not hidden by the passing harness tests.

P1.8 INVESTIGATION — user challenges attribution to model capability.
Verified local /api/tags includes qwen3.8:27b, qwen3-coder:30b, and older
qwen3:30b-a3b-instruct-2507-q8_0. config/coder.yaml and frozen failing
run_8311... both specify the older Qwen3 tag. All recorded native CRLF probes
used that configured tag, NOT qwen3.8:27b. They cannot support any assessment
of Qwen3.8. Previous broad "model reliability remains unresolved" wording must
not be read as an isolated capability result or a Qwen3.8 evaluation.
Inspected actual captured model context: read_file output is JSON serialized
inside result.preview, then that wrapper is serialized again into tool.content.
The model receives nested escaped source, hash and pagination metadata. Probe
patches contained literal backslashes before quotes and invented whitespace.
Nested serialization is a concrete harness usability concern consistent with
those mistakes; causation is not established without a controlled comparison.
No model inference, paid call, configuration change or production restart in
this inspection. Passing scripted harness tests are not evidence of effective
native-model coding or a fair comparison between models/harness conditions.


P1.9 ACTIVE — user requested actual Qwen3.8 native-versus-harness comparison.
Installed tag qwen3.8:27b verified via local /api/show:27.3B,Q4_K_M,
family metadata qwen35; exact tag/digest/version retained in benchmark metadata.
Three independent tiny Python tasks: addition, CRLF original character counts,
and JSON quoted/multiline string encoding. Three arms per task: native direct
Ollama file-map answer, independent clean plain-output tool loop, and actual
browser harness runtime with project checks. Same model/temperature0/think=false,
65536context/4096output; tool loops12turns/36calls/600seconds, modeltimeout180s.
Thinking-disabled is a matched condition, not a best-possible-model evaluation.
Direct arm is one-shot with complete visible source/tests; tool arms inspect files
and can iterate. This protocol difference is reported, not concealed as causal
proof. Order rotates across tasks to reduce cache/order bias; one trial per cell.
Original visible tests and separate5-case private checks are identical per task
across arms. Baseline must fail each private suite. All code/tests execute in
network-disabled pinned Docker, bounded resources; no generated code executes on
host. Sources/checks/raw HTTP payloads/results/run IDs retained under
review-repair-task/qwen38-comparison; benchmark.py is reproducible. Real runtime
source/config unchanged; no paid calls or production workspace/loop changes.
Results not yet claimed: benchmark is running and results.json updates per cell.

P1.9 VERIFIED COMPLETE — actual Qwen3.8 comparison, retained Report.md and
reviewed-results.json under review-repair-task/qwen38-comparison.
All9implementation candidates passed5/5privatechecks=45/45. Complete task results
including generated regressions: native direct2/3, clean tools3/3, harness3/3.
Direct CRLF answer generated a bad Unicode test expecting14instead of13characters;
implementation itself passed all private checks. Test was not repaired. Iterative
paths' regressions all passed independently. Supplied public tests unchanged,
no unexpected project files. Docker grading was read-only/offline, separate from
model tests. No mocked inference, paid calls, production config change, merge,
production task/loop restart, or leftover native-clean benchmark containers.
Measured coding-run totals: direct3requests/732input+654output/21.75s;
clean14requests/15472input+1581output/23.14s;
harness25requests/111618input+2665output/85.08s. Shared harness capability preflight
adds2requests/2669input+35output and is separately recorded. Timings include each
path's setup, exclude common independent grading, and have cache/load/order effects.
One trial per cell, think=false for all: not statistical evidence or a best-settings
model comparison. Clean tool interface differs in several ways, not a single JSON
wrapper ablation. No reproduction of the original large continued workspace.
Harness runs (all controller tests passed, audits true):
addition run_89e070d10a764a20970741135599b24f;
CRLF run_6299355720fe4614878693bc475c1848;
JSON strings run_b9fdbed2cd4144c29240468be2ccde12.
Runtime file hashes matched before/after. Exact installed tag digest:
aaee06c39dcf2437cde036998d960e1fc1494b8191be7cc9657d01e509097813.
This evidence supersedes capability speculation from earlier tests of the older
qwen3:30b-a3b-instruct-2507-q8_0 tag. Production coder.yaml still uses that older
default; benchmark selection explicitly used qwen3.8:27b without changing it.

## 2026-10-29 — Current-chat header token counters

Authorship: Codex direct implementation, explicitly authorized by the user's
“you do it by yourself” instruction for this task. No harness model run was
invoked; no agent run ID or model authorship is claimed. Existing uncommitted
work was preserved.

The header now renders the selected thread's existing usage report rather than
all-browser usage. New chat resets local and OpenAI/review counters synchronously
to zero. Late results for a previously selected thread cannot replace the active
header. All-chat totals remain in the expandable usage details; header accessibility
text describes current-chat scope.

Validation: 11 tests passed in Docker using `uv run --locked --no-sync --python
/opt/check/.venv/bin/python pytest -q -p no:cacheprovider
tests/test_workspace_results_ui.py tests/test_mobile_tokens.py`. Coverage includes
saved-chat restoration, distinct per-chat counters, new-chat zero counters, delayed
previous-chat usage, and existing accounting/partial-usage behavior. Container used
a read-only source mount, no network, UID 1000, and cached tokenizer data. An initial
accounting run lacked tokenizer data and failed its encoding-dependent test; the
rerun with existing cache passed. Python 3.12 in the test image, versus the repo's
3.14 preference. `git diff --check` passed. No live browser session or running server
was restarted or exercised.

### Follow-up — retain global cards and add current-chat cards

User clarified that two additional cards were wanted alongside the original two.
Codex directly updated the same task: four header cards now show all-chat local,
all-chat OpenAI/verifier, current-chat local, and current-chat OpenAI/verifier
usage, with explicit scope labels and a two-column layout. Starting a new chat
zeros only its current-chat counters. Extended DOM checks verify all four labels,
distinct totals, and preservation of global counters on New chat. Same offline
Docker validation: 11 tests passed. No live server restart or browser interaction.

### Runtime refresh for token cards

Restarted the browser server at 192.168.1.22:8767 on user request, retaining its
data root and verifier configuration. The old server cached static assets at
startup. Verified via HTTP that the restarted server serves all four token-card
IDs. Pairing sessions reset; the new pairing code is in the existing private
workspace-review-server.log (not copied into this record).

### Game project source path

Created /home/ruthvik/projects/dodge-the-blocks and initialized main with an empty
Git commit so the harness can create a workspace from HEAD. No game code written.
Restarted browser server with its original repository root plus an explicit allow
root for this game directory; retained data root and verifier configuration.
HTTP root returned 200. Pairing reset; code stays in the existing private log.

### Shared project root

Created /home/ruthvik/harness-athored-projects using the user's exact spelling.
Restarted browser with that parent as an additional --allow-root, retaining the
harness repository and existing dodge-the-blocks path, data root, and reviewer.
Projects beneath the new parent can be selected without another allow-root change.
HTTP root returned 200. Existing game folder was not moved. Pairing reset; the new
code remains in workspace-review-server.log.

### Default source workspace ordering

The browser's workspace input defaults to allowed_roots[0]. Reordered the live
browser startup arguments so /home/ruthvik/harness-athored-projects is first,
retaining both other allowed paths and existing data/reviewer configuration.
Restarted server; HTTP root returned 200. No implementation changes. Reload and
re-pair are needed to obtain the new default in a fresh form.

### Generated game verification and preview

Inspected sandbox ws_eb981235e7174e15b607c76564163297 without changing its code.
Independent Docker execution of existing tests: 17 passed. These cover game.py,
a Python mirror, not the browser's game.js; browser behavior remains unverified.
Started read-only static preview container local-agent-dodge-preview at
http://192.168.1.22:8768/; page and game.js returned HTTP 200. Project code is not
executed on the host by the preview server; JavaScript executes in the player's
browser. This preview is separate from the paired harness browser server.

## 2026-10-29 — Continuation failure investigation and Git bootstrap work

Production job 4c70c528e52dc4de219cb5fc8d79ef48 reported a phantom run ID
run_8db7ed747f8f40b0b8e0ae9213152048. Read-only DB inspection confirmed no such
run row. Its requested workspace ws_eb981235e7174e15b607c76564163297 has no managed
Git record: original source was an empty non-Git folder, imported as a snapshot.
Continuation validation fails before create_run, but the allocated run ID leaks
into the result and job_usage lookup obscures the underlying setup error.

Preserved original game files byte-for-byte into the previously empty source
/home/ruthvik/harness-athored-projects/dodge-the-blocks and initialized main with
baseline ef9216e. `diff -qr --exclude=.git` confirmed identical files. No game
implementation or leaderboard changes were written by Codex.

Harness task artifacts: ~/.local/share/local-agent-development/continuation-error-task/.
Older configured Qwen3 run run_9ef52ea31f354439b6c879b2c3691985 was cancelled after
review found regression tests using nonexistent APIs; nothing integrated. Qwen3.8
run run_885e1ce6037048ca865eeb67a1363114 exhausted its inherited 12-turn budget with
no changes. Expanded retry run_12ba139d692f4ccea511d66158c43ddb was cancelled after
repeated broad inspection without a patch. Concrete follow-up briefs split the
work into Git bootstrap and pre-run failure reporting; each uses actual
local-agent run with task-only coder-run.yaml (qwen3.8:27b, 60 turns), isolated
source snapshots/data roots. No product configuration changes or direct Codex
implementation. Final run results and verification will be recorded below.

Baseline independent Docker checks: 29 passed, 3 skipped across git_workspaces,
workspace_tasks, mobile_tokens, browser_runtime. Test image is the prepared
local-agent-chat-meter-check image; source read-only and network disabled.

### Final scope and direct Git implementation

User explicitly instructed “you just do the git part, i will make the harness add
the leaderboard part.” Codex implemented only automatic Git bootstrap directly
under that authorization; no harness-authored patch is claimed or integrated.
Broader repair/model tasks were cancelled. Pending phantom-run reporting remains
outside this final Git-only change.

Workspaces.create_coding now validates the source/data-root relationship, then
initializes non-Git projects before normal managed-worktree creation. The helper
builds a validated temporary source snapshot beside the project, creates main
and a literal baseline commit using sanitized Git plumbing, and publishes only
its .git directory. Existing source files stay unchanged. Import exclusions and
.gitignore apply; no Git hooks/templates/clean filters/signing execute. Existing
Git repositories retain their history and dirty files; general snapshots are
unchanged. Docs explain new Git projects and legacy snapshot continuation.

Regression first run before implementation: 3 failed / 9 passed. New coverage
includes empty/populated project initialization, binary-preserving CRLF baseline
with attributes, exclusions/ignore rules, candidate publication and continuation,
invalid starting refs and nested data roots without partial .git, and symlink
rejection without partial .git. Existing dirty-source/history tests remain green.
Focused Docker verification: 33 passed, 6 skipped. Full independent Docker suite:
446 passed, 82 skipped in 39.36s (tests requiring live/nested Docker services are
among skips). Full log: continuation-error-task/direct-git-tests.log. Commands
used uv run --locked --no-sync with the prepared image's Python environment;
source read-only, network disabled, tokenizer cache read-only. git diff --check
passed. Browser coding jobs start a fresh CLI subprocess and therefore load this
change for new requests; no browser server/pairing restart needed.

## 2026-10-29 — Game startup and repeated import failures

Inspected user browser run run_76cca172d92c48a6a44d14bd313d9dbe: 31 Python tests
passed, then the agent repeatedly probed unavailable Python modules including
esbuild, py_mini_racer, quickjs, and others. The exact quickjs import command
failed three times, triggering normalized-request failure counting. Different
module names in the last three UI rows are not themselves identical actions.
No dependency installation or harness failure-policy changes were made.

Actual startup issue: game.js begins in READY, while index.html hides #overlay
and boot never reveals it. Enter/Space can start the game. Local harness fix run
run_7db1f1349b5c48dda3e8be9cb62d8cac, qwen3.8:27b, completed_unverified; artifacts
under ~/.local/share/local-agent-development/game-start-overlay/ retain task,
run config reference, output, trace data, and isolated source. Reviewed diff is
one HTML change making the initial Start overlay visible, with game-over still
hidden. Only that exact agent-authored index.html was copied into workspace
ws_1fdd17910a9b4468b17bcea00602b134 after checking its original file matched the
captured source and no active browser job owned the workspace. No Codex-authored
game implementation. The change is an uncommitted workspace edit retained for
subsequent continuation; it is not claimed as a newly published candidate commit.
Independent Docker verification: 31 existing Python tests passed; these test the
Python mirror, not browser gameplay. HTTP preview confirms visible initial
overlay markup and hidden game-over markup. No live-browser gameplay test.

## 2026-10-29 — Model-requested Docker environments

Authorization: user requested two local implementation attempts, then explicitly
allowed Codex takeover if unsuccessful. Both actual local-agent run attempts used
qwen3.8:27b, task-only terminal-tool configuration, 128K context/32K output reserve,
25 model turns, isolated snapshot and data roots. Artifacts, task brief, configs,
run JSON, SQLite traces/blobs and logs remain under
~/.local/share/local-agent-development/environment-requests/.

- Attempt 1: run_cd7bab4320bb47f797156300023e079e, budget_exhausted on three
  repeated failed imports (pydantic/local_agent absent). No implementation diff.
- Attempt 2: run_a9c8b59230124248a42e7715a9d114c4, enabled existing Python project
  preparation and supplied concrete follow-up; exhausted 25 turns inspecting
  without producing a patch. No implementation diff integrated.
- Codex then authored the implementation/tests directly under the user's explicit
  fallback authorization. No successful local-agent authorship is claimed.

Implementation: environment_inventory and prepare_environment tools, strict
operator preparation settings, separate controller-owned adapter recipes, actual
image inventory, declarative Debian/Python packages and locked npm/UV manifests,
image cache keyed by base/spec/recipe/manifest bytes, structured blocked outcomes
and per-run failed-request reuse. Docker builds can download when explicitly
allowed; subsequent code commands remain offline. Commands, streamed chunks,
bounded complete stdout/stderr, Dockerfiles, captured manifest bytes, exit codes,
duration and immutable image selection are durable and included in run exports.
Builds do not receive project source/control/secrets mounts. Registry installers
and UV lock export execute inside Docker. Protected worker/verifier/toolkit bytes
are checked from image archives using Docker cp, without executing the prepared
interpreter for that check.

Persistent keeper replacement preserves source files, stops old processes and
refreshes installed npm dependencies. Completion checks, independent workspace
checks/review, continuation and resume retain the originating run's selected
image. Interrupted preparation with a known result is reconciled without
rebuilding; without a published result it requires reconciliation. New coding
context includes inventory and instructions to request setup instead of repeatedly
probing absent packages. Coder token/model/turn settings were preserved; only
new tools and an explicit preparation-download grant were added.

Chromium's full GUI binary exceeded the existing 128-task limit. The tested
adapter instead uses Debian chromium-headless-shell plus harness-browser with
bounded CPU affinity, retaining Docker's existing process/privilege restrictions.
Real verification built a mixed Python/npm environment, imported a locked Python
wheel and a locked npm dependency (including ESM use), executed JavaScript in a
headless browser, inspected a candidate through the real review/check pipeline
with a scripted reviewer, and continued offline with the same image. This tests
review plumbing, not an independent LLM's approval of this implementation. No
paid verifier inference was used.

Validation (all code/tests executed in Docker):
- Final full suite: 466 passed, 83 skipped in 41.00s. Skips include tests requiring
  explicitly enabled live/nested services; real Docker cases were also run below.
- Real mixed-environment/review/continuation integration: 1 passed in 34.32s.
- Docker-enabled project-test/Git-runtime regressions: 16 passed; the initial
  three persistent-recovery cases exposed an older crash fixture attempting to
  initialize Git in a read-only repository fixture. Fixed that test driver to
  create a writable temporary source copy. Rerun: all 3 passed in 16.44s.
- Additional new fault-injection tests cover a crash after environment result
  publication but before DB commit, both with and without the result marker;
  no build replay and successful audit of known-result recovery.
- Ruff on touched Python paths and git diff --check passed.
- Logs: verification/full-tests.log, real-docker.log, docker-regressions.log
  (includes the explained initial fixture failures), recovery-final.log.

Operational check: browser restart exposed the earlier phantom
run_8db7ed747f8f40b0b8e0ae9213152048 during migration. Missing historical runs now
produce explicit unavailable token usage, retain the failed exchange, and make
savings estimates unavailable rather than fabricating counts. Added idempotent
restart/accounting/UI tests. Original run/job identifiers and errors are retained.
Browser restarted with its prior data root, allowed roots and reviewer profile.
Authenticated live API checks confirmed coder profile validity, both new tools,
allow_network=true, window_tokens=131072, output_reserve_tokens=32768, and explicit
unavailable accounting. New pairing code remains only in the existing private
workspace-review-server.log. No code-generation attempt was automatically replayed.

Limits: initial built-in capability adapters target the pinned Debian/Python
sandbox, Node/npm and Chromium headless; generic registry package requests cover
additional installed tooling. Other OS/package managers and private/local/Git
dependency sources need operator adapters. npm lifecycle scripts are disabled in
preparation; needed scripts run subsequently in the offline sandbox. Preparation
has time, request-count and captured-output limits; cached images occupy disk.
Documentation: docs/environment-preparation.md and README/executor links.

## 2026-10-29 — Inspection of user leaderboard attempt

Inspected run_b79efbcf32684d1e981c7434a76bb16d in workspace
ws_b919b8b20c1c4d8cb4188aedd7d41564. Environment inventory and actual preparation
succeeded: Node/npm and Chromium headless were installed into immutable image
sha256:896939ce838daba09e83772f8496d61dc278752188b2356b744e96e50b375507.
This is real Qwen use of the new tools, distinct from earlier scripted integration.

The run stopped later after real test failures, browser-process leakage and EAGAIN
spawn failures. Its smoke test invokes the raw /usr/bin/chromium-headless-shell
instead of the inventory's harness-browser launcher, fixes debugger port 9333,
and kills only its immediate child without waiting for the browser process tree.
Observed surviving Chromium processes in persistent keeper 411e84f0bb39. Docker
stats confirmed PIDs=128 (the configured task/thread cap) and ~126.9 MiB/4 GiB;
this is process/thread exhaustion, not memory exhaustion. Even node --version and
sleep failed with worker BlockingIOError errno 11. Repeated identical node-version
calls eventually hit the failure guard. Persistent executor currently retains
this failed-but-running keeper; recovery classification/recycling needs follow-up.

Independent read-only Docker rerun of the current actual JavaScript unit tests
in a fresh container using the prepared image: 20 passed, zero failures.
Log: environment-requests/verification/current-game-unit.log. Browser assertions
previously failed on timing/state counts, and fixed-port reconnection to surviving
browsers is a likely contamination cause, not yet independently reproduced. No
browser correctness approval is claimed. Feature files remain uncommitted in the
worktree, candidate unpublished. No source files or containers were changed by
this inspection; stopping the keeper and repairing test cleanup remain follow-up.

## 2026-10-29 — Docker task-limit diagnosis and recovery work

User authorized three local harness implementation attempts, followed by direct Codex implementation if those fail. Existing uncommitted source and game work are preserved. Isolated task source/evidence: `/home/ruthvik/.local/share/local-agent-development/process-limit-recovery/`.

Production evidence (`production-exhaustion-evidence.json`): container `411e84f0bb397af641d874eb5c3173667efadef58ac68649eefa92e717836cea`, workspace `ws_b919b8b20c1c4d8cb4188aedd7d41564`, had `pids.current=128`, `pids.max=128`, `pids.events max=428`. Linux tasks include threads; the memory ceiling was not the cause. Diagnostic counters are readable by the host without spawning another process inside the exhausted container. The independent game preview for `ws_1fdd...` is separate and remains unchanged.

Local implementation attempt 1: `run_45b63ae31a9646feb29ee88ea08da8d8`, Ollama `qwen3.8:27b`, isolated workspace `ws_17db9dcd3d764b1d9a7a72438a698543`. Ended `budget_exhausted`, 900-second deadline, 40 model requests, **no implementation diff**. Capability probe `run_7f87b09a57f247dcb7d9be4fbfff9bfa` passed; this is tool-capability evidence, not feature completion.

Local implementation attempt 2: `run_9eb84fe05cfc4594ad807421152189be`, same model/workspace, narrowed follow-up with direct file tools enabled. Ended `budget_exhausted`, 24/24 model turns, **no implementation diff**. Repeated successful inspections of unchanged files. Attempt 3 uses a fresh workspace and a smaller propagation-only task to avoid inheriting that inspection history.


Local implementation attempt 3: `run_07b699a40ae64ed9a03819972689435c`, Ollama `qwen3.8:27b`, fresh workspace `ws_22f1ad5068344ef385f2b0994833a4a2`, 32K context for the reduced propagation-only task. Ended `budget_exhausted`, 24/24 model turns, **no implementation diff**. Probe `run_f3c3a074b5b6402888d7772e8a006b00` passed separately. All three attempts were actual `uv run --locked local-agent run` workflows; task briefs, configs, run outputs, SQLite events and immutable blobs remain under the evidence directory. No local-agent implementation was integrated because none was produced.

Following the user's explicit three-attempt fallback authorization, **Codex authored this process-limit implementation and its tests**:

- Strict `execution.container_pids_limit`, default128/range64–1024; controller normalization, durable dispatch authorization, audit reconstruction, Docker create/attestation, worker cgroup attestation, cleanup and environment inventory use the operator limit. Model tool arguments cannot raise it. The immediately preceding offline policy remains supported for frozen 128-task recovery, without granting its old runs the expanded ceiling.
- Host cgroup counters diagnose a full keeper without another in-container fork; Docker stats provide a remote-daemon full-container fallback. Historical peak/max counters alone do not classify ordinary application failures. Results retain task measurements, explicit `process_limit`, unknown command side effects and correlation IDs. Model feedback and browser diagnostics show the cause and measured task/rejection counts.
- Exhausted owned keepers are removed, preserving the workspace and selected immutable image. No automatic command replay. Published process-limit results are reconciled and their matching keeper retired after controller crashes. Healthy keepers survive ordinary exit1.
- `harness-browser --help` exits immediately. The launcher uses the Chromium binary directly, owns one browser process group, and uses a separate watchdog for cleanup even on launcher SIGKILL. No unrelated background groups are killed. Inventory/docs describe isolated CDP profiles/ports and terminate+await. Recipe version3 refreshes launcher preparations; existing images are not silently rewritten.

Validation (all repository tests and generated browser checks executed inside Docker):

- Full suite: **485 passed, 90 skipped**, `pure-tests-final.log` (optional Docker/live tests skipped in this invocation).
- Selected Docker regression suites: **44 passed**, `docker-regressions.log`, covering persistent execution, three controller crash boundaries (ordinary and exhaustion cases), worker/tool consistency, custom tools, Git workspaces, and controlled task exhaustion.
- Final default/configured task-limit acceptance: **4 passed**, `default-limit-tests.log`, limits64 and128, both mid-command exhaustion and a pre-exhausted keeper. Count file changes exactly once or zero times respectively; next command uses a different container with the same image/files. Audits pass.
- Existing prepared Node/Chromium image with its older worker: **2 passed**, `old-prepared-tests.log`, at default128. No dependency reinstall or worker upgrade needed for recovery at that limit.
- Real Chromium: three repeated help/DOM runs and three isolated CDP runs, including TERM and KILL; task count returned to baseline2 each time (`browser-tests.log`). Pure browser tests additionally verify group cleanup using a parent/child test process tree.
- Configured256 dispatch/inventory/audit, legacy128 policy recovery, schema/worker bounds, counter classification and browser diagnostics are covered in the full suite. Ruff on touched Python modules/tests and `git diff --check` pass.

Sandbox rebuilt through `uv run --locked local-agent build-sandbox` (not handwritten hashes): `sha256:dfa516f7bd756978276c90ca02310ba76e770c3baa7b9132871ed64a24a457c0`, worker `sha256:bbbebca85ed67da2b66796a87219cc6084f08b143a1abcea51d573c9bba6dd6b`; build log retained.

Deployment: verified there were no running/queued browser jobs, gracefully stopped the old server, restarted the same browser-web command on `192.168.1.22:8767` with its existing verifier and allowed roots. Authenticated live check confirms coder profile validity, default128 and the new diagnostic JavaScript (`live-ui-check.log`). Pairing credentials were not printed; the new code remains in the existing private server log. The separate game preview on8768 was not restarted or edited. The old failed workspace container record is REMOVED; workspace files remain.

Limits/gotchas: settings apply to future runs; interrupted runs retain frozen grants. Old prepared workers support128; changing their limit requires a new task from the desired commit and a current-worker environment preparation, with an explicit actionable error on incompatible continuations. Refresh old browser launchers by requesting headless_browser preparation again. Remote controllers lacking host cgroup access can diagnose a full container via daemon stats but cannot reliably capture every short-lived spike. No paid model calls were made for this work. The user's coder model/token settings and default task limit were not changed.

## 2026-10-29 — Paid workspace reviewer discovers and executes tests

- User explicitly authorized direct Codex implementation after overriding the normal local-harness authorship workflow. These changes are Codex-authored; no local-model or paid-model run authored them. Earlier interrupted local attempts (`run_88e44962c92c49d8847dc4a6adf0743f`, `run_d3e4043481cf484d8d0192f7b6f75971`) were not integrated.
- Browser workspace review with `auto` (or blank command) now instructs the selected paid reviewer to inspect code, test directories, README and manifests, discover relevant suites across languages, execute them, and return exact successful test commands. Manual overrides and inherited contracts remain required checks. Automatic environment blockers no longer prevent inspection, but still prevent approval.
- Selected test commands must match actual successful captured tool executions, including complete argv and project-local cwd. The controller independently replays them in a fresh candidate copy; approval requires passing checks, valid audits, inspection evidence and unchanged source copies. Merge re-audits every recorded check run. Existing explicit-command reports remain compatible.
- Browser reports show controller checks, reviewer commands, replay results, commands/directories/output and environment blockers. Updated browser/project-test documentation explains the command-free workflow.
- Exercising the blocker path exposed missing recording-span setup before controller environment preparation; fixed it and added a no-Docker regression. Also repaired the intended environment fallback for imported/legacy source run IDs, previously unreachable because events lookup raised first.
- Validation: `uv run --locked pytest -q tests/test_workspace_review.py tests/test_reviewer_test_discovery.py tests/test_project_tests.py --docker-image sha256:45e771fa041541ce8981886b02666f7c1cd90e206429f20b4c7947b619d9e65b --tb=short` → 60 passed. Covers mixed/JS-only projects, absent automatic plan, fabricated/failed executions, missing dependencies, clean-copy replay failure, source preservation and existing merge/contract boundaries.
- Additional validation: browser widgets, mobile reviewers, review repair and browser loops → 55 passed, 2 skipped; actual HTTP/Responses/Docker loop and Responses transport tests → 9 passed using mocked paid responses. Targeted Ruff and `git diff --check` passed. No paid API inference was dispatched.
- Independently checked the user's actual game candidate `3eb75ddf96b450ff29cf6178be43f1409ccca675` in an offline container with a read-only project mount: 59 Python tests and 20 Node tests passed. This is test execution evidence, not a live paid-model code review or interactive gameplay verification.
- Restarted the idle browser at `http://192.168.1.22:8767`, preserving its launch arguments and credentials in memory, and verified updated review assets over HTTP. Existing chats retained; browser sessions require re-pairing after restart using the private server log. Existing user changes preserved; no game candidate was merged and previews were retained.

## 2026-10-29 — Paid review loop diagnosis and bounded completion

- Investigated the user's real failed paid review `run_23e80b7e686a4e3a87472ba9bf4b7ea7` (`gpt-6.1-sol`, browser job `ee364503ccef7b42bad85611821ff1fb`) without issuing another paid request. Its context began dropping old exchanges after the first few turns; the reviewer repeatedly reread files and reran the Python/Node suites, then reached 100 attempted tools without a final report. Also observed a rejected 16000-byte read and a diff against original commit objects absent from the export.
- Continued direct Codex implementation under the user's explicit authorization for this review feature; no local harness authorship is claimed. Added bounded progress derived from captured execution evidence to fixed review context, retaining read pagination, command results, repeat counts and evidence references across compaction. Output remains explicitly untrusted evidence. Two consecutive rounds of repeated work without new evidence switch to reporting.
- Reserved the final model turn and two tool slots for completion; the report turn retains the same API transport/reasoning/history but offers no tools. Oversized model batches are visibly skipped when they reach the completion reserve, preserving tool results, audit invariants and capacity to capture the final diff. Existing tool/model limits are unchanged. Incomplete evidence continues to prevent approval.
- Clarified read limits/pagination and that original Git commit objects are absent. Review initialization now records the separate controller-check report in its event stream. Historical job diagnostics also recover saved controller-test evidence, include all independent replay runs, and display reserved/skipped tools correctly. The user's saved failed review now reads: "Tool-call limit reached (configured cap: 100). Independent controller checks: passed." Its verdict and immutable trace were not changed.
- Added regressions for memory under context compaction, bounded progress/pagination, repeated-work detection, oversized batches, final-model-turn reporting, successful final diff/audits and truthful historical diagnostics. The focused real Docker completion tests passed in all three modes. Broader non-Docker checks: 59 passed, 2 skipped. Targeted Ruff and `git diff --check` passed. All paid-model responses in new tests are mocked; no additional paid inference/retry was dispatched.
- Testing gotcha: an initial focused budget fixture encountered the existing workspace-monitor output-limit classification while pytest generated cache files. That fixture now validates the candidate value with Python's no-bytecode mode to isolate budget behavior; broader review regressions still run actual pytest and Node suites.
- Final broader Docker gate: `uv run --locked pytest -q tests/test_workspace_review.py tests/test_reviewer_test_discovery.py tests/test_openai_responses.py --docker-image sha256:45e771fa041541ce8981886b02666f7c1cd90e206429f20b4c7947b619d9e65b --tb=short` → 59 passed. Together with the additional non-Docker gate: 118 passed, 2 skipped. Restarted the idle browser on port 8767 with the same launch settings and credentials; HTTP readiness verified. No paid retry performed; the saved failed review remains failed pending an explicit new review.

## 2026-10-29 — Local repair reliability, progress ledger and paid-review gates

- Implemented directly by Codex under the user's explicit authorization to start the work and delegate only bounded pieces if useful. No local model authored the harness implementation. Three actual `qwen3.8:27b` Ollama trials authored changes only in isolated trial repositories; no fourth attempt, paid inference, merge or deployment to the game was performed.
- Added `RepairProgressSettings` to frozen agent configuration (off/observe/enforce, inspection/probe/recovery allowances, bounded recoveries, file/byte measurement bounds). Enforcement is scoped to reviewed local repairs and continuations with unresolved saved findings. Plain coding/chat and paid workspace review keep their existing policy.
- Added `runtime/repair_progress.py`: safe regular-file content measurement excluding caches; controller observations for probes, reads, command-based edits, validation attempts and setup blockers; durable bounded ledger and recovery decisions. New argument variants of equivalent capability probes do not count as new repair milestones. Ordinary diagnostic output, `git log`/`cat` of test paths, and no-op write tools do not earn test/edit credit. New actual file content, concrete validation attempts and diagnosed setup results are recorded without claiming semantic correctness.
- Integrated recovery at model boundaries and within tool batches in BrowserAgent. `repair.progress` events retain authoritative snapshots, with bounded untrusted evidence in fixed context and a scratch ledger for inspection. Resume restores counters from recorded state; changing scratch JSON cannot reset them. `local_stalled` is a terminal runtime outcome preserving work; loops stop rather than scheduling paid rescue for this outcome. Observation mode records decisions without enforcement.
- Added automatic paid eligibility checks requiring an audited published candidate and audited passing independent tests. Fingerprints use candidate content and normalized verification evidence, excluding run IDs, no-change commit IDs and output timing. Duplicate states stop as `review_blocked`; materially new independent evidence can support a no-code resolution. Reservations occur only after eligibility/authorization. Explicit manual review remains available. Existing paid token/attempt limits and unknown-usage/no-replay protections retained.
- Added bounded structured review findings with stable IDs, observed/expected behavior, impact and acceptance criteria. Legacy prose adapts without requesting another paid review. Handoff and subsequent reviews retain IDs and acceptance criteria. Browser reports show findings, criteria, repair stages and review-block reasons.
- Reviewer selection now respects a smaller operator-configured output allowance rather than always raising it for reasoning models. Paid reasoning usage is shown as a reported breakdown of output (not double counted); missing details remain explicit. No new dependencies or model defaults were introduced.
- Added `scripts/check_local_repairs.py`, operating documentation `docs/local-repair-reliability.md`, and updated the implementation plan/browser guide. Reusable trials retain their task/config, result, usage, diagnostics, immutable traces and worktrees. Primary artifacts: `~/.local/share/local-agent-development/local-repair-reliability-20261029/Report.md` and `summary.json`.
- Real local trial 1, Python: `run_37781582312c48949c05ee728d3f3f0e`, completed_unverified, 7 model requests, 37,034 input / 740 output tokens. Model added a failing upper-bound regression, fixed clamp, and passed 3 independent tests. Exact diff reviewed; original tests retained.
- Real local trial 2, game: `run_b9ffd49fc36540a8b5d0186311294a43`, completed_unverified, 22 model requests, 394,038 input / 5,007 output tokens. Candidate fixed keyboard target/Enter propagation and independent checks passed (59 Python, 20 existing JS plus 6 new checks). Artifact review found the new tests mostly asserted source text rather than behavior, so this remains unverified.
- Real local trial 3, focused test follow-up: `run_36ec2c9516e94cad9c0b251d2b1cc3eb`, budget_exhausted after 600 seconds. 23 model requests; recorded 409,955 input / 33,789 output tokens with partial usage. Source-string assertions remain. A separate independent partial-artifact check (`run_340ddf9e1de54d2d88ba9c9b5a4d20c4`) passed the configured checks, but does NOT resolve test quality, establish behavioral correctness, or turn the timed-out attempt into completion. Stopped at three local trials. No trial code was integrated into the user's game.
- Deterministic replay of the original failed local run's 61 observed actions records recovery interventions at actions 16/24 and a stop at 32. This is policy replay, not proof of how a live model would react or a measured token-savings experiment. The follow-up exposed misclassification of inspection commands mentioning test files; corrected it and added runner/assertion/ordinary-print boundary regressions.
- Validation: `uv run --locked pytest -q --tb=short` → 540 passed, 107 skipped; `uv run --locked ruff check src tests scripts` → passed; `git diff --check` → passed. Skipped Docker cases are not claimed as executed.
- Docker gates with immutable image `sha256:45e771fa041541ce8981886b02666f7c1cd90e206429f20b4c7947b619d9e65b`: earlier review/loop/recovery gate → 46 passed; final `tests/test_local_repair_runtime.py tests/test_loop_integration.py` → 8 passed, covering recovery/stall/observe, batches, interrupted-controller resume and authorized loops. Structured-findings handoff gate → 1 passed. Paid responses in all acceptance tests were mocked; no live paid model dispatched.
- Testing gotchas: legacy finding adapters initially produced empty acceptance criteria, causing loop handoff validation to reject them; compatibility normalization now provides an explicit generic verification criterion. The new reasoning-accounting test initially called a fixture helper with duplicate keyword fields; fixed the test and reran the complete suite. The resume test must reuse its recorded prepared sandbox metadata, matching the production CLI's reconciliation rule.
- Existing user changes preserved; the original game worktree remained clean. The browser was idle before activation. Runtime evidence and trial outcomes deliberately distinguish passing tests, completion, model claims, and independent semantic verification.
- Activation complete: restarted the idle browser on `http://192.168.1.22:8767` with its existing launch arguments and credentials retained only in memory. Verified all four updated browser assets exactly match source over HTTP. New sessions require re-pairing using the latest private log entry. Final full Ruff and whitespace checks passed.

## 2026-10-31 — High-level functional instruction manual

- Added `docs/functional-manual.md` at the user's request, directly authored by Codex as documentation. No harness/local/paid model run was invoked for this documentation task; implementation and existing user changes were preserved.
- Covers the browser's complete coding/review/repair/merge flow; source/chat/job/workspace/worktree/run/commit/container identities; exactly when new worktrees are created or reused; committed source versus pending agent changes; version-selection evidence; and live previews versus frozen approved commits. Explicitly states that the current UI/reviewer does not globally rank workspaces or provide automatic latest/passing/approved version selectors.
- Includes functional steps for new tasks, continuation, local repairs, paid workspace review with auto tests, bounded loops, failure diagnosis, token/cost interpretation, and separate merging. Distinguishes publication, passing checks, job completion, and exact-commit approval.
- Linked the manual prominently from README, the documentation index, browser guide, worktree guide, TLDR and implementation guide. Corrected outdated documentation claiming every continuation stops its keeper, and clarified automatic repository initialization for coding folders without Git. No runtime behavior changed.
- Validation: checked 87 local documentation links and their referenced heading anchors across the edited guides; all resolved. `git diff --check` passed. No application tests were needed for documentation-only edits.

## 2026-10-31 — Restore candidate review controls in chat replies

- User could not find "Verify this candidate" on the completed repair. Confirmed its saved reply contains candidate `1b863309532c15606a6fb5a69e22ff6ca23ef730`, job/run IDs and coding mode. The widget module was loaded, but `render()` never invoked its `appendRequest` function; module-only tests had missed the missing integration.
- Direct Codex fix under the existing authorization for this review workflow: render per-candidate review controls for completed coding replies, retaining legacy metadata compatibility, and suppress them on failed/interrupted/error replies. Existing primary workspace-review controls remain available. Rendering never starts a paid request.
- Added regression assertions against the actual chat renderer for visible candidate controls, no paid action on render, hiding failed attempts and restoring completed-attempt controls.
- Validation: `uv run --locked pytest -q tests/test_workspace_results_ui.py --tb=short` → 6 passed; `git diff --check` passed. No paid/model calls or game-source changes made.

## 2026-10-31 — Remove duplicate per-candidate review form

- Corrected the preceding diagnosis/fix: `WorkspaceResults.append` already called `WorkspaceReviews.appendRequest` inside the workspace card. Adding a second call in the chat renderer produced duplicate forms for replies with complete workspace metadata. The prior test stubbed the workspace widget, hiding this integration path.
- Kept the chat renderer as the single owner of candidate-request forms, retaining completed/legacy eligibility and failed-attempt suppression; removed the nested workspace-card invocation. Added explicit candidate commit and workspace labels to each form so distinct historical replies are identifiable.
- Integration tests now load the real workspace and review widgets, use realistic result metadata, and require exactly one form. The new test failed before removal and all 6 UI checks passed after the fix. `git diff --check` passed. Direct Codex fix under the existing authorization; no model calls or game edits.

## 2026-10-31 — Verified browser capabilities and classified recovery

- Implemented directly by Codex under the user's explicit authorization to write code and use direct Ollama for bounded modules. Preserved the existing working changes and the game's source/worktree. Three direct localhost Ollama requests to `qwen3-coder:30b` proposed a small classifier (251/412, 556/569 and 223/385 recorded prompt/output tokens). All drafts were rejected after failing routing requirements; none was integrated. There is no `local-agent run` ID for these direct calls and no claim of harness-agent authorship. Briefs, responses and rejected drafts are retained under `/home/ruthvik/.local/share/local-agent-development/capability-recovery-20261031/`. No paid inference was invoked.
- Added a versioned, dependency-free interactive Chromium runner using the debugging pipe. It supports navigation, real clicks/keyboard input, filling, JavaScript assertions, waits, initialization and reload in one isolated profile with one overall deadline. It reuses the launcher watchdog, cleans up browser children, and runs inside the existing offline Docker resource limits. `--help` documents the bounded JSON plan schema. Staging atomically replaces the helper without following model-created symlinks/hard links; resume restores the run's recorded helper source.
- Environment inventory now distinguishes discovered DOM-dump tooling from verified interaction support. A real input/click/reload/localStorage self-test establishes readiness; successful probes are cached by immutable image, helper hash and execution settings. Failed probes do not become permanent negative facts. Added `browser_interaction` preparation, requiring the self-test before selecting fresh or cached images. Coding/browser prompts, repair ledgers and paid-review preflight expose this capability and a shared command rather than encouraging optional-library discovery.
- Command recovery now distinguishes dependencies, executables, missing paths, assertions, timeouts, output limits, cancellation and actual PID-limit evidence. Stderr cannot authorize arbitrary package installation. Missing-dependency evidence survives context trimming/resume; identical commands with unchanged measured source/image/directory are explicitly skipped, retain original evidence and consume normal budgets. Source/image/argument changes and successful potentially mutating operations allow new attempts. Skipped-call recovery does not replay execution; tests and audit cover the interrupted-controller boundary. Blocked setup is no longer recorded as a successful repair setup milestone.
- Independent checks restage the helper in fresh candidate copies and preserve distinct browser failure categories (`environment_blocked`, `timeout`, `collection_error`, `test_failed`). Added tests for probe caching and cache revalidation, source/image invalidation, real keyboard/persistence behavior, assertions, hung scripts, helper hard-link replacement, audit and resume.
- Docker validation on immutable image `sha256:45e771fa041541ce8981886b02666f7c1cd90e206429f20b4c7947b619d9e65b`: targeted capability/browser/tool-recovery/workspace-review/local-repair suite → 67 passed; additional browser/controller-replay/launcher suite → 16 passed. These suites overlap and are not presented as 83 unique tests. Paid-model responses in integration tests are scripted, not live paid calls.
- Executed a 17-step actual-game browser plan in a disposable read-only copy: Start, deterministic natural game over, native typing of `Ada L`, save, restart, second save, reload and persistence assertions all passed. The plan controls randomness and animation timing before document scripts; it does not replace game source or bypass game event handlers. Artifacts: `game-browser-plan.json`, `game-browser-output.json` and `game-browser-stderr.txt` in the directory above. This confirms these particular flows, not complete gameplay coverage.
- Added `docs/browser-verification.md` and linked it from the functional manual, documentation index, environment preparation and repair reliability guides. Existing unrelated user changes remain uncommitted and preserved.
- Final broad validation: `uv run --locked pytest -q tests/ --tb=short` → 568 passed, 115 skipped. The skipped optional Docker cases are separate from the explicitly executed Docker suites above. Full Ruff and whitespace checks passed; 36 local documentation links resolved. A final diagnostic hardening requires the controller's `process_limit` status, so matching words printed by project code alone cannot claim a container was retired; focused capability/process-limit checks → 34 passed, 5 skipped.
- Activation: verified no active browser jobs or loops, restarted the existing browser with its launch arguments and credentials preserved only in memory, and confirmed HTTP 200 at `http://192.168.1.22:8767` (PID 243836). Pairing rotated and the new code is in the existing private `sidebar-reviewer-task/workspace-review-server.log`; no credential was printed. Restart did not dispatch a coding or paid-review job. Existing local repair state is preserved; a new/continued run loads the new preflight and recovery behavior.

## 2026-11-01 — Place profile editing beside profile selection

- Moved the existing collapsed Agent profile editor directly below Agent profile (config) and its summary, before the model override selector. Direct Codex HTML rearrangement under the user's existing authorization; no model calls or configuration values changed.
- Validation: configuration/UI checks → 11 passed, 1 skipped; whitespace check passed. Restarted the idle browser with its existing arguments and credentials retained only in memory, then verified the served HTML matches source and the editor appears between profile selection and model override. Pairing rotated into the existing private server log.

## 2026-11-01 — Simplify profile editing and task settings

- Direct Codex implementation under the user's explicit request and continuing direct-coding authorization. Added an Edit profile button beside the selected agent profile; it loads that exact file into a hidden-by-default inline editor. Existing files show a filename label, YAML/JSON and Validate/Save/Cancel; naming is shown for Save as new profile and blank profiles. Advanced file management remains available separately, including infrastructure JSON files. Profile summaries now show model/mode concisely.
- Cancel discards the draft without a write; successful saves close the editor. Existing-file saves retain their loaded expected hash; copies use new-file semantics and retain unsaved content. A rejected save preserves the draft and reports the error. Grouped model override/execution mode in Advanced run settings and paid reviewer/scope in Review settings, both initially collapsed. Shortened execution-mode help. No profile contents or model authorization settings changed.
- Extended the executed widget fixture to cover selected-file editing, Cancel, failed-save draft retention, optimistic concurrency, successful close, copy naming and copy content. Configuration/UI tests: 11 passed, 1 optional Docker test skipped. A separate real Chromium check exercised the actual HTML and editor JS with an in-memory API fixture: 19 steps passed, including native clicks/fill, Cancel with zero saves and Save carrying the original hash. This fixture did not write real configuration files or call a model.
- Ruff and whitespace checks passed. Updated docs/browser.md. Restarted the idle browser, preserving launch arguments/credentials only in memory, and verified served HTML (accounting for CSP nonce substitution) and config-controls.js match the source. Active browser PID: 118348. Pairing rotated into the existing private server log; no paid or local inference was invoked for this UI change.


## 2026-11-01 — Provider-aware context and output limits via local Qwen

- Implemented by the user's actual `local-agent run` workflow with native Ollama `qwen3.8:27b`. Codex prepared briefs, diagnosed failed attempts, reviewed source/tests, ran independent checks, and applied the exact agent-authored candidate patch; no handwritten implementation or tests were substituted. Existing `docs/README.md` and `docs/key-concepts.md` changes were preserved. No paid inference/review or game-source changes were made.
- `AgentConfig` now has a 2,097,152-token structural safety ceiling and enforces output reserve below window even on direct construction. Explicit browser Validate/Save checks read-only provider metadata: Ollama architecture context fields and explicit compatible-provider context/output fields. Known violations reject; missing/ambiguous output maxima remain unknown, never certified. Unknown context permits legacy-sized settings with warnings; increased settings require known context metadata. Passive catalog/read/load and audit/replay remain offline. Save preserves its content/hash/checked-metadata response and optimistic edit protections; validation messages show the model, input budget, reserve and unknown limits.
- Live startup, resume and CLI capability preflight apply the shared checks to the effective model using already-fetched metadata, before workspace/probe work. Native request options remain `num_ctx` / `num_predict`. Increased `ModelResponse.text`'s separate character ceiling to 2,097,152 while preserving raw capture/evidence caps. Added offline metadata, bounded streaming, credential-error sanitization, fallback-policy, profile, preflight, resume, wire-format and long-response regressions. Updated `docs/configs.md`, including stale coder table values; shipped YAML settings are unchanged.
- Authorship evidence: initial helper/schema/tests were written in `run_01835ad1c7484b7fb56fb7bb176a6235` (cancelled after review); helper corrections in `run_9f2bb32df6184c9d906a0a6bae841a4f` and `run_996aafd93fea4c059aa6dcfbfffe8e13` (budget-exhausted partial work retained); profile/runtime/correction runs include `run_14b163097d614d72bef0c268ef2063f8`, `run_76f704e723524af3991239ef6e787ef6`, `run_bf3f721888554744a95a91abc3f6b90a`, `run_0fbb54dd59164efe8e496f55401b2524`, `run_8c1aa3e199b64121804e5801e89b1fa5`, and `run_5c90b1446da449a0b3bf247f0167e1b0` (completed_unverified). Formatting and final CLI fixtures were authored in `run_efe22f339de44d46a67814c3e2c11880` (budget_exhausted after controller check failures). These statuses are not verification claims.
- Final publication-only run `run_8b92752f392943378f443201896141a1` captured the retained agent-authored source as candidate `921389c5dac3c5671be816e6088b0edf525a34d5` in `ws_145df695c44c49448a0c11bc7932b0d6`, branch `agent/ws_145df695c44c49448a0c11bc7932b0d6`. Publication audit passed; status remains completed_unverified. Codex independently reviewed and integrated exactly its 15-file diff against source `576c109`, without switching/committing the source branch. Mechanical formatting was additionally reviewed by AST comparison: only the intended final CLI-test fixture corrections changed Python ASTs versus pre-format candidate `97b1186`.
- Independent validation: locked-UV full suite in the agent worktree **636 passed, 115 skipped**; explicit Docker context/Responses suites on pinned sandbox image `sha256:dfa516f7bd756978276c90ca02310ba76e770c3baa7b9132871ed64a24a457c0` **9 passed** (overlaps the full suite, not added as unique tests); focused tests after integration in the main checkout **69 passed**. Repository Ruff lint, formatting checks on all 13 affected Python files, and whitespace checks passed. Real Ollama metadata validation accepted 262144/65536 for the installed coder model, reported a 262144 context maximum and unknown separate output maximum, and rejected a 524288 window. No inference was used for those validations.
- Gotchas: broad Qwen tasks repeatedly inspected files, even after increasing authoring context to a provider-reported 262144; increasing context alone did not fix progress. Smaller preloaded-source tasks with exact hashes and a write/patch tool profile produced reviewable changes. A bare-image formatting attempt lacked Ruff/Pydantic; enabling existing project-test preparation selected the dependency image. The controller's full offline suite then failed `tests/test_mobile_tokens.py::test_official_image_tiles_and_transport_are_not_text_tokens` because tiktoken attempted an uncached network fetch. This failure remains recorded and was not called a passing controller check or fixed by weakening tests. Independent installed-environment full checks passed. Final publication disabled automatic tests only in its temporary authoring config; shipped project-test policy remains enabled.
- Evidence is retained under `/home/ruthvik/.local/share/local-agent-development/provider-token-limits/`: task briefs and author configs, `state/control/agent.db` and blobs, `run-index.json`, `reviewed-agent.patch`, `publication-result.json`, `independent-tests.log`, `docker-checks.log`, and `validation-summary.json`. Frozen run configs are authoritative where temporary author config files changed between attempts.
- Activation: confirmed the browser had no active jobs/loops, preserved its exact launch arguments and credentials only in memory, restarted PID 118348 as **1715817**, and verified HTTP 200 at `http://192.168.1.22:8767`. Authenticated browser Validate accepted 262144/65536 and rejected 524288; served editor JS matches source. No profile was saved and no inference/review job was submitted. Pairing rotated into the existing private `sidebar-reviewer-task/workspace-review-server.log`; no credential was printed. Updated the stale operational `phone/server-process.json` PID record.

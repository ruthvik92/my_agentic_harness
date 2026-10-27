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

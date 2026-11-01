# Git branches and worktrees for coding runs

For the high-level workflow and a table of actions that create or reuse a
worktree, see the [functional instruction manual](functional-manual.md#when-a-new-worktree-is-created).

Select `coder.yaml` and enter the **project directory** in the browser's
source-workspace field. CLI `local-agent run` uses the same behavior. The host
creates a new branch named `agent/<workspace-id>` (for example `agent/ws_…`) and a linked Git worktree
from the current branch's committed `HEAD` by default, or a selected Git revision.
It leaves your checkout on its existing
branch and does not include staged, unstaged or untracked edits in the candidate.
The result records the exact base commit and reports local differences.

For a new coding project without its own `.git`, the harness automatically creates
a `main` branch and initial commit before creating the managed worktree. Empty
projects receive an empty commit; populated projects retain their existing file
bytes as the baseline. `.gitignore` rules and the harness's import exclusions
(such as `.venv` and caches) apply. Hooks, filters and user Git templates are not
executed. Existing repositories and their uncommitted files retain the behavior
described above. An existing repository needs a committed starting revision.

A selected subdirectory without its own `.git` also becomes a separate repository.
Select the enclosing repository root and use **Working subdirectory** when you
want its history instead. Noncoding snapshots are unchanged. Previously created
snapshot workspaces remain snapshots; start a new coding task from a source
project containing their files to obtain a workspace that supports continuation.

## New tasks, continuation, and task directory

In the browser, select `coder.yaml` and enter the repository root as the source:

- **New task** creates a new worktree. Leave **Starting revision** blank for
  the source checkout's current `HEAD`, or enter a commit, tag, or branch.
  The result records the exact resolved commit.
- **Continue task** accepts a previous managed `ws_<id>` and reuses that same
  worktree and agent branch, including uncommitted and untracked files. You can
  also click **Continue this worktree** on a coding result. Keep the source field
  pointed at the original repository root. A new starting revision cannot be
  selected while continuing.
- **Working subdirectory** is relative to the repository root; for the harness
  calculator example use `tests/fixtures/broken_repo`. Blank means the root for
  new tasks, or the previous task directory when continuing; enter `.` to return
  to the root. The model gets the full `project/...` prefix, and commands default
  to that directory unless they explicitly specify another cwd. File tools still
  use workspace-relative paths. The directory must exist without symlink traversal.

The directory is a task focus, not an access restriction or sparse checkout.
The whole committed working tree remains available for dependencies and tests;
Git objects and history are shared with the source repository.

CLI equivalents:

```bash
uv run --locked local-agent run --agent config/coder.yaml \
  --repo /path/to/repository --task-file /tmp/task.md \
  --base-ref HEAD --working-directory tests/fixtures/broken_repo

uv run --locked local-agent run --agent config/coder.yaml \
  --repo /path/to/repository --task-file /tmp/next-task.md \
  --continue-workspace ws_<32-hex-digits>
```

Continuation creates a fresh run ID and keeps each run's baseline and captured
diff separately. If the prior task published a candidate, that commit becomes
the new parent. Otherwise its original base remains the parent. Pending edits
are retained and included in the next candidate and final diff. Prior run
results keep their original commit details. Active tasks, unresolved executions,
unknown workspaces, different source repositories, and externally moved branches
must be resolved before continuing. Old copied workspaces cannot be continued
with this Git workflow.

Container persistence is separate from worktree identity. In persistent mode,
continuation can reuse a compatible healthy keeper, retaining `/tmp` and background
processes while consistent snapshots pause and unpause it. Expiry, incompatible
settings or an unhealthy keeper cause replacement; switching to ephemeral mode
stops the old keeper. Workspace files survive these changes. A new run does not
automatically give the model the full earlier conversation. Use `resume` for
recovery of an interrupted run; **Continue task** starts a new task instead.
See [executor lifecycle](executor.md) for the exact reuse rules.

## What appears in the browser

Each Git-backed coding reply shows an **Agent Git branch** card:

```text
Source folder:     /home/you/projects/my-app
Branch:            agent/ws_<id>
Base branch:       main
Starting commit:   <exact commit at run start>
Candidate commit:  <actual published commit>
Review state:      ready_for_review
Edited project:    <data-root>/sandboxes/ws_<id>/project

[Copy path]  [View changes]  [Continue this worktree]
```

The path still uses the harness's existing workspace layout. Its `project/`
directory is now an actual linked Git worktree, visible through ordinary host
Git commands. `memory/`, `tools/`, `scratch/`, and `outputs/` remain run-local
support directories. Continuation also reuses these directories. Opening a saved
reply retains its captured branch and commit details; its worktree path points
at the current mutable candidate.

**View changes** loads the captured diff through an authenticated job endpoint;
it does not use the model's prose or execute a Git command supplied by the model.
The preview is capped at 1 MiB; larger artifacts remain inspectable in traces.
Paths, branch names and diffs are rendered as literal text. Copy path works over
LAN HTTP as well as secure origins.

Candidate publication does not certify the code or its tests. The model can still
make incorrect completion claims. Review the actual diff, test evidence and
candidate files. A general coding run remains `completed_unverified`.

## Review and merge

Use the paths and branch name shown on your reply:

```bash
git -C /path/to/source-repository worktree list
git -C /path/to/source-repository show agent/ws_<id>
git -C /path/to/source-repository diff BASE_COMMIT CANDIDATE_COMMIT
```

The browser can run an explicit **Review workspace and run checks (paid)** on a
published result. It inspects an exported commit in a separate sandbox and saves
execution evidence and a structured verdict. After approval, a separate
**Merge reviewed commit** action confirms the exact commit and fast-forwards a
clean, unchanged source branch. See [workspace review](browser.md#workspace-review-and-merge).
There is no automatic merge after review.

For manual integration after reviewing and testing, merge in the intended clean checkout. For a source
branch that has not advanced since the run started:

```bash
git -C /path/to/source-repository merge --ff-only agent/ws_<id>
```

If it has advanced, review the combined changes and resolve conflicts through
your normal Git process. No automatic merge, push, source-branch switch, stash,
reset, or deletion of local edits is performed. A separately authorized reviewer
on the host can use the same branch and commit IDs.

Worktrees and branches are retained after runs for inspection; failed runs can
leave unpublished edits in their worktree. The UI distinguishes a missing
candidate commit from one ready for review. Use ordinary `git worktree remove`
and branch cleanup only after you no longer need that worktree. Recorded run
evidence remains in the host control store.

## Execution and Git ownership

Docker still receives one writable bind mount of the run workspace. Model tools
write directly to the host-visible worktree inside it. Shared repository metadata
stays outside the mount. The linked `.git` file is a pointer, not access to its
host target. Host operations verify that pointer, branch identity and branch tip
before dispatch and publication; an unexpected external branch change stops
the operation instead of overwriting it.

Container `run_command` and `git_diff` receive a private `GIT_DIR` under
`tools/.git-shadow`. Their Git history is scratch history for tool compatibility,
not the published host branch. Changing that history cannot hide edits from the
protected final diff. Host branch commits are produced from the captured candidate,
using literal blobs and a private index. Source hooks, signing programs and
clean/smudge filters are not executed by publication or checkout. The source index
and current branch are preserved.

Publication records its intended commit before updating the branch ref. Recovery
can finish that same publication without creating another commit. A branch moved
by a host reviewer is never forcibly reset. Provenance is stored in the run's
configuration, source revision, workspace events, final result, and the private
`control/git-workspaces/` manifests.

## Initial limitations

- An existing repository must have a committed `HEAD` and ordinary tracked files;
  a source directory without a repository is initialized as described above.
  Tracked symlinks, submodules and committed cache/development directories are
  rejected before checkout. This keeps the existing symlink/special-file boundary.
- Git checkout filters are intentionally bypassed. Git LFS objects and submodule
  contents are not fetched or expanded. Dependencies still need to be available
  in the offline environment.
- Changes are based on committed code; local-only configuration or dependencies
  are not silently copied into the worktree.
- Chat, PDF circuit investigations, capability probes and trusted verification
  workspaces keep their current copy-based behavior. Existing saved runs are not
  converted retroactively.

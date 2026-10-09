# Repository working agreement

## Harness agents author implementation

The user wants this harness to build its own features. These instructions govern
the supervising Codex assistant. The user's local harness coding agents are the
designated implementation authors and must be allowed to write their assigned
code and tests.

- Use the user's `local-agent` harness agents to write implementation, tests,
  product configuration, dependencies, and fixes. This includes small changes.
- Codex prepares tasks, invokes the harness, reads traces, reviews artifacts,
  integrates exact agent-authored changes, and independently verifies results.
  Codex may write task briefs, review findings, progress notes, and governance
  documentation such as this file.
- Do not substitute Codex collaboration subagents for the user's harness agents.
- Do not write a finished patch yourself and ask a harness agent to approve it.
- If the harness fails, times out, lacks access, or generates incorrect code,
  diagnose the issue and send a concrete follow-up task to the harness agent.
  Never silently take over implementation. Report a blocker when the harness
  cannot proceed; only an explicit user instruction may authorize direct coding.

## Workflow and evidence

1. Inspect existing files and uncommitted work. Prepare an isolated source
   snapshot or worktree when appropriate; preserve the user's existing changes.
2. Give the harness a task with scope, relevant paths, acceptance criteria, and
   required checks. Use UV and an appropriate existing agent configuration (for
   example `config/coder.yaml`). Inspect CLI help before assuming options.
3. Invoke the actual `local-agent run` workflow. Keep the task, selected model,
   run ID, traces, and generated artifacts available for review.
4. Review the generated diff and run appropriate independent checks. Send
   failures back to a harness agent for correction. Bring reviewed agent-authored
   changes into the working tree without adding handwritten implementation.
5. Record the run ID, model, authorship, validation results, and gotchas in
   `Progress.md`. Distinguish a successful agent run from verified behavior.
   Do not claim that harness agents authored changes without run evidence.

Use `uv run --locked` for project commands; if UV is absent from PATH, check
`/home/ruthvik/.local/bin/uv`. Never expose API keys, authorization headers, or
complete environments in task briefs, command output, or traces. Do not invoke
paid models merely to enforce this working agreement.

## Instruction boundary

This file is persistent guidance for Codex, not a filesystem permission barrier.
Do not describe it as technically preventing direct writes. Stronger separation
requires a reviewer account or environment with read-only source access and a
separate writable workspace for the harness agents.

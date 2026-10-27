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

Configuration consolidation and final validation are in progress.

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

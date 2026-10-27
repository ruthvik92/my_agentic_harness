# Repository layout and local data

| Location | Contents |
|---|---|
| `src/local_agent/` | Application implementation |
| `tests/` | Unit and Docker acceptance tests; fixtures are intentionally separate |
| `config/` | Three active agent YAML profiles and generated `sandbox.json` |
| `examples/` | Optional configurations and a clean circuit-case template |
| `sandbox/` | Trusted Docker build and worker support files |
| `docs/` | Current usage and developer documentation |
| `docs/history/` | Earlier build plans, evidence indexes and full progress log |
| `scripts/` | Developer checks |
| `browser`, `phone`, `traces`, `mcp-harness` | Small command launchers |
| `Progress.md` | Current status, validation and pointers to historical evidence |

`src/local_agent/circuits/` is application code: PDF investigation orchestration,
circuit graph contracts, model instructions, and a conservative passive-netlist
compiler. Investigation PDFs, measurements and generated outputs belong in a
case outside the source checkout. Copy `examples/circuit-case/` to begin one.

## Existing local investigation

The original `circuit-case/` was preserved at
`/home/ruthvik/local-agent-cases/circuit-case`, including the Dragon manual,
measurements, extracted images, reports and netlists. Use that directory as
`--case`; all PDF paths stay relative to the case.

For browser access to both the checkout and external cases:

```bash
./browser --allow-root "$PWD" --allow-root "$HOME/local-agent-cases"
```

MCP uses the same explicit roots:

```bash
./mcp-harness --allow-root "$PWD" --allow-root "$HOME/local-agent-cases"
```

Moving data does not expand the server's allowed roots automatically. Saved runs
keep their captured inputs and frozen configurations; authoritative runtime
state remains in the existing `~/.local/share/local-agent*` data roots.

## Development archives and recovery

The 2026-10-26 cleanup preserved the checkout at:

```text
/home/ruthvik/.local/share/local-agent-development/
  repository-cleanup-20261027T043015Z/
    checkout-before.tar.gz
    backup.json
    git-status-before.txt
    working-tree-before.patch
    relocations.json
    development/
      .browser-build/
      .tool-build/
      .config-cleanup/
      .config-consolidation/
      .executor-review/
      .executor-fixes/
```

The UTC timestamp falls on October 27; the cleanup date in America/Boise is
October 26. `backup.json` records the archive SHA-256, entry count and previous
Git HEAD. The archive includes Git metadata, source, case data, and uncommitted
files. Only the recreatable root virtual environment and test/lint caches were
excluded. Extract into a **new directory** to inspect or restore the old state.

Git commit `97c61a6` separately checkpoints the working implementation before
cleanup. Development archives preserve unsaved changes in the old tracked
`.tool-build` tree as well as untracked drafts. Earlier progress entries retain
their original paths; resolve those paths against `development/` above.

Keep future task snapshots and run-review artifacts outside the repository,
under `~/.local/share/local-agent-development/`. They are excluded from source
imports and protected baselines. `.gitignore` also prevents the old development
folder names and root `circuit-case/` from being committed again. Normal source
and test files must stay visible to Git.

`.git/` is repository history; keep it. `.venv/` is recreatable with
`uv sync --locked`. `.pytest_cache/` and `.ruff_cache/` are disposable caches.
`.gitignore`, `.dockerignore`, and `.python-version` are intentional project files.

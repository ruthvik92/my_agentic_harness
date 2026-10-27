# Browser interface and editable config profiles

User request: browser naming, load every agent config in config/, browser creation
and editing, and a complete config guide. Existing reviewed tool/zoom changes and
uncommitted work are preserved. Implementation and tests are authored by native
local harness agents via MCP; Codex prepares briefs, reviews, integrates exact
outputs and independently verifies.

## Small sequential tasks

1. Config text validation and profile metadata: reuse load_config; agent YAML/JSON
   vs sandbox.json distinction, no secret values or environment expansion.
2. Config catalog/read/save: bounded regular files in config directory, no traversal
   or symlinks, atomic save, create-only/expected hash conflicts, validate first.
3. Config API routes: existing pairing, Host/Origin checks; list/read/validate/save.
4. Browser run request validation: explicit workspace/case path, PDF inputs, known
   config workflow; reuse screenshot/image/history validation and allowed roots.
5. General browser Agent adapter: selected config instructions/tools preserved,
   captured images and history delivered, no false no-tools diagnostic for coding.
6. CLI browser-run dispatch: screenshot, coding and circuit native runtimes with
   immutable per-job config; auditing, capability gates and case exports retained.
7. Jobs dispatch and result metadata: selected profile snapshot, no queued mutation,
   preserve legacy screenshot jobs and recovery.
8. Server profile selection: per-turn config, model choice preserves selected
   provider/tools/instructions, execution fields routed to correct workflow.
9. Browser controls: config selector with tools/workflow, YAML/JSON editor, create,
   validate, save/reload/conflict errors, workspace/PDF inputs; existing chat works.
10. Naming: browser-web/./browser public launch, compatibility phone aliases,
    BrowserServer primary name, visible labels and messages use browser.
11. Agent-authored regression tests: catalog validation/conflicts/path isolation,
    paired APIs, selected immutable jobs, real Docker tool-enabled browser run.
12. Docs: README/browser guide/config guide covers every shipped config and keys,
    editing workflow, snapshots, workspace isolation, trace roots and legacy aliases.
13. Independent lint/full tests/pinned Docker/browser JS checks/native MCP smoke.

## Decisions

- Load every valid agent config in the configured directory, including new ones.
  sandbox.json is runtime infrastructure and is shown separately, never sent as an
  LLM profile. It can be edited with strict JSON structure/fingerprint validation.
- Config writes update host config files because the user explicitly requested
  browser editing. Validate before atomic replacement; stale editors get conflicts.
  Config/model changes apply to subsequent submissions; queued runs keep snapshots.
- Tool-enabled runs require an explicit workspace under allowed roots (default
  harness checkout); browser inputs cannot expand filesystem permissions. Native
  Agent isolates code snapshots, without automatically integrating generated code.
- Phone-v1 remains a compatible screenshot instruction version. Public interface
  naming is browser; config role/instructions determine actual tools, not the UI name.
- Preserve existing saved chats, job directories, cookies and instruction hashes.
  No paid model invocations for testing; remote profiles checked with mocked providers.

Evidence is retained in .browser-build/review and actual MCP data root
~/.local/share/local-agent-mcp. Progress.md records run IDs/models/review/checks.

Additional prerequisite: coding the harness checkout must exclude its internal
.tool-build/.browser-build supervision archives from workspace imports. Keep the
256MiB cap and existing symlink/special-file protections; local author makes the
small exclusion change and a targeted import regression verifies it.

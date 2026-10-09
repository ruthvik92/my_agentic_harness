# Trace browser sources and projects — implementation plan

User requested harness-authored implementation through MCP, arbitrary local trace locations, consolidated MCP build traces, and advice on project names.

## Design

A persistent source catalog federates existing trace ledgers in one browser. Source roots are retained; no ledger migration, run rewriting, or blob copying. A project label is collected when adding a source, with a directory-name default and optional override. Existing run IDs and evidence remain unchanged. Logical grouping can later become per-run metadata when creating a coding run, circuit case, or phone thread; do not retroactively invent event metadata.

## Small local-agent tasks

1. Standalone source catalog: normalize trace locations, validate databases, atomic sidecar persistence, aggregate all runs, isolate unavailable sources.
2. Browser HTTP routing: list/register sources, route events/audit/evidence by source ID, retain loopback and origin protections.
3. Browser controls: location input, project label, source and project filters, source-aware run selection, useful errors.
4. Agent-authored tests and launcher/docs updates. Independent review and checks; corrections returned to harness.
5. Register main, MCP authoring, live acceptance, vision acceptance, and current trace-browser build databases under project labels. Verify real existing runs and evidence through browser endpoints; restart viewer after checks.

## Evidence

Coding tasks are invoked through the installed MCP SDK client and harness_run_code with native Ollama qwen3.8:27b. Implementation is reviewed in isolated source snapshots before exact integration. Authoring traces are stored at ~/.local/share/local-agent-trace-build. Progress.md will record run IDs, checks, and limitations.

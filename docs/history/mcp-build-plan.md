# MCP frontend build plan

Implementation and permanent tests are written by native Ollama agents through
`local-agent run`. Codex prepares tasks, reviews the resulting artifacts, and
runs independent checks. No paid verifier is exposed by this frontend.

Work proceeds through small, sequential acceptance gates:

1. Official MCP SDK stdio handshake and honest capability discovery.
2. Installed Ollama models and their actual reported capabilities.
3. Subprocess execution with secret filtering, cancellation and timeout cleanup.
4. Trusted local profile selection, then the existing coding CLI wrapper.
5. Connect one coding tool; test a real MCP → harness → Ollama → Docker run.
6. Read persisted runs, paginated trace events, and run-owned artifacts.
7. Add screenshot and PDF entry points separately, using existing harness flows.
8. Agent-authored regression tests, launcher, dependency declaration and setup docs.
9. Independent regression checks and client registration.

Each task changes one file or function. Partial source snapshots contain only
relevant files; import dependencies may be absent there, so agent syntax checks
are followed by independent checks against the full checkout. A compile check
prints `COMPILE_OK` to give the agent an explicit stopping signal. Failed checks
return to a harness agent as a focused correction task. Successful model runs
remain `completed_unverified` until their outputs pass review.

Run IDs, selected models, failures and accepted checks are recorded in
[Progress.md](../Progress.md). Temporary build work and traces currently live
under `/tmp/harness-mcp-small` and `/tmp/harness-mcp-build/state`; accepted evidence
is recorded in `docs/mcp-build-evidence.json`; durable traces and source workspaces
are preserved at `/home/ruthvik/.local/share/local-agent-mcp-build`. Existing phone chats and phone
server state are outside this build's data root.

All nine gates completed: 140 tests passed with the pinned Docker image,
lint/format checks passed, actual coding and vision calls reached native Ollama,
and the installed launcher passed a real SDK handshake. Codex registration is
enabled; restart the client to discover tools. Claude setup is documented.

For tests, small scope needs a complete runnable environment: supply source and
offline wheels, and allow enough turns for SDK inspection. Keep documentation in
a separate reference-only workspace. Native model completion remains a draft;
review its behavior and artifacts independently.

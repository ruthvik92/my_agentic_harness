# Browser Interface User Guide

The browser interface is the web front end for the local agent. It is the same
product as the phone interface, exposed through a standard browser.

## Starting the server

Start the server with the public command:

```
./browser
```

or, equivalently:

```
uv run --locked local-agent browser-web
```

By default the server reads `config/browser.yaml`, binds to `127.0.0.1`, and
listens on port `8767`. Open `http://127.0.0.1:8767` in a browser.

`./phone` and the phone-web entry point remain aliases for the same server,
using the same default `config/browser.yaml` profile. The screenshot CLI and MCP
screenshot tool use this profile too. The old phone profile now exists only as
a compatibility test fixture. Existing `phone_session` cookies
and data under `~/.local/share/local-agent/phone` keep saved chats compatible
with the browser interface.

There is no OAuth. Pairing uses a code printed in the terminal.

If you need to reach the server from another device on your LAN, bind a
specific LAN IPv4 address rather than `0.0.0.0`, for example:

```
./browser --host 192.168.1.10
```

Note the spaces between flags and values.

If you update the server while an old one is still running, restart the old
server and reload or re-pair in the browser, because the server loads its
static assets once at startup.

## Config selector

The config selector reads the configured config directory — the directory
containing the `--agent` profile, normally `config/`. Every valid YAML, YML,
or JSON agent profile in that directory appears in the selector, including
newly added files. Selecting a profile shows its detail: mode, provider,
model, instructions, and tools.

`sandbox.json` is editable in the config editor, but it is infrastructure
only and never appears in the agent run selector. Invalid files are shown so
you can repair them, but they are not runnable. See the table of every config
in [configs.md](configs.md).

## Model selection

The default model option, "Use config model", preserves all fields of the
chosen profile: tools, provider, instructions, and budgets. You may manually
override the model, but only within the same provider; the model menu
discovers available models, but model discovery never silently overrides the
config model.

If a remote API key is missing, it stays as the server-terminal environment
variable named in the config. Do not put API keys into the editor or the
browser. CONFIG selection or editing does not invoke inference; generating answers or
requesting reviews through a paid remote OpenAI API may incur charges. `openai-local.yaml` uses the
OpenAI protocol against a local Ollama endpoint and is not a paid remote
profile. Editing config never invokes a model.

Only `browser.yaml`, `analog.yaml`, and `coder.yaml` ship in the active config
directory. Optional compatibility examples are under `examples/configs/` and
do not appear in the selector. The external reviewer is disabled by default;
enable it explicitly with:

```bash
./browser --verifier-agent examples/configs/openai-reviewer.yaml
```

An API key alone does not enable reviewer discovery or requests. See
[optional configurations](../examples/configs/README.md).

## Workflow

The `browser-v1` and `phone-v1` chat workflows accept an uploaded screenshot
plus conversation history. The default browser profile has an empty `tools[]`
list, and `browser-v1` can explicitly enable any listed tool helpers.

Coder profiles require an explicit host workspace under the allowed roots
(default launch cwd is the harness checkout). The workspace is copied into an
isolated Docker workspace, and the resulting diff requires review and
integration before it is applied.

Each coding reply shows **Edited workspace**, including the edited project path
on the harness computer and a **Copy path** button. The source folder is shown
for new jobs. These locations remain available when reopening saved chats,
including older replies whose job record still contains the workspace path.
On another device, open the copied path on the harness computer or in its IDE;
it is not a downloadable browser filesystem link.

The source-workspace field grants permission to import that project. Docker gets
a writable mount of the isolated copy, not the original host directory. Review
the candidate diff and tests before integrating changes. A completed reply does
not mean changes have been applied to your source folder.

Analog (circuit) profiles require a case workspace plus a relative PDF path,
page, and dpi, with an optional context page and normalized region
`[left, top, right, bottom]`. Circuit runs use the PDF workflow; an uploaded
screenshot is not used in circuit runs.

Configure additional trusted roots by repeating `--allow-root` on the server
command; a request cannot change the allowed roots. `--config-dir` optionally
selects another config directory, and the `--agent` path must be inside it.

## Config editor

In the editor, choose a file and press Load or Reload, then edit the raw
YAML or JSON. Validate before Save. You can create a new blank profile or
clone the currently loaded draft to a new valid filename: the stem must be
ASCII alphanumeric plus `_` or `-`, start with an alphanumeric character, be
at most 64 characters, and end in `.yaml`, `.yml`, or `.json`.

Saving an existing file requires the loaded content hash; a concurrent stale
edit returns 409 and your draft is retained — use Reload to refresh. New and
clone operations create the file exclusively. Saves are validated and atomic,
with a maximum of 64 KiB per file and 128 configs. A saved new valid profile
immediately becomes selectable.

Changes affect future submissions; a queued run captures a frozen copy of the
config.

## Saved state

Saved chats, the recent image, and history are retained across profile
changes. Circuit runs ignore the saved image and use the chosen PDF. Paid
review, netlist, and feedback flows are retained. Each answer stores the
actual selected profile, model, tools, mode, and hash — not the current
selector value.

## Traces

Normal browser server data lives under `~/.local/share/local-agent`. The host
writes `control/agent.db`, `control/blobs`, and `control/runs/<runid>/events.jsonl`.
Per-job frozen config, request, and status are stored at
`~/.local/share/local-agent/phone/jobs/<jobid>/`. Docker executes in isolated
`sandboxes/ws_id` workspaces; the selected code source is unchanged until a
reviewed integration.

The trace viewer is available with:

```
uv run --locked local-agent trace-web
```

It provides a Model input instructions/tools button and references the
config, request, and artifacts. Coding results expose the workspace and
`diff_ref`; circuit results expose `exported_case` as unverified artifacts.
Local build author traces use separate roots, documented in `Progress.md`.

See [mcp.md](mcp.md) and [configs.md](configs.md) for related reference.

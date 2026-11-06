# Context, evidence and helpers

The selected profile's estimated input budget is `window_tokens` minus
`output_reserve_tokens`. For example, an 8,192-token window with a 2,048-token
output reserve leaves 6,144 estimated input tokens; these are example values,
not the coding or review defaults. The input estimate covers the complete JSON
payload, including all schemas. Fixed instructions and the task remain present;
selection removes entire assistant/tool exchange groups. Every omitted group is
retained as immutable evidence. `context.compacted` records the deterministic
rule, input hashes, derived index and preserved constraints. This index is working
memory, not authoritative instructions. Provider input counts exceeding the input
budget stop dispatch. The byte-based estimate is conservative, not an exact tokenizer.

Identical successful inspections within an uninterrupted inspection sequence are
coalesced in active context, with the newest complete exchange retained and the
original evidence preserved. Changed results, failed actions, tests, and mutation
boundaries remain distinct. A controller note identifies repeated inspection.
Repair ledgers keep unresolved test commands and failure excerpts until a passing
rerun of the same command and directory. Review-specific progress summaries are
separate. See [review context and paid usage](reviews.md#context-per-request-and-total-paid-usage)
and [the context builder](../src/local_agent/runtime/context.py).

Tool results contain bounded previews and evidence references. To retrieve later
bytes, use `read_file(evidence_ref="blob://...", byte_offset=30000, byte_limit=8192)`.
The resolver grants only stdout/stderr/output blobs and artifacts produced by the
same run. Knowing a blob hash or putting it in a prompt does not grant access.
Protected blobs remain outside the Docker mount. Slice boundaries are bytes;
UTF-8 split boundaries are decoded with replacement.

Helpers remain untrusted files under `tools`. Create a manifest with schema_version
1, name, description, entrypoint `["python", "tools/demo/main.py"]`, version and
requested_capabilities. Execute through `run_command` with that exact argv,
`cwd="tools"` and `helper_manifest="tools/demo/manifest.json"`. The trusted in-image
worker captures and hashes the manifest and single-file Python code, then executes
the captured code using isolated Python. Result evidence identifies both hashes,
the declared version and the immutable execution image. Requests for extra
capabilities grant nothing. Imported sibling packages and arbitrary helper
entrypoints are not supported by this initial manifest interface.

Memory is ordinary untrusted workspace data. A memory file cannot change the tool
allowlist, policy, image or protected task instructions. Shared helper promotion
requires a separate reviewed immutable packaging workflow; no host imports occur.

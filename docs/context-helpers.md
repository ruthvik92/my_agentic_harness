# Context, evidence and helpers

The 8k profile reserves 2k for output. The input estimate covers the complete JSON
payload, including all schemas. Fixed instructions and the task remain present;
selection removes entire assistant/tool exchange groups. Every omitted group is
retained as immutable evidence. `context.compacted` records the deterministic
rule, input hashes, derived index and preserved constraints. This index is working
memory, not authoritative instructions. Provider input counts exceeding the input
budget stop dispatch. The byte-based estimate is conservative, not an exact tokenizer.

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

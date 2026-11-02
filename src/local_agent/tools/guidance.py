"""Host-side tool instructions and corrective feedback; never relax validation."""

GUIDE = """Tool operations run inside offline Docker, rooted at /workspace. Tool paths are
workspace-relative, e.g. project/src/app.py; cwd='project' means /workspace/project.
cwd is a directory argument, not a shell command. Omit cwd to use the task directory.
Tool paths and command argv paths have different bases: scratch/helper.js passed
to write_file is /workspace/scratch/helper.js. To run it with cwd='project', use
argv=['node','/workspace/scratch/helper.js'], not ['node','scratch/helper.js'].
Never use '.', './', absolute host paths, or '..' in path arguments. argv is an
array of executable arguments, not shell text. For environment variables use
['env','PYTHONPATH=src','python','-m','pytest','-q']; do not put 'X=y' in argv[0].
Read named files directly; avoid repeatedly listing or rereading unchanged pages.
read_file returns content_hash and pagination. For the next page use returned
next_line as line_offset (and next_byte_offset as byte_offset when present).
byte_offset is an absolute file byte position and takes precedence over line_offset.
When replacing an existing file, read it first, then write_file with BOTH
create_only=false AND expected_hash equal to its returned content_hash. To create
a new file use create_only=true and omit expected_hash. Prefer a small patch_file:
copy a minimal exact old_text from the decoded read content, provide new_text and expected_hash.
Do not copy JSON serialization backslashes before quotes; preserve actual source whitespace.
Tool versions are selected by the harness. Omit schema_version (or use 1), even
when a tool description names a newer implementation version.
Make one small edit/tool call per response, inspect its result, then proceed.
Do not batch entire file rewrites or many repeated calls. When a call fails,
correct its arguments based on the error; do not repeat the same failed call.
The shared interactive browser runner is staged at tools/harness_browser_test.py.
Run ['python','/workspace/tools/harness_browser_test.py','--help'] for plan usage.
Use environment inventory capabilities.browser_interaction to check verified readiness.
DOM dumps only verify initial page structure. Use the shared runner for clicks, keyboard,
assertions and reload/persistence; it needs no Node ws or browser automation package.
Use prepare_environment capabilities=['browser_interaction'] when interactive control is missing.
Use the provided offline test-plan runner when available. Command output and exit
status return as tool results; a successful edit alone does not prove tests pass.
"""


def correction(name, arguments, error):
    """Actionable hints returned alongside the original validation/execution error."""
    if "process_limit" in error or "Docker process/thread limit reached" in error:
        return (
            "The exhausted container was retired; the next new command gets a fresh container "
            "with the same workspace and selected image. Inspect files for partial effects before "
            "deciding whether to retry. Clean up and await browser children; use harness-browser "
            "with isolated profiles/ports. Only the operator can change execution.container_pids_limit."
        )
    hints = []
    if "schema_version" in error:
        hints.append(
            "Omit schema_version or use 1; tool implementation version is selected by the harness."
        )
    if name in {"run_command", "git_diff"}:
        hints.append(
            "Omit cwd for the task directory, or use cwd='project' (not '.' or './'). argv is a list, not a shell command."
        )
    if name == "write_file":
        hints.append(
            "Existing file: read_file first, then create_only=false AND expected_hash=<returned content_hash>. New file: create_only=true and omit expected_hash. Never guess a hash."
        )
    if name == "patch_file":
        if '\\"' in str(arguments.get("old_text", "")):
            hints.append(
                "Your old_text contains literal backslashes before quotes. Read content is JSON-encoded for transport: match the actual decoded source text, not its serialization escapes."
            )
        hints.append(
            "Read the target page; copy a minimal old_text matching actual content exactly once and use its content_hash as expected_hash. Preserve actual whitespace/quotes. Change the mismatched old_text before retrying; do not repeat an identical failed patch."
        )
    if name == "read_file":
        hints.append(
            "Use a path beginning project/, scratch/, memory/, tools/ or outputs/. Continue with returned next_line/next_byte_offset rather than repeating the first page."
        )
    if not hints:
        hints.append(
            "Use workspace-relative paths beginning project/; correct the rejected arguments before retrying."
        )
    return " ".join(hints)

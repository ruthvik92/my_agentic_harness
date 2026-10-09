from local_agent.contracts import (
    EffectiveLimits,
    GitDiffArgs,
    ListFilesArgs,
    PatchFileArgs,
    ReadFileArgs,
    ReadFileV1Args,
    ReadFileV2Args,
    RunCommandArgs,
    RunCommandV1Args,
    SearchFilesArgs,
    WriteFileArgs,
)
from local_agent.storage.blobs import canonical
from local_agent.tools.extensions import (
    ExecuteToolArgs,
    RegisterToolArgs,
    RenderPdfRegionArgs,
    ViewImageArgs,
)

SCHEMAS = {
    "read_file": ReadFileArgs,
    "run_command": RunCommandArgs,
    "write_file": WriteFileArgs,
    "patch_file": PatchFileArgs,
    "list_files": ListFilesArgs,
    "search_files": SearchFilesArgs,
    "git_diff": GitDiffArgs,
    "register_tool": RegisterToolArgs,
    "execute_tool": ExecuteToolArgs,
    "view_image": ViewImageArgs,
    "render_pdf_region": RenderPdfRegionArgs,
}


def _description(name: str) -> str:
    if name == "register_tool":
        return (
            "Register a Python helper created under tools/ in the run-local "
            "registry, recording its metadata and JSON-schema parameters."
        )
    if name == "execute_tool":
        return (
            "Execute a previously registered tool offline by passing its JSON "
            "arguments on stdin to the sandbox worker."
        )
    if name == "view_image":
        return (
            "Deliver a PNG/JPEG image from the sandbox as evidence to the "
            "vision model."
        )
    if name == "render_pdf_region":
        return (
            "Render a normalized crop of a PDF page at the requested DPI and "
            "deliver the image, identified by page and region."
        )
    return f"Version {VERSIONS[name]} {name}; workspace-relative paths."


VERSIONS = {name: 1 for name in SCHEMAS}
VERSIONS["read_file"] = 3
VERSIONS["run_command"] = 2


def definitions() -> tuple[dict, ...]:
    return tuple(
        {
            "type": "function",
            "function": {
                "name": name,
                "description": _description(name),
                "parameters": schema.model_json_schema(),
            },
        }
        for name, schema in SCHEMAS.items()
    )


def normalize(name: str, arguments: dict, *, version=None, legacy_evidence=False) -> dict:
    if len(canonical(arguments)) > 1536 * 1024:
        raise ValueError("tool arguments exceed the serialized size limit")
    if name not in SCHEMAS:
        raise ValueError("unknown tool")
    # JSON-mode accepts JSON arrays for tuple fields while retaining strict scalar types.
    version = VERSIONS[name] if version is None else version
    schema = SCHEMAS[name]
    supported = {VERSIONS[name]}
    if name == "read_file":
        supported = {1, 2, 3}
        if version == 1 and not legacy_evidence:
            schema = ReadFileV1Args
        elif version < 3:
            schema = ReadFileV2Args
    elif name == "run_command":
        supported = {1, 2}
        if version == 1:
            schema = RunCommandV1Args
    if version not in supported:
        raise ValueError("unsupported tool schema version")
    value = schema.model_validate_json(canonical(arguments))
    return {
        "tool": name,
        "arguments": value.model_dump(mode="json"),
        "effective_limits": EffectiveLimits().model_dump(mode="json"),
    }

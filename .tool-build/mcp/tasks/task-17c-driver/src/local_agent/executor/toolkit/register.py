"""Register a tool from workspace source (stdlib only)."""
import json
import re

from .custom_schema import validate_schema
from .registry_records import encode_record
from .registry_storage import write_registration
from .workspace_io import read_bytes

_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_REQUIRED = ("name", "description", "version", "code_path", "parameters")
_MAX_CODE = 131072


def _check_str(value, label, lo, hi):
    if not isinstance(value, str) or not (lo <= len(value) <= hi):
        raise ValueError(f"{label} must be a string of length {lo}..{hi}")


def register_tool(args, root="/workspace"):
    if not isinstance(args, dict):
        raise ValueError("args must be a dict")
    extra = set(args) - set(_REQUIRED) - {"schema_version"}
    if extra:
        raise ValueError(f"unknown keys: {sorted(extra)}")
    if "schema_version" in args:
        if type(args["schema_version"]) is not int or args["schema_version"] != 1:
            raise ValueError("schema_version must be 1")
    for key in _REQUIRED:
        if key not in args:
            raise ValueError(f"missing required key {key!r}")
    name = args["name"]
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise ValueError("name must match ^[a-z][a-z0-9_]{0,63}$")
    _check_str(args["description"], "description", 1, 1000)
    _check_str(args["version"], "version", 1, 64)
    code_path = args["code_path"]
    if not isinstance(code_path, str) or not code_path.startswith("tools/"):
        raise ValueError("code_path must be a string beginning with 'tools/'")
    validate_schema(args["parameters"])
    code = read_bytes(code_path, limit=_MAX_CODE, root=root)
    if b"\x00" in code:
        raise ValueError("source contains NUL bytes")
    try:
        compile(code, code_path, "exec")
    except SyntaxError as exc:
        raise ValueError(f"source has a syntax error: {exc}") from exc
    metadata = {
        "name": name,
        "description": args["description"],
        "version": args["version"],
        "code_path": code_path,
        "parameters": args["parameters"],
    }
    encoded = encode_record(metadata, code)
    write_registration(encoded, root=root)
    return {"registered": metadata, "record": json.loads(encoded)}

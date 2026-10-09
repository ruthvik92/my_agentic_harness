"""Execute a registered tool in an isolated subprocess (stdlib only)."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

from .custom_schema import validate_arguments
from .registry_storage import read_registration

_ALLOWED = {"name", "arguments", "timeout_seconds", "schema_version"}


def _strict_int(value, label, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if not lo <= value <= hi:
        raise ValueError(f"{label} must be in {lo}..{hi}")
    return value


def execute_tool(args, root="/workspace"):
    if not isinstance(args, dict):
        raise ValueError("args must be a dict")
    extra = set(args) - _ALLOWED
    if extra:
        raise ValueError(f"unknown keys: {sorted(extra)}")
    if "name" not in args:
        raise ValueError("missing required key 'name'")
    name = args["name"]
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    arguments = args.get("arguments", {})
    timeout = _strict_int(args.get("timeout_seconds", 60), "timeout_seconds", 1, 300)
    if "schema_version" in args:
        _strict_int(args["schema_version"], "schema_version", 1, 1)
    record = read_registration(name, root=root)
    validate_arguments(record["metadata"]["parameters"], arguments)
    payload = json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(payload) > 65536:
        raise ValueError("arguments payload exceeds 65536 bytes")
    code = record["code"]
    digest = hashlib.sha256(code).hexdigest()
    version = record["metadata"].get("version", "")
    tmp = tempfile.NamedTemporaryFile(dir="/tmp", suffix=".py", delete=False)
    try:
        tmp.write(code)
        tmp.flush()
        os.fchmod(tmp.fileno(), 0o600)
        tmp.close()
        print(json.dumps({"name": name, "version": version, "code_sha256": digest},
                         ensure_ascii=False, allow_nan=False), flush=True)
        proc = subprocess.run([sys.executable, "-I", "-B", tmp.name],
                              cwd=os.path.join(root, "project"),
                              input=payload, timeout=timeout)
        return proc.returncode
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

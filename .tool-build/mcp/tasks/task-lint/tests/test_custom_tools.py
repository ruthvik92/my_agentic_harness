import os
import sys

sys.path.insert(0, "src")

from local_agent.executor.toolkit.register import register_tool
from local_agent.executor.toolkit.registry_storage import read_registration
from local_agent.executor.toolkit.custom_schema import validate_arguments
from local_agent.executor.toolkit.workspace_io import read_bytes

ARGS = {"name": "sample", "description": "sample", "version": "1",
        "code_path": "tools/a.py",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}


def test_register_snapshot_and_duplicate(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    src = b"X = 1\n"
    (tools / "a.py").write_bytes(src)
    register_tool(dict(ARGS), root=str(tmp_path))
    (tools / "a.py").write_bytes(b"X = 2\n")
    assert read_registration("sample", root=str(tmp_path))["code"] == src
    try:
        register_tool(dict(ARGS), root=str(tmp_path))
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate registration did not raise")


def test_validate_arguments_rejects():
    schema = {"type": "object", "properties": {"n": {"type": "number"}},
              "required": ["n"], "additionalProperties": False}
    for bad in ({"n": True}, {"n": float("nan")}, {"n": 1, "x": 2}):
        try:
            validate_arguments(schema, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted {bad!r}")


def test_read_bytes_rejects_symlink_and_traversal(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    real = tmp_path / "real.txt"
    real.write_bytes(b"data")
    os.symlink(str(real), str(tools / "link.txt"))
    for bad in ("tools/link.txt", "tools/../real.txt"):
        try:
            read_bytes(bad, root=str(tmp_path))
        except (ValueError, OSError):
            pass
        else:
            raise AssertionError(f"accepted {bad!r}")

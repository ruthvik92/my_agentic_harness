"""Regressions for executor payload limits and trusted helper cleanup."""

import builtins
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_agent.executor import worker
from local_agent.executor.toolkit.custom_schema import (
    MAX_ARGS_BYTES,
    serialize_arguments,
    validate_arguments,
)
from local_agent.executor.toolkit.execute import execute_tool
from local_agent.executor.toolkit.register import register_tool
from local_agent.tools.registry import normalize

STRING_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}


def boundary_arguments():
    framing = len(serialize_arguments({"text": ""}))
    room = MAX_ARGS_BYTES - framing
    return {"text": "é" * (room // 2) + "a" * (room % 2)}


@pytest.mark.parametrize("arguments", [{"text": "é" * 15000}, boundary_arguments()])
def test_unicode_payload_validation_matches_subprocess_input(tmp_path, monkeypatch, arguments):
    (tmp_path / "tools").mkdir()
    (tmp_path / "project").mkdir()
    (tmp_path / "tools/echo.py").write_text("import sys\nprint(sys.stdin.read())\n")
    register_tool({
        "name": "echo", "description": "Echo JSON", "version": "1",
        "code_path": "tools/echo.py", "parameters": STRING_SCHEMA,
    }, root=str(tmp_path))
    expected = json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode("utf-8")
    assert validate_arguments(STRING_SCHEMA, arguments) is None
    assert serialize_arguments(arguments) == expected
    normalized = normalize("execute_tool", {"name": "echo", "arguments": arguments})
    assert normalized["arguments"]["arguments"] == arguments
    if arguments == boundary_arguments():
        assert len(expected) == MAX_ARGS_BYTES
    invocations = []

    def run(argv, *, cwd, input, timeout):
        invocations.append(input)
        assert Path(argv[-1]).read_bytes().startswith(b"import sys")
        assert cwd == str(tmp_path / "project")
        assert timeout == 60
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("local_agent.executor.toolkit.execute.subprocess.run", run)
    assert execute_tool({"name": "echo", "arguments": arguments}, root=str(tmp_path)) == 0
    assert invocations == [expected]

    oversized = {"text": boundary_arguments()["text"] + "a"}
    assert len(json.dumps(oversized, ensure_ascii=False).encode("utf-8")) == MAX_ARGS_BYTES + 1
    for check in (serialize_arguments, lambda value: validate_arguments(STRING_SCHEMA, value)):
        with pytest.raises(ValueError, match="exceed"):
            check(oversized)
    with pytest.raises(ValueError, match="exceed"):
        execute_tool({"name": "echo", "arguments": oversized}, root=str(tmp_path))
    with pytest.raises(ValueError, match="exceed"):
        normalize("execute_tool", {"name": "echo", "arguments": oversized})
    assert invocations == [expected], "oversized payload must not launch a subprocess"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_shared_serializer_rejects_nonfinite_numbers(value):
    with pytest.raises(ValueError):
        serialize_arguments({"number": value})
    with pytest.raises(ValueError, match="finite"):
        validate_arguments({"properties": {"number": {"type": "number"}}}, {"number": value})


@pytest.mark.parametrize("outcome", [0, 7, "subprocess_error", "header_error", "snapshot_error"])
def test_helper_snapshot_cleanup(tmp_path, monkeypatch, capsys, outcome):
    for name in worker.ALLOWED:
        (tmp_path / name).mkdir()
    monkeypatch.setattr(worker, "ROOT", str(tmp_path))
    code = b"print('captured helper')\n"
    (tmp_path / "tools/helper.py").write_bytes(code)
    (tmp_path / "tools/helper.json").write_text(json.dumps({
        "schema_version": 1, "entrypoint": ["python", "tools/helper.py"], "version": "1",
    }))
    captures = tmp_path / "captures"
    captures.mkdir()
    unrelated = captures / "unrelated.py"
    unrelated.write_text("keep")
    created = []
    temporary_directory = worker.tempfile.TemporaryDirectory

    def temporary(**kwargs):
        assert kwargs["dir"] == "/tmp"
        kwargs["dir"] = captures
        directory = temporary_directory(**kwargs)
        created.append(Path(directory.name))
        return directory

    def run(argv, **kwargs):
        assert argv[:3] == ["python", "-I", "-B"]
        captured = Path(argv[-1])
        assert captured.read_bytes() == code
        assert captured.parent == created[0]
        # Changing workspace source after capture must not change the executed bytes.
        (tmp_path / "tools/helper.py").write_text("raise RuntimeError('changed')\n")
        assert captured.read_bytes() == code
        if outcome == "subprocess_error":
            raise OSError("subprocess failed")
        return SimpleNamespace(returncode=outcome)

    def fail_print(*args, **kwargs):
        raise OSError("header failed")

    def fail_snapshot(path, *args, **kwargs):
        if str(path).endswith("/helper.py"):
            raise OSError("snapshot failed")
        return builtins.open(path, *args, **kwargs)

    monkeypatch.setattr(worker.tempfile, "TemporaryDirectory", temporary)
    monkeypatch.setattr(worker.subprocess, "run", run)
    if outcome == "header_error":
        monkeypatch.setattr(worker, "print", fail_print, raising=False)
    elif outcome == "snapshot_error":
        monkeypatch.setattr(worker, "open", fail_snapshot, raising=False)
    args = {
        "argv": ["python", "tools/helper.py"], "cwd": "tools",
        "helper_manifest": "tools/helper.json",
    }
    if isinstance(outcome, str):
        with pytest.raises(OSError, match="failed"):
            worker.operate("run_command", args)
    else:
        assert worker.operate("run_command", args) == outcome
    assert len(created) == 1
    assert not created[0].exists()
    assert list(captures.iterdir()) == [unrelated]
    assert unrelated.read_text() == "keep"
    if outcome not in {"header_error", "snapshot_error"}:
        header = capsys.readouterr().out.strip().removeprefix("LOCAL_AGENT_HELPER:")
        assert json.loads(header)["code_hash"] == worker.content_hash(code)

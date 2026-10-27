import asyncio
import json


def execute(sandbox, name, args):
    return asyncio.run(sandbox.execute(name, args))


def test_custom_tool_capture_and_strict_validation(sandbox):
    helper = "tools/double.py"
    source = "import json\nimport sys\n\npayload = json.load(sys.stdin)\nprint(int(payload[\"n\"]) * 2)\n"
    assert (
        execute(
            sandbox,
            "write_file",
            {"path": helper, "content": source},
        ).exit_code
        == 0
    )
    read = execute(sandbox, "read_file", {"path": helper})
    assert read.status == "succeeded", read.preview
    original = json.loads(read.preview)
    original_hash = original["content_hash"]

    registered = execute(
        sandbox,
        "register_tool",
        {
            "name": "double",
            "description": "Double an integer",
            "version": "1",
            "code_path": helper,
            "parameters": {
                "type": "object",
                "properties": {"n": {"type": "integer"}},
                "required": ["n"],
                "additionalProperties": False,
            },
        },
    )
    assert registered.status == "succeeded", registered.preview

    result = execute(sandbox, "execute_tool", {"name": "double", "arguments": {"n": 21}})
    assert result.status == "succeeded", result.preview
    stdout = sandbox.store.blobs.read(result.stdout_ref).decode("utf-8")
    lines = [line for line in stdout.splitlines() if line.strip()]
    header = json.loads(lines[0])
    assert header["name"] == "double"
    assert header["version"] == "1"
    assert ("sha256:" + header["code_sha256"]) == original_hash
    assert lines[-1] == "42"

    # Overwriting the helper on disk must not change the captured code.
    assert (
        execute(
            sandbox,
            "write_file",
            {
                "path": helper,
                "content": "print(999)\n",
                "create_only": False,
                "expected_hash": original_hash,
            },
        ).exit_code
        == 0
    )
    result = execute(sandbox, "execute_tool", {"name": "double", "arguments": {"n": 21}})
    assert result.status == "succeeded", result.preview
    stdout = sandbox.store.blobs.read(result.stdout_ref).decode("utf-8")
    assert [line for line in stdout.splitlines() if line.strip()][-1] == "42"

    # Strict integer validation rejects booleans.
    result = execute(sandbox, "execute_tool", {"name": "double", "arguments": {"n": True}})
    assert result.status == "failed", result.preview

    # Duplicate registration is rejected.
    result = execute(
        sandbox,
        "register_tool",
        {
            "name": "double",
            "description": "Double an integer",
            "version": "1",
            "code_path": helper,
            "parameters": {
                "type": "object",
                "properties": {"n": {"type": "integer"}},
                "required": ["n"],
                "additionalProperties": False,
            },
        },
    )
    assert result.status == "failed", result.preview

    # Reserved native tool names cannot be registered.
    result = execute(
        sandbox,
        "register_tool",
        {
            "name": "read_file",
            "description": "Reserved",
            "version": "1",
            "code_path": helper,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    )
    assert result.status == "failed", result.preview

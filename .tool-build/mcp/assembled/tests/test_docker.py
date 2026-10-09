import asyncio
import json

import pytest

from local_agent.executor.docker import docker


def execute(sandbox, name, args):
    return asyncio.run(sandbox.execute(name, args))


def test_actual_settings_and_seven_tools(sandbox):
    assert execute(sandbox, "run_command", {"argv": ["git", "init"]}).exit_code == 0
    assert execute(sandbox, "run_command", {"argv": ["git", "add", "."]}).exit_code == 0
    assert (
        execute(
            sandbox,
            "run_command",
            {
                "argv": [
                    "git",
                    "-c",
                    "user.name=Harness",
                    "-c",
                    "user.email=local-agent@localhost",
                    "commit",
                    "-m",
                    "baseline",
                ]
            },
        ).exit_code
        == 0
    )
    result = execute(sandbox, "read_file", {"path": "project/calculator.py"})
    assert result.status == "succeeded", result.preview
    assert all(sandbox.store.blobs.json(result.attestation_ref)["checks"].values())
    original = json.loads(result.preview)
    assert "return a - b" in original["content"]
    result = execute(
        sandbox,
        "patch_file",
        {
            "path": "project/calculator.py",
            "old_text": "a - b",
            "new_text": "a + b",
            "expected_hash": original["content_hash"],
        },
    )
    assert result.status == "succeeded", result.preview
    assert (
        execute(sandbox, "run_command", {"argv": ["python", "-m", "pytest", "-q"]}).exit_code == 0
    )
    assert (
        execute(sandbox, "write_file", {"path": "memory/note.md", "content": "hello"}).exit_code
        == 0
    )
    assert execute(sandbox, "list_files", {}).exit_code == 0
    assert execute(sandbox, "search_files", {"query": "a + b"}).exit_code == 0
    diff = execute(sandbox, "git_diff", {})
    assert diff.exit_code == 0 and "+    return a + b" in diff.preview


def test_host_protected_state_and_import_shadowing(sandbox):
    sentinel = sandbox.store.root.parent / "host-sentinel"
    sentinel.write_text("host-only")
    for filename in ("json.py", "sitecustomize.py"):
        execute(
            sandbox,
            "write_file",
            {"path": "project/" + filename, "content": "raise RuntimeError('shadowed')"},
        )
    assert execute(sandbox, "read_file", {"path": "project/calculator.py"}).status == "succeeded"
    source = f"import os; assert not os.path.exists('/var/run/docker.sock'); assert not os.path.exists('/workspace/control'); assert not os.path.exists({str(sentinel)!r}); assert os.getuid()!=0; assert not os.path.exists('/dev/nvidia0'); print('protected')"
    assert execute(sandbox, "run_command", {"argv": ["python", "-I", "-c", source]}).exit_code == 0
    source = "import os; os.symlink('/etc/passwd','link')"
    execute(sandbox, "run_command", {"argv": ["python", "-I", "-c", source]})
    assert execute(sandbox, "read_file", {"path": "project/link"}).status == "failed"
    source = "import socket;\ntry: socket.create_connection(('1.1.1.1',443),1)\nexcept OSError: print('offline')\nelse: raise RuntimeError('network escaped')"
    assert execute(sandbox, "run_command", {"argv": ["python", "-I", "-c", source]}).exit_code == 0


def test_timeout_kills_descendants(sandbox):
    code = "import subprocess,time; subprocess.Popen(['python','-c',\"import time,pathlib;time.sleep(3);pathlib.Path('escaped').write_text('bad')\"]); time.sleep(30)"
    result = execute(
        sandbox, "run_command", {"argv": ["python", "-I", "-c", code], "timeout_seconds": 1}
    )
    assert result.status == "timeout"
    result = execute(
        sandbox,
        "run_command",
        {
            "argv": [
                "python",
                "-I",
                "-c",
                "import time,pathlib;time.sleep(4);assert not pathlib.Path('escaped').exists()",
            ]
        },
    )
    assert result.exit_code == 0, result.preview


def test_output_flood_is_terminated(sandbox):
    sandbox.executor.output_cap = 65536
    result = execute(
        sandbox,
        "run_command",
        {
            "argv": [
                "python",
                "-I",
                "-c",
                "import os;\nwhile True: os.write(1,b'x'*65536); os.write(2,b'y'*65536)",
            ]
        },
    )
    assert result.status == "output_limit"
    assert result.captured_bytes <= 65536
    assert result.truncated


def test_unsupported_protection_and_missing_image_fail_closed(sandbox):
    result = execute(sandbox, "read_file", {"path": "project/calculator.py"})
    info = sandbox.store.blobs.json(result.attestation_ref)["inspect"]
    info["HostConfig"]["Memory"] = 0
    with pytest.raises(RuntimeError, match="attestation failed"):
        sandbox.executor.attest(info, sandbox.path)
    with pytest.raises(RuntimeError, match="Docker image failed"):
        asyncio.run(docker("image", "inspect", "sha256:" + "0" * 64))

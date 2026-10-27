"""Exercise mutation evidence and helper cleanup against the trusted image."""

import asyncio
import json

import pytest
from test_circuits import make_pdf
from test_persistent_docker import command, configure

from local_agent.contracts import ExecutionSettings
from local_agent.executor.docker import DockerExecutor
from local_agent.executor.worker import content_hash


@pytest.mark.parametrize("mode", ["ephemeral", "persistent"])
def test_custom_tool_mutations_and_typed_failure_metadata(sandbox, mode):
    async def scenario():
        sandbox.executor = DockerExecutor(
            sandbox.store, sandbox.workspaces, sandbox.executor.image,
            settings=ExecutionSettings(execution_mode_default=mode),
        )
        manager = sandbox.executor.make_manager(
            lambda kind, data: sandbox.store.append(sandbox.run_id, kind, "test", data)
        )
        try:
            source = (
                "import json, sys\nfrom pathlib import Path\n"
                "args = json.load(sys.stdin)\n"
                "Path('custom-output.txt').write_text(args['text'], encoding='utf-8')\n"
                "sys.exit(7 if args['fail'] else 0)\n"
            )
            written = await sandbox.execute("write_file", {
                "path": "tools/mutate.py", "content": source,
            })
            assert written.status == "succeeded" and written.side_effect_status == "applied"
            read = await sandbox.execute("read_file", {"path": "tools/mutate.py"})
            assert read.status == "succeeded" and read.side_effect_status == "none"
            registration = {
                "name": "mutate", "description": "Write text then optionally fail", "version": "1",
                "code_path": "tools/mutate.py",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}, "fail": {"type": "boolean"}},
                    "required": ["text", "fail"], "additionalProperties": False,
                },
            }
            registered = await sandbox.execute("register_tool", registration)
            assert registered.status == "succeeded"
            assert registered.side_effect_status == "applied"
            for fail, text in [(False, "é" * 15000), (True, "partially changed")]:
                result = await sandbox.execute("execute_tool", {
                    "name": "mutate", "arguments": {"text": text, "fail": fail},
                })
                assert result.status == ("failed" if fail else "succeeded"), result.preview
                assert result.exit_code == (7 if fail else 0)
                assert result.side_effect_status == "unknown"
                assert (sandbox.path / "project/custom-output.txt").read_text("utf-8") == text
            duplicate = await sandbox.execute("register_tool", registration)
            assert duplicate.status == "failed" and duplicate.side_effect_status == "unknown"
            conflict = await sandbox.execute("write_file", {
                "path": "tools/mutate.py", "content": "cannot replace existing file",
            })
            assert conflict.status == "failed" and conflict.side_effect_status == "unknown"
        finally:
            await manager.stop(sandbox.workspace_id)

    asyncio.run(scenario())


def test_pdf_render_reports_created_output(sandbox):
    make_pdf(sandbox.path / "project/manual.pdf")

    async def scenario():
        rendered = await sandbox.execute("render_pdf_region", {
            "pdf": "project/manual.pdf", "page": 1, "region": [0, 0, 1, 1], "dpi": 72,
        })
        assert rendered.status == "succeeded", rendered.preview
        assert rendered.side_effect_status == "applied"
        path = json.loads(sandbox.store.blobs.read(rendered.stdout_ref))["path"]
        assert (sandbox.path / path).is_file()
        viewed = await sandbox.execute("view_image", {"path": path})
        assert viewed.status == "succeeded" and viewed.side_effect_status == "none"
        failed = await sandbox.execute("render_pdf_region", {
            "pdf": "project/manual.pdf", "page": 2, "region": [0, 0, 1, 1], "dpi": 72,
        })
        assert failed.status == "failed" and failed.side_effect_status == "unknown"

    asyncio.run(scenario())


def test_persistent_helper_calls_remove_snapshots_and_preserve_evidence(sandbox):
    async def scenario():
        manager = configure(sandbox)
        try:
            initial = await command(sandbox, (
                "from pathlib import Path; Path('/tmp/unrelated.txt').write_text('keep')"
            ))
            source = (
                "import sys\nfrom pathlib import Path\nprint('captured helper')\n"
                "sys.exit(7 if Path('/workspace/project/fail').exists() else 0)\n"
            )
            await sandbox.execute("write_file", {"path": "tools/helper.py", "content": source})
            await sandbox.execute("write_file", {
                "path": "tools/helper.json",
                "content": json.dumps({
                    "schema_version": 1, "entrypoint": ["python", "tools/helper.py"],
                    "version": "1",
                }),
            })
            references = []
            for fail in (False, False, True, True):
                if fail and not (sandbox.path / "project/fail").exists():
                    await sandbox.execute("write_file", {"path": "project/fail", "content": "1"})
                result = await sandbox.execute("run_command", {
                    "argv": ["python", "tools/helper.py"], "cwd": "tools",
                    "helper_manifest": "tools/helper.json",
                })
                assert result.status == ("failed" if fail else "succeeded"), result.preview
                assert result.exit_code == (7 if fail else 0)
                assert result.container_id == initial.container_id
                assert result.helper_ref is not None
                references.append(result.helper_ref)
                checked = await command(sandbox, (
                    "from pathlib import Path; "
                    "assert not list(Path('/tmp').glob('local-agent-helper-*')); "
                    "assert not list(Path('/tmp').glob('helper-*.py')); "
                    "assert Path('/tmp/unrelated.txt').read_text() == 'keep'"
                ))
                assert checked.status == "succeeded", checked.preview
            assert len(set(references)) == 1, "cleanup must retain immutable helper evidence"
            helper = sandbox.store.blobs.json(references[0])
            assert helper["code_hash"] == content_hash(source.encode())
        finally:
            await manager.stop(sandbox.workspace_id)

    asyncio.run(scenario())

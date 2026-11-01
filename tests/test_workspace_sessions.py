"""A continued workspace retains its keeper, processes and files across attempts."""

import asyncio
from pathlib import Path

import pytest

from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.executor.docker import DockerExecutor
from local_agent.mobile.browser_runtime import run_browser
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.storage.database import Store
from local_agent.workspace.git import git
from local_agent.workspace.manager import Workspaces


def test_continue_preserves_keeper_tmp_and_background_process_then_replaces_incompatible(
    tmp_path, request
):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    source = tmp_path / "repo"
    source.mkdir()
    (source / "notes.txt").write_text("initial")
    git("-C", source, "init", "-b", "main")
    git("-C", source, "add", ".")
    git("-C", source, "commit", "-m", "Initial")
    cfg = load_config(Path("config/coder.yaml")).model_copy(update={"project_tests": False})
    cfg = cfg.model_copy(
        update={
            "execution": cfg.execution.model_copy(update={"execution_mode_default": "persistent"})
        }
    )
    store = Store(tmp_path / "data")

    async def execute(code, workspace=None, config=cfg):
        task = {
            "mode": "coding",
            "workspace": str(source),
            "question": "Continue notes",
            "history": [],
        }
        if workspace:
            task["continue_workspace_id"] = workspace
            from local_agent.workspace.git import GitWorktrees

            record = GitWorktrees(Workspaces(store.root)).load(workspace)
            task["task_context"] = {
                "workspace_id": workspace, "original_task": "notes goal", "attempts": [],
                "expected": {key: record.get(key) for key in ("workspace_id", "run_id", "candidate_commit", "repository")},
            }
        provider = ScriptedProvider(
            [
                {
                    "text": "Work",
                    "tool_calls": [
                        {"name": "run_command", "arguments": {"argv": ["python", "-c", code]}}
                    ],
                    "finish_status": "tool_calls",
                },
                {"text": "Done", "tool_calls": [], "finish_status": "stop"},
            ]
        )
        result = await run_browser(
            store, config, task, {**sandbox_config(), "image": image}, provider=provider
        )
        assert result["status"] == "completed_unverified", result
        assert audit(store, result["run_id"])["ok"]
        return result

    async def scenario():
        manager = DockerExecutor(
            store, Workspaces(store.root), image, settings=cfg.execution
        ).make_manager(lambda *_: None)
        try:
            first = await execute(
                "from pathlib import Path; import subprocess; "
                "Path('/tmp/marker').write_text('kept'); "
                "p=subprocess.Popen(['python','-c','import time; time.sleep(120)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                "Path('/tmp/background.pid').write_text(str(p.pid)); Path('notes.txt').write_text('first')"
            )
            ws = first["workspace_id"]
            original = manager.load(ws)["container_id"]
            await manager.docker("rename", original, "local-agent-session-legacy-" + ws)
            second = await execute(
                "from pathlib import Path; import os,json; assert Path('/tmp/marker').read_text()=='kept'; "
                "assert json.loads(Path('/workspace/scratch/task-context.json').read_text())['original_task']=='notes goal'; "
                "os.kill(int(Path('/tmp/background.pid').read_text()),0); Path('notes.txt').write_text('second')",
                ws,
            )
            assert second["workspace_id"] == ws and second["run_id"] != first["run_id"]
            assert manager.load(ws)["container_id"] == original
            assert (await manager.inspect(original))["Name"].lstrip("/") == manager.container_name(
                ws
            )
            changed = cfg.model_copy(
                update={
                    "execution": cfg.execution.model_copy(update={"container_memory_limit": 1024})
                }
            )
            third = await execute(
                "from pathlib import Path; assert not Path('/tmp/marker').exists(); Path('notes.txt').write_text('third')",
                ws,
                changed,
            )
            assert third["workspace_id"] == ws
            assert manager.load(ws)["container_id"] != original
            assert await manager.inspect(original) is None
            assert (source / "notes.txt").read_text() == "initial"
        finally:
            for path in manager.directory.glob("ws_*.json"):
                await manager.stop(path.stem)

    try:
        asyncio.run(scenario())
    finally:
        store.close()

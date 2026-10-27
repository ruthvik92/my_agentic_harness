import asyncio
import json
import time

import pytest

from local_agent.contracts import ExecutionSettings
from local_agent.executor.docker import DockerExecutor
from local_agent.executor.maintenance import ensure_reaper, sweep
from local_agent.observability.audit import audit


def configure(sandbox, **settings):
    sandbox.executor = DockerExecutor(
        sandbox.store, sandbox.workspaces, sandbox.executor.image,
        settings=ExecutionSettings(execution_mode_default="persistent", **settings),
    )
    return sandbox.executor.make_manager(
        lambda kind, data: sandbox.store.append(sandbox.run_id, kind, "test", data)
    )


async def command(sandbox, code, **kwargs):
    return await sandbox.execute("run_command", {
        "argv": ["python", "-c", code], "cwd": "project", **kwargs,
    })


def test_persistent_reuse_failure_metadata_and_workspace_survival(sandbox):
    async def scenario():
        manager = configure(sandbox)
        try:
            first = await command(sandbox, (
                "from pathlib import Path; Path('/tmp/session-state').write_text('kept'); "
                "Path('durable.txt').write_text('workspace')"
            ))
            second = await command(sandbox, (
                "from pathlib import Path; import sys; "
                "print(Path('/tmp/session-state').read_text()); print('stderr',file=sys.stderr)"
            ))
            assert first.container_id == second.container_id
            assert second.status == "succeeded"
            assert sandbox.store.blobs.read(second.stdout_ref) == b"kept\n"
            assert sandbox.store.blobs.read(second.stderr_ref) == b"stderr\n"
            assert second.run_id == sandbox.run_id
            assert second.workspace_id == sandbox.workspace_id
            assert second.tool_call_id and second.execution_mode == "persistent"
            assert second.started_at <= second.completed_at and second.duration_ms >= 0
            assert second.command[0] == "python"
            failed = await command(sandbox, "import sys; sys.exit(7)")
            assert failed.status == "failed" and failed.exit_code == 7
            third = await command(sandbox, "print('still running')")
            assert third.container_id == first.container_id
            await manager.stop(sandbox.workspace_id)
            assert (sandbox.path / "project/durable.txt").read_text() == "workspace"
            restarted = await command(sandbox, "print('new keeper')")
            assert restarted.container_id != first.container_id
            names = {event.event_type for event in sandbox.store.events(sandbox.run_id)}
            assert {"execution.requested", "container.created", "container.started",
                    "container.idle", "container.stopped", "container.removed"} <= names
            assert audit(sandbox.store, sandbox.run_id)["ok"]
        finally:
            await manager.stop(sandbox.workspace_id)
    asyncio.run(scenario())


def test_persistent_timeout_kills_descendants_and_recovers(sandbox):
    async def scenario():
        manager = configure(sandbox)
        try:
            timed = await command(sandbox, (
                "import subprocess,time; subprocess.Popen(['python','-c',"
                "\"import time; from pathlib import Path; time.sleep(2); "
                "Path('escaped.txt').write_text('bad')\"]); time.sleep(30)"
            ), timeout_seconds=1)
            assert timed.status == "timeout"
            assert await manager.inspect(timed.container_id) is None
            await asyncio.sleep(2.1)
            assert not (sandbox.path / "project/escaped.txt").exists()
            after = await command(sandbox, "print('recovered')")
            assert after.status == "succeeded" and after.container_id != timed.container_id
        finally:
            await manager.stop(sandbox.workspace_id)
    asyncio.run(scenario())


def test_persistent_limits_restart_idle_cleanup_and_audit(sandbox):
    async def scenario():
        manager = configure(
            sandbox, container_memory_limit=1024, container_cpu_limit=1,
            persistent_container_idle_timeout=1,
        )
        try:
            first = await command(sandbox, "print('limited')")
            assert first.status == "succeeded"
            settings = sandbox.executor.settings
            sandbox.executor = DockerExecutor(
                sandbox.store, sandbox.workspaces, sandbox.executor.image, settings=settings
            )
            second = await command(sandbox, "print('same keeper after controller restart')")
            assert first.container_id == second.container_id
            record = manager.load(sandbox.workspace_id)
            record["last_used_at"] = "2000-01-01T00:00:00+00:00"
            manager.save(record)
            result = await sweep(sandbox.store.root, sandbox.executor.image, ExecutionSettings())
            assert result["removed"] == [first.container_id]
            assert audit(sandbox.store, result["maintenance_run_id"])["ok"]
        finally:
            await manager.stop(sandbox.workspace_id)
    asyncio.run(scenario())


def test_persistent_environment_is_explicit_and_not_saved(sandbox, monkeypatch):
    async def scenario():
        manager = configure(sandbox)
        execute = sandbox.executor.execute
        secret = "execution-env-sentinel-92831"

        async def with_env(request):
            return await execute(request, environment={"CUSTOM_TEST": secret})

        try:
            monkeypatch.setattr(sandbox.executor, "execute", with_env)
            first = await command(sandbox, "import os; assert os.environ['CUSTOM_TEST']")
            monkeypatch.setattr(sandbox.executor, "execute", execute)
            second = await command(sandbox, "import os; assert 'CUSTOM_TEST' not in os.environ")
            assert first.status == second.status == "succeeded"
            for path in (sandbox.store.control / "attempts").glob("*.container.json"):
                assert secret not in path.read_text()
            assert secret not in manager.path(sandbox.workspace_id).read_text()
            assert secret not in json.dumps([e.model_dump() for e in sandbox.store.events(sandbox.run_id)])
        finally:
            await manager.stop(sandbox.workspace_id)
    asyncio.run(scenario())


def test_automatic_host_reaper_removes_idle_container(sandbox):
    async def scenario():
        manager = configure(sandbox, persistent_container_idle_timeout=1)
        try:
            ensure_reaper(sandbox.store.root, sandbox.executor.image, sandbox.executor.settings)
            result = await command(sandbox, "print('expire automatically')")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if await manager.inspect(result.container_id) is None:
                    break
                await asyncio.sleep(0.2)
            else:
                pytest.fail("detached host reaper did not expire the idle keeper")
            assert (sandbox.path / "project").is_dir()
        finally:
            await manager.stop(sandbox.workspace_id)
    asyncio.run(scenario())


def test_persistent_output_limit_removes_keeper(sandbox):
    async def scenario():
        manager = configure(sandbox)
        sandbox.executor.output_cap = 1024
        try:
            result = await command(sandbox, "import sys; sys.stdout.write('x'*100000)")
            assert result.status == "output_limit"
            assert result.captured_bytes <= 1024
            assert await manager.inspect(result.container_id) is None
        finally:
            await manager.stop(sandbox.workspace_id)
    asyncio.run(scenario())


def test_ephemeral_metadata_and_removal(sandbox):
    async def scenario():
        result = await command(sandbox, "print('ephemeral')")
        assert result.execution_mode == "ephemeral"
        manager = sandbox.executor.make_manager(lambda *_: None)
        assert await manager.inspect(result.container_id) is None
        assert sandbox.store.blobs.read(result.stdout_ref) == b"ephemeral\n"
    asyncio.run(scenario())


def test_persistent_workspaces_share_owner_but_not_containers_or_files(sandbox):
    from conftest import Sandbox

    async def scenario():
        other = Sandbox(
            sandbox.store.root, sandbox.path / "project", sandbox.executor.image
        )
        first_manager, second_manager = configure(sandbox), configure(other)
        try:
            first = await command(sandbox, (
                "from pathlib import Path; Path('/tmp/private').write_text('first'); "
                "Path('private.txt').write_text('first')"
            ))
            second = await command(other, (
                "from pathlib import Path; assert not Path('/tmp/private').exists(); "
                "assert not Path('private.txt').exists()"
            ))
            assert first_manager.owner == second_manager.owner
            assert first.container_id != second.container_id
            assert first.workspace_id != second.workspace_id
            assert second.status == "succeeded"
        finally:
            await first_manager.stop(sandbox.workspace_id)
            await second_manager.stop(other.workspace_id)
            other.store.close()
    asyncio.run(scenario())


def test_idle_polling_is_quiet_and_cleanup_preserves_completed_run(sandbox):
    async def scenario():
        manager = configure(sandbox)
        executed = await command(sandbox, "print('done')")
        run_count = sandbox.store.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        idle = await sweep(sandbox.store.root, sandbox.executor.image, sandbox.executor.settings)
        assert idle["maintenance_run_id"] is None and idle["remaining"] == 1
        assert sandbox.store.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == run_count
        sandbox.store.append(sandbox.run_id, "completion.proposed", "test", {"reason": "test complete"})
        sandbox.store.transition(sandbox.run_id, "completed_unverified")
        before = sandbox.store.events(sandbox.run_id)
        cleaned = await sweep(
            sandbox.store.root, sandbox.executor.image, sandbox.executor.settings,
            workspace_id=sandbox.workspace_id,
        )
        assert sandbox.store.events(sandbox.run_id) == before
        report = audit(sandbox.store, cleaned["maintenance_run_id"])
        assert report["ok"], report["errors"]
        removed_event = next(e for e in sandbox.store.events(cleaned["maintenance_run_id"])
                             if e.event_type == "container.removed")
        assert removed_event.data["execution_id"] == executed.execution_id
        assert removed_event.data["tool_call_id"] == executed.tool_call_id
        assert removed_event.data["origin_run_id"] == sandbox.run_id
        assert removed_event.data["origin_trace_id"]
        assert manager.load(sandbox.workspace_id)["state"] == "REMOVED"
    asyncio.run(scenario())


def test_deleted_workspace_does_not_leave_a_permanent_keeper(sandbox):
    import shutil

    async def scenario():
        manager = configure(sandbox)
        executed = await command(sandbox, "print('workspace will be deleted by host')")
        shutil.rmtree(sandbox.path)
        cleaned = await sweep(sandbox.store.root, sandbox.executor.image, sandbox.executor.settings)
        assert cleaned["removed"] == [executed.container_id]
        assert await manager.inspect(executed.container_id) is None
        assert manager.load(sandbox.workspace_id)["state"] == "REMOVED"
        with pytest.raises(ValueError, match="workspace"):
            async with manager.session(sandbox.workspace_id, sandbox.run_id, "unused", []):
                pytest.fail("missing workspaces cannot execute commands")
    asyncio.run(scenario())

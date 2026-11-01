"""Docker acceptance tests for capability-probe container identity and release."""

import asyncio
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.executor.docker import DockerExecutor, ExecutionSettings
from local_agent.models.capabilities import _probe_config
from local_agent.models.scripted import ScriptedProvider
from local_agent.runtime.agent import Agent

MARKER = "SANDBOX_CAPABILITY_OK"


def _docker_inspect(name):
    proc = subprocess.run(
        ["docker", "inspect", name], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout)[0]


def _force_remove(names):
    for name in names:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def _probe_responses():
    return (
        {
            "text": "Reading the probe file.",
            "tool_calls": [{"name": "read_file", "arguments": {"path": "project/probe.txt"}}],
            "finish_status": "tool_calls",
        },
        {"text": MARKER, "tool_calls": [], "finish_status": "stop"},
    )


def _run_probe(tmp_path, image):
    root = tmp_path / "data"
    source = tmp_path / "probe_source"
    source.mkdir(parents=True)
    (source / "probe.txt").write_text(MARKER + "\n")

    parent = load_config(Path("config/coder.yaml"))
    parent = parent.model_copy(
        update={
            "project_tests": False,
            "window_tokens": 8192,
            "output_reserve_tokens": 2048,
            "execution": parent.execution.model_copy(
                update={"execution_mode_default": "persistent"}
            ),
        }
    )
    probe_config = _probe_config(parent)
    sandbox = {**sandbox_config(), "image": image}
    provider = ScriptedProvider(responses=_probe_responses())

    from local_agent.storage.database import Store

    store = Store(root)
    agent = Agent(store, probe_config, sandbox, provider=provider)
    known = []

    original_release = agent.executor.release

    async def wrapped_release(execution_id):
        mapping = agent.executor.mapping(execution_id)
        if mapping is None:
            return await original_release(execution_id)
        container_id = mapping["container_id"]
        known.append(container_id)
        manager = agent.executor.make_manager(lambda *_: None)
        info = await manager.inspect(container_id)
        assert info is not None
        assert info["Name"].lstrip("/") == f"local-agent-{manager.owner[:12]}-probe-{execution_id}"
        labels = info.get("Config", {}).get("Labels", {})
        assert labels.get("local-agent.role") == "capability-probe"
        assert labels.get("local-agent.mode") == "ephemeral"
        assert labels.get("local-agent.run") == agent.run_id
        assert labels.get("local-agent.workspace") == mapping["workspace_id"]
        assert labels.get("local-agent.execution") == execution_id
        keeper = agent.executor.keeper
        assert keeper is not None
        assert mapping["workspace_id"] not in keeper.records
        return await original_release(execution_id)

    agent.executor.release = wrapped_release

    try:
        result = asyncio.run(agent.run(source, "Probe", probe=True))
        assert result["status"] == "completed_unverified", f"probe result: {result}"
        assert known, "probe container was not observed"
        for container_id in known:
            assert _docker_inspect(container_id) is None
        assert not (store.control / "containers" / f"{agent.workspace_id}.json").exists()
        from local_agent.observability.audit import audit

        audit_result = audit(store, agent.run_id)
        assert audit_result["ok"], f"audit failed: {audit_result}"
    finally:
        store.close()
        _force_remove(known)
    return result, known


def test_probe_release_normal(tmp_path, request):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("Docker acceptance requires --docker-image sha256:...")
    result, known = _run_probe(tmp_path, image)
    assert result["status"] == "completed_unverified"


def test_probe_release_missing_mapping(tmp_path, request):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("Docker acceptance requires --docker-image sha256:...")
    root = tmp_path / "data"
    source = tmp_path / "probe_source"
    source.mkdir(parents=True)
    (source / "probe.txt").write_text(MARKER + "\n")

    from local_agent.storage.database import Store

    store = Store(root)
    parent = load_config(Path("config/coder.yaml"))
    parent = parent.model_copy(
        update={
            "project_tests": False,
            "window_tokens": 8192,
            "output_reserve_tokens": 2048,
            "execution": parent.execution.model_copy(
                update={"execution_mode_default": "persistent"}
            ),
        }
    )
    probe_config = _probe_config(parent)
    sandbox = {**sandbox_config(), "image": image}
    provider = ScriptedProvider(responses=_probe_responses())
    agent = Agent(store, probe_config, sandbox, provider=provider)
    known = []

    original_release = agent.executor.release

    async def wrapped_release(execution_id):
        mapping = agent.executor.mapping(execution_id)
        if mapping is None:
            return await original_release(execution_id)
        container_id = mapping["container_id"]
        known.append(container_id)
        (store.control / "attempts" / f"{execution_id}.container.json").unlink()
        return await original_release(execution_id)

    agent.executor.release = wrapped_release
    try:
        result = asyncio.run(agent.run(source, "Probe", probe=True))
        assert result["status"] == "completed_unverified", f"probe result: {result}"
        assert known
        for container_id in known:
            assert _docker_inspect(container_id) is None
    finally:
        store.close()
        _force_remove(known)


def test_probe_release_legacy_missing_mapping(tmp_path, request):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("Docker acceptance requires --docker-image sha256:...")
    root = tmp_path / "data"
    source = tmp_path / "probe_source"
    source.mkdir(parents=True)
    (source / "probe.txt").write_text(MARKER + "\n")

    from local_agent.storage.database import Store

    store = Store(root)
    parent = load_config(Path("config/coder.yaml"))
    parent = parent.model_copy(
        update={
            "project_tests": False,
            "window_tokens": 8192,
            "output_reserve_tokens": 2048,
            "execution": parent.execution.model_copy(
                update={"execution_mode_default": "persistent"}
            ),
        }
    )
    probe_config = _probe_config(parent)
    sandbox = {**sandbox_config(), "image": image}
    provider = ScriptedProvider(responses=_probe_responses())
    agent = Agent(store, probe_config, sandbox, provider=provider)
    known = []

    original_release = agent.executor.release

    async def wrapped_release(execution_id):
        mapping = agent.executor.mapping(execution_id)
        if mapping is None:
            return await original_release(execution_id)
        container_id = mapping["container_id"]
        known.append(container_id)
        (store.control / "attempts" / f"{execution_id}.container.json").unlink()
        subprocess.run(
            ["docker", "rename", container_id, f"local-agent-{execution_id}"],
            capture_output=True,
            check=True,
        )
        return await original_release(execution_id)

    agent.executor.release = wrapped_release
    try:
        result = asyncio.run(agent.run(source, "Probe", probe=True))
        assert result["status"] == "completed_unverified", f"probe result: {result}"
        assert known
        for container_id in known:
            assert _docker_inspect(container_id) is None
    finally:
        store.close()
        _force_remove(known)


def test_probe_release_legacy_missing_labels(tmp_path, request, monkeypatch):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("Docker acceptance requires --docker-image sha256:...")
    root = tmp_path / "data"
    source = tmp_path / "probe_source"
    source.mkdir(parents=True)
    (source / "probe.txt").write_text(MARKER + "\n")

    from local_agent.storage.database import Store

    store = Store(root)
    parent = load_config(Path("config/coder.yaml"))
    parent = parent.model_copy(
        update={
            "project_tests": False,
            "window_tokens": 8192,
            "output_reserve_tokens": 2048,
            "execution": parent.execution.model_copy(
                update={"execution_mode_default": "persistent"}
            ),
        }
    )
    probe_config = _probe_config(parent)
    sandbox = {**sandbox_config(), "image": image}
    provider = ScriptedProvider(responses=_probe_responses())
    agent = Agent(store, probe_config, sandbox, provider=provider)
    known = []

    original_release = agent.executor.release

    async def wrapped_release(execution_id):
        mapping = agent.executor.mapping(execution_id)
        if mapping is None:
            return await original_release(execution_id)
        container_id = mapping["container_id"]
        known.append(container_id)
        (store.control / "attempts" / f"{execution_id}.container.json").unlink()
        subprocess.run(
            ["docker", "rename", container_id, f"local-agent-{execution_id}"],
            capture_output=True,
            check=True,
        )

        manager = agent.executor.make_manager(lambda *_: None)
        original_class_inspect = type(manager).inspect

        async def scoped_inspect(self, name):
            info = await original_class_inspect(self, name)
            if info is None:
                return None
            copy = deepcopy(info)
            if copy.get("Id") == container_id:
                labels = copy.get("Config", {}).get("Labels", {})
                labels.pop("local-agent.owner", None)
                labels.pop("local-agent.mode", None)
            return copy

        with monkeypatch.context() as mp:
            mp.setattr(type(manager), "inspect", scoped_inspect)
            try:
                return await original_release(execution_id)
            finally:
                mp.undo()

    agent.executor.release = wrapped_release
    try:
        result = asyncio.run(agent.run(source, "Probe", probe=True))
        assert result["status"] == "completed_unverified", f"probe result: {result}"
        assert known
        for container_id in known:
            assert _docker_inspect(container_id) is None
    finally:
        store.close()
        _force_remove(known)


def test_probe_release_foreign_owner(tmp_path, request, monkeypatch):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("Docker acceptance requires --docker-image sha256:...")
    root = tmp_path / "data"
    source = tmp_path / "probe_source"
    source.mkdir(parents=True)
    (source / "probe.txt").write_text(MARKER + "\n")

    from local_agent.storage.database import Store

    store = Store(root)
    parent = load_config(Path("config/coder.yaml"))
    parent = parent.model_copy(
        update={
            "project_tests": False,
            "window_tokens": 8192,
            "output_reserve_tokens": 2048,
            "execution": parent.execution.model_copy(
                update={"execution_mode_default": "persistent"}
            ),
        }
    )
    probe_config = _probe_config(parent)
    sandbox = {**sandbox_config(), "image": image}
    provider = ScriptedProvider(responses=_probe_responses())
    agent = Agent(store, probe_config, sandbox, provider=provider)
    known = []

    original_release = agent.executor.release

    async def wrapped_release(execution_id):
        mapping = agent.executor.mapping(execution_id)
        if mapping is None:
            return await original_release(execution_id)
        container_id = mapping["container_id"]
        known.append(container_id)
        (store.control / "attempts" / f"{execution_id}.container.json").unlink()

        manager = agent.executor.make_manager(lambda *_: None)
        original_class_inspect = type(manager).inspect

        async def scoped_inspect(self, name):
            info = await original_class_inspect(self, name)
            if info is None:
                return None
            copy = deepcopy(info)
            if copy.get("Id") == container_id:
                labels = copy.get("Config", {}).get("Labels", {})
                labels["local-agent.owner"] = "foreignowner0000"
            return copy

        with monkeypatch.context() as mp:
            mp.setattr(type(manager), "inspect", scoped_inspect)
            try:
                with pytest.raises(PermissionError):
                    await original_release(execution_id)
            finally:
                mp.undo()
        assert _docker_inspect(container_id) is not None
        await original_release(execution_id)

    agent.executor.release = wrapped_release
    try:
        result = asyncio.run(agent.run(source, "Probe", probe=True))
        assert result["status"] == "completed_unverified", f"probe result: {result}"
        assert known
    finally:
        store.close()
        _force_remove(known)


def test_probe_release_foreign_mode(tmp_path, request, monkeypatch):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("Docker acceptance requires --docker-image sha256:...")
    root = tmp_path / "data"
    source = tmp_path / "probe_source"
    source.mkdir(parents=True)
    (source / "probe.txt").write_text(MARKER + "\n")

    from local_agent.storage.database import Store

    store = Store(root)
    parent = load_config(Path("config/coder.yaml"))
    parent = parent.model_copy(
        update={
            "project_tests": False,
            "window_tokens": 8192,
            "output_reserve_tokens": 2048,
            "execution": parent.execution.model_copy(
                update={"execution_mode_default": "persistent"}
            ),
        }
    )
    probe_config = _probe_config(parent)
    sandbox = {**sandbox_config(), "image": image}
    provider = ScriptedProvider(responses=_probe_responses())
    agent = Agent(store, probe_config, sandbox, provider=provider)
    known = []

    original_release = agent.executor.release

    async def wrapped_release(execution_id):
        mapping = agent.executor.mapping(execution_id)
        if mapping is None:
            return await original_release(execution_id)
        container_id = mapping["container_id"]
        known.append(container_id)
        (store.control / "attempts" / f"{execution_id}.container.json").unlink()

        manager = agent.executor.make_manager(lambda *_: None)
        original_class_inspect = type(manager).inspect

        async def scoped_inspect(self, name):
            info = await original_class_inspect(self, name)
            if info is None:
                return None
            copy = deepcopy(info)
            if copy.get("Id") == container_id:
                labels = copy.get("Config", {}).get("Labels", {})
                labels["local-agent.mode"] = "persistent"
            return copy

        with monkeypatch.context() as mp:
            mp.setattr(type(manager), "inspect", scoped_inspect)
            try:
                with pytest.raises(PermissionError):
                    await original_release(execution_id)
            finally:
                mp.undo()
        assert _docker_inspect(container_id) is not None
        await original_release(execution_id)

    agent.executor.release = wrapped_release
    try:
        result = asyncio.run(agent.run(source, "Probe", probe=True))
        assert result["status"] == "completed_unverified", f"probe result: {result}"
        assert known
    finally:
        store.close()
        _force_remove(known)


def test_persistent_execution(sandbox):
    executor = DockerExecutor(
        sandbox.store,
        sandbox.workspaces,
        sandbox.executor.image,
        settings=ExecutionSettings(execution_mode_default="persistent"),
    )
    sandbox.executor = executor

    async def scenario():
        manager = executor.make_manager(
            lambda kind, data: sandbox.store.append(sandbox.run_id, kind, "test", data)
        )
        try:
            first = await sandbox.execute("read_file", {"path": "project/calculator.py"})
            second = await sandbox.execute("read_file", {"path": "project/calculator.py"})
            assert first.status == "succeeded"
            assert second.status == "succeeded"
            assert first.container_id == second.container_id
            info = await manager.inspect(first.container_id)
            assert info is not None
            labels = info.get("Config", {}).get("Labels", {})
            assert labels.get("local-agent.role") == "task"
            assert labels.get("local-agent.mode") == "persistent"
            assert info["Name"].lstrip("/") == manager.container_name(sandbox.workspace_id)
        finally:
            await manager.stop(sandbox.workspace_id)

    asyncio.run(scenario())

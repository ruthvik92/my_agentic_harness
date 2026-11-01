"""Docker acceptance tests for probe container lifecycle and cleanup.

These tests require ``--docker-image`` and a running Docker daemon. They use a
scripted provider (no real inference) and inspect real Docker containers to
verify probe naming, labels, and cleanup behavior across lifecycle variants.
"""

import copy
import json
from pathlib import Path

import pytest

from local_agent.config import load_config
from local_agent.contracts import new_id
from local_agent.executor.container_identity import (
    PROBE_ROLE,
    TASK_ROLE,
    container_role,
    ephemeral_container_names,
)
from local_agent.executor.docker import DockerExecutor
from local_agent.storage.database import Store
from local_agent.workspace.manager import Workspaces


def _probe_config(parent):
    """Clone a persistent parent config into an ephemeral probe config."""
    execution = parent.execution.model_copy(update={"execution_mode_default": "ephemeral"})
    return parent.model_copy(
        update={
            "tools": ("read_file",),
            "execution": execution,
        }
    )


def _parent_config():
    cfg = load_config()
    return cfg.model_copy(
        update={
            "window_tokens": 8192,
            "output_reserve_tokens": 2048,
            "project_tests": False,
            "execution": cfg.execution.model_copy(update={"execution_mode_default": "persistent"}),
        }
    )


def _sandbox_config():
    from local_agent.executor.docker import sandbox_config

    return sandbox_config()


def _docker(*args):
    """Run a docker CLI command and return (returncode, stdout, stderr)."""
    import subprocess

    proc = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=30
    )
    return proc.returncode, proc.stdout, proc.stderr


def _inspect(container_id):
    """Return docker inspect JSON for a container, or None if absent."""
    rc, out, _ = _docker("inspect", container_id)
    if rc != 0:
        return None
    return json.loads(out)[0]


def _remove(container_id):
    """Force-remove a container (best-effort)."""
    _docker("rm", "-f", container_id)


class ScriptedProvider:
    """Two-response scripted provider: read_file then SANDBOX_CAPABILITY_OK."""

    def __init__(self, blobs, config):
        self.blobs = blobs
        self.config = config
        self._responses = [
            {"text": "", "tool_calls": [{"name": "read_file", "arguments": {"path": "project/probe.txt"}}], "finish_status": "tool_calls"},
            {"text": "SANDBOX_CAPABILITY_OK", "tool_calls": [], "finish_status": "stop"},
        ]
        self._index = 0

    async def metadata(self, model):
        return {"installed": {"digest": "scripted-digest"}}

    async def complete(self, request):
        resp = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return resp

    async def close(self):
        pass


def _make_store(tmp_path):
    store = Store(tmp_path / "data")
    return store


def _setup_probe_run(store, source_dir, image):
    """Create a workspace and run manifest for a probe run."""
    workspaces = Workspaces(store.root)
    workspace_id, path = workspaces.create(source_dir)
    run_id = new_id("run")
    from local_agent.contracts import RunManifest
    from local_agent.storage.blobs import digest

    config_ref = store.blobs.put_json(
        {"policy": "offline", "policy_hash": "h", "agent": {"execution": {}}}
    )
    store.create_run(
        RunManifest(
            run_id=run_id,
            thread_id=new_id("thread"),
            workspace_id=workspace_id,
            config_ref=config_ref,
            config_hash=digest(store.blobs.read(config_ref)),
            model_identity="scripted-probe",
            sandbox_image_digest=image,
            mode="live",
            package_versions={},
        )
    )
    store.transition(run_id, "running")
    return workspace_id, run_id


@pytest.mark.parametrize(
    "variant",
    ["normal", "missing_mapping", "legacy_missing_mapping", "legacy_missing_labels", "foreign_owner"],
)
async def test_probe_lifecycle_variant(tmp_path, request, variant):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("Docker acceptance requires --docker-image sha256:...")

    from local_agent.runtime.agent import Agent

    store = _make_store(tmp_path)
    parent = _parent_config()
    probe_cfg = _probe_config(parent)
    sandbox_meta = {**_sandbox_config(), "image": image}

    # Create a source folder with probe.txt
    source = tmp_path / "probe_source"
    source.mkdir()
    (source / "probe.txt").write_text("SANDBOX_CAPABILITY_OK\n")

    workspace_id, run_id = _setup_probe_run(store, source, image)

    # Track created container IDs for cleanup
    created_ids = []

    # Intercept executor.release to inspect the container before cleanup
    executor = DockerExecutor(store, Workspaces(store.root), image, settings=probe_cfg.execution)

    original_release = executor.release

    async def intercepting_release(execution_id):
        # Resolve the execution request to identify the tool
        row = store.db.execute(
            "SELECT request_ref FROM execution_attempts WHERE id=?", (execution_id,)
        ).fetchone()
        if row is None:
            await original_release(execution_id)
            return
        req = json.loads(store.blobs.read(row["request_ref"]))
        tool = req.get("tool", "")

        if tool != "read_file":
            # For other trusted calls, immediately call original release
            await original_release(execution_id)
            return

        # For read_file: inspect the container before cleanup
        mapping = executor.mapping(execution_id)
        if mapping:
            container_id = mapping["container_id"]
        else:
            # Derive name from role
            from local_agent.executor.lifecycle import ExecutionManager
            manager = executor.make_manager(lambda *a: None)
            current, legacy = ephemeral_container_names(PROBE_ROLE, manager.owner, execution_id)
            info = await manager.inspect(current)
            if info is None:
                info = await manager.inspect(legacy)
            if info is None:
                await original_release(execution_id)
                return
            container_id = info["Id"]

        created_ids.append(container_id)
        info = _inspect(container_id)
        assert info is not None, f"Container {container_id} not found"

        # Assert name
        expected_name = f"local-agent-{manager.owner[:12]}-probe-{execution_id}"
        actual_name = info.get("Name", "").lstrip("/")
        assert actual_name == expected_name, f"Name mismatch: {actual_name} != {expected_name}"

        # Assert labels
        labels = info["Config"].get("Labels", {})
        assert labels.get("local-agent.role") == "capability-probe"
        assert labels.get("local-agent.mode") == "ephemeral"
        assert labels.get("local-agent.run") == run_id
        assert labels.get("local-agent.workspace") == workspace_id
        assert labels.get("local-agent.execution") == execution_id

        # Now exercise the variant
        if variant == "missing_mapping":
            # Delete ONLY that temp execution .container.json sidecar
            mapping_path = store.control / "attempts" / (execution_id + ".container.json")
            if mapping_path.exists():
                mapping_path.unlink()
        elif variant == "legacy_missing_mapping":
            # Docker rename owned stopped container to legacy name, then delete sidecar
            legacy_name = f"local-agent-{execution_id}"
            _docker("rename", container_id, legacy_name)
            mapping_path = store.control / "attempts" / (execution_id + ".container.json")
            if mapping_path.exists():
                mapping_path.unlink()
        elif variant == "legacy_missing_labels":
            # Temporarily mock inspect to remove owner and mode labels
            from local_agent.executor.lifecycle import ExecutionManager
            original_inspect = ExecutionManager.inspect

            async def mock_inspect(self, cid):
                info = await original_inspect(self, cid)
                if info is None:
                    return None
                info = copy.deepcopy(info)
                labels = info["Config"].get("Labels", {})
                labels.pop("local-agent.owner", None)
                labels.pop("local-agent.mode", None)
                info["Config"]["Labels"] = labels
                return info

            ExecutionManager.inspect = mock_inspect
            try:
                await original_release(execution_id)
            finally:
                ExecutionManager.inspect = original_inspect
            return
        elif variant == "foreign_owner":
            # Delete temp sidecar; mock inspect to return wrong owner
            mapping_path = store.control / "attempts" / (execution_id + ".container.json")
            if mapping_path.exists():
                mapping_path.unlink()
            from local_agent.executor.lifecycle import ExecutionManager
            original_inspect = ExecutionManager.inspect

            async def mock_inspect_wrong_owner(self, cid):
                info = await original_inspect(self, cid)
                if info is None:
                    return None
                info = copy.deepcopy(info)
                labels = info["Config"].get("Labels", {})
                labels["local-agent.owner"] = "wrong-owner"
                info["Config"]["Labels"] = labels
                return info

            ExecutionManager.inspect = mock_inspect_wrong_owner
            try:
                with pytest.raises(PermissionError):
                    await original_release(execution_id)
            finally:
                ExecutionManager.inspect = original_inspect
            # Container should still be present
            assert _inspect(container_id) is not None
            # Cleanup with original release (restore correct owner)
            await original_release(execution_id)
            return

        # For normal, missing_mapping, legacy_missing_mapping: call original release
        await original_release(execution_id)

    executor.release = intercepting_release

    try:
        agent = Agent(store, probe_cfg, sandbox_meta, provider=ScriptedProvider(store.blobs, probe_cfg))
        result = await agent.run(source, "Call read_file once with path project/probe.txt.", probe=True)
        assert result["status"] == "completed_unverified"

        # After Agent.run, assert no persistent workspace manifest
        ws_manifest = store.control / "containers" / (workspace_id + ".json")
        assert not ws_manifest.exists(), "Persistent workspace manifest should not exist for probe"

        # Every created probe container should be removed
        for cid in created_ids:
            assert _inspect(cid) is None, f"Container {cid} should be removed"

    finally:
        # Emergency cleanup: remove any known owned temp IDs
        for cid in created_ids:
            _remove(cid)
        store.close()


async def test_persistent_task_uses_same_container(tmp_path, request):
    """A persistent task should reuse the same container across executions."""
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("Docker acceptance requires --docker-image sha256:...")

    from local_agent.contracts import ExecutionSettings

    store = _make_store(tmp_path)
    workspaces = Workspaces(store.root)

    # Use the existing fixture source (broken_repo contains calculator.py)
    source = Path(__file__).parent / "fixtures" / "broken_repo"
    workspace_id, path = workspaces.create(source)

    settings = ExecutionSettings(execution_mode_default="persistent")
    executor = DockerExecutor(store, workspaces, image, settings=settings)

    from local_agent.contracts import ExecutionRequest
    from local_agent.observability.spans import correlation

    ctx = correlation()

    async def execute_tool(name, arguments):
        # Create a minimal execution request
        run_id = new_id("run")
        from local_agent.contracts import RunManifest
        from local_agent.storage.blobs import digest

        config_ref = store.blobs.put_json({"policy": "offline", "policy_hash": "h"})
        store.create_run(
            RunManifest(
                run_id=run_id,
                thread_id=new_id("thread"),
                workspace_id=workspace_id,
                config_ref=config_ref,
                config_hash=digest(store.blobs.read(config_ref)),
                model_identity="scripted-persistent",
                sandbox_image_digest=image,
                mode="live",
                package_versions={},
            )
        )
        store.transition(run_id, "running")

        execution = ExecutionRequest(
            execution_id=new_id("exec"),
            call_id=new_id("call"),
            workspace_id=workspace_id,
            tool=name,
            tool_version="1",
            arguments=arguments,
            effective_limits={},
            authorization_ref=new_id("auth"),
            normalized_request_hash="h",
            trace_id=ctx["trace_id"],
            parent_span_id=ctx["span_id"],
        )
        result = await executor.execute(execution)
        return result, execution.execution_id

    try:
        result1, exec1 = await execute_tool("read_file", {"path": "project/calculator.py"})
        result2, exec2 = await execute_tool("read_file", {"path": "project/calculator.py"})

        # Both should succeed
        assert result1["status"] == "completed"
        assert result2["status"] == "completed"

        # Inspect the keeper: same container ID for both
        mapping1 = executor.mapping(exec1)
        mapping2 = executor.mapping(exec2)
        assert mapping1 is not None
        assert mapping2 is not None
        assert mapping1["container_id"] == mapping2["container_id"], "Persistent task should reuse same container"

        container_id = mapping1["container_id"]
        info = _inspect(container_id)
        assert info is not None
        labels = info["Config"].get("Labels", {})
        assert labels.get("local-agent.role") == "task"
        assert labels.get("local-agent.mode") == "persistent"

        # Name should match manager.container_name(workspace_id)
        from local_agent.executor.lifecycle import ExecutionManager
        manager = executor.make_manager(lambda *a: None)
        expected_name = manager.container_name(workspace_id)
        actual_name = info.get("Name", "").lstrip("/")
        assert actual_name == expected_name, f"Name mismatch: {actual_name} != {expected_name}"

    finally:
        # Stop the persistent container before store closes
        from local_agent.executor.lifecycle import ExecutionManager
        manager = executor.make_manager(lambda *a: None)
        try:
            await manager.stop(workspace_id)
        except Exception:
            pass
        store.close()


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))

"""Tests for the capability-probe config, container identity, and lifecycle."""

import asyncio
from pathlib import Path

import pytest

from local_agent.contracts import Limits
from local_agent.executor.container_identity import (
    PROBE_ROLE,
    TASK_ROLE,
    container_role,
    ephemeral_container_names,
)
from local_agent.models.capabilities import _probe_config, ensure_capabilities
from local_agent.storage.blobs import BlobStore


def _make_config(tmp_path):
    from local_agent.config import load_config

    return load_config(Path("config/coder.yaml"))


def test_probe_config_parent_persistent_to_ephemeral(tmp_path):
    config = _make_config(tmp_path)
    assert config.execution.execution_mode_default == "persistent"
    probe = _probe_config(config)
    assert probe.execution.execution_mode_default == "ephemeral"
    # All other execution fields preserved.
    assert probe.execution.container_memory_limit == 512
    assert probe.execution.container_cpu_limit == 2
    assert probe.execution.container_pids_limit == 128
    assert probe.execution.max_execution_seconds == 120
    # Parent config unchanged.
    assert config.execution.execution_mode_default == "persistent"
    # Tools restricted to read_file.
    assert probe.tools == ("read_file",)
    # Limits.
    assert probe.limits.max_model_turns == 3
    assert probe.limits.max_attempted_tool_calls == 6
    assert probe.limits.run_timeout_seconds == 300
    assert probe.limits.model_timeout_seconds == 180
    # Parent window/reserve/project_tests preserved.
    assert probe.window_tokens == 8192
    assert probe.output_reserve_tokens == 2048
    assert probe.project_tests is False


def test_container_role_strict_true(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    config_ref = store.put_json({"probe": True})
    manifest_ref = store.put_json({"config_ref": config_ref})
    store.db.execute(
        "INSERT INTO runs (run_id, manifest_ref) VALUES (?, ?)",
        ("run1", manifest_ref),
    )
    assert container_role(store, "run1") == PROBE_ROLE


def test_container_role_false_missing_one_string(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    for i, cfg in enumerate([{"probe": False}, {}, {"probe": 1}, {"probe": "true"}]):
        config_ref = store.put_json(cfg)
        manifest_ref = store.put_json({"config_ref": config_ref})
        store.db.execute(
            "INSERT INTO runs (run_id, manifest_ref) VALUES (?, ?)",
            (f"run{i}", manifest_ref),
        )
        assert container_role(store, f"run{i}") == TASK_ROLE


def test_manifest_probe_flag_cannot_override_config(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    config_ref = store.put_json({"probe": False})
    manifest_ref = store.put_json({"config_ref": config_ref, "probe": True})
    store.db.execute(
        "INSERT INTO runs (run_id, manifest_ref) VALUES (?, ?)",
        ("run1", manifest_ref),
    )
    assert container_role(store, "run1") == TASK_ROLE


def test_ephemeral_container_names_probe(tmp_path):
    current, legacy = ephemeral_container_names(PROBE_ROLE, "ownerfirst12chars", "exec1")
    assert current == "local-agent-ownerfirst12-probe-exec1"
    assert legacy == "local-agent-exec1"


def test_ephemeral_container_names_task(tmp_path):
    current, legacy = ephemeral_container_names(TASK_ROLE, "owner", "exec2")
    assert current == "local-agent-exec2"
    assert legacy == "local-agent-exec2"
    assert current == legacy


def test_ensure_capabilities_first_and_cached(tmp_path, monkeypatch):
    store = BlobStore(tmp_path / "blobs")
    control = tmp_path / "control"
    control.mkdir()
    store.control = control

    config = _make_config(tmp_path)

    # Fake provider.
    class FakeProvider:
        def __init__(self, blobs, cfg):
            self.blobs = blobs
            self.cfg = cfg

        async def metadata(self, model):
            return {
                "installed": {"digest": "testdigest"},
                "show": {
                    "model_info": {
                        "general.architecture": "test",
                        "test.context_length": 262144,
                    }
                },
            }

        async def close(self):
            pass

    # Fake agent.
    calls = {"count": 0}

    class FakeAgent:
        def __init__(self, store, config, sandbox):
            self.store = store
            self.config = config
            self.sandbox = sandbox
            self.captured_config = config

        async def run(self, source, task, probe=False):
            calls["count"] += 1
            marker = (source / "probe.txt").read_text()
            assert "SANDBOX_CAPABILITY_OK" in marker
            return {
                "status": "completed_unverified",
                "run_id": "run-fake-1",
                "answer": "SANDBOX_CAPABILITY_OK",
            }

    # Fake db.execute returning one valid tool row using real blobs.
    req_ref = store.put_json({"provider": config.provider})
    args_ref = store.put_json({"path": "project/probe.txt"})
    call_ref = store.put_json({"name": "read_file", "arguments_ref": args_ref})
    validated_ref = store.put_json({"ok": True})
    row = {
        "record_ref": call_ref,
        "validated_ref": validated_ref,
        "rejected": False,
        "request_ref": req_ref,
    }

    class FakeCursor:
        def fetchall(self):
            return [row]

    class FakeDB:
        def execute(self, *a, **kw):
            return FakeCursor()

    store.db = FakeDB()

    # Patch create_provider and Agent.
    import local_agent.models.capabilities as caps_mod
    import local_agent.runtime.agent as agent_mod

    monkeypatch.setattr(caps_mod, "create_provider", lambda blobs, cfg: FakeProvider(blobs, cfg))
    monkeypatch.setattr(agent_mod, "Agent", FakeAgent)

    def run_ensure():
        return asyncio.run(ensure_capabilities(store, config, {"image": "test"}))

    report1 = run_ensure()
    assert calls["count"] == 1
    assert report1["passed"] is True
    # FakeAgent received ephemeral config.
    assert FakeAgent.captured_config.execution.execution_mode_default == "ephemeral"

    report2 = run_ensure()
    assert calls["count"] == 1
    assert report2 == report1

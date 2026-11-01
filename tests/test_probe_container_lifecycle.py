"""Unit tests for probe container lifecycle helpers and capability caching.

These tests exercise pure helpers (``_probe_config``, ``container_role``,
``ephemeral_container_names``) and the ``ensure_capabilities`` cache-hit path
without any Docker or model inference.
"""

import json
from types import SimpleNamespace

import pytest

from local_agent.config import load_config
from local_agent.contracts import new_id
from local_agent.executor.container_identity import (
    PROBE_ROLE,
    TASK_ROLE,
    container_role,
    ephemeral_container_names,
)
from local_agent.models import capabilities
from local_agent.models.capabilities import _probe_config, ensure_capabilities
from local_agent.storage.blobs import BlobStore


class FakeDB:
    """Minimal DB stand-in returning pre-seeded rows for the probe query."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, query, params=()):
        return self

    def fetchall(self):
        return list(self._rows)


class FakeAgent:
    """Captures Agent construction and run calls; returns a passing probe result."""

    calls = 0

    def __init__(self, store, config, sandbox, **kwargs):
        self.store = store
        self.config = config
        self.sandbox = sandbox

    async def run(self, source, task, probe=True):
        FakeAgent.calls += 1
        return {
            "status": "completed_unverified",
            "run_id": new_id("run"),
            "answer": "SANDBOX_CAPABILITY_OK",
        }


def _parent_config(tmp_path):
    cfg = load_config()
    return cfg.model_copy(
        update={
            "window_tokens": 8192,
            "output_reserve_tokens": 2048,
            "project_tests": False,
            "execution": cfg.execution.model_copy(update={"execution_mode_default": "persistent"}),
        }
    )


def test_probe_config_clones_persistent_to_ephemeral(tmp_path):
    parent = _parent_config(tmp_path)
    parent.execution = parent.execution.model_copy(
        update={
            "memory_limit_bytes": 512,
            "cpu_limit": 2,
            "container_pids_limit": 128,
            "run_timeout_seconds": 120,
        }
    )
    before = parent.model_dump()

    probe = _probe_config(parent)

    assert probe.execution.execution_mode_default == "ephemeral"
    # All other execution fields identical to the parent.
    for field, value in parent.execution.model_dump().items():
        if field == "execution_mode_default":
            continue
        assert probe.execution.model_dump()[field] == value
    # Parent is unchanged.
    assert parent.model_dump() == before
    assert parent.execution.execution_mode_default == "persistent"
    # Tools restricted to read_file only.
    assert probe.tools == ("read_file",)
    # Probe limits.
    assert probe.limits.max_model_turns == 3
    assert probe.limits.max_attempted_tool_calls == 6
    assert probe.limits.run_timeout_seconds == 300


def test_container_role_strict_probe_flag():
    run_id = new_id("run")
    manifest_ref = new_id("blob")
    config_ref = new_id("blob")

    def make_store(probe_value):
        blobs = BlobStore(tmp_path / "blobs")
        blobs.put_json({"probe": probe_value})
        blobs.put_json({"config_ref": config_ref})
        blobs.put_json({"manifest_ref": manifest_ref})
        store = SimpleNamespace(
            run=lambda rid: {"manifest_ref": manifest_ref},
            blobs=blobs,
        )
        return store

    # strict True -> probe
    assert container_role(make_store(True), run_id) == PROBE_ROLE
    # missing / False / 1 / 'true' -> task
    assert container_role(make_store(False), run_id) == TASK_ROLE
    assert container_role(make_store(1), run_id) == TASK_ROLE
    assert container_role(make_store("true"), run_id) == TASK_ROLE


def test_container_role_top_level_manifest_probe_does_not_override():
    """A top-level manifest probe=True must not override a protected config probe=False."""
    run_id = new_id("run")
    manifest_ref = new_id("blob")
    config_ref = new_id("blob")
    blobs = BlobStore(tmp_path / "blobs")
    # config says probe False (protected)
    blobs.put_json({"probe": False})
    # manifest has top-level probe True but points to config
    blobs.put_json({"probe": True, "config_ref": config_ref})
    store = SimpleNamespace(
        run=lambda rid: {"manifest_ref": manifest_ref},
        blobs=blobs,
    )
    assert container_role(store, run_id) == TASK_ROLE


def test_ephemeral_container_names_probe_vs_task():
    owner = new_id("owner")
    execution_id = new_id("exec")

    probe_current, probe_legacy = ephemeral_container_names(PROBE_ROLE, owner, execution_id)
    assert probe_current == f"local-agent-{owner[:12]}-probe-{execution_id}"
    assert probe_legacy == f"local-agent-{execution_id}"

    task_current, task_legacy = ephemeral_container_names(TASK_ROLE, owner, execution_id)
    assert task_current == f"local-agent-{execution_id}"
    assert task_legacy == f"local-agent-{execution_id}"
    # Task pair contains identical legacy (current API pair).
    assert task_current == task_legacy


def test_ensure_capabilities_cache_hit_prevents_second_run(tmp_path, monkeypatch):
    FakeAgent.calls = 0
    blobs = BlobStore(tmp_path / "blobs")
    control = tmp_path / "control"
    control.mkdir()

    # Seed the DB rows the probe query expects.
    request_ref = new_id("blob")
    record_ref = new_id("blob")
    args_ref = new_id("blob")
    blobs.put_json({"provider": "ollama"})
    blobs.put_json({"name": "read_file", "arguments_ref": args_ref})
    blobs.put_json({"path": "project/probe.txt"})
    rows = [
        {
            "record_ref": record_ref,
            "validated_ref": new_id("blob"),
            "rejected": False,
            "request_ref": request_ref,
        }
    ]
    store = SimpleNamespace(control=control, blobs=blobs, db=FakeDB(rows))

    # Seed a passing cached report so the cache-hit path is taken.
    report = {
        "passed": True,
        "run_id": new_id("run"),
        "model": "test",
        "key": "k",
        "checks": ["valid_tool_selection"],
    }
    report_ref = blobs.put_json(report)
    cache_dir = control / "capabilities"
    cache_dir.mkdir()
    # Compute the same key ensure_capabilities would compute.
    from local_agent.storage.blobs import canonical, digest
    from local_agent.tools.registry import definitions

    cfg = _parent_config(tmp_path)
    sandbox = {"image": "sha256:test"}
    key = digest(
        canonical(
            {
                "digest": "installed-digest",
                "version": None,
                "provider": cfg.provider,
                "completion_token_field": cfg.completion_token_field,
                "sandbox": sandbox["image"],
                "schemas": definitions(),
                "instructions": cfg.instructions_hash,
                "window": cfg.window_tokens,
                "reserve": cfg.output_reserve_tokens,
            }
        )
    )[7:]
    (cache_dir / (key + ".json")).write_text(canonical({"report_ref": report_ref}))

    # Stub create_provider to avoid real inference.
    class FakeProvider:
        async def metadata(self, model):
            return {"installed": {"digest": "installed-digest"}}

        async def close(self):
            pass

    monkeypatch.setattr(capabilities, "create_provider", lambda blobs, config: FakeProvider())
    monkeypatch.setattr(capabilities, "Agent", FakeAgent, raising=False)

    # First call: cache hit, no Agent.run.
    first = ensure_capabilities(store, cfg, sandbox)
    assert FakeAgent.calls == 0
    assert first["passed"] is True

    # Second call with same inputs: still no Agent.run, same cached report.
    second = ensure_capabilities(store, cfg, sandbox)
    assert FakeAgent.calls == 0
    assert second == first


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))

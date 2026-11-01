"""Tests for the missing-mapping fallback in runtime.recovery.reconcile.

Covers the new probe/legacy ephemeral container name lookup, ownership
validation, and the guarantee that an unknown outcome is never replayed.
"""

import asyncio
from types import SimpleNamespace

import pytest

from local_agent.contracts import ExecutionRequest, new_id
from local_agent.executor.container_identity import container_role, ephemeral_container_names
from local_agent.runtime import recovery
from local_agent.storage.blobs import BlobStore, digest


def _make_agent(tmp_path, monkeypatch, probe=True, owner="a" * 64):
    """Build a real BlobStore-backed agent with a fake executor/store surface."""
    blobs = BlobStore(tmp_path / "blobs")
    control = tmp_path / "control"
    control.mkdir()

    # Probe chain: config -> manifest -> run row.
    config_ref = blobs.put_json({"probe": probe})
    manifest_ref = blobs.put_json({"config_ref": config_ref})

    execution = ExecutionRequest(
        execution_id=new_id("exec"),
        call_id=new_id("call"),
        workspace_id=new_id("ws"),
        tool="read_file",
        arguments={"path": "project/probe"},
        authorization_ref=new_id("auth"),
        normalized_request_hash=digest(b"test"),
        trace_id="a" * 32,
        parent_span_id="b" * 16,
    )

    # Fake executor: mapping returns None (the missing-mapping fallback path).
    async def inspect(name):
        raise RuntimeError("not found")

    async def release(execution_id):
        raise AssertionError("release must not be called for unknown outcome")

    executor = SimpleNamespace(
        mapping=lambda execution_id: None,
        make_manager=lambda event: SimpleNamespace(owner=owner),
        inspect=inspect,
        release=release,
    )

    events = []

    def event(kind, source, data):
        events.append((kind, source, data))

    reconciled = []

    def reconcile_execution(run_id, execution_id, result, outcome, causes=None):
        reconciled.append(
            SimpleNamespace(
                run_id=run_id,
                execution_id=execution_id,
                result=result,
                outcome=outcome,
                causes=causes,
            )
        )
        return SimpleNamespace(event_id=new_id("evt"))

    store = SimpleNamespace(
        blobs=blobs,
        control=control,
        run=lambda run_id: {"manifest_ref": manifest_ref},
        reconcile_execution=reconcile_execution,
    )

    agent = SimpleNamespace(
        store=store,
        run_id=new_id("run"),
        last=SimpleNamespace(event_id=new_id("evt")),
        executor=executor,
        event=event,
    )

    # Docker must never be touched: no published result, no logs, no kills.
    async def docker(*args, **kwargs):
        raise AssertionError("docker must not be called")

    monkeypatch.setattr(recovery, "docker", docker)

    return agent, execution, reconciled, events


def _info(owner, mode, execution, agent, container_id="c" * 64):
    labels = {
        "local-agent.execution": execution.execution_id,
        "local-agent.workspace": execution.workspace_id,
        "local-agent.run": agent.run_id,
    }
    if owner is not None:
        labels["local-agent.owner"] = owner
    if mode is not None:
        labels["local-agent.mode"] = mode
    return {
        "Id": container_id,
        "Config": {"Labels": labels},
        "State": {"Running": False, "Status": "created", "ExitCode": 0},
    }


def _expected_names(agent, execution):
    role = container_role(agent.store, agent.run_id)
    owner = agent.executor.make_manager(lambda *a: None).owner
    return ephemeral_container_names(role, owner, execution.execution_id)


def _run_reconcile(agent, execution):
    row = {"request_ref": agent.store.blobs.put_json(execution)}
    with pytest.raises(recovery.NeedsReconciliation, match="will not be replayed"):
        asyncio.run(recovery.reconcile(agent, row))


def test_probe_current_name_found(tmp_path, monkeypatch):
    agent, execution, reconciled, events = _make_agent(tmp_path, monkeypatch, probe=True)
    current, legacy = _expected_names(agent, execution)
    assert current != legacy

    inspected = []

    async def inspect(name):
        inspected.append(name)
        if name == current:
            return _info("a" * 64, "ephemeral", execution, agent)
        raise RuntimeError("not found")

    agent.executor.inspect = inspect

    _run_reconcile(agent, execution)

    assert inspected == [current]
    assert len(reconciled) == 1
    assert reconciled[0].outcome == "unknown"
    assert reconciled[0].result is None
    assert reconciled[0].execution_id == execution.execution_id


def test_probe_legacy_name_found(tmp_path, monkeypatch):
    agent, execution, reconciled, events = _make_agent(tmp_path, monkeypatch, probe=True)
    current, legacy = _expected_names(agent, execution)
    assert current != legacy

    inspected = []

    async def inspect(name):
        inspected.append(name)
        if name == legacy:
            return _info("a" * 64, "ephemeral", execution, agent)
        raise RuntimeError("not found")

    agent.executor.inspect = inspect

    _run_reconcile(agent, execution)

    assert inspected == [current, legacy]
    assert len(reconciled) == 1
    assert reconciled[0].outcome == "unknown"
    assert reconciled[0].result is None


def test_probe_absent_both_names(tmp_path, monkeypatch):
    agent, execution, reconciled, events = _make_agent(tmp_path, monkeypatch, probe=True)
    current, legacy = _expected_names(agent, execution)
    assert current != legacy

    inspected = []

    async def inspect(name):
        inspected.append(name)
        raise RuntimeError("not found")

    agent.executor.inspect = inspect

    _run_reconcile(agent, execution)

    assert inspected == [current, legacy]
    assert len(reconciled) == 1
    assert reconciled[0].outcome == "unknown"
    assert reconciled[0].result is None


def test_task_absent_single_inspect(tmp_path, monkeypatch):
    agent, execution, reconciled, events = _make_agent(tmp_path, monkeypatch, probe=False)
    current, legacy = _expected_names(agent, execution)
    assert current == legacy

    inspected = []

    async def inspect(name):
        inspected.append(name)
        raise RuntimeError("not found")

    agent.executor.inspect = inspect

    _run_reconcile(agent, execution)

    # Names coincide, so only one inspect call is made.
    assert inspected == [current]
    assert len(reconciled) == 1
    assert reconciled[0].outcome == "unknown"
    assert reconciled[0].result is None


def test_legacy_info_without_owner_mode_accepted(tmp_path, monkeypatch):
    agent, execution, reconciled, events = _make_agent(tmp_path, monkeypatch, probe=True)
    current, legacy = _expected_names(agent, execution)

    inspected = []

    async def inspect(name):
        inspected.append(name)
        if name == legacy:
            # No owner/mode labels: must remain accepted and reach unknown.
            return _info(None, None, execution, agent)
        raise RuntimeError("not found")

    agent.executor.inspect = inspect

    _run_reconcile(agent, execution)

    assert inspected == [current, legacy]
    assert len(reconciled) == 1
    assert reconciled[0].outcome == "unknown"
    assert reconciled[0].result is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda info, execution, agent: info["Config"]["Labels"].update(
            {"local-agent.owner": "f" * 64}
        ),
        lambda info, execution, agent: info["Config"]["Labels"].update(
            {"local-agent.mode": "persistent"}
        ),
        lambda info, execution, agent: info["Config"]["Labels"].update(
            {"local-agent.execution": new_id("exec")}
        ),
        lambda info, execution, agent: info["Config"]["Labels"].update(
            {"local-agent.workspace": new_id("ws")}
        ),
        lambda info, execution, agent: info["Config"]["Labels"].update(
            {"local-agent.run": new_id("run")}
        ),
    ],
    ids=["foreign-owner", "foreign-mode", "wrong-execution", "wrong-workspace", "wrong-run"],
)
def test_foreign_identity_no_fallback(tmp_path, monkeypatch, mutate):
    agent, execution, reconciled, events = _make_agent(tmp_path, monkeypatch, probe=True)
    current, legacy = _expected_names(agent, execution)

    inspected = []

    async def inspect(name):
        inspected.append(name)
        if name == current:
            info = _info("a" * 64, "ephemeral", execution, agent)
            mutate(info, execution, agent)
            return info
        raise RuntimeError("not found")

    agent.executor.inspect = inspect

    row = {"request_ref": agent.store.blobs.put_json(execution)}
    with pytest.raises(recovery.NeedsReconciliation, match="ownership mismatch"):
        asyncio.run(recovery.reconcile(agent, row))

    # Only the current name is inspected; no legacy fallback.
    assert inspected == [current]
    # No reconcile_execution call: the mismatch raises before recording.
    assert reconciled == []
    # No events (no retry.decided) and no release/docker (verified by spies).
    assert events == []

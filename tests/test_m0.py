import asyncio
import json
import sqlite3

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from local_agent.cli import main
from local_agent.contracts import AgentConfig, Limits, ReadFileArgs, new_id
from local_agent.executor.mock import MockExecutor
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.observability.spans import Spans
from local_agent.runtime.loop import INSTRUCTIONS, simulate
from local_agent.runtime.replay import recorded_replay
from local_agent.storage.blobs import BlobStore, canonical, digest
from local_agent.storage.database import Store
from local_agent.tools.registry import normalize


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "data")
    yield value
    value.close()


def scenario(store, **kwargs):
    return asyncio.run(simulate(store, **kwargs))


def test_complete_simulation_reconstructs_all_decisions(store):
    executor = MockExecutor()
    provider = ScriptedProvider()
    result = scenario(store, executor=executor, provider=provider)
    assert result["status"] == "completed_unverified", result
    run_id = result["run_id"]
    report = audit(store, run_id)
    assert report["ok"], report["errors"]
    assert len(executor.dispatched) == 2
    assert len(provider.requests) == 3
    replay = recorded_replay(store, run_id)
    assert replay == {
        "run_id": run_id,
        "status": "completed_unverified",
        "model_turns": 3,
        "attempted_calls": 4,
        "rejected": 1,
        "denied": 1,
        "finished": 2,
        "pending_execution_ids": [],
        "real_tools_executed": 0,
        "mode": "recorded-only",
        "capture_mode": "full",
    }
    events = store.events(run_id)
    assert len({event.trace_id for event in events}) == 1
    assert len({event.tool_call_id for event in events if event.event_type == "tool.proposed"}) == 4
    assert [event.run_seq for event in events] == list(range(1, len(events) + 1))
    ids = set()
    for event in events:
        assert set(event.caused_by) <= ids
        ids.add(event.event_id)
        assert len(event.trace_id) == 32 and len(event.span_id) == 16
    for request in provider.requests[1:]:
        snapshot = store.blobs.json(request.context_ref)
        messages = snapshot["messages"]
        for index, message in enumerate(messages):
            if message["role"] == "assistant":
                calls = message["tool_calls"]
                results = messages[index + 1 : index + 1 + len(calls)]
                assert [r["tool_call_id"] for r in results] == [c["id"] for c in calls]


@pytest.mark.parametrize(
    "event_type,expected_models,expected_tools",
    [
        ("model.requested", 0, 0),
        ("model.responded", 1, 0),
        ("policy.evaluated", 1, 0),
        ("execution.dispatch_intent", 1, 0),
        ("execution.started", 1, 0),
    ],
)
def test_actual_commit_failure_blocks_external_callbacks(
    store, event_type, expected_models, expected_tools
):
    # The trigger succeeds; the deferred FK fails at COMMIT, not at INSERT.
    store.db.executescript("""
        CREATE TABLE fail_commit (
          event_id TEXT REFERENCES events(event_id) DEFERRABLE INITIALLY DEFERRED
        );
    """)
    store.db.execute(f"""CREATE TRIGGER fail_boundary AFTER INSERT ON events
        WHEN NEW.event_type='{event_type}' BEGIN
          INSERT INTO fail_commit VALUES ('absent-event');
        END""")
    executor = MockExecutor()
    provider = ScriptedProvider()
    result = scenario(store, executor=executor, provider=provider)
    assert result["status"] == "audit_unavailable", result
    assert len(provider.requests) == expected_models
    assert len(executor.dispatched) == expected_tools
    assert not store.healthy
    assert not store.db.execute("SELECT 1 FROM events WHERE event_type=?", (event_type,)).fetchall()
    assert not store.db.execute("SELECT 1 FROM fail_commit").fetchall()
    # Cannot commit a terminal event after authoritative storage fails.
    assert store.run(result["run_id"])["status"] == "running"


@pytest.mark.parametrize(
    "values",
    [
        {"path": "project/a", "line_limit": True},
        {"path": "project/a", "line_limit": "10"},
        {"path": "project/a", "extra": "field"},
        {"path": "project/a", "schema_version": 2},
        {"path": "project/a", "schema_version": True},
        {"path": "project/a", "line_limit": 1001},
        {"path": "../secret"},
        {"path": "/etc/passwd"},
        {"path": "project/../secret"},
        {"path": "project//a"},
        {"path": "project/a\x00"},
        {"path": "control/a"},
        {"path": "project\\a"},
    ],
)
def test_strict_contracts_reject_invalid_inputs(values):
    with pytest.raises(ValidationError):
        ReadFileArgs.model_validate_json(canonical(values))


def test_frozen_ids_and_contracts():
    value = ReadFileArgs(path="project/a")
    with pytest.raises(ValidationError):
        value.path = "project/b"
    with pytest.raises(ValidationError):
        AgentConfig(instructions_hash="not-a-hash")
    assert len(new_id("call").split("_")[1]) == 32
    with pytest.raises(ValidationError):
        normalize("run_command", {"argv": ["python"], "timeout_seconds": True})


def test_sqlite_constraints_and_durability(store):
    result = scenario(store)
    event = store.events(result["run_id"])[0]
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (new_id("evt"), event.run_id, event.run_seq, event.event_type, event.model_dump_json()),
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute(
            "INSERT INTO tool_calls(id,request_id,record_ref) VALUES (?,?,?)",
            (new_id("call"), new_id("req"), "blob://" + "0" * 64),
        )
    assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert store.db.execute("PRAGMA synchronous").fetchone()[0] == 2
    assert store.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert store.root.stat().st_mode & 0o777 == 0o700
    assert (store.control / "agent.db").stat().st_mode & 0o777 == 0o600


def test_missing_and_corrupted_evidence_is_reported(store):
    result = scenario(store)
    run_id = result["run_id"]
    row = store.db.execute("SELECT result_ref FROM execution_attempts LIMIT 1").fetchone()
    output_ref = store.blobs.json(row[0])["output_ref"]
    path = store.blobs.path(output_ref)
    path.chmod(0o600)
    path.write_bytes(b"tampered")
    report = audit(store, run_id)
    assert not report["ok"] and any("mismatch" in error for error in report["errors"])
    path.unlink()
    assert not audit(store, run_id)["ok"]


def test_blob_immutability_and_reference_validation(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    ref = blobs.put(b"private evidence")
    inode = blobs.path(ref).stat().st_ino
    assert blobs.put(b"private evidence") == ref
    assert blobs.path(ref).stat().st_ino == inode
    assert blobs.path(ref).stat().st_mode & 0o777 == 0o400
    assert not list(blobs.root.glob(".publish-*"))
    with pytest.raises(ValueError):
        blobs.read("blob://../secret")
    with pytest.raises(ValueError):
        blobs.put(b"a" * (10 * 1024 * 1024 + 1))


def test_blob_failure_prevents_provider_work(store, monkeypatch):
    provider = ScriptedProvider()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(store.blobs, "put", fail)
    result = scenario(store, provider=provider)
    assert result["status"] == "audit_unavailable"
    assert not provider.requests


def test_deleted_model_evidence_prevents_tool_dispatch(store, monkeypatch):
    original = store.commit_dispatch

    def remove_evidence_then_dispatch(run_id, request, **kwargs):
        row = store.db.execute("SELECT request_ref FROM model_requests LIMIT 1").fetchone()
        context = store.blobs.json(store.blobs.json(row[0])["context_ref"])
        store.blobs.path(context["payload_ref"]).unlink()
        return original(run_id, request, **kwargs)

    monkeypatch.setattr(store, "commit_dispatch", remove_evidence_then_dispatch)
    executor = MockExecutor()
    result = scenario(store, executor=executor)
    assert result["status"] == "audit_unavailable"
    assert not executor.dispatched


@pytest.mark.parametrize(
    "change",
    [
        {"workspace_id": new_id("ws")},
        {"authorization_ref": new_id("policy")},
        {"normalized_request_hash": "sha256:" + "0" * 64},
        {"arguments": {"path": "project/different-file"}},
        {"tool": "run_command"},
    ],
)
def test_dispatch_rejects_changed_authorization_binding(store, monkeypatch, change):
    original = store.commit_dispatch

    def tampered_dispatch(run_id, request, **kwargs):
        return original(run_id, request.model_copy(update=change), **kwargs)

    monkeypatch.setattr(store, "commit_dispatch", tampered_dispatch)
    executor = MockExecutor()
    result = scenario(store, executor=executor)
    assert result["status"] == "failed", result
    assert not executor.dispatched
    assert not store.db.execute("SELECT 1 FROM execution_attempts").fetchall()


def test_read_only_trace_audit_and_replay_never_dispatch(store, monkeypatch):
    result = scenario(store)
    before = store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def forbidden(*args, **kwargs):
        raise AssertionError("real execution attempted")

    monkeypatch.setattr(MockExecutor, "execute", forbidden)
    monkeypatch.setattr(ScriptedProvider, "generate", forbidden)
    readonly = Store(store.root, readonly=True)
    try:
        assert audit(readonly, result["run_id"])["ok"]
        assert recorded_replay(readonly, result["run_id"])["real_tools_executed"] == 0
        assert readonly.events(result["run_id"])
        with pytest.raises(sqlite3.OperationalError):
            readonly.db.execute("DELETE FROM events")
        with pytest.raises(PermissionError):
            readonly.blobs.put(b"new")
    finally:
        readonly.close()
    assert store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == before


def test_run_and_dispatch_state_tampering_is_detected(store):
    result = scenario(store)
    run_id = result["run_id"]
    store.db.execute("UPDATE runs SET status='verified' WHERE id=?", (run_id,))
    assert not audit(store, run_id)["ok"]
    store.db.execute("UPDATE runs SET status='completed_unverified' WHERE id=?", (run_id,))
    store.db.execute("UPDATE execution_attempts SET state='dispatch_intent',result_ref=NULL")
    report = audit(store, run_id)
    assert not report["ok"] and any("reconciliation" in error for error in report["errors"])


def test_jsonl_can_be_regenerated_from_committed_events(store):
    result = scenario(store)
    path = store.export_jsonl(result["run_id"])
    assert [json.loads(line)["event_id"] for line in path.read_text().splitlines()] == [
        event.event_id for event in store.events(result["run_id"])
    ]
    path.write_text("broken export")
    assert store.export_jsonl(result["run_id"]).read_text() != "broken export"
    assert audit(store, result["run_id"])["ok"]


def test_boundary_spans_are_recording_and_correlated():
    from local_agent.observability.spans import correlation

    spans = Spans()
    exporter = InMemorySpanExporter()
    spans.provider.add_span_processor(SimpleSpanProcessor(exporter))
    with spans.boundary("agent.run"):
        root = correlation()
        with spans.boundary("policy.evaluate"):
            child = correlation()
    spans.shutdown()
    assert child["trace_id"] == root["trace_id"]
    assert child["parent_span_id"] == root["span_id"]
    assert {span.name for span in exporter.get_finished_spans()} == {"agent.run", "policy.evaluate"}


def test_attempted_call_budget_includes_rejections(store):
    config = AgentConfig(
        instructions_hash=digest(INSTRUCTIONS.encode()), limits=Limits(max_attempted_tool_calls=3)
    )
    result = scenario(store, config=config)
    assert result["status"] == "budget_exhausted", result
    report = audit(store, result["run_id"])
    assert report["ok"], report["errors"]
    assert recorded_replay(store, result["run_id"])["attempted_calls"] == 3


def test_provider_transport_error_is_not_completion(store):
    result = scenario(store, provider=ScriptedProvider(responses=()))
    assert result["status"] == "failed"
    events = store.events(result["run_id"])
    assert any(event.event_type == "model.failed" for event in events)
    assert not any(event.event_type == "completion.proposed" for event in events)


def test_cli_smoke_and_unknown_run(tmp_path, capsys):
    args = ["--data-root", str(tmp_path / "data")]
    assert main([*args, "simulate"]) == 0
    result = json.loads(capsys.readouterr().out)
    run_id = result["run_id"]
    for command in ("audit", "trace", "replay", "export-events"):
        tail = ["--recorded-only"] if command == "replay" else []
        assert main([*args, command, run_id, *tail]) == 0
        capsys.readouterr()
    assert main([*args, "audit", new_id("run")]) == 1
    assert "unknown run" in capsys.readouterr().out


def test_newer_database_schema_rejected(store):
    store.db.execute("PRAGMA user_version=2")
    with pytest.raises(ValueError, match="unsupported database schema"):
        Store(store.root, readonly=True)

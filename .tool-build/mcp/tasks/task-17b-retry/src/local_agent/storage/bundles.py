"""Private, fsynced backups and explicitly classified run exports."""

import json
import os
import sqlite3
from pathlib import Path

from local_agent.storage.blobs import canonical, digest, fsync_directory, private_directory


def write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def roots(store, run_id):
    """Traverse explicit record fields, never refs invented in raw model text."""
    refs = set()

    def add(ref):
        if ref:
            store.blobs.read(ref)
            refs.add(ref)

    def record(ref, fields=()):
        add(ref)
        data = store.blobs.json(ref)
        for key in fields:
            add(data.get(key))
        return data

    manifest = record(store.run(run_id)["manifest_ref"], ("config_ref",))
    for row in store.db.execute("SELECT * FROM model_requests WHERE run_id=?", (run_id,)):
        request = record(row["request_ref"], ("context_ref", "workspace_grant_ref"))
        context = record(request["context_ref"], ("payload_ref",))
        for item in (*context.get("provenance", []), *context.get("exclusions", [])):
            add(item.get("source_ref"))
        if row["response_ref"]:
            record(row["response_ref"], ("original_response_ref",))
        for call in store.db.execute("SELECT * FROM tool_calls WHERE request_id=?", (row["id"],)):
            record(call["record_ref"], ("arguments_ref",))
            add(call["validated_ref"])
            for decision in store.db.execute(
                "SELECT * FROM policy_decisions WHERE call_id=?", (call["id"],)
            ):
                record(decision["record_ref"], ("normalized_request_ref",))
            for execution in store.db.execute(
                "SELECT * FROM execution_attempts WHERE call_id=?", (call["id"],)
            ):
                record(execution["request_ref"], ("workspace_grant_ref",))
                if execution["result_ref"]:
                    record(
                        execution["result_ref"],
                        ("output_ref", "stdout_ref", "stderr_ref", "attestation_ref", "helper_ref"),
                    )
            for approval in store.db.execute(
                "SELECT record_ref FROM approvals WHERE call_id=?", (call["id"],)
            ):
                add(approval[0])
    for row in store.db.execute("SELECT record_ref FROM checkpoints WHERE run_id=?", (run_id,)):
        checkpoint = record(row[0])
        for ref in checkpoint["conversation_refs"]:
            add(ref)
    for row in store.db.execute("SELECT record_ref FROM artifacts WHERE run_id=?", (run_id,)):
        record(row[0], ("blob_ref",))
    for event in store.events(run_id):
        # These keys are produced by the harness, not recursively discovered in prose.
        for key in (
            "metadata_ref",
            "capability_ref",
            "grant_ref",
            "snapshot_ref",
            "summary_ref",
            "preserved_constraints_ref",
            "inspect_ref",
            "response_ref",
            "input_ref",
            "validation_ref",
        ):
            add(event.data.get(key))
        if event.event_type == "context.compacted":
            for ref in event.data["inputs"]:
                add(ref)
        if event.event_type == "screenshot.prepared":
            record(event.data["input_ref"], ("image_ref", "history_ref"))
    return refs, manifest


def sqlite_snapshot(store, target, run_id=None):
    connection = sqlite3.connect(target)
    try:
        store.db.backup(connection)
        connection.execute("PRAGMA journal_mode=DELETE")
        if run_id:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute(
                "DELETE FROM event_causes WHERE event_id IN "
                "(SELECT event_id FROM events WHERE run_id!=?)",
                (run_id,),
            )
            connection.execute("DELETE FROM events WHERE run_id!=?", (run_id,))
            calls = "SELECT t.id FROM tool_calls t JOIN model_requests m ON m.id=t.request_id WHERE m.run_id!=?"
            for table in ("approvals", "execution_attempts", "policy_decisions"):
                connection.execute(f"DELETE FROM {table} WHERE call_id IN ({calls})", (run_id,))
            connection.execute("DELETE FROM tool_calls WHERE id IN (" + calls + ")", (run_id,))
            for table in ("model_requests", "artifacts", "checkpoints"):
                connection.execute(f"DELETE FROM {table} WHERE run_id!=?", (run_id,))
            connection.execute("DELETE FROM runs WHERE id!=?", (run_id,))
            connection.commit()
            connection.execute("VACUUM")  # Removed runs must not survive in free pages.
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("backup database integrity failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("backup foreign keys failed")
    finally:
        connection.close()
    target.chmod(0o600)
    with target.open("rb") as stream:
        os.fsync(stream.fileno())


def finish(target, classification, replay, extra):
    checksums = {
        str(p.relative_to(target)): digest(p.read_bytes())
        for p in sorted(target.rglob("*"))
        if p.is_file()
    }
    manifest = {
        "schema_version": 1,
        "classification": classification,
        "capture_mode": "full" if replay else "metadata-only",
        "recorded_replay_available": replay,
        "workspace_restore_available": False,
        "checksums": checksums,
        **extra,
    }
    write(target / "bundle.json", canonical(manifest))
    for path in sorted((p for p in target.rglob("*") if p.is_dir()), reverse=True):
        fsync_directory(path)
    fsync_directory(target)
    fsync_directory(target.parent)
    return {"output": str(target), **manifest}


def export_run(store, run_id, output, *, include_evidence=False):
    from local_agent.evaluation.report import report
    from local_agent.observability.audit import audit
    from local_agent.storage.locks import run_lock

    target = Path(output).expanduser().absolute()
    if target.is_relative_to(store.root):
        raise ValueError("bundle destination must be outside the live data root")
    if target.exists():
        raise ValueError("export destination must not exist")
    # One lease keeps terminal records and the SQLite snapshot consistent.
    with run_lock(store.control):
        source_report = report(store, run_id)
        audit_report = audit(store, run_id)
        private_directory(target)
        if not include_evidence:
            audit_report = {k: v for k, v in audit_report.items() if k != "errors"}
            metadata = {
                k: v for k, v in source_report.items() if k not in ("models", "otel_metrics")
            }
            write(target / "report.json", canonical(metadata))
            write(
                target / "events.json",
                canonical(
                    [
                        {
                            "event_type": e.event_type,
                            "run_seq": e.run_seq,
                            "timestamp_utc": e.timestamp_utc,
                            "trace_id": e.trace_id,
                            "span_id": e.span_id,
                        }
                        for e in store.events(run_id)
                    ]
                ),
            )
            return finish(
                target,
                "metadata; payloads omitted",
                False,
                {"run_id": run_id, "audit": audit_report},
            )
        refs, _ = roots(store, run_id)
        control = target / "control"
        private_directory(control)
        private_directory(control / "blobs")
        private_directory(control / "runs")
        sqlite_snapshot(store, control / "agent.db", run_id)
        for ref in refs:
            write(control / "blobs" / ref[7:], store.blobs.read(ref))
        return finish(
            target,
            "private source/prompt/output evidence; explicitly included",
            True,
            {"run_id": run_id, "audit": audit_report},
        )


def backup(store, output):
    from local_agent.storage.locks import run_lock

    target = Path(output).expanduser().absolute()
    if target.is_relative_to(store.root):
        raise ValueError("bundle destination must be outside the live data root")
    if target.exists():
        raise ValueError("backup destination must not exist")
    with run_lock(store.control):
        private_directory(target)
        control = target / "control"
        private_directory(control)
        private_directory(control / "blobs")
        private_directory(control / "runs")
        sqlite_snapshot(store, control / "agent.db")
        # Include all published blobs: preserves evidence not rooted in SQL, such as reports.
        for path in store.blobs.root.iterdir():
            if len(path.name) == 64 and all(c in "0123456789abcdef" for c in path.name):
                ref = "blob://" + path.name
                write(control / "blobs" / path.name, store.blobs.read(ref))
        return finish(
            target,
            "private complete ledger/evidence backup",
            True,
            {"run_ids": [row[0] for row in store.db.execute("SELECT id FROM runs")]},
        )


def verify_bundle(output):
    target = Path(output)
    data = json.loads((target / "bundle.json").read_text())
    for relative, expected in data["checksums"].items():
        path = target / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink():
            raise ValueError("unsafe bundle path")
        if digest(path.read_bytes()) != expected:
            raise ValueError("bundle checksum mismatch: " + relative)
    return {"ok": True, "files": len(data["checksums"]), "capture_mode": data["capture_mode"]}

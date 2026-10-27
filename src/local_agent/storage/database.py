"""SQLite schema v1. State changes and their events share a single transaction."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from local_agent.contracts import ExecutionRequest, PolicyDecision, RunManifest, ToolCall, new_id
from local_agent.observability.events import TERMINAL, TRANSITIONS, Event
from local_agent.observability.spans import correlation
from local_agent.storage.blobs import (
    BlobStore,
    canonical,
    digest,
    fsync_directory,
    private_directory,
)

SCHEMA = """
CREATE TABLE runs (
 id TEXT PRIMARY KEY, status TEXT NOT NULL, manifest_ref TEXT NOT NULL,
 latest_checkpoint TEXT REFERENCES checkpoints(id), created_utc TEXT NOT NULL
);
CREATE TABLE events (
 event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
 run_seq INTEGER NOT NULL CHECK(run_seq>0), event_type TEXT NOT NULL,
 payload TEXT NOT NULL, UNIQUE(run_id, run_seq)
);
CREATE TABLE event_causes (
 event_id TEXT NOT NULL REFERENCES events(event_id),
 cause_id TEXT NOT NULL REFERENCES events(event_id), PRIMARY KEY(event_id,cause_id)
);
CREATE TABLE model_requests (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
 request_ref TEXT NOT NULL, response_ref TEXT
);
CREATE TABLE tool_calls (
 id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES model_requests(id),
 record_ref TEXT NOT NULL, validated_ref TEXT, rejected INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE policy_decisions (
 id TEXT PRIMARY KEY, call_id TEXT NOT NULL REFERENCES tool_calls(id),
 record_ref TEXT NOT NULL
);
CREATE TABLE execution_attempts (
 id TEXT PRIMARY KEY, call_id TEXT NOT NULL REFERENCES tool_calls(id),
 decision_id TEXT NOT NULL REFERENCES policy_decisions(id),
 request_ref TEXT NOT NULL, state TEXT NOT NULL, result_ref TEXT, container_id TEXT,
 UNIQUE(call_id)
);
CREATE TABLE artifacts (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
 execution_id TEXT NOT NULL REFERENCES execution_attempts(id), record_ref TEXT NOT NULL
);
CREATE TABLE checkpoints (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
 event_seq INTEGER NOT NULL, record_ref TEXT NOT NULL,
 FOREIGN KEY(run_id,event_seq) REFERENCES events(run_id,run_seq)
);
CREATE TABLE approvals (
 id TEXT PRIMARY KEY, call_id TEXT NOT NULL REFERENCES tool_calls(id), record_ref TEXT NOT NULL
);
PRAGMA user_version=1;
"""


class AuditUnavailable(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def references(value):
    if isinstance(value, str) and value.startswith("blob://"):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from references(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from references(item)


class Store:
    def __init__(self, data_root: Path, *, readonly: bool = False):
        self.root = data_root.expanduser().absolute()
        self.control = self.root / "control"
        self.readonly = readonly
        self.healthy = True
        if not readonly:
            private_directory(self.root)
            fsync_directory(self.root.parent)
            private_directory(self.control)
            fsync_directory(self.root)
            private_directory(self.control / "runs")
            fsync_directory(self.control)
        self.blobs = BlobStore(self.control / "blobs", readonly=readonly)
        path = self.control / "agent.db"
        if readonly:
            self.db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        else:
            if path.is_symlink():
                raise ValueError("database may not be a symlink")
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.fchmod(fd, 0o600)
            os.close(fd)
            self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        if not readonly:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                try:
                    self.db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")
                except Exception:
                    self.db.rollback()
                    raise
            elif version != 1:
                raise ValueError(f"unsupported database schema: {version}")
            settings = [
                self.db.execute(f"PRAGMA {key}").fetchone()[0]
                for key in ("foreign_keys", "journal_mode", "synchronous")
            ]
            if settings != [1, "wal", 2]:
                raise AuditUnavailable(f"durability settings not enforced: {settings}")
        elif self.db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("unsupported database schema")

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        if self.readonly or not self.healthy:
            raise AuditUnavailable("audit writer unavailable")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            yield
            self.db.commit()
        except sqlite3.Error as exc:
            self.db.rollback()
            self.healthy = False
            raise AuditUnavailable(str(exc)) from exc
        except BaseException:
            self.db.rollback()
            raise

    def run(self, run_id):
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown run: {run_id}")
        return row

    def _event(self, run_id, event_type, actor, data, *, causes=(), call_id=None):
        run = self.run(run_id)
        if run["status"] in TERMINAL:
            raise ValueError("cannot append to terminal run")
        # Recursively validate evidence before the authoritative commit.
        for ref in references(data):
            self.blobs.read(ref)
        for cause in causes:
            row = self.db.execute("SELECT run_id FROM events WHERE event_id=?", (cause,)).fetchone()
            if row is None or row[0] != run_id:
                raise ValueError("causal predecessor must exist in the same run")
        seq = self.db.execute(
            "SELECT COALESCE(MAX(run_seq),0)+1 FROM events WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        event = Event(
            event_id=new_id("evt"),
            run_id=run_id,
            run_seq=seq,
            timestamp_utc=utc_now(),
            event_type=event_type,
            actor=actor,
            tool_call_id=call_id,
            caused_by=tuple(causes),
            data=data,
            **correlation(),
        )
        self.db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (event.event_id, run_id, seq, event_type, canonical(event).decode()),
        )
        self.db.executemany(
            "INSERT INTO event_causes VALUES (?,?)", [(event.event_id, cause) for cause in causes]
        )
        return event

    def append(self, run_id, event_type, actor, data, **kwargs):
        with self.transaction():
            return self._event(run_id, event_type, actor, data, **kwargs)

    def create_run(self, manifest: RunManifest):
        ref = self.blobs.put_json(manifest)
        with self.transaction():
            self.db.execute(
                "INSERT INTO runs VALUES (?,?,?,NULL,?)",
                (manifest.run_id, "created", ref, utc_now()),
            )
            return self._event(manifest.run_id, "run.created", "runtime", {"manifest_ref": ref})

    def transition(self, run_id, status, *, causes=(), reason=None):
        with self.transaction():
            prior = self.run(run_id)["status"]
            if status not in TRANSITIONS.get(prior, set()):
                raise ValueError(f"invalid run transition {prior} -> {status}")
            if status == "verified":
                verified = self.db.execute(
                    "SELECT payload FROM events WHERE run_id=? AND event_type='completion.verified' "
                    "ORDER BY run_seq DESC LIMIT 1",
                    (run_id,),
                ).fetchone()
                if verified is None:
                    raise ValueError("verification evidence is required")
                evidence = Event.model_validate_json(verified[0]).data
                result = self.blobs.json(evidence["result_ref"])
                if not evidence.get("passed") or result["exit_code"] != 0 or result["simulated"]:
                    raise ValueError("independent verification did not pass")
            event = self._event(
                run_id,
                "run.started" if status == "running" else "run.stopped",
                "runtime",
                {"previous_status": prior, "status": status, "reason": reason},
                causes=causes,
            )
            self.db.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))
            return event

    def record_request(self, request, *, causes):
        ref = self.blobs.put_json(request)
        with self.transaction():
            snapshot = self.blobs.json(request.context_ref)
            self.blobs.read(snapshot["payload_ref"])
            self.db.execute(
                "INSERT INTO model_requests VALUES (?,?,?,NULL)",
                (request.request_id, request.run_id, ref),
            )
            return self._event(
                request.run_id,
                "model.requested",
                "runtime",
                {"request_id": request.request_id, "request_ref": ref},
                causes=causes,
            )

    def record_response(self, run_id, response, calls, *, causes):
        ref = self.blobs.put_json(response)
        with self.transaction():
            request = self.db.execute(
                "SELECT * FROM model_requests WHERE id=?", (response.request_id,)
            ).fetchone()
            if request is None or request["run_id"] != run_id or request["response_ref"]:
                raise ValueError("response must bind an unanswered request in this run")
            self.db.execute(
                "UPDATE model_requests SET response_ref=? WHERE id=?", (ref, response.request_id)
            )
            event = self._event(
                run_id,
                "model.responded",
                "model",
                {"response_ref": ref, "request_id": response.request_id},
                causes=causes,
            )
            proposed = []
            self.blobs.read(response.original_response_ref)
            if len(calls) != len(response.tool_calls):
                raise ValueError("incomplete response call list")
            for index, (call, original) in enumerate(zip(calls, response.tool_calls, strict=True)):
                if (
                    call.request_id != response.request_id
                    or call.index != index
                    or call.name != original.name
                    or self.blobs.json(call.arguments_ref) != original.arguments
                ):
                    raise ValueError("call does not match provider response")
                call_ref = self.blobs.put_json(call)
                self.db.execute(
                    "INSERT INTO tool_calls(id,request_id,record_ref) VALUES (?,?,?)",
                    (call.call_id, call.request_id, call_ref),
                )
                proposed.append(
                    self._event(
                        run_id,
                        "tool.proposed",
                        "model",
                        {"call_ref": call_ref},
                        causes=(event.event_id,),
                        call_id=call.call_id,
                    )
                )
            return event, proposed

    def record_validation(self, run_id, call_id, normalized, error, *, causes):
        ref = self.blobs.put_json(normalized) if normalized is not None else None
        with self.transaction():
            row = self.db.execute(
                "SELECT t.*,m.run_id FROM tool_calls t JOIN model_requests m "
                "ON m.id=t.request_id WHERE t.id=?",
                (call_id,),
            ).fetchone()
            if row is None or row["run_id"] != run_id or row["validated_ref"] or row["rejected"]:
                raise ValueError("call cannot be validated")
            self.db.execute(
                "UPDATE tool_calls SET validated_ref=?,rejected=? WHERE id=?",
                (ref, int(ref is None), call_id),
            )
            return self._event(
                run_id,
                "tool.validated" if ref else "tool.rejected",
                "registry",
                {"normalized_ref": ref, "error": error},
                causes=causes,
                call_id=call_id,
            )

    def record_policy(self, run_id, decision: PolicyDecision, *, causes):
        ref = self.blobs.put_json(decision)
        with self.transaction():
            row = self.db.execute(
                "SELECT t.*,m.run_id FROM tool_calls t JOIN model_requests m "
                "ON m.id=t.request_id WHERE t.id=?",
                (decision.call_id,),
            ).fetchone()
            if (
                row is None
                or row["run_id"] != run_id
                or row["validated_ref"] is None
                or row["validated_ref"] != decision.normalized_request_ref
            ):
                raise ValueError("policy must bind validated arguments in this run")
            if digest(self.blobs.read(row["validated_ref"])) != decision.normalized_request_hash:
                raise ValueError("policy request hash mismatch")
            self.db.execute(
                "INSERT INTO policy_decisions VALUES (?,?,?)",
                (decision.decision_id, decision.call_id, ref),
            )
            return self._event(
                run_id,
                "policy.evaluated",
                "policy",
                {"decision_ref": ref},
                causes=causes,
                call_id=decision.call_id,
            )

    def commit_dispatch(self, run_id, request: ExecutionRequest, *, causes):
        ref = self.blobs.put_json(request)
        with self.transaction():
            row = self.db.execute(
                "SELECT t.record_ref,t.validated_ref,m.run_id,m.request_ref model_request_ref,p.record_ref policy_ref "
                "FROM tool_calls t JOIN model_requests m ON m.id=t.request_id "
                "JOIN policy_decisions p ON p.call_id=t.id "
                "WHERE t.id=? AND p.id=?",
                (request.call_id, request.authorization_ref),
            ).fetchone()
            if row is None or row["run_id"] != run_id or not row["validated_ref"]:
                raise ValueError("dispatch missing validation or policy")
            decision = PolicyDecision.model_validate_json(self.blobs.read(row["policy_ref"]))
            call = ToolCall.model_validate_json(self.blobs.read(row["record_ref"]))
            normalized = self.blobs.json(row["validated_ref"])
            from local_agent.tools.registry import normalize
            from local_agent.workspace.options import task_arguments

            manifest = self.blobs.json(self.run(run_id)["manifest_ref"])
            config = self.blobs.json(manifest["config_ref"])
            provider = self.blobs.json(row["model_request_ref"])["provider"]
            arguments = task_arguments(call.name, self.blobs.json(call.arguments_ref),
                                       config.get("working_directory", ".") if provider != "harness" else ".")

            if normalized != normalize(
                call.name,
                arguments,
                version=call.tool_version,
                legacy_evidence="evidence_ref" in normalized["arguments"],
            ):
                raise ValueError("validated arguments differ from the original proposal")
            manifest = self.blobs.json(self.run(run_id)["manifest_ref"])
            policy = self.blobs.json(manifest["config_ref"])["policy_hash"]
            evidence = self.db.execute(
                "SELECT m.request_ref,m.response_ref FROM model_requests m "
                "JOIN tool_calls t ON t.request_id=m.id WHERE t.id=?",
                (request.call_id,),
            ).fetchone()
            response = self.blobs.json(evidence["response_ref"])
            self.blobs.read(response["original_response_ref"])
            model_request = self.blobs.json(evidence["request_ref"])
            granted_workspace = manifest["workspace_id"]
            if request.workspace_grant_ref is not None:
                grant = self.blobs.json(request.workspace_grant_ref)
                recorded_grant = self.db.execute(
                    "SELECT 1 FROM events WHERE run_id=? AND event_type='workspace.prepared' "
                    "AND json_extract(payload,'$.data.grant_ref')=?",
                    (run_id, request.workspace_grant_ref),
                ).fetchone()
                if (
                    not recorded_grant
                    or grant["run_id"] != run_id
                    or model_request["provider"] != "harness"
                    or grant["purpose"] != model_request["purpose"]
                ):
                    raise ValueError("invalid trusted workspace grant")
                granted_workspace = grant["workspace_id"]
            snapshot = self.blobs.json(model_request["context_ref"])
            self.blobs.read(snapshot["payload_ref"])
            if (
                decision.verdict != "allow"
                or decision.policy_hash != policy
                or decision.normalized_request_hash != request.normalized_request_hash
                or digest(canonical(normalized)) != request.normalized_request_hash
                or normalized
                != {
                    "tool": request.tool,
                    "arguments": request.arguments,
                    "effective_limits": request.effective_limits.model_dump(mode="json"),
                }
                or call.name != request.tool
                or call.tool_version != request.tool_version
                or request.workspace_id != granted_workspace
            ):
                raise ValueError("dispatch authorization binding mismatch")
            self.db.execute(
                "INSERT INTO execution_attempts VALUES (?,?,?,?,?,NULL,NULL)",
                (
                    request.execution_id,
                    request.call_id,
                    request.authorization_ref,
                    ref,
                    "dispatch_intent",
                ),
            )
            return self._event(
                run_id,
                "execution.dispatch_intent",
                "runtime",
                {"execution_id": request.execution_id, "request_ref": ref},
                causes=causes,
                call_id=request.call_id,
            )

    def execution_event(self, run_id, execution_id, result=None, *, causes):
        ref = self.blobs.put_json(result) if result is not None else None
        with self.transaction():
            row = self.db.execute(
                "SELECT e.*,m.run_id FROM execution_attempts e "
                "JOIN tool_calls t ON t.id=e.call_id JOIN model_requests m "
                "ON m.id=t.request_id WHERE e.id=?",
                (execution_id,),
            ).fetchone()
            expected = "started" if result is not None else "dispatch_intent"
            if row is None or row["run_id"] != run_id or row["state"] != expected:
                raise ValueError("invalid execution transition")
            if result is not None and result.execution_id != execution_id:
                raise ValueError("result identity mismatch")
            if result is not None:
                self.blobs.read(result.output_ref)
            state = "finished" if result is not None else "started"
            self.db.execute(
                "UPDATE execution_attempts SET state=?,result_ref=? WHERE id=?",
                (state, ref, execution_id),
            )
            return self._event(
                run_id,
                "execution." + state,
                "executor",
                {"execution_id": execution_id, "result_ref": ref},
                causes=causes,
                call_id=row["call_id"],
            )

    def checkpoint(self, checkpoint, *, causes):
        ref = self.blobs.put_json(checkpoint)
        with self.transaction():
            self.db.execute(
                "INSERT INTO checkpoints VALUES (?,?,?,?)",
                (checkpoint.checkpoint_id, checkpoint.run_id, checkpoint.completed_event_seq, ref),
            )
            event = self._event(
                checkpoint.run_id,
                "checkpoint.committed",
                "runtime",
                {"checkpoint_ref": ref},
                causes=causes,
            )
            self.db.execute(
                "UPDATE runs SET latest_checkpoint=? WHERE id=?",
                (checkpoint.checkpoint_id, checkpoint.run_id),
            )
            return event

    def register_artifact(self, artifact, *, causes):
        ref = self.blobs.put_json(artifact)
        if digest(self.blobs.read(artifact.blob_ref)) != artifact.content_hash:
            raise ValueError("artifact content hash mismatch")
        with self.transaction():
            self.db.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?)",
                (artifact.artifact_id, artifact.run_id, artifact.execution_id, ref),
            )
            return self._event(
                artifact.run_id,
                "artifact.registered",
                "runtime",
                {"artifact_ref": ref},
                causes=causes,
            )

    def reconcile_execution(self, run_id, execution_id, result, outcome, *, causes):
        ref = self.blobs.put_json(result) if result is not None else None
        with self.transaction():
            row = self.db.execute(
                "SELECT e.*,m.run_id FROM execution_attempts e JOIN tool_calls t "
                "ON t.id=e.call_id JOIN model_requests m ON m.id=t.request_id WHERE e.id=?",
                (execution_id,),
            ).fetchone()
            if row is None or row["run_id"] != run_id or row["state"] == "finished":
                raise ValueError("invalid reconciliation")
            if result is not None:
                if result.execution_id != execution_id:
                    raise ValueError("reconciled result mismatch")
                self.blobs.read(result.output_ref)
            self.db.execute(
                "UPDATE execution_attempts SET state=?,result_ref=? WHERE id=?",
                ("finished" if result else "uncertain", ref, execution_id),
            )
            return self._event(
                run_id,
                "execution.reconciled",
                "recovery",
                {
                    "execution_id": execution_id,
                    "result_ref": ref,
                    "outcome": outcome,
                    "side_effect_status": result.side_effect_status if result else "unknown",
                },
                causes=causes,
                call_id=row["call_id"],
            )

    def events(self, run_id):
        self.run(run_id)
        return [
            Event.model_validate_json(row[0])
            for row in self.db.execute(
                "SELECT payload FROM events WHERE run_id=? ORDER BY run_seq", (run_id,)
            )
        ]

    def export_jsonl(self, run_id):
        if self.readonly:
            raise PermissionError("read-only store")
        directory = self.control / "runs" / run_id
        private_directory(directory)
        fsync_directory(directory.parent)
        # Export is derived; failure here must not change authoritative run state.
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile(dir=directory, delete=False) as stream:
            temp = Path(stream.name)
            try:
                for event in self.events(run_id):
                    stream.write(canonical(event) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(temp, directory / "events.jsonl")
                fsync_directory(directory)
            finally:
                temp.unlink(missing_ok=True)
        return directory / "events.jsonl"

"""Host-owned persistent Docker sessions; workspace files outlive every container."""

import asyncio
import fcntl
import hashlib
import json
import os
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from local_agent.storage.blobs import canonical, fsync_directory, private_directory


def utc_now():
    return datetime.now(UTC).isoformat()


def publish(path, value):
    """Publish mutable host control metadata atomically and durably."""
    private_directory(path.parent)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".publish-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@asynccontextmanager
async def lease(path, *, wait=True):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not wait:
                    raise
                await asyncio.sleep(0.05)
        yield
    finally:
        os.close(fd)


class ExecutionManager:
    def __init__(self, store, workspaces, image, settings, *, docker, attest, emit):
        self.store, self.workspaces, self.image = store, workspaces, image
        self.settings, self.docker, self.attest, self.emit = settings, docker, attest, emit
        self.directory = store.control / "containers"
        private_directory(self.directory)
        self.owner = hashlib.sha256(str(store.control.resolve()).encode()).hexdigest()

    def path(self, workspace_id, *, allow_missing=False):
        self.workspaces.path(workspace_id, allow_missing=allow_missing)
        return self.directory / (workspace_id + ".json")

    def load(self, workspace_id):
        path = self.path(workspace_id, allow_missing=True)
        try:
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
                record = json.load(stream)
        except FileNotFoundError:
            return None
        if (
            not isinstance(record, dict)
            or record.get("workspace_id") != workspace_id
            or record.get("owner") != self.owner
        ):
            raise ValueError("invalid persistent container manifest")
        return record

    def save(self, record):
        publish(self.path(record["workspace_id"], allow_missing=True), record)

    def event(self, kind, record, **extra):
        execution_id = record.get("active_execution_id") or record.get("last_execution_id")
        correlation = {}
        if execution_id and hasattr(self.store, "db"):
            row = self.store.db.execute(
                "SELECT call_id,request_ref FROM execution_attempts WHERE id=?", (execution_id,)
            ).fetchone()
            if row:
                request = self.store.blobs.json(row["request_ref"])
                correlation = {
                    "tool_call_id": row["call_id"], "origin_trace_id": request["trace_id"],
                    "origin_span_id": request["parent_span_id"],
                }
        self.emit(kind, {
            **{key: record.get(key) for key in (
                "workspace_id", "container_id", "state", "active_execution_id"
            )},
            "execution_id": execution_id,
            **correlation,
            "origin_run_id": record.get("run_id"),
            **extra,
        })

    async def inspect(self, container_id):
        data = await self.docker("inspect", container_id, check=False)
        value = json.loads(data) if data.strip() else []
        if value == []:
            # check=False must not turn a daemon outage into "container removed".
            await self.docker("ps", "-q")
            return None
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
            raise ValueError("invalid Docker inspect response")
        return value[0]

    async def owned(self):
        ids = (await self.docker(
            "ps", "-aq", "--no-trunc",
            "--filter", "label=local-agent.owner=" + self.owner,
            "--filter", "label=local-agent.mode=persistent",
        )).decode().split()
        return ids

    def verify(self, info, record, *, cleanup=False):
        labels = info["Config"].get("Labels") or {}
        if (
            info["Id"] != record["container_id"]
            or labels.get("local-agent.owner") != self.owner
            or labels.get("local-agent.mode") != "persistent"
            or labels.get("local-agent.workspace") != record["workspace_id"]
        ):
            raise PermissionError("persistent container ownership mismatch")
        self.attest(info, self.workspaces.path(record["workspace_id"], allow_missing=cleanup))

    async def remove(self, record, *, kill=False):
        """Caller holds the workspace lease. Never select a container by name."""
        try:
            info = await self.inspect(record["container_id"])
            if info is not None:
                self.verify(info, record, cleanup=True)
                if info["State"]["Running"]:
                    record["state"] = "STOPPING"
                    self.save(record)
                    try:
                        self.event("container.stopped", record)
                    except BaseException:
                        # A broken audit store must not leave an already-active command running.
                        await self.docker("kill", record["container_id"])
                        raise
                    # Stop before publishing the STOPPED outcome.
                    if kill:
                        await self.docker("kill", record["container_id"])
                    else:
                        await self.docker("stop", "--time", "1", record["container_id"])
                    record["state"] = "STOPPED"
                    self.save(record)
                    self.event("container.stopped", record)
                await self.docker("rm", record["container_id"])
            record["state"] = "REMOVED"
            self.save(record)
            self.event("container.removed", record)
            record["active_execution_id"] = None
            self.save(record)
        except BaseException:
            self.event("container.cleanup_failed", record, error="container cleanup failed")
            raise

    async def ensure(self, workspace_id, run_id, execution_id, create_args):
        fingerprint = hashlib.sha256(canonical({
            "image": self.image, "args": create_args,
            "idle_timeout": self.settings.persistent_container_idle_timeout,
        })).hexdigest()
        previous = self.load(workspace_id)
        if previous:
            info = await self.inspect(previous["container_id"])
            if info is not None:
                self.verify(info, previous)
                reusable = (
                    previous["config_fingerprint"] == fingerprint
                    and not previous.get("active_execution_id")
                    and previous["state"] == "IDLE"
                    and info["State"]["Running"]
                )
                if reusable:
                    return previous
                await self.remove(previous, kill=True)

        async with lease(self.directory / "capacity.lock"):
            if len(await self.owned()) >= self.settings.max_persistent_containers:
                raise RuntimeError("persistent container capacity reached")
            container_id = (await self.docker(
                "create", "--name", "local-agent-session-" + uuid4().hex,
                "--label", "local-agent.owner=" + self.owner,
                "--label", "local-agent.mode=persistent",
                "--label", "local-agent.workspace=" + workspace_id,
                *create_args, "--entrypoint", "python", self.image,
                "-I", "-S", "-c", "import time; time.sleep(2147483647)",
            )).decode().strip()
            record = {
                "workspace_id": workspace_id, "container_id": container_id,
                "owner": self.owner, "image": self.image,
                "config_fingerprint": fingerprint, "state": "CREATED",
                "created_at": utc_now(), "last_used_at": utc_now(),
                "idle_timeout": self.settings.persistent_container_idle_timeout,
                "active_execution_id": execution_id, "last_execution_id": execution_id, "run_id": run_id,
                "settings": self.settings.model_dump(mode="json"),
            }
            info = None
            try:
                info = await self.inspect(container_id)
                if info is None:
                    raise RuntimeError("created container disappeared")
                self.verify(info, record)
                self.save(record)
                self.event("container.created", record)
                record["state"] = "STARTING"
                self.save(record)
                self.event("container.started", record)
                await self.docker("start", container_id)
                info = await self.inspect(container_id)
                if info is None or not info["State"]["Running"]:
                    raise RuntimeError("persistent container did not start")
                self.verify(info, record)
                record["state"] = "RUNNING"
                self.save(record)
                self.event("container.started", record)
                return record
            except BaseException:
                # Owned startup failures remain discoverable by labels after crashes.
                if info is not None:
                    self.verify(info, record)
                    await self.docker("rm", "-f", container_id)
                    record["state"] = "REMOVED"
                    self.save(record)
                self.event("container.failed", {**record, "state": "FAILED"},
                           error="persistent startup failed")
                raise

    @asynccontextmanager
    async def session(self, workspace_id, run_id, execution_id, create_args):
        self.path(workspace_id)
        async with lease(self.directory / (workspace_id + ".lock")):
            record = await self.ensure(workspace_id, run_id, execution_id, create_args)
            record.update(state="EXECUTING", active_execution_id=execution_id,
                          last_execution_id=execution_id, run_id=run_id)
            self.save(record)
            try:
                self.event("container.started", record)
                yield record
            except BaseException:
                current = self.load(workspace_id)
                if current and current["container_id"] == record["container_id"]:
                    await self.remove(current, kill=True)
                raise
            else:
                current = self.load(workspace_id)
                if current and current["state"] != "REMOVED":
                    current.update(state="IDLE", active_execution_id=None, last_used_at=utc_now())
                    self.save(current)
                    self.event("container.idle", {**current, "active_execution_id": execution_id})

    async def terminate(self, workspace_id, container_id):
        record = self.load(workspace_id)
        if record is None or record["container_id"] != container_id:
            raise PermissionError("persistent execution container changed")
        await self.remove(record, kill=True)

    async def stop(self, workspace_id, *, expected_container_id=None, expected_execution_id=None):
        self.path(workspace_id, allow_missing=True)
        async with lease(self.directory / (workspace_id + ".lock")):
            record = self.load(workspace_id)
            if record is None:
                return False
            if record["state"] == "REMOVED" and await self.inspect(record["container_id"]) is None:
                return False
            if expected_container_id and record["container_id"] != expected_container_id:
                return False
            if expected_execution_id and (
                record.get("active_execution_id") not in (None, expected_execution_id)
                or record.get("last_execution_id") not in (None, expected_execution_id)
            ):
                return False
            await self.remove(record)
            return True

    async def cleanup_idle(self):
        removed = []
        for container_id in await self.owned():
            info = await self.inspect(container_id)
            if info is None:
                continue
            workspace_id = (info["Config"].get("Labels") or {}).get("local-agent.workspace")
            self.path(workspace_id, allow_missing=True)
            workspace_exists = self.workspaces.path(workspace_id, allow_missing=True).is_dir()
            try:
                async with lease(self.directory / (workspace_id + ".lock"), wait=False):
                    record = self.load(workspace_id)
                    matched = record is not None and record["container_id"] == container_id
                    if matched and workspace_exists and record["state"] == "IDLE" and not record["active_execution_id"]:
                        elapsed = time.time() - datetime.fromisoformat(record["last_used_at"]).timestamp()
                        if elapsed < record["idle_timeout"]:
                            continue
                    if not matched:
                        # Preserve a newer keeper's manifest when removing an orphan.
                        orphan = {
                            "workspace_id": workspace_id, "container_id": container_id,
                            "owner": self.owner, "state": "FAILED", "run_id": None,
                            "active_execution_id": None,
                        }
                        self.verify(info, orphan, cleanup=True)
                        try:
                            self.event("container.stopped", {**orphan, "state": "STOPPING"})
                            await self.docker("rm", "-f", container_id)
                            self.event("container.removed", {**orphan, "state": "REMOVED"})
                        except BaseException:
                            self.event("container.cleanup_failed", orphan, error="orphan removal failed")
                            raise
                    else:
                        await self.remove(record, kill=bool(record.get("active_execution_id")))
                    removed.append(container_id)
            except BlockingIOError:
                continue
        return removed

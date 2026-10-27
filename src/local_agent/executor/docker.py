"""Docker-only executor. Controller subprocesses are fixed Docker CLI operations."""

import asyncio
import json
import os
import re
import time
from datetime import UTC, datetime

from local_agent.contracts import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    ExecutionSettings,
)
from local_agent.executor.lifecycle import ExecutionManager, publish
from local_agent.executor.worker import validate_execution_options
from local_agent.storage.blobs import canonical

OUTPUT_CAP = 10 * 1024 * 1024
PREVIEW_CAP = 16384


async def docker(*argv, timeout=60, check=True, progress=False):
    proc = await asyncio.create_subprocess_exec(
        "docker",
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=None if progress else asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except BaseException:
        proc.kill()
        await proc.wait()
        raise
    if check and proc.returncode:
        raise RuntimeError(
            f"Docker {argv[0]} failed: {(stderr or b'see build log').decode(errors='replace')[:4096]}"
        )
    return stdout


class DockerExecutor:
    def __init__(self, store, workspaces, image, *, output_cap=OUTPUT_CAP, settings=None):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise ValueError("sandbox image must be pinned by immutable local image ID")
        self.store, self.workspaces, self.image = store, workspaces, image
        if not 1 <= output_cap <= OUTPUT_CAP:
            raise ValueError("invalid output capture cap")
        self.output_cap = output_cap
        self.settings = settings or ExecutionSettings()
        if self.settings.container_network_enabled:
            raise ValueError("current execution policy requires network disabled")
        self.active = set()
        self.fault_hook = None

    async def inspect(self, name):
        return json.loads(await docker("inspect", name))[0]

    def attest(self, info, workspace):
        host, config = info["HostConfig"], info["Config"]
        checks = {
            "image": info["Image"] == self.image,
            "nonroot": config["User"] == f"{os.getuid()}:{os.getgid()}" and os.getuid() != 0,
            "readonly": host["ReadonlyRootfs"],
            "network": host["NetworkMode"] == "none",
            "privileged": not host["Privileged"],
            "capabilities": host["CapDrop"] == ["ALL"],
            "no_new_privileges": "no-new-privileges" in host["SecurityOpt"],
            "seccomp": not any("seccomp=unconfined" in s for s in host["SecurityOpt"]),
            "memory": host["Memory"] == self.settings.container_memory_limit * 1024 * 1024,
            "swap": host["MemorySwap"] == host["Memory"],
            "cpu": host["NanoCpus"] == self.settings.container_cpu_limit * 1000000000,
            "pids": host["PidsLimit"] == 128,
            "pid_namespace": host["PidMode"] == "",
            "devices": not host["Devices"] and not host["DeviceRequests"],
            "mount_scope": len(info["Mounts"]) == 1
            and info["Mounts"][0]["Source"] == str(workspace)
            and info["Mounts"][0]["Destination"] == "/workspace"
            and info["Mounts"][0]["RW"],
            "tmpfs": set(host["Tmpfs"]) == {"/tmp"},
        }
        if not all(checks.values()):
            raise RuntimeError(
                f"sandbox attestation failed: {[k for k, v in checks.items() if not v]}"
            )
        return {"checks": checks, "inspect": info, "workspace_disk_guarantee": "soft_monitor"}

    def make_manager(self, emit):
        return ExecutionManager(
            self.store, self.workspaces, self.image, self.settings,
            docker=docker, attest=self.attest, emit=emit,
        )

    def create_args(self, workspace):
        return [
            "--user", f"{os.getuid()}:{os.getgid()}", "--read-only",
            "--network", "none", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--cpus", str(self.settings.container_cpu_limit),
            "--memory", f"{self.settings.container_memory_limit}m",
            "--memory-swap", f"{self.settings.container_memory_limit}m",
            "--pids-limit", "128", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=128m,mode=1777",
            "--init", "--mount", f"type=bind,src={workspace},dst=/workspace",
            "--env", "HOME=/tmp", "--env", "LANG=C.UTF-8",
            "--env", "PYTHONDONTWRITEBYTECODE=1", "--log-driver", "local",
            "--log-opt", "max-size=12m", "--log-opt", "max-file=1",
            "--log-opt", "compress=false", "-i",
        ]

    def attempt_context(self, execution_id):
        row = self.store.db.execute(
            "SELECT m.run_id,e.call_id FROM execution_attempts e JOIN tool_calls t "
            "ON t.id=e.call_id JOIN model_requests m ON m.id=t.request_id WHERE e.id=?",
            (execution_id,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown execution")
        return row["run_id"], row["call_id"]

    def emitter(self, run_id, call_id, execution_id, workspace_id):
        def emit(kind, data):
            self.store.append(run_id, kind, "executor", {
                **data, "run_id": run_id, "tool_call_id": call_id,
                "execution_id": execution_id, "workspace_id": workspace_id,
            }, call_id=call_id)
        return emit

    async def execute(
        self,
        request: ExecutionRequest,
        *,
        execution_mode: ExecutionMode | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        row = self.store.db.execute(
            "SELECT state,request_ref FROM execution_attempts WHERE id=?", (request.execution_id,)
        ).fetchone()
        if row is None or row[0] != "started" or self.store.blobs.read(row[1]) != canonical(request):
            raise ValueError("executor requires a durable started attempt")
        mode = execution_mode or self.settings.execution_mode_default
        if mode not in ("ephemeral", "persistent"):
            raise ValueError("unknown execution mode")
        options = validate_execution_options({"environment": {} if environment is None else environment})
        if self.workspaces.git_info(request.workspace_id):
            from local_agent.workspace.git import GitWorktrees

            worktrees = GitWorktrees(self.workspaces)
            worktrees.verify(worktrees.load(request.workspace_id))
            # Shared host Git metadata is outside the mount. Container Git is scratch history only.
            options["environment"].update({
                "GIT_DIR": "/workspace/tools/.git-shadow",
                "GIT_WORK_TREE": "/workspace/project",
            })
        run_id, call_id = self.attempt_context(request.execution_id)
        emit = self.emitter(run_id, call_id, request.execution_id, request.workspace_id)
        emit("execution.requested", {"execution_mode": mode, "state": "CREATED"})
        manager = self.make_manager(emit)
        if mode == "persistent":
            async with manager.session(
                request.workspace_id, run_id, request.execution_id,
                self.create_args(self.workspaces.path(request.workspace_id)),
            ) as session:
                return await self._execute(
                    request, mode, session["container_id"], manager, options["environment"], emit
                )
        return await self._execute(request, mode, None, manager, options["environment"], emit)

    async def _execute(self, request, mode, container_id, manager, environment, emit):
        row = self.store.db.execute(
            "SELECT state,request_ref FROM execution_attempts WHERE id=?", (request.execution_id,)
        ).fetchone()
        if (
            row is None
            or row[0] != "started"
            or self.store.blobs.read(row[1]) != canonical(request)
        ):
            raise ValueError("executor requires a durable started attempt")
        workspace = self.workspaces.path(request.workspace_id)
        run_id = self.store.db.execute(
            "SELECT m.run_id FROM execution_attempts e JOIN tool_calls t "
            "ON t.id=e.call_id JOIN model_requests m ON m.id=t.request_id WHERE e.id=?",
            (request.execution_id,),
        ).fetchone()[0]
        name = container_id or ("local-agent-" + request.execution_id)
        created = False
        proc = None
        started = time.monotonic()
        started_at = datetime.now(UTC).isoformat()
        status = "succeeded"
        outputs = [bytearray(), bytearray()]
        total = 0
        exceeded = asyncio.Event()
        resource_reason = "output"
        timeout = min(self.settings.max_execution_seconds, request.arguments.get("timeout_seconds", 60))
        if request.deadline_utc:
            timeout = min(
                timeout,
                (datetime.fromisoformat(request.deadline_utc) - datetime.now(UTC)).total_seconds(),
            )
            if timeout <= 0:
                raise RuntimeError("execution deadline expired before dispatch")
        try:
            if mode == "ephemeral":
                await docker(
                    "create", "--name", name,
                    "--label", "local-agent.execution=" + request.execution_id,
                    "--label", "local-agent.workspace=" + request.workspace_id,
                    "--label", "local-agent.run=" + run_id,
                    "--label", "local-agent.owner=" + manager.owner,
                    "--label", "local-agent.mode=ephemeral",
                    *self.create_args(workspace), self.image,
                )
                created = True
            info = await self.inspect(name)
            attestation_ref = self.store.blobs.put_json(self.attest(info, workspace))
            with self.store.transaction():
                self.store.db.execute(
                    "UPDATE execution_attempts SET container_id=? WHERE id=?",
                    (info["Id"], request.execution_id),
                )
            container_id = info["Id"]
            publish(self.store.control / "attempts" / (request.execution_id + ".container.json"), {
                "execution_id": request.execution_id, "execution_mode": mode,
                "container_id": container_id, "workspace_id": request.workspace_id,
                "run_id": run_id, "tool_call_id": request.call_id, "owner": manager.owner,
            })
            if mode == "ephemeral":
                emit("container.created", {"container_id": container_id, "state": "CREATED"})
            self.active.add(container_id)
            command = (
                ["exec", "-i", "--workdir", "/workspace", container_id,
                 "python", "-I", "-S", "/opt/local-agent/worker.py"]
                if mode == "persistent" else ["start", "-ai", container_id]
            )
            proc = await asyncio.create_subprocess_exec(
                "docker", *command, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            emit("container.started", {"container_id": container_id, "state": "EXECUTING"})

            async def stop_command():
                if mode == "persistent":
                    await manager.terminate(request.workspace_id, container_id)
                else:
                    await docker("kill", container_id, check=False)

            async def drain(stream, index):
                nonlocal total
                while chunk := await stream.read(65536):
                    room = max(0, self.output_cap - total)
                    outputs[index].extend(chunk[:room])
                    total += min(len(chunk), room)
                    if len(chunk) > room:
                        exceeded.set()

            async def disk_monitor():
                nonlocal status, resource_reason
                while True:
                    if self.store.db.execute(
                        "SELECT 1 FROM events WHERE run_id=? AND event_type='cancel.requested' LIMIT 1",
                        (run_id,),
                    ).fetchone():
                        info = await self.inspect(name)
                        if info["State"]["Status"] == "created":
                            await asyncio.sleep(0.05)
                            continue
                        status = "cancelled"
                        exceeded.set()
                        return

                    # Host traversal never opens workspace files or follows links.
                    def measure():
                        size = count = 0

                        def failed(error):
                            raise error

                        for _, dirs, files, fd in os.fwalk(
                            workspace, follow_symlinks=False, onerror=failed
                        ):
                            count += len(dirs) + len(files)
                            if count > 100000:
                                return 1024**3 + 1
                            for name in files:
                                try:
                                    size += os.stat(name, dir_fd=fd, follow_symlinks=False).st_size
                                except FileNotFoundError:
                                    pass
                        return size

                    try:
                        size = await asyncio.to_thread(measure)
                    except OSError:
                        resource_reason = "workspace_monitor"
                        exceeded.set()
                        return
                    if size > 1024 * 1024 * 1024:
                        resource_reason = "workspace_disk"
                        exceeded.set()
                        return
                    await asyncio.sleep(0.25)

            readers = [
                asyncio.create_task(drain(proc.stdout, 0)),
                asyncio.create_task(drain(proc.stderr, 1)),
            ]
            monitor = asyncio.create_task(disk_monitor())
            waiter = asyncio.create_task(proc.wait())
            flood = asyncio.create_task(exceeded.wait())
            try:
                payload = request.model_dump(mode="json")
                payload["_execution"] = {
                    "memory_mb": self.settings.container_memory_limit,
                    "cpu_cores": self.settings.container_cpu_limit,
                    "environment": environment,
                }
                proc.stdin.write(canonical(payload))
                await asyncio.wait_for(proc.stdin.drain(), timeout=min(timeout, 10))
                proc.stdin.close()
                if self.fault_hook:
                    self.fault_hook("after_container_launch")
                done, _ = await asyncio.wait(
                    [waiter, flood], timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                )
                if flood in done:
                    if status != "cancelled":
                        status = "output_limit"
                    await stop_command()
                elif waiter not in done:
                    status = "timeout"
                    await stop_command()
                await asyncio.wait_for(waiter, 15)
                await asyncio.gather(*readers)
            finally:
                for task in [monitor, flood, waiter, *readers]:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(monitor, flood, waiter, *readers, return_exceptions=True)
            if mode == "persistent":
                exit_code = proc.returncode
            else:
                info = await self.inspect(name)
                exit_code = info["State"]["ExitCode"]
            if status in ("timeout", "output_limit"):
                emit(
                    "execution.timed_out" if status == "timeout" else "execution.resource_limited",
                    {"container_id": container_id, "status": status,
                     "resource": resource_reason if status == "output_limit" else "time"},
                )
            if status == "succeeded" and exit_code:
                status = "failed"
            stdout, stderr = map(bytes, outputs)
            helper_ref = None
            if request.arguments.get("helper_manifest") and stdout.startswith(
                b"LOCAL_AGENT_HELPER:"
            ):
                header = stdout.split(b"\n", 1)[0]
                helper = json.loads(header[len(b"LOCAL_AGENT_HELPER:") :])
                helper["image"] = self.image
                helper_ref = self.store.blobs.put_json(helper)
            combined = stdout + stderr
            side_effect_status = "none"
            if request.tool in {"run_command", "execute_tool"}:
                side_effect_status = "unknown"
            elif request.tool in {"write_file", "patch_file", "register_tool", "render_pdf_region"}:
                # A failed mutation can still leave directories, files or registry records behind.
                side_effect_status = "applied" if status == "succeeded" else "unknown"
            result = ExecutionResult(
                execution_id=request.execution_id,
                run_id=run_id, workspace_id=request.workspace_id, tool_call_id=request.call_id,
                container_id=container_id, execution_mode=mode,
                command=tuple(request.arguments.get("argv", ())) or None,
                started_at=started_at, completed_at=datetime.now(UTC).isoformat(),
                duration_ms=(time.monotonic() - started) * 1000,
                error=None if status == "succeeded" else "execution " + status,
                status=status,
                exit_code=exit_code,
                output_ref=self.store.blobs.put(combined),
                stdout_ref=self.store.blobs.put(stdout),
                stderr_ref=self.store.blobs.put(stderr),
                attestation_ref=attestation_ref,
                captured_bytes=len(combined),
                helper_ref=helper_ref,
                preview=combined[:PREVIEW_CAP].decode(errors="replace"),
                duration_seconds=time.monotonic() - started,
                truncated=len(combined) > PREVIEW_CAP or status == "output_limit",
                side_effect_status=side_effect_status,
            )
            # Recovery can find published result even if SQLite outcome commit is lost.
            directory = self.store.control / "attempts"
            from local_agent.storage.blobs import fsync_directory, private_directory

            private_directory(directory)
            marker = directory / (request.execution_id + ".json")
            result_ref = self.store.blobs.put_json(result)
            fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(canonical({"result_ref": result_ref}))
                stream.flush()
                os.fsync(stream.fileno())
            fsync_directory(directory)
            if self.fault_hook:
                self.fault_hook("after_result_publication")
            return result
        except BaseException:
            if created:
                await docker("kill", name, check=False)
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
        finally:
            self.active.discard(container_id)
            # Ended container remains until result is durably committed by the runtime.

    def mapping(self, execution_id):
        path = self.store.control / "attempts" / (execution_id + ".container.json")
        return json.loads(path.read_text()) if path.exists() else None

    async def release(self, execution_id: str) -> None:
        row = self.store.db.execute(
            "SELECT state,request_ref FROM execution_attempts WHERE id=?", (execution_id,)
        ).fetchone()
        if row is None or row["state"] not in {"finished", "reconciled"}:
            return
        request = ExecutionRequest.model_validate_json(self.store.blobs.read(row["request_ref"]))
        run_id, call_id = self.attempt_context(execution_id)
        emit = self.emitter(run_id, call_id, execution_id, request.workspace_id)
        mapping = self.mapping(execution_id)
        if mapping and mapping["execution_mode"] == "persistent":
            return
        name = mapping["container_id"] if mapping else "local-agent-" + execution_id
        manager = self.make_manager(emit)
        info = await manager.inspect(name)
        if info is None:
            return
        labels = info["Config"].get("Labels") or {}
        if any(labels.get(key) != value for key, value in {
            "local-agent.execution": execution_id,
            "local-agent.workspace": request.workspace_id,
            "local-agent.run": run_id,
        }.items()) or (mapping and (
            info["Id"] != mapping["container_id"]
            or labels.get("local-agent.owner") != manager.owner
            or labels.get("local-agent.mode") != "ephemeral"
        )):
            raise PermissionError("ephemeral cleanup ownership mismatch")
        try:
            emit("container.stopped", {"container_id": info["Id"], "state": "STOPPED"})
            await docker("rm", info["Id"])
            emit("container.removed", {"container_id": info["Id"], "state": "REMOVED"})
        except BaseException:
            emit("container.cleanup_failed", {"container_id": info["Id"], "error": "removal failed"})
            raise

    async def emergency_cleanup(self, run_id):
        # Audit may be broken: only best-effort safety, never manufacture a committed result.
        rows = self.store.db.execute(
            "SELECT e.id FROM execution_attempts e JOIN tool_calls t ON t.id=e.call_id "
            "JOIN model_requests m ON m.id=t.request_id WHERE m.run_id=? AND e.state='started'",
            (run_id,),
        ).fetchall()
        for row in rows:
            try:
                mapping = self.mapping(row["id"])
                if not mapping:
                    continue
                info = await self.inspect(mapping["container_id"])
                labels = info["Config"].get("Labels") or {}
                manager = self.make_manager(lambda *_: None)
                if (
                    info["Id"] == mapping["container_id"]
                    and labels.get("local-agent.owner") == manager.owner
                    and labels.get("local-agent.workspace") == mapping["workspace_id"]
                    and info["State"]["Running"]
                ):
                    if mapping["execution_mode"] == "persistent":
                        await manager.stop(
                            mapping["workspace_id"], expected_container_id=info["Id"],
                            expected_execution_id=row["id"],
                        )
                    else:
                        await docker("kill", info["Id"])
            except (RuntimeError, OSError, TimeoutError):
                pass

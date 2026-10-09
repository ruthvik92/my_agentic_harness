"""Docker-only executor. Controller subprocesses are fixed Docker CLI operations."""

import asyncio
import json
import os
import re
import time
from datetime import UTC, datetime

from local_agent.contracts import ExecutionRequest, ExecutionResult
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
    def __init__(self, store, workspaces, image, *, output_cap=OUTPUT_CAP):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise ValueError("sandbox image must be pinned by immutable local image ID")
        self.store, self.workspaces, self.image = store, workspaces, image
        if not 1 <= output_cap <= OUTPUT_CAP:
            raise ValueError("invalid output capture cap")
        self.output_cap = output_cap
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
            "memory": host["Memory"] == 4096 * 1024 * 1024,
            "swap": host["MemorySwap"] == host["Memory"],
            "cpu": host["NanoCpus"] == 4000000000,
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

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
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
        name = "local-agent-" + request.execution_id
        created = False
        proc = None
        started = time.monotonic()
        status = "succeeded"
        outputs = [bytearray(), bytearray()]
        total = 0
        exceeded = asyncio.Event()
        timeout = min(300, request.arguments.get("timeout_seconds", 60))
        if request.deadline_utc:
            timeout = min(
                timeout,
                (datetime.fromisoformat(request.deadline_utc) - datetime.now(UTC)).total_seconds(),
            )
            if timeout <= 0:
                raise RuntimeError("execution deadline expired before dispatch")
        try:
            await docker(
                "create",
                "--name",
                name,
                "--label",
                "local-agent.execution=" + request.execution_id,
                "--label",
                "local-agent.workspace=" + request.workspace_id,
                "--label",
                "local-agent.run=" + run_id,
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--read-only",
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--cpus",
                "4",
                "--memory",
                "4096m",
                "--memory-swap",
                "4096m",
                "--pids-limit",
                "128",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,size=128m,mode=1777",
                "--init",
                "--mount",
                f"type=bind,src={workspace},dst=/workspace",
                "--env",
                "HOME=/tmp",
                "--env",
                "LANG=C.UTF-8",
                "--env",
                "PYTHONDONTWRITEBYTECODE=1",
                "--log-driver",
                "local",
                "--log-opt",
                "max-size=12m",
                "--log-opt",
                "max-file=1",
                "--log-opt",
                "compress=false",
                "-i",
                self.image,
            )
            created = True
            info = await self.inspect(name)
            attestation_ref = self.store.blobs.put_json(self.attest(info, workspace))
            with self.store.transaction():
                self.store.db.execute(
                    "UPDATE execution_attempts SET container_id=? WHERE id=?",
                    (info["Id"], request.execution_id),
                )
            self.active.add(name)
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "start",
                "-ai",
                name,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def drain(stream, index):
                nonlocal total
                while chunk := await stream.read(65536):
                    room = max(0, self.output_cap - total)
                    outputs[index].extend(chunk[:room])
                    total += min(len(chunk), room)
                    if len(chunk) > room:
                        exceeded.set()

            async def disk_monitor():
                nonlocal status
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
                        exceeded.set()
                        return
                    if size > 1024 * 1024 * 1024:
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
                proc.stdin.write(canonical(request))
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
                    await docker("kill", name, check=False)
                elif waiter not in done:
                    status = "timeout"
                    await docker("kill", name, check=False)
                await asyncio.wait_for(waiter, 15)
                await asyncio.gather(*readers)
            finally:
                for task in [monitor, flood, waiter, *readers]:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(monitor, flood, waiter, *readers, return_exceptions=True)
            info = await self.inspect(name)
            exit_code = info["State"]["ExitCode"]
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
            result = ExecutionResult(
                execution_id=request.execution_id,
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
                side_effect_status="unknown"
                if request.tool == "run_command"
                else (
                    "applied"
                    if request.tool in {"write_file", "patch_file"} and status == "succeeded"
                    else "none"
                ),
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
            self.active.discard(name)
            # Ended container remains until result is durably committed by the runtime.

    async def release(self, execution_id):
        row = self.store.db.execute(
            "SELECT state FROM execution_attempts WHERE id=?", (execution_id,)
        ).fetchone()
        if row is not None and row[0] in {"finished", "reconciled"}:
            await docker("rm", "local-agent-" + execution_id, check=False)

    async def emergency_cleanup(self, run_id):
        try:
            ids = (
                (await docker("ps", "-q", "--filter", "label=local-agent.run=" + run_id))
                .decode()
                .split()
            )
            for container_id in ids:
                await docker("kill", container_id, check=False)
        except (RuntimeError, OSError, TimeoutError):
            pass  # Never manufacture a committed cleanup outcome when audit is broken.

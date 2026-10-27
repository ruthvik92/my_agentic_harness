"""Host maintenance uses the same Docker manager and durable audit store."""

import argparse
import asyncio
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from local_agent.contracts import ExecutionSettings, RunManifest, new_id
from local_agent.executor.docker import DockerExecutor
from local_agent.executor.lifecycle import publish
from local_agent.observability.spans import Spans
from local_agent.storage.blobs import digest, private_directory
from local_agent.storage.database import Store
from local_agent.workspace.manager import Workspaces

_children = {}


def cleanup_attestor(store, workspaces):
    """Validate security for removal only, including sessions from older profiles."""
    def attest(info, workspace):
        host = info["HostConfig"]
        memory = host["Memory"] // (1024 * 1024)
        cpu = host["NanoCpus"] // 1000000000
        settings = ExecutionSettings(container_memory_limit=memory, container_cpu_limit=cpu)
        # Exact matching below rejects fractional limits and all unsafe host settings.
        return DockerExecutor(store, workspaces, info["Image"], settings=settings).attest(
            info, workspace
        )
    return attest


async def sweep(data_root, image, settings, *, workspace_id=None):
    store, spans = Store(Path(data_root)), Spans()
    try:
        with spans.boundary("containers.maintenance"):
            executor = DockerExecutor(store, Workspaces(store.root), image, settings=settings)
            manager = executor.make_manager(lambda *_: None)
            if workspace_id is None and not await manager.owned():
                return {"maintenance_run_id": None, "removed": [], "remaining": 0}
            run_id = None

            def emit(kind, data):
                nonlocal run_id
                if run_id is None:
                    run_id = new_id("run")
                    config_ref = store.blobs.put_json({
                        "purpose": "container-maintenance", "image": image,
                        "execution": settings.model_dump(mode="json"),
                    })
                    store.create_run(RunManifest(
                        run_id=run_id, thread_id=new_id("thread"), workspace_id=new_id("ws"),
                        config_ref=config_ref, config_hash=digest(store.blobs.read(config_ref)),
                        model_identity="host-maintenance", sandbox_image_digest=image,
                        mode="live", package_versions={},
                    ))
                    store.transition(run_id, "running")
                store.append(run_id, kind, "maintenance", data)

            manager.emit = emit
            manager.attest = cleanup_attestor(store, manager.workspaces)
            try:
                if workspace_id:
                    record = manager.load(workspace_id)
                    stopped = await manager.stop(workspace_id)
                    removed = [record["container_id"]] if stopped and record else []
                else:
                    removed = await manager.cleanup_idle()
            except BaseException:
                emit("container.cleanup_failed", {
                    "error": "maintenance sweep failed", "workspace_id": workspace_id,
                })
                store.transition(run_id, "failed", reason="container cleanup failed")
                store.export_jsonl(run_id)
                raise
            if run_id:
                store.append(run_id, "completion.proposed", "maintenance", {
                    "purpose": "container-maintenance", "removed": removed,
                })
                store.transition(run_id, "completed_unverified", reason="host maintenance completed")
                store.export_jsonl(run_id)
            return {"maintenance_run_id": run_id, "removed": removed, "remaining": len(await manager.owned())}
    finally:
        store.close()
        spans.shutdown()


def ensure_reaper(data_root, image, settings):
    root = Path(data_root).resolve()
    directory = root / "control" / "containers"
    private_directory(directory)
    publish(directory / "reaper.json", {
        "image": image, "settings": settings.model_dump(mode="json"),
    })
    fd = os.open(directory / "reaper.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
    finally:
        os.close(fd)
    previous = _children.get(str(root))
    if previous is not None and previous.poll() is None:
        return
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    _children[str(root)] = subprocess.Popen(
        [sys.executable, "-m", "local_agent.executor.maintenance", "--data-root", str(root)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True, start_new_session=True, env=environment,
        cwd=Path(__file__).resolve().parents[3],
    )


async def reap(root):
    directory = root / "control" / "containers"
    private_directory(directory)
    fd = os.open(directory / "reaper.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        started = time.monotonic()
        while True:
            config = json.loads((directory / "reaper.json").read_text())
            settings = ExecutionSettings.model_validate(config["settings"])
            try:
                result = await sweep(root, config["image"], settings)
                if result["remaining"] == 0 and time.monotonic() - started >= 10:
                    return
            except (OSError, RuntimeError, ValueError):
                # Sweep persists failure when storage is available. Retry transient daemon failures.
                pass
            await asyncio.sleep(1)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(reap(args.data_root.resolve()))


if __name__ == "__main__":
    main()

import json
import os
import shutil
from pathlib import Path

from local_agent.executor.docker import docker
from local_agent.storage.blobs import digest


def sandbox_config(path=None):
    path = path or Path(__file__).resolve().parents[2] / "config" / "sandbox.json"
    config = json.loads(path.read_text())
    if config.get("schema_version") != 1:
        raise ValueError("unsupported sandbox config")
    worker = Path(__file__).parent / "executor" / "worker.py"
    if config["worker_hash"] != digest(worker.read_bytes()):
        raise ValueError("trusted worker changed; rebuild the pinned sandbox image")
    verifier = Path(__file__).resolve().parents[2] / "sandbox" / "verify.py"
    if config.get("verifier_hash") != digest(verifier.read_bytes()):
        raise ValueError("protected verifier changed; rebuild the pinned sandbox image")
    helper = Path(__file__).resolve().parents[2] / "sandbox/pdf_extract.py"
    if config.get("pdf_helper_hash") != digest(helper.read_bytes()):
        raise ValueError("PDF renderer changed; rebuild the pinned sandbox image")
    toolkit = {
        p.name: digest(p.read_bytes())
        for p in sorted((Path(__file__).parent / "executor" / "toolkit").glob("*.py"))
    }
    if config.get("toolkit_hashes", {}) != toolkit:
        raise ValueError("trusted toolkit changed; rebuild the pinned sandbox image")
    return config


async def doctor(store, agent_path=None):
    config = sandbox_config()
    image = json.loads(await docker("image", "inspect", config["image"]))[0]
    info = json.loads(await docker("info", "--format", "{{json .}}"))
    checks = {
        "nonroot_user": os.getuid() != 0,
        "memory_limits": info["MemoryLimit"],
        "swap_limits": info["SwapLimit"],
        "cpu_limits": info["CpuCfsQuota"],
        "pid_limits": info["PidsLimit"],
        "cgroup_v2": info["CgroupVersion"] == "2",
        "seccomp": any("seccomp" in value for value in info["SecurityOptions"]),
        "audit": store.healthy,
        "disk": shutil.disk_usage(store.root).free > 1024**3,
        "database_wal": store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal",
        "database_full_sync": store.db.execute("PRAGMA synchronous").fetchone()[0] == 2,
        "database_foreign_keys": store.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1,
        "protected_permissions": all(
            p.stat().st_uid == os.getuid() and p.stat().st_mode & 0o077 == 0
            for p in (store.root, store.control, store.blobs.root, store.control / "agent.db")
        ),
        "image_nonroot": image["Config"]["User"] == f"{os.getuid()}:{os.getgid()}",
    }
    from local_agent.config import load_config
    from local_agent.contracts import new_id
    from local_agent.models.capabilities import ensure_capabilities
    from local_agent.models.scripted import ScriptedProvider
    from local_agent.observability.audit import audit
    from local_agent.runtime.agent import Agent
    from local_agent.storage.blobs import private_directory

    agent_config = load_config(
        agent_path or Path(__file__).resolve().parents[2] / "config/coder.yaml"
    )
    capability = await ensure_capabilities(store, agent_config, config)
    checks["model_capability"] = capability["passed"]
    source = store.control / "probe_sources" / new_id("doctor")
    private_directory(source)
    probe = await Agent(
        store,
        agent_config,
        config,
        provider=ScriptedProvider(
            responses=(
                {"text": "Kernel limits checked", "tool_calls": [], "finish_status": "stop"},
            )
        ),
    ).run(source, "Attest the configured sandbox")
    checks["effective_kernel_sandbox"] = probe["status"] == "completed_unverified"
    checks["telemetry_and_trace"] = audit(store, probe["run_id"])["ok"]
    return {
        "ok": all(checks.values()),
        "capability": capability,
        "sandbox_probe_run_id": probe["run_id"],
        "checks": checks,
        "image": config["image"],
        "workspace_disk_guarantee": "soft_monitor",
        "docker_version": info["ServerVersion"],
    }

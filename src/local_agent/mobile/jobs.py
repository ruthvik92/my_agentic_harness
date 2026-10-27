"""Reviewed replacement for the local model's job persistence and worker draft."""

import json
import os
import queue
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from local_agent.circuits.agent import read_evidence
from local_agent.storage.blobs import canonical, fsync_directory, private_directory
from local_agent.storage.locks import run_lock

JOB_ID = re.compile(r"[0-9a-f]{32}")


def publish(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fsync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Jobs:
    def __init__(self, root, agent_path, config, runner=None, on_result=None, allowed_roots=None):
        self.root, self.agent_path, self.config = Path(root), Path(agent_path).absolute(), config
        self.on_result = on_result
        self.allowed_roots = tuple(Path(root).resolve() for root in (allowed_roots if allowed_roots is not None else [Path.cwd()]))
        private_directory(self.root)
        private_directory(self.root / "phone")
        self.directory = self.root / "phone" / "jobs"
        private_directory(self.directory)
        self.lease = run_lock(self.root / "phone")
        self.lease.__enter__()
        try:
            for path in self.directory.iterdir():
                if JOB_ID.fullmatch(path.name):
                    job = self.get(path.name)
                    if job and job["status"] in {"queued", "running"}:
                        job.update(
                            status="interrupted", error="Server stopped; request was not replayed."
                        )
                        publish(path / "status.json", job)
            self.pending = queue.Queue(maxsize=3)
            self.lock = threading.Lock()
            self.stopping = False
            self.runner = runner or self.execute
            self.worker = threading.Thread(target=self.work, name="browser-jobs", daemon=False)
            self.worker.start()
        except BaseException:
            self.lease.__exit__(*sys.exc_info())
            raise

    def get(self, job_id):
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            return None
        try:
            return json.loads(read_evidence(self.directory, job_id + "/status.json", 1024 * 1024))
        except FileNotFoundError:
            return None

    def recent(self, limit=20):
        ids = [path.name for path in self.directory.iterdir() if JOB_ID.fullmatch(path.name)]
        jobs = [job for job_id in ids if (job := self.get(job_id))]
        return sorted(jobs, key=lambda j: j["created"], reverse=True)[:limit]

    def submit(self, request, *, config=None, metadata=None):
        with self.lock:
            if self.stopping or self.pending.full():
                raise RuntimeError("Queue is full; wait for an active question to finish.")
            if sum(bool(JOB_ID.fullmatch(p.name)) for p in self.directory.iterdir()) >= 1000:
                raise RuntimeError("Browser job storage limit reached (1000 jobs).")
            job_id = secrets.token_hex(16)
            directory = self.directory / job_id
            private_directory(directory)
            publish(directory / "request.json", request)
            chosen = config or self.config
            publish(directory / "config.json", chosen.model_dump(mode="json"))
            job = {
                "job_id": job_id,
                "status": "queued",
                "created": time.time(),
                "model": chosen.model,
                "provider": chosen.provider,
                "run_id": None,
                "answer": None,
                "error": None,
            }
            job.update(metadata or {})
            publish(directory / "status.json", job)
            self.pending.put_nowait(job_id)
            return job_id

    def execute(self, request_path):
        config_path = request_path.with_name("config.json")
        chosen_path = config_path if config_path.exists() else self.agent_path
        from local_agent.config import load_config

        chosen = load_config(chosen_path)
        request = json.loads(read_evidence(request_path.parent, request_path.name, 6 * 1024 * 1024))
        command = "browser-run" if isinstance(request, dict) and "mode" in request else "screenshot"
        argv = [
            sys.executable,
            "-m",
            "local_agent.cli",
            "--data-root",
            str(self.root),
            command,
            "--agent",
            str(chosen_path),
            "--request",
            str(request_path),
        ]
        if command == "browser-run":
            for root in self.allowed_roots:
                argv.extend(["--allow-root", str(root)])
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=chosen.limits.run_timeout_seconds + 120,
            check=False,
        )
        try:
            output = json.loads(result.stdout)
        except ValueError as exc:
            raise RuntimeError(
                "Browser controller returned no valid result: " + result.stderr[-2000:]
            ) from exc
        if not isinstance(output, dict):
            raise RuntimeError("Browser controller returned an invalid result")
        return output

    def work(self):
        while True:
            job_id = self.pending.get()
            try:
                if job_id is None:
                    return
                job = self.get(job_id)
                with self.lock:
                    stop = self.stopping
                    job["status"] = "interrupted" if stop else "running"
                    if stop:
                        job["error"] = "Server stopped before request started."
                    publish(self.directory / job_id / "status.json", job)
                if stop:
                    continue
                try:
                    result = self.runner(self.directory / job_id / "request.json")
                    job.update(
                        run_id=result.get("run_id"),
                        answer=result.get("answer"),
                        error=result.get("error"),
                    )
                    for field in (
                        "workspace",
                        "workspace_id",
                        "diff_ref",
                        "exported_case",
                        "circuit",
                        "audit",
                        "capability_probe",
                        "git_workspace",
                        "working_directory",
                        "task_mode",
                    ):
                        if field in result:
                            job[field] = result[field]
                    audit_ok = result.get("audit", {"ok": True}).get("ok")
                    ok = (
                        result.get("status") == "completed_unverified"
                        and bool(job["answer"])
                        and audit_ok
                    )
                    job["status"] = "completed" if ok else "failed"
                    if not ok and not job["error"]:
                        job["error"] = (
                            "Run audit did not pass"
                            if not audit_ok
                            else "Run ended with status " + str(result.get("status"))
                        )
                except Exception as exc:
                    job.update(status="failed", error=str(exc))
                if self.on_result:
                    try:
                        self.on_result(job)
                    except Exception as exc:
                        job.update(status="failed", error="Thread persistence failed: " + str(exc))
                publish(self.directory / job_id / "status.json", job)
            finally:
                self.pending.task_done()

    def close(self):
        with self.lock:
            if self.stopping:
                return
            self.stopping = True
        # Queued requests are marked interrupted; the active bounded controller finishes.
        self.pending.put(None)
        self.worker.join()
        self.lease.__exit__(None, None, None)

"""Shared project test contracts, installed src packages, and offline execution."""

import asyncio
import json
from pathlib import Path

import pytest

from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.runtime.agent import Agent
from local_agent.storage.database import Store
from local_agent.testing.checks import run_checks
from local_agent.testing.environment import prepare
from local_agent.testing.plans import resolve


def test_contract_scope_paths_and_auto_discovery(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_x.py").write_text("def test_x(): pass\n")
    automatic = resolve(project)
    assert automatic["commands"][0]["argv"] == ["python", "-m", "pytest", "-q"]
    child = project / "isolated"
    child.mkdir()
    (child / ".local-agent-tests.json").write_text(
        json.dumps(
            {
                "version": 1,
                "install_project": False,
                "commands": [
                    {"argv": ["python", "-m", "pytest", "--confcutdir=.", "-q"], "cwd": "."}
                ],
            }
        )
    )
    plan = resolve(project, "isolated")
    assert plan["commands"][0]["cwd"] == "isolated"
    assert plan["origin"] == "isolated/.local-agent-tests.json"
    assert plan["network"] == "none"
    assert (
        resolve(project, "isolated", discover_contract=False)["origin"]
        == "automatic Python detection"
    )
    with pytest.raises(ValueError):
        resolve(project, "../host")
    (project / ".local-agent-tests.json").write_text(
        json.dumps({"version": 1, "commands": [{"argv": ["python"], "cwd": "../host"}]})
    )
    with pytest.raises(ValueError):
        resolve(project)


def test_dependency_preparation_is_cacheable_dependency_only_build(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname="sample"\nversion="0.1.0"\n[build-system]\nrequires=["setuptools>=77"]\nbuild-backend="setuptools.build_meta"\n'
    )
    (project / "secret-code.py").write_text(
        'raise RuntimeError("must never execute in preparation")'
    )
    calls = []
    image = "sha256:" + "b" * 64

    def command(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["docker", "build"]:
            path = Path(argv[-1])
            assert sorted(p.name for p in path.iterdir()) == ["Dockerfile", "requirements.txt"]
            assert "secret-code" not in (path / "Dockerfile").read_text()
            return image + "\n"
        if argv[0] == "docker":
            return "setuptools==80.9.0\n"
        raise AssertionError(argv)

    monkeypatch.setattr("local_agent.testing.environment._run", command)
    plan = resolve(project)
    base = {"image": "sha256:" + "a" * 64}
    first = prepare(tmp_path / "data", project, plan, base)
    second = prepare(tmp_path / "data", project, plan, base)
    assert first["image"] == second["image"] == image
    assert len([c for c in calls if c[:2] == ["docker", "build"]]) == 1
    assert base["image"] == "sha256:" + "a" * 64


@pytest.mark.parametrize("mode", ["ephemeral", "persistent"])
def test_shared_runner_installs_src_package_and_stays_offline(tmp_path, request, mode):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    project = tmp_path / "project"
    (project / "src/sample_app").mkdir(parents=True)
    (project / "src/sample_app/__init__.py").write_text("VALUE = 42\n")
    (project / "pyproject.toml").write_text(
        '[project]\nname="sample-app"\nversion="0.1.0"\n[build-system]\nrequires=["setuptools>=77"]\nbuild-backend="setuptools.build_meta"\n[tool.setuptools.packages.find]\nwhere=["src"]\n'
    )
    (project / "test_app.py").write_text(
        'import importlib.metadata,socket\nfrom sample_app import VALUE\ndef test_app():\n assert VALUE==42\n assert importlib.metadata.version("sample-app")=="0.1.0"\n try:\n  socket.create_connection(("1.1.1.1",443),timeout=.2)\n except OSError:\n  pass\n else:\n  raise AssertionError("network access must be blocked")\n'
    )
    config = load_config(Path("config/coder.yaml")).model_copy(update={"project_tests": False})
    config = config.model_copy(
        update={"execution": config.execution.model_copy(update={"execution_mode_default": mode})}
    )
    store = Store(tmp_path / "data")
    try:
        report, result, prepared = asyncio.run(
            run_checks(
                store, config, project, resolve(project), {**sandbox_config(), "image": image}
            )
        )
        assert report["status"] == "passed", report
        assert report["commands"][0]["counts"]["collected"] == 1
        assert report["commands"][0]["exit_code"] == 0
        assert report["audit"]["ok"]
        assert prepared["image"] != image
        assert not list(project.glob("**/*.egg-info"))
        assert not (project / ".venv").exists()
        for event in store.events(result["run_id"]):
            if event.event_type == "execution.finished":
                outcome = store.blobs.json(event.data["result_ref"])
                proof = store.blobs.json(outcome["attestation_ref"])
                assert proof["checks"]["network"]
    finally:
        try:
            if mode == "persistent":
                from local_agent.executor.maintenance import sweep

                for path in (store.control / "containers").glob("ws_*.json"):
                    record = json.loads(path.read_text())
                    if record["state"] != "REMOVED":
                        asyncio.run(sweep(store.root, record["image"], config.execution,
                                          workspace_id=record["workspace_id"]))
        finally:
            store.close()


@pytest.mark.parametrize("case", ["no_tests", "collection_error", "test_failed"])
def test_runner_distinguishes_failure_types(tmp_path, request, case):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    project = tmp_path / "project"
    project.mkdir()
    content = {
        "no_tests": "VALUE=1\n",
        "collection_error": "import nonexistent_project_dependency\n",
        "test_failed": "def test_bad():\n assert False\n",
    }[case]
    (project / "test_sample.py").write_text(content)
    config = load_config(Path("config/coder.yaml")).model_copy(update={"project_tests": False})
    store = Store(tmp_path / "data")
    try:
        report, _, _ = asyncio.run(
            run_checks(
                store, config, project, resolve(project), {**sandbox_config(), "image": image}
            )
        )
        assert report["status"] == case, report
    finally:
        store.close()


def test_coding_completion_runs_checks_and_returns_repair_evidence(tmp_path, request):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_feature.py").write_text("def test_ok():\n assert True\n")
    config = load_config(Path("config/coder.yaml"))
    scripted = ScriptedProvider(
        [{"text": "Candidate ready", "tool_calls": [], "finish_status": "stop"}]
    )
    store = Store(tmp_path / "data")
    try:
        result = asyncio.run(
            Agent(store, config, {**sandbox_config(), "image": image}, provider=scripted).run(
                project, "Inspect and test the project"
            )
        )
        assert result["project_tests"]["status"] == "passed", result
        assert result["project_tests"]["run_id"] != result["run_id"]
        assert audit(store, result["run_id"])["ok"]
        assert any(e.event_type == "project.tests" for e in store.events(result["run_id"]))
    finally:
        store.close()


def test_tdd_helper_records_red_then_independent_green_on_pending_git_edits(tmp_path, request):
    from local_agent.storage.blobs import digest
    from local_agent.workspace.git import git

    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    project = tmp_path / "project"
    project.mkdir()
    original = b"VALUE = 1\n"
    (project / "feature.py").write_bytes(original)
    git("-C", project, "init", "-b", "main")
    git("-C", project, "add", ".")
    git("-C", project, "commit", "-m", "Initial")
    script = ScriptedProvider(
        [
            {
                "text": "Write the regression test first",
                "tool_calls": [
                    {
                        "name": "write_file",
                        "arguments": {
                            "path": "project/test_feature.py",
                            "content": "from feature import VALUE\ndef test_value():\n assert VALUE == 2\n",
                        },
                    },
                    {
                        "name": "run_command",
                        "arguments": {"argv": ["python", "/workspace/tools/test_project.py"]},
                    },
                ],
                "finish_status": "tool_calls",
            },
            {
                "text": "Repair after the red test",
                "tool_calls": [
                    {
                        "name": "write_file",
                        "arguments": {
                            "path": "project/feature.py",
                            "content": "VALUE = 2\n",
                            "create_only": False,
                            "expected_hash": digest(original),
                        },
                    }
                ],
                "finish_status": "tool_calls",
            },
            {
                "text": "Candidate ready for independent checks",
                "tool_calls": [],
                "finish_status": "stop",
            },
        ]
    )
    store = Store(tmp_path / "data")
    progress = tmp_path / "progress.json"
    try:
        result = asyncio.run(
            Agent(
                store,
                load_config(Path("config/coder.yaml")),
                {**sandbox_config(), "image": image},
                provider=script,
                progress_path=progress,
            ).run(project, "Add a regression test, reproduce failure, then fix VALUE.")
        )
        assert result["project_tests"]["status"] == "passed", result
        assert result["project_tests"]["commands"][0]["counts"]["collected"] == 1
        red = []
        for event in store.events(result["run_id"]):
            if event.event_type == "execution.finished":
                outcome = store.blobs.json(event.data["result_ref"])
                if outcome.get("command") == ["python", "/workspace/tools/test_project.py"]:
                    red.append(json.loads(store.blobs.read(outcome["stdout_ref"])))
        assert red[0]["status"] == "test_failed"
        assert (project / "feature.py").read_bytes() == original
        assert audit(store, result["run_id"])["ok"]
        assert json.loads(progress.read_text())["run_id"] == result["run_id"]
    finally:
        store.close()


def test_live_usage_reads_progress_without_mutating_frozen_job(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from local_agent.mobile.web import BrowserServer

    jid = "a" * 32
    path = tmp_path / jid
    path.mkdir()
    (path / "progress.json").write_text(
        json.dumps({"run_id": "run_active", "phase": "model.responded"})
    )
    original = {"job_id": jid, "status": "running", "run_id": None, "kind": "answer"}
    server = object.__new__(BrowserServer)
    server.root = tmp_path
    server.jobs = SimpleNamespace(directory=tmp_path, recent=lambda **kwargs: [original])
    seen = []

    def usage(root, job, baseline):
        seen.append(job["run_id"])
        return {"rows": [{"request_id": "request1", "input_tokens": 13, "output_tokens": 7}]}

    monkeypatch.setattr("local_agent.mobile.web.job_usage", usage)
    live = server.usage_jobs()
    assert seen == ["run_active"]
    assert live[0]["token_usage"]["rows"][0]["output_tokens"] == 7
    assert original["run_id"] is None


def test_dependency_network_never_blocks_missing_cache(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname="sample"\nversion="1"\n[build-system]\nrequires=["setuptools>=77"]\n'
    )
    (project / ".local-agent-tests.json").write_text(
        json.dumps(
            {
                "version": 1,
                "dependency_network": "never",
                "commands": [{"argv": ["python", "-m", "pytest", "-q"], "cwd": "."}],
            }
        )
    )
    with pytest.raises(ValueError, match="dependency_network is never"):
        prepare(tmp_path / "data", project, resolve(project), {"image": "sha256:" + "a" * 64})


def test_model_cannot_weaken_frozen_contract_to_hide_failure(tmp_path, request):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    project = tmp_path / "project"
    project.mkdir()
    original = json.dumps(
        {"version": 1, "commands": [{"argv": ["python", "-m", "pytest", "-q"], "cwd": "."}]}
    )
    (project / ".local-agent-tests.json").write_text(original)
    (project / "test_original.py").write_text("def test_original():\n assert False\n")
    from local_agent.storage.blobs import digest

    weakened = json.dumps(
        {"version": 1, "commands": [{"argv": ["python", "-c", "pass"], "cwd": "."}]}
    )
    provider = ScriptedProvider(
        [
            {
                "text": "Change test config",
                "tool_calls": [
                    {
                        "name": "write_file",
                        "arguments": {
                            "path": "project/.local-agent-tests.json",
                            "content": weakened,
                            "create_only": False,
                            "expected_hash": digest(original.encode()),
                        },
                    }
                ],
                "finish_status": "tool_calls",
            },
            *[
                {"text": "Candidate ready", "tool_calls": [], "finish_status": "stop"}
                for _ in range(3)
            ],
        ]
    )
    store = Store(tmp_path / "data")
    try:
        result = asyncio.run(
            Agent(
                store,
                load_config(Path("config/coder.yaml")),
                {**sandbox_config(), "image": image},
                provider=provider,
            ).run(project, "Improve the project without weakening tests")
        )
        assert result["project_tests"]["status"] == "test_failed", result
        assert result["project_tests"]["plan"]["commands"][0]["argv"] == [
            "python",
            "-m",
            "pytest",
            "-q",
        ]
        assert sum(e.event_type == "project.tests" for e in store.events(result["run_id"])) == 3
    finally:
        store.close()


def test_multiple_store_connections_preserve_wal_with_external_maintenance(tmp_path):
    import subprocess
    import sys

    from local_agent.runtime.loop import simulate

    root = tmp_path / "data"
    first = Store(root)
    try:
        run_id = asyncio.run(simulate(first))["run_id"]
        second = Store(root)
        second.close()
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; from local_agent.storage.database import Store; import sys; s=Store(Path(sys.argv[1])); s.close()",
                str(root),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert child.returncode == 0, child.stderr
        readonly = Store(root, readonly=True)
        try:
            assert readonly.run(run_id)["status"] == "completed_unverified"
            assert audit(first, run_id)["ok"]
        finally:
            readonly.close()
    finally:
        first.close()

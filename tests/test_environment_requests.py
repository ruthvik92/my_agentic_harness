"""Environment requests use the real dispatch/audit path and mocked Docker commands."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from local_agent.config import instruction_text, load_config
from local_agent.contracts import EnvironmentSettings, ExecutionSettings, RunManifest, new_id
from local_agent.environments import service
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.policy.engine import LEGACY_OFFLINE_HASH, OFFLINE_HASH
from local_agent.runtime.agent import Agent
from local_agent.runtime.recovery import NeedsReconciliation, reconcile, restore
from local_agent.storage.blobs import canonical, digest
from local_agent.storage.bundles import roots
from local_agent.storage.database import Store
from local_agent.tools.registry import normalize

BASE = "sha256:" + "a" * 64
PREPARED = "sha256:" + "b" * 64


@pytest.fixture
def agent(tmp_path, request):
    store = Store(tmp_path / "data")
    source = tmp_path / "project"
    source.mkdir()
    (source / "keep.txt").write_text("preserve this")
    profile = getattr(request, "param", 128)
    legacy = isinstance(profile, tuple)
    pids = profile[0] if legacy else profile
    config = load_config(Path("config/coder.yaml")).model_copy(update={
        "project_tests": False, "tools": ("environment_inventory", "prepare_environment", "run_command"),
        "environment": EnvironmentSettings(allow_network=True),
        "execution": ExecutionSettings(container_pids_limit=pids),
    })
    a = Agent(store, config, {"image": BASE}, provider=ScriptedProvider())
    a.policy_hash = LEGACY_OFFLINE_HASH if legacy else OFFLINE_HASH
    a.workspace_id, a.path = a.workspaces.create(source)
    a.baseline = source
    frozen = {"agent": config.model_dump(mode="json"), "sandbox": a.sandbox,
              "base_sandbox": a.sandbox, "model_metadata": {"scripted": True},
              "task": "test environment", "instructions": a.instructions, "verify_fixture": False,
              "policy_hash": a.policy_hash, "baseline_id": "unused"}
    ref = store.blobs.put_json(frozen)
    with a.spans.boundary("test.environment"):
        store.create_run(RunManifest(run_id=a.run_id, thread_id=new_id("thread"),
            workspace_id=a.workspace_id, config_ref=ref, config_hash=digest(store.blobs.read(ref)),
            model_identity="scripted", package_versions={}, mode="live"))
        a.last = store.transition(a.run_id, "running")
        a.created = True
        yield a
    a.spans.shutdown()
    store.close()


async def call(agent, name, arguments):
    _, ref = agent.context.build(agent.fixed_messages("test environment"), [])
    request = agent.request(ref)
    _, calls, proposals = agent.response(request, {
        "text": "", "finish_status": "tool_calls",
        "tool_calls": [{"name": name, "arguments": arguments}],
    })
    return await agent.dispatch(calls[0], proposals[0])


@pytest.fixture
def docker(monkeypatch):
    commands, stops = [], []

    async def run(self, args, **kwargs):
        commands.append([str(arg) for arg in args])
        if args[0] == "build":
            context = Path(args[-1])
            assert set(p.name for p in context.iterdir()) <= {"Dockerfile", "harness-browser"}
            assert "secret" not in (context / "Dockerfile").read_text()
            Path(args[args.index("--iidfile") + 1]).write_text(PREPARED)
        if args[0] == "run":
            return canonical({"tools": {"python": {"available": True}, "node": {"available": True},
                "chromium": {"available": True}, "harness-browser": {"available": True}}, "python_packages": []})
        return b"[]"

    async def stop(a):
        stops.append(a.sandbox["image"])

    monkeypatch.setattr(service.Commands, "run", run)
    monkeypatch.setattr(service, "stop_keeper", stop)
    return commands, stops


@pytest.mark.parametrize("agent", [256], indirect=True)
def test_configured_process_grant_is_bound_through_dispatch_and_audit(agent, docker):
    _, result = asyncio.run(call(agent, "environment_inventory", {}))
    assert result.status == "succeeded"
    row = agent.store.db.execute(
        "SELECT request_ref FROM execution_attempts WHERE id=?", (result.execution_id,)
    ).fetchone()
    assert agent.store.blobs.json(row[0])["effective_limits"]["pids"] == 256
    commands, _ = docker
    probe = next(c for c in commands if c[0] == "run")
    assert probe[probe.index("--pids-limit") + 1] == "256"
    assert audit(agent.store, agent.run_id)["ok"]


@pytest.mark.parametrize("args", [
    {"reason": "bad", "runtimes": ["unknown"]},
    {"reason": "bad", "system_packages": ["nodejs; touch /tmp/x"]},
    {"reason": "bad", "python_packages": ["--index-url=https://example.org"]},
    {"reason": "bad", "dependency_manifests": ["project/../secret/uv.lock"]},
    {"reason": "bad", "dependency_manifests": ["tools/package.json"]},
    {"reason": "bad", "image": BASE},
])
def test_declarative_schema_rejects_commands_host_authority_and_paths(args):
    with pytest.raises(ValidationError):
        normalize("prepare_environment", args)


def test_inventory_and_prepare_switch_are_audited_and_preserve_files(agent, docker):
    async def scenario():
        await call(agent, "environment_inventory", {})
        _, result = await call(agent, "prepare_environment", {
            "reason": "browser tests", "runtimes": ["node"], "capabilities": ["headless_browser"],
        })
        assert json.loads(result.preview)["status"] == "ready"
        assert agent.sandbox["image"] == agent.executor.image == PREPARED
        assert (agent.path / "project/keep.txt").read_text() == "preserve this"
        assert service.selected(agent.store, agent.run_id)["image"] == PREPARED
        assert "Installed inventory:" in agent.fixed_messages("x")[3]["content"]
        assert audit(agent.store, agent.run_id)["ok"]
    asyncio.run(scenario())
    commands, stops = docker
    assert len([c for c in commands if c[0] == "build"]) == 1
    assert stops and all(image == BASE for image in stops)


def test_cache_reuses_image_and_changed_manifests_invalidate(agent, monkeypatch):
    builds = []
    async def run(self, args, **kwargs):
        if args[0] == "build":
            context = Path(args[-1])
            assert not (context / "keep.txt").exists()
            assert (context / "spec0/package.json").is_file()
            builds.append((context / "spec0/package.json").read_bytes())
            Path(args[args.index("--iidfile") + 1]).write_text(PREPARED)
        if args[0] == "run":
            return canonical({"tools": {"python": {"available": True}, "node": {"available": True}}})
        return b"[]"
    async def stop(a):
        pass
    monkeypatch.setattr(service.Commands, "run", run)
    monkeypatch.setattr(service, "stop_keeper", stop)
    project = agent.path / "project"
    (project / "package.json").write_text('{"name":"test","version":"1.0.0"}')
    (project / "package-lock.json").write_text('{"lockfileVersion":3}')
    args = {"reason": "npm tests", "dependency_manifests": ["project/package.json", "project/package-lock.json"]}
    async def scenario():
        await call(agent, "prepare_environment", args)
        _, second = await call(agent, "prepare_environment", {**args, "reason": "same requirements"})
        assert json.loads(second.preview)["cache_hit"]
        (project / "package.json").write_text('{"name":"test","version":"2.0.0"}')
        await call(agent, "prepare_environment", args)
    asyncio.run(scenario())
    assert len(builds) == 2 and builds[0] != builds[1]


def test_failed_build_is_reused_and_keeps_previous_image(agent, monkeypatch):
    builds = []
    async def run(self, args, **kwargs):
        if args[0] == "build":
            builds.append(args)
            raise service.Blocked("package could not be downloaded")
        return b"[]"
    monkeypatch.setattr(service.Commands, "run", run)
    async def scenario():
        for index in range(4):
            _, result = await call(agent, "prepare_environment", {"reason": "need node", "runtimes": ["node"]})
            output = json.loads(result.preview)
            assert output["status"] == "environment_blocked"
            if index:
                assert output["reused_failure"]
        assert agent.sandbox["image"] == BASE
    asyncio.run(scenario())
    assert len(builds) == 1


def test_operator_network_grant_and_symlink_manifests(agent, docker, tmp_path):
    agent.config = agent.config.model_copy(update={"environment": EnvironmentSettings()})
    async def scenario():
        _, result = await call(agent, "prepare_environment", {"reason": "need node", "runtimes": ["node"]})
        assert "allow_network" in json.loads(result.preview)["error"]
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "package.json").write_text("private data")
        (agent.path / "project/link").symlink_to(outside, target_is_directory=True)
        _, result = await call(agent, "prepare_environment", {
            "reason": "unsafe", "dependency_manifests": ["project/link/package.json"],
        })
        assert json.loads(result.preview)["status"] == "environment_blocked"
    asyncio.run(scenario())
    assert not any(c[0] == "build" for c in docker[0])


def test_recipe_never_copies_source_or_runs_installers_on_host(tmp_path):
    spec = {"system_packages": [], "python_packages": [], "runtimes": [], "capabilities": [], "dependency_manifests": []}
    manifests = {"project/package.json": b'{"scripts":{"postinstall":"touch /host"}}',
                 "project/package-lock.json": b'{"lockfileVersion":3}'}
    roots = service.recipe(spec, manifests, "trusted-base:tag", tmp_path)
    text = (tmp_path / "Dockerfile").read_text()
    assert "--ignore-scripts" in text
    assert roots == [{"slot": 0, "path": "project"}]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Dockerfile", "spec0"]
    bad = {"project/package.json": b'{"dependencies":{"bad":"file:/host"}}',
           "project/package-lock.json": b'{}'}
    other = tmp_path / "bad"
    other.mkdir()
    with pytest.raises(service.Blocked, match="Local/Git"):
        service.recipe(spec, bad, "trusted-base:tag", other)


@pytest.mark.parametrize("agent", [128, (128, True)], indirect=True)
def test_resume_restores_selected_image_and_never_rebuilds(agent, docker):
    async def scenario():
        await call(agent, "prepare_environment", {"reason": "need node", "runtimes": ["node"]})
        agent.checkpoint()
        second = Agent(agent.store, agent.config, {"image": BASE}, provider=ScriptedProvider())
        try:
            agent.store.blobs.begin_budget(agent.config.limits.max_evidence_bytes)
            await restore(second, agent.run_id)
            assert second.sandbox["image"] == second.executor.image == PREPARED
            assert second.policy_hash == agent.policy_hash
            await call(second, "environment_inventory", {})
            assert audit(agent.store, agent.run_id)["ok"]
            assert len([c for c in docker[0] if c[0] == "build"]) == 1
        finally:
            second.spans.shutdown()
        # Losing a result marker must not cause download/build replay.
        row = agent.store.db.execute("SELECT * FROM execution_attempts WHERE result_ref IS NOT NULL ORDER BY rowid DESC LIMIT 1").fetchone()
        (agent.store.control / "attempts" / (row["id"] + ".json")).unlink()
        with pytest.raises(NeedsReconciliation, match="interrupted without a published result"):
            await reconcile(agent, row)
    asyncio.run(scenario())


@pytest.mark.parametrize("published", [True, False])
def test_preparation_crash_before_database_commit_never_replays_build(agent, docker, published):
    def crash(point):
        if point == "after_environment_result_publication":
            raise SystemExit(86)
    agent.fault_hook = crash
    async def scenario():
        with pytest.raises(SystemExit):
            await call(agent, "prepare_environment", {"reason": "need node", "runtimes": ["node"]})
        row = agent.store.db.execute("SELECT * FROM execution_attempts ORDER BY rowid DESC LIMIT 1").fetchone()
        assert row["state"] == "started" and row["result_ref"] is None
        if not published:
            (agent.store.control / "attempts" / (row["id"] + ".json")).unlink()
        second = Agent(agent.store, agent.config, {"image": BASE}, provider=ScriptedProvider())
        agent.store.blobs.begin_budget(agent.config.limits.max_evidence_bytes)
        try:
            if published:
                await restore(second, agent.run_id)
                assert second.sandbox["image"] == PREPARED
                assert agent.store.db.execute("SELECT state FROM execution_attempts WHERE id=?", (row["id"],)).fetchone()[0] == "finished"
                assert any(e.event_type == "execution.reconciled" and e.data.get("result_ref")
                           for e in agent.store.events(agent.run_id))
                report = audit(agent.store, agent.run_id)
                assert report["ok"], report
            else:
                with pytest.raises(NeedsReconciliation, match="without a published result"):
                    await restore(second, agent.run_id)
            assert len([c for c in docker[0] if c[0] == "build"]) == 1
        finally:
            second.spans.shutdown()
    asyncio.run(scenario())


def test_command_logs_are_in_export_roots(agent):
    out, err = agent.store.blobs.put(b"setup output"), agent.store.blobs.put(b"setup warning")
    agent.event("environment.command_finished", "environment", {"stdout_ref": out, "stderr_ref": err})
    refs, _ = roots(agent.store, agent.run_id)
    assert out in refs and err in refs


def test_preparation_rejects_modified_trusted_worker_without_executing_it():
    import io
    import tarfile

    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        body = b"untrusted replacement"
        member = tarfile.TarInfo("worker.py")
        member.size = len(body)
        archive.addfile(member, io.BytesIO(body))
    calls = []
    class Runner:
        async def run(self, args):
            calls.append(args)
            if args[0] == "create":
                return b"container-id"
            if args[0] == "cp":
                return stream.getvalue()
            return b""
    with pytest.raises(service.Blocked, match="protected sandbox file"):
        asyncio.run(service.verify_worker(Runner(), {"image": BASE, "worker_hash": digest(b"trusted original")}))
    assert calls[-1] == ["rm", "-f", "container-id"]
    assert not any(c[0] == "run" for c in calls)


@pytest.mark.parametrize("field", ["dependency_groups", "dependency_extras"])
def test_python_check_reuses_matching_image_but_reprepares_extra_groups(tmp_path, monkeypatch, field):
    from local_agent.testing import environment

    project = tmp_path / "project"
    project.mkdir()
    metadata = b'[project]\nname="example"\nversion="0.1.0"\n'
    lock = b'version=1\n'
    (project / "pyproject.toml").write_bytes(metadata)
    (project / "uv.lock").write_bytes(lock)
    sandbox = {"image": PREPARED, "prepared_environment": {"key": "fixture", "manifest_hashes": {
        "project/pyproject.toml": digest(metadata), "project/uv.lock": digest(lock),
    }}}
    plan = {"install_project": False, "prepare_dependencies": True}
    assert environment.prepare(tmp_path / "data", project, plan, sandbox)["image"] == PREPARED
    def blocked(*args, **kwargs):
        raise RuntimeError("extra dependencies need preparation")
    monkeypatch.setattr(environment, "_run", blocked)
    with pytest.raises(RuntimeError, match="extra dependencies need preparation"):
        environment.prepare(tmp_path / "data", project, {**plan, field: ["extra"]}, sandbox)


def test_real_commands_capture_stdout_stderr_and_timeout(agent, monkeypatch):
    import sys

    original = asyncio.create_subprocess_exec
    scripts = iter(["import sys;print('out');print('err',file=sys.stderr)", "import time;time.sleep(30)"])
    async def spawn(*args, **kwargs):
        assert args[0] == "docker"
        return await original(sys.executable, "-c", next(scripts), **kwargs)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    async def scenario():
        runner = service.Commands(agent, "test-commands")
        assert await runner.run(["image", "inspect", BASE]) == b"out\n"
        with pytest.raises(service.Blocked):
            await runner.run(["image", "inspect", BASE], timeout=0.05)
    asyncio.run(scenario())
    events = [e for e in agent.store.events(agent.run_id) if e.event_type == "environment.command_finished"]
    assert agent.store.blobs.read(events[0].data["stderr_ref"]) == b"err\n"
    assert events[1].data["status"] == "timeout"
    refs, _ = roots(agent.store, agent.run_id)
    assert events[0].data["stderr_ref"] in refs


def test_real_docker_node_chromium_and_offline_execution(tmp_path, request):
    image = request.config.getoption("--docker-image")
    if not image:
        pytest.skip("requires --docker-image and operator-authorized Docker downloads")
    from local_agent.doctor import sandbox_config

    source = tmp_path / "web-project"
    source.mkdir()
    (source / "index.html").write_text("<title>before</title><script>document.title='browser-ok'</script>")
    import re
    import tomllib

    # Use a real pinned wheel record already maintained in this repository's lock.
    lock_text = Path("uv.lock").read_text()
    package = next(p for p in tomllib.loads(lock_text)["package"] if p["name"] == "typing-extensions")
    package_block = re.search(r'(?ms)^\[\[package\]\]\nname = "typing-extensions"\n.*?(?=^\[\[package\]\]|\Z)', lock_text).group(0)
    (source / "pyproject.toml").write_text(
        '[project]\nname="environment-python-test"\nversion="0.1.0"\nrequires-python=">=3.11"\n'
        + 'dependencies=["typing-extensions==' + package["version"] + '"]\n'
    )
    (source / "uv.lock").write_text(
        'version=1\nrevision=3\nrequires-python=">=3.11"\n\n[[package]]\n'
        'name="environment-python-test"\nversion="0.1.0"\nsource={virtual="."}\n'
        'dependencies=[{name="typing-extensions"}]\n[package.metadata]\n'
        'requires-dist=[{name="typing-extensions",specifier="==' + package["version"] + '"}]\n\n' + package_block
    )
    dependencies = {"is-number": "7.0.0"}
    (source / "package.json").write_text(json.dumps({
        "name": "environment-test", "version": "1.0.0", "type": "module", "dependencies": dependencies,
    }))
    (source / "package-lock.json").write_text(json.dumps({
        "name": "environment-test", "version": "1.0.0", "lockfileVersion": 3, "requires": True,
        "packages": {"": {"name": "environment-test", "version": "1.0.0", "dependencies": dependencies},
            "node_modules/is-number": {"version": "7.0.0", "resolved": "https://registry.npmjs.org/is-number/-/is-number-7.0.0.tgz"}},
    }))
    (source / ".local-agent-tests.json").write_text(json.dumps({
        "version": 1, "install_project": False, "prepare_dependencies": True,
        "commands": [{"argv": ["node", "-e", "if(!require('is-number')(4))process.exit(1)"], "cwd": "."}],
    }))
    config = load_config(Path("config/coder.yaml")).model_copy(update={
        "project_tests": False, "environment": EnvironmentSettings(allow_network=True, timeout_seconds=900),
    })
    provider = ScriptedProvider([
        {"text": "", "finish_status": "tool_calls", "tool_calls": [{"name": "prepare_environment", "arguments": {
            "reason": "test real JavaScript and browser execution", "runtimes": ["node"],
            "capabilities": ["headless_browser"], "python_packages": ["six==1.17.0"],
            "dependency_manifests": ["project/package.json", "project/package-lock.json", "project/pyproject.toml", "project/uv.lock"],
        }}]},
        {"text": "", "finish_status": "tool_calls", "tool_calls": [
            {"name": "run_command", "arguments": {"argv": ["node", "--input-type=module", "-e", "import isNumber from 'is-number';if(!isNumber(4))throw Error('dependency failed');console.log('node-ok')"]}},
            {"name": "run_command", "arguments": {"argv": ["harness-browser", "--dump-dom", "file:///workspace/project/index.html"], "timeout_seconds": 60}},
            {"name": "run_command", "arguments": {"argv": ["python", "-c", "import typing_extensions,six;assert six.__version__=='1.17.0';print('python-ok')"]}},
        ]},
        {"text": "Environment and browser tests complete", "finish_status": "stop", "tool_calls": []},
    ])
    store = Store(tmp_path / "data")
    try:
        a = Agent(store, config, {**sandbox_config(), "image": image}, provider=provider)
        result = asyncio.run(a.run(source, "Prepare a browser test environment"))
        assert result["status"] == "completed_unverified", result
        assert a.sandbox["image"] != image
        outputs = [store.blobs.json(row[0]) for row in store.db.execute(
            "SELECT e.result_ref FROM execution_attempts e JOIN tool_calls t ON t.id=e.call_id "
            "JOIN model_requests m ON m.id=t.request_id WHERE m.run_id=? AND e.state='finished'", (a.run_id,)
        )]
        assert any("node-ok" in o["preview"] for o in outputs)
        assert any("python-ok" in o["preview"] for o in outputs)
        assert any("<title>browser-ok</title>" in o["preview"] for o in outputs)
        assert audit(store, a.run_id)["ok"]
        events = store.events(a.run_id)
        assert any(e.event_type == "environment.command_finished" for e in events)
        assert (a.path / "project/index.html").read_text() == (source / "index.html").read_text()
        from local_agent.mobile.review_instructions import REVIEW_TOOLS
        from local_agent.mobile.workspace_review import run_review
        from local_agent.workspace.review import capture_target

        target = capture_target(store.root, a.workspace_id, result["git_workspace"]["candidate_commit"], [source], ".")
        reviewer_config = config.model_copy(update={"instructions_version": "workspace-review-v1",
            "instructions_hash": digest(instruction_text("workspace-review-v1").encode()),
            "tools": REVIEW_TOOLS, "environment": EnvironmentSettings()})
        reviewer = ScriptedProvider([
            {"text": "", "finish_status": "tool_calls", "tool_calls": [
                {"name": "read_file", "arguments": {"path": "scratch/review.diff"}},
                {"name": "read_file", "arguments": {"path": "project/index.html"}},
            ]},
            {"text": json.dumps({"verdict": "approve", "summary": "Inspected candidate and recorded Node checks"}), "finish_status": "stop", "tool_calls": []},
        ])
        reviewed = asyncio.run(run_review(store, reviewer_config, {
            "review_target": target, "test_command": "node -e \"require('is-number')(4)||process.exit(1)\"",
        }, {**sandbox_config(), "image": image}, [source], provider=reviewer))
        assert reviewed["workspace_review"]["status"] == "approved", reviewed
        assert service.selected(store, reviewed["run_id"])["image"] == a.sandbox["image"]
        follow_config = config.model_copy(update={"environment": EnvironmentSettings(), "project_tests": True})
        follow = Agent(store, follow_config, {**sandbox_config(), "image": image}, provider=ScriptedProvider([
            {"text": "", "finish_status": "tool_calls", "tool_calls": [{"name": "run_command", "arguments": {
                "argv": ["node", "-e", "if(!require('is-number')(4))process.exit(1)"],
            }}]},
            {"text": "Continued offline", "finish_status": "stop", "tool_calls": []},
        ]), workspace_options={"continue_workspace_id": a.workspace_id})
        continued = asyncio.run(follow.run(source, "Continue using the prepared dependencies"))
        assert continued["status"] == "completed_unverified", continued
        assert follow.sandbox["image"] == a.sandbox["image"]
        assert not any(e.event_type == "environment.command_started" and e.data["command"][:2] == ["docker", "build"]
                       for e in store.events(follow.run_id))
        assert audit(store, follow.run_id)["ok"]
    finally:
        store.close()

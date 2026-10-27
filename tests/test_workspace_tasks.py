"""Task selection preserves source checkouts and continued candidate edits."""

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from test_browser_web import completed, login, running

from local_agent.config import load_config
from local_agent.mobile.browser_requests import validate_browser_request
from local_agent.mobile.browser_runtime import run_browser
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.storage.database import Store
from local_agent.workspace.git import GitWorktrees, git
from local_agent.workspace.manager import Workspaces, copy_tree
from local_agent.workspace.options import check_directory, validate_options


@pytest.fixture
def repo(tmp_path):
    source = tmp_path / "repo"
    (source / "nested").mkdir(parents=True)
    (source / "nested/value.txt").write_text("first")
    git("-C", source, "init", "-b", "topic")
    git("-C", source, "add", ".")
    git("-C", source, "commit", "-m", "First")
    first = git("-C", source, "rev-parse", "HEAD").decode().strip()
    (source / "nested/value.txt").write_text("second")
    git("-C", source, "add", ".")
    git("-C", source, "commit", "-m", "Second")
    return source, first


def test_selected_commit_uses_literal_old_tree_without_switching_source(repo, tmp_path):
    source, first = repo
    manager = Workspaces(tmp_path / "state")
    ws, root = manager.create_coding(source, "run_first", base_ref=first)
    info = manager.git_info(ws)
    assert info["base_commit"] == first
    assert info["base_branch"] == "topic"
    assert info["source_dirty"] is False
    assert (root / "project/nested/value.txt").read_text() == "first"
    _, latest = manager.create_coding(source, "run_latest")
    assert (latest / "project/nested/value.txt").read_text() == "second"
    assert (source / "nested/value.txt").read_text() == "second"
    assert git("-C", source, "symbolic-ref", "--short", "HEAD").strip() == b"topic"
    with pytest.raises(RuntimeError):
        manager.create_coding(source, "run_bad", base_ref="--not-a-ref")
    with pytest.raises(ValueError, match="repository root"):
        manager.create_coding(source / "nested", "run_bad", base_ref=first)


@pytest.mark.parametrize("published", [False, True])
def test_continue_preserves_pending_files_and_publishes_on_same_branch(repo, tmp_path, published):
    source, _ = repo
    workspaces = Workspaces(tmp_path / "state")
    ws, root = workspaces.create_coding(source, "run_first")
    manager = GitWorktrees(workspaces)
    project = root / "project"
    (project / "nested/value.txt").write_text("candidate")
    if published:
        copy_tree(project, tmp_path / "snapshot", exclude=(".git",))
        manager.finalize(ws, tmp_path / "snapshot")
    previous = manager.public(ws)
    (project / "pending.txt").write_text("keep pending")
    manager.continue_task(ws, source, "run_second", working_directory="nested")
    assert (project / "pending.txt").read_text() == "keep pending"
    assert (project / "nested/value.txt").read_text() == "candidate"
    manager.baseline(ws, tmp_path / "baseline")
    expected = "candidate" if published else "second"
    assert (tmp_path / "baseline/nested/value.txt").read_text() == expected
    assert not (tmp_path / "baseline/pending.txt").exists()
    copy_tree(project, tmp_path / "continued", exclude=(".git",))
    result = manager.finalize(ws, tmp_path / "continued")
    parent = previous["candidate_commit"] or previous["base_commit"]
    assert git("-C", source, "rev-parse", result["candidate_commit"] + "^").decode().strip() == parent
    assert result["branch"] == previous["branch"]
    assert result["working_directory"] == "nested"
    assert (source / "nested/value.txt").read_text() == "second"
    assert not (source / "pending.txt").exists()
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="selected repository"):
        manager.continue_task(ws, other, "run_wrong")
    git("-C", project, "update-ref", "refs/heads/" + result["branch"], parent)
    # External advancement to an unrelated commit must never be overwritten.
    git("-C", project, "update-ref", "refs/heads/" + result["branch"],
        git("-C", source, "rev-parse", "HEAD~1").decode().strip())
    with pytest.raises(RuntimeError, match="moved outside"):
        manager.continue_task(ws, source, "run_moved")


@pytest.mark.parametrize("directory", ["../nested", "/tmp", "nested/../nested", "nested//x", "nested\\x", ".git", "nested/."])
def test_directory_cannot_escape_or_use_git_metadata(directory):
    with pytest.raises(ValueError):
        validate_options({"working_directory": directory})


def test_directory_requires_existing_directory_without_symlinks(repo):
    source, _ = repo
    check_directory(source, "nested")
    (source / "link").symlink_to(source / "nested", target_is_directory=True)
    for directory in ("missing", "link", "nested/value.txt"):
        with pytest.raises(ValueError):
            check_directory(source, directory)
    with pytest.raises(ValueError, match="starting revision"):
        validate_options({"base_ref": "HEAD", "continue_workspace_id": "ws_" + "a" * 32})


@pytest.mark.parametrize("version", ["browser-v1", "analog-v2"])
def test_coding_options_do_not_leak_to_other_workflows(repo, version):
    from types import SimpleNamespace

    source, _ = repo
    with pytest.raises(ValueError):
        validate_browser_request({"question": "Inspect", "workspace": str(source),
                                  "working_directory": "nested"},
                                 SimpleNamespace(instructions_version=version), [source])


def test_browser_queues_options_and_persists_result_directory(repo, tmp_path):
    source, first = repo
    configs = tmp_path / "configs"
    configs.mkdir()
    shutil.copy2("config/coder.yaml", configs / "coder.yaml")
    shutil.copy2("config/browser.yaml", configs / "browser.yaml")
    captured = []

    def runner(path):
        captured.append(json.loads(path.read_text()))
        return {"status": "completed_unverified", "run_id": None, "answer": "Done",
                "workspace": "/managed/workspace", "working_directory": "nested", "task_mode": "new"}

    with running(tmp_path / "state", runner, configs, source) as (server, client):
        login(server, client)
        tid = client.post("/api/threads", json={"title": "Directory"}).json()["thread_id"]
        response = client.post(f"/api/threads/{tid}/ask", json={
            "profile_name": "coder.yaml", "question": "Inspect", "workspace": str(source),
            "base_ref": first, "working_directory": "nested",
        })
        assert response.status_code == 202, response.text
        job = completed(client, response.json()["job_id"])
        assert captured[0]["base_ref"] == first
        assert captured[0]["working_directory"] == "nested"
        assert job["working_directory"] == "nested"
        saved = client.get(f"/api/threads/{tid}").json()["messages"][-1]
        assert saved["working_directory"] == "nested" and saved["task_mode"] == "new"


def tool(code, **extra):
    return {"text": "", "tool_calls": [{"name": "run_command", "arguments": {
        "argv": ["python", "-c", code], **extra,
    }}], "finish_status": "tool_calls"}


@pytest.mark.parametrize("execution_mode", ["ephemeral", "persistent"])
def test_browser_continues_actual_worktree_with_focused_commands_and_valid_audits(repo, tmp_path, request, execution_mode):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    source, first = repo
    config = load_config(Path("config/coder.yaml"))
    config = config.model_copy(update={"execution": config.execution.model_copy(
        update={"execution_mode_default": execution_mode}
    )})
    store = Store(tmp_path / "state")
    stop = {"text": "Done", "tool_calls": [], "finish_status": "stop"}
    provider = ScriptedProvider(responses=(
        tool("from pathlib import Path; assert Path('value.txt').read_text()=='first'; Path('result.txt').write_text('candidate')"),
        tool("from pathlib import Path; assert Path('nested').is_dir(); Path('root.txt').write_text('explicit')", cwd="project"),
        {"text": "", "tool_calls": [{"name": "git_diff", "arguments": {}}], "finish_status": "tool_calls"},
        stop,
    ))
    try:
        first_result = asyncio.run(run_browser(store, config, {
            "mode": "coding", "question": "Work", "workspace": str(source),
            "base_ref": first, "working_directory": "nested",
        }, {"image": image}, provider=provider))
        assert first_result["status"] == "completed_unverified", first_result
        assert audit(store, first_result["run_id"])["ok"]
        ws = first_result["workspace_id"]
        root = Path(first_result["workspace"])
        assert (root / "project/nested/result.txt").read_text() == "candidate"
        assert (root / "project/root.txt").read_text() == "explicit"
        (root / "project/nested/pending.txt").write_text("preserve")
        provider2 = ScriptedProvider(responses=(
            tool("from pathlib import Path; assert Path('pending.txt').read_text()=='preserve'; assert Path('result.txt').read_text()=='candidate'; Path('result.txt').write_text('continued')"),
            stop,
        ))
        result = asyncio.run(run_browser(store, config, {
            "mode": "coding", "question": "Continue", "workspace": str(source),
            "continue_workspace_id": ws,
        }, {"image": image}, provider=provider2))
        assert result["status"] == "completed_unverified", result
        assert result["workspace_id"] == ws and result["workspace"] == str(root)
        assert result["run_id"] != first_result["run_id"]
        assert result["working_directory"] == "nested" and result["task_mode"] == "continue"
        assert result["git_workspace"]["base_commit"] == first_result["git_workspace"]["candidate_commit"]
        assert audit(store, result["run_id"])["ok"]
        assert audit(store, first_result["run_id"])["ok"]
        diff = store.blobs.read(result["diff_ref"])
        assert b"pending.txt" in diff and b"+continued" in diff
        assert b"root.txt" not in diff
        assert (source / "nested/value.txt").read_text() == "second"
        assert not (source / "nested/result.txt").exists()
        configs = [store.blobs.json(store.blobs.json(store.run(r["run_id"])["manifest_ref"])["config_ref"])
                   for r in (first_result, result)]
        assert configs[0]["baseline_id"] != configs[1]["baseline_id"]
        assert all((store.control / "baselines" / c["baseline_id"]).is_dir() for c in configs)
        context = store.blobs.json(provider2.requests[0].context_ref)
        messages = store.blobs.json(context["payload_ref"])["messages"]
        assert any("Task working directory: project/nested" in m.get("content", "") for m in messages)
    finally:
        from local_agent.executor.docker import DockerExecutor

        async def cleanup():
            executor = DockerExecutor(store, Workspaces(store.root), image, settings=config.execution)
            manager = executor.make_manager(lambda *_: None)
            for manifest in manager.directory.glob("ws_*.json"):
                await manager.stop(manifest.stem)

        asyncio.run(cleanup())
        store.close()


def test_active_and_unknown_workspaces_are_rejected_without_modifying_candidate(repo, tmp_path):
    from local_agent.contracts import RunManifest, new_id
    from local_agent.observability.spans import Spans
    from local_agent.runtime.agent import Agent
    from local_agent.storage.blobs import digest

    source, _ = repo
    store = Store(tmp_path / "state")
    config = load_config(Path("config/coder.yaml"))
    old_run = new_id("run")
    workspaces = Workspaces(store.root)
    ws, root = workspaces.create_coding(source, old_run)
    (root / "project/pending.txt").write_text("untouched")
    ref = store.blobs.put_json({})
    spans = Spans()
    with spans.boundary("test.create"):
        store.create_run(RunManifest(
            run_id=old_run, thread_id=new_id("thread"), workspace_id=ws,
            config_ref=ref, config_hash=digest(store.blobs.read(ref)), model_identity="test",
            sandbox_image_digest="sha256:" + "a" * 64, mode="live", package_versions={},
        ))
    spans.shutdown()
    original = GitWorktrees(workspaces).load(ws)
    try:
        for previous, error in ((ws, "active"), ("ws_" + "f" * 32, "workspace")):
            agent = Agent(store, config, {"image": "sha256:" + "a" * 64},
                          provider=ScriptedProvider(responses=()),
                          workspace_options={"continue_workspace_id": previous})
            result = asyncio.run(agent.run(source, "Continue"))
            assert result["status"] == "failed" and error in result["error"], result
        assert GitWorktrees(workspaces).load(ws) == original
        assert (root / "project/pending.txt").read_text() == "untouched"
    finally:
        store.close()

"""Real Docker edits a host worktree while host-only Git publishes its branch."""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.mobile.browser_runtime import run_browser
from local_agent.mobile.web import BrowserServer
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.storage.blobs import digest
from local_agent.storage.database import Store
from local_agent.workspace.git import git


@pytest.mark.parametrize("mode", ["ephemeral", "persistent"])
def test_coding_worktree_publication_and_diff_api(tmp_path, request, mode):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    source = tmp_path / "repo"
    source.mkdir()
    original = b"def add(a, b):\n    return a - b\n"
    (source / "calculator.py").write_bytes(original)
    (source / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    git("-C", source, "init", "-b", "main")
    git("-C", source, "add", ".")
    git("-C", source, "commit", "-m", "Initial")
    base = git("-C", source, "rev-parse", "HEAD").decode().strip()
    tests = "from calculator import add\ndef test_add():\n    assert add(2,3)==5\n    assert add(-2,-3)==-5\n    assert add(0,1)==1\n    assert abs(add(0.1,0.2)-0.3)<1e-12\n"
    check = (
        "import os, pathlib, subprocess; "
        "assert os.environ['GIT_DIR']=='/workspace/tools/.git-shadow'; "
        "marker=pathlib.Path('/workspace/project/.git').read_text(); "
        "assert not pathlib.Path(marker.split(': ',1)[1].strip()).exists(); "
        "subprocess.run(['python','-m','pytest','-q'],check=True); "
        "subprocess.run(['git','-c','user.name=Sandbox','-c',"
        "'user.email=sandbox@localhost','add','.'],check=True); "
        "subprocess.run(['git','-c','user.name=Sandbox','-c',"
        "'user.email=sandbox@localhost','commit','-am','private history'],check=True)"
    )
    provider = ScriptedProvider(responses=(
        {"text": "", "tool_calls": [{"name": "write_file", "arguments": {
            "path": "project/calculator.py", "content": "def add(a, b):\n    return a + b\n",
            "create_only": False, "expected_hash": digest(original),
        }}], "finish_status": "tool_calls"},
        {"text": "", "tool_calls": [{"name": "write_file", "arguments": {
            "path": "project/test_calculator.py", "content": tests,
        }}], "finish_status": "tool_calls"},
        {"text": "", "tool_calls": [{"name": "run_command", "arguments": {
            "argv": ["python", "-c", check],
        }}], "finish_status": "tool_calls"},
        {"text": "Candidate ready", "tool_calls": [], "finish_status": "stop"},
    ))
    config = load_config(Path("config/coder.yaml"))
    config = config.model_copy(update={"execution": config.execution.model_copy(
        update={"execution_mode_default": mode}
    )})
    store = Store(tmp_path / "data")

    async def scenario():
        try:
            result = await run_browser(store, config, {
                "mode": "coding", "workspace": str(source), "question": "Fix addition", "history": [],
            }, {**sandbox_config(), "image": image}, provider=provider)
            assert result["status"] == "completed_unverified", result
            record = result["git_workspace"]
            assert record["base_commit"] == base and record["state"] == "ready_for_review"
            assert record["candidate_commit"] != base
            assert record["branch"] == "agent/" + result["workspace_id"]
            assert Path(record["worktree"]) == Path(result["workspace"]) / "project"
            assert (source / "calculator.py").read_bytes() == original
            assert git("-C", source, "rev-parse", "HEAD").decode().strip() == base
            assert b"a + b" in git("-C", source, "show", record["branch"] + ":calculator.py")
            assert git("-C", source, "show", record["branch"] + ":test_calculator.py").decode() == tests
            assert audit(store, result["run_id"])["ok"]
            command_results = [store.blobs.json(e.data["result_ref"])
                               for e in store.events(result["run_id"])
                               if e.event_type == "execution.finished"]
            assert all(r["status"] == "succeeded" for r in command_results), command_results
            server = object.__new__(BrowserServer)
            server.root = store.root
            diff = server.job_diff(result)
            assert "+    return a + b" in diff["content"]
            assert "+def test_add" in diff["content"]
            with pytest.raises(ValueError, match="not an artifact"):
                server.job_diff({**result, "diff_ref": store.blobs.put(b"unrelated private bytes")})
            return result
        finally:
            from local_agent.executor.docker import DockerExecutor
            from local_agent.workspace.manager import Workspaces

            executor = DockerExecutor(store, Workspaces(store.root), image, settings=config.execution)
            manager = executor.make_manager(lambda *_: None)
            for path in manager.directory.glob("ws_*.json"):
                await manager.stop(path.stem)

    try:
        asyncio.run(scenario())
    finally:
        store.close()


def test_worktree_resume_keeps_branch_and_does_not_repeat_mutation(tmp_path, request):
    from local_agent.runtime.agent import Agent

    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    source = tmp_path / "repo"
    source.mkdir()
    (source / "readme").write_text("base")
    git("-C", source, "init", "-b", "main")
    git("-C", source, "add", ".")
    git("-C", source, "commit", "-m", "Initial")
    root = tmp_path / "data"
    crashed = subprocess.run([
        sys.executable, str(Path(__file__).parent / "crash_driver.py"),
        str(root), "after_result_publication", image, "ephemeral", str(source),
    ], timeout=60, check=False, capture_output=True)
    assert crashed.returncode == 86, crashed.stderr
    store = Store(root)
    try:
        run_id = store.db.execute("SELECT id FROM runs").fetchone()[0]
        agent = Agent(store, load_config(Path("config/coder.yaml")),
                      {**sandbox_config(), "image": image},
                      provider=ScriptedProvider(responses=(
                          {"text": "Recovered", "tool_calls": [], "finish_status": "stop"},
                      )))
        result = asyncio.run(agent.run(None, "", resume_run_id=run_id))
        assert result["status"] == "completed_unverified", result
        branch = result["git_workspace"]["branch"]
        assert git("-C", source, "show", branch + ":count") == b"X"
        assert not (source / "count").exists()
        assert audit(store, run_id)["ok"]
    finally:
        store.close()

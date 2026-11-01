"""Full HTTP -> local Docker -> mocked paid Responses -> local Docker loop."""

import asyncio
import json
import threading
import time
from pathlib import Path

import httpx
import pytest
from test_mobile_threads import catalog
from test_mobile_web import login
from test_openai_responses import output
from test_workspace_review import candidate as candidate_factory

from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.executor.maintenance import sweep
from local_agent.mobile.browser_runtime import run_browser
from local_agent.mobile.jobs import publish
from local_agent.mobile.models import Models
from local_agent.mobile.web import BrowserServer
from local_agent.mobile.workspace_review import run_review
from local_agent.models.openai import OpenAIProvider
from local_agent.models.scripted import ScriptedProvider
from local_agent.runtime.loop import simulate
from local_agent.storage.database import Store
from local_agent.workspace.git import GitWorktrees
from local_agent.workspace.manager import Workspaces


@pytest.fixture
def candidate(tmp_path):
    return candidate_factory.__wrapped__(tmp_path)


def exercise_loop(candidate_data, request, monkeypatch, outcome, start_callback=None):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    root, repository, project, reviewed = candidate_data
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setattr(Models, "catalog", lambda *_a, **_k: catalog())
    store = Store(root)
    source_run = asyncio.run(simulate(store))["run_id"]
    manager = GitWorktrees(Workspaces(root))
    record = manager.load(reviewed["workspace_id"])
    record["run_id"] = source_run
    manager.save(record)
    store.close()
    local_count, review_count = 0, 0
    containers = []
    sandbox = {**sandbox_config(), "image": image}

    def runner(path):
        nonlocal local_count, review_count
        task = json.loads(path.read_text())
        cfg = load_config(path.with_name("config.json"))
        store = Store(root)
        try:
            if task["mode"] == "coding":
                local_count += 1
                value = local_count + 2
                code = (
                    "from pathlib import Path; import json; "
                    "c=json.loads(Path('/workspace/scratch/task-context.json').read_text()); "
                    "assert c['original_task']=='Improve the value implementation'; "
                    + (
                        "assert 'Missing behavior' in str(c['latest_review']); "
                        if local_count > 1
                        else ""
                    )
                    + f"Path('value.py').write_text('VALUE = {value}\\n'); "
                    + f"Path('test_value.py').write_text('from value import VALUE\\ndef test_value():\\n    assert VALUE == {value}\\n')"
                )
                responses = [
                    {
                        "text": "Repair",
                        "tool_calls": [
                            {"name": "run_command", "arguments": {"argv": ["python", "-c", code]}}
                        ],
                        "finish_status": "tool_calls",
                        "usage": {"prompt_eval_count": 20, "eval_count": 10},
                    },
                    {
                        "text": "Candidate ready",
                        "tool_calls": [],
                        "finish_status": "stop",
                        "usage": {"prompt_eval_count": 20, "eval_count": 10},
                    },
                ]
                result = asyncio.run(
                    run_browser(
                        store,
                        cfg,
                        task,
                        sandbox,
                        provider=ScriptedProvider(responses),
                        progress_path=path.with_name("progress.json"),
                    )
                )
                keeper = json.loads(
                    (
                        store.control / "containers" / (reviewed["workspace_id"] + ".json")
                    ).read_text()
                )
                containers.append(keeper["container_id"])
                return result
            review_count += 1
            calls = 0

            def endpoint(incoming):
                nonlocal calls
                if incoming.url.path.endswith("/models"):
                    return httpx.Response(200, json={"data": [{"id": cfg.model}]})
                assert incoming.url.path.endswith("/responses")
                calls += 1
                response = output(calls=calls == 1)
                tests = [{"argv": ["python", "-m", "pytest", "-q"], "cwd": "project"}]
                if calls == 1:
                    response["output"].append({
                        "id": "fc_tests", "type": "function_call", "call_id": "call_tests",
                        "name": "run_command", "arguments": json.dumps(tests[0]),
                        "status": "completed",
                    })
                else:
                    verdict = json.loads(response["output"][-1]["content"][0]["text"])
                    verdict["tests"] = tests
                    response["output"][-1]["content"][0]["text"] = json.dumps(verdict)
                if calls > 1 and (review_count == 1 or outcome != "approved"):
                    response["output"][-1]["content"][0]["text"] = json.dumps(
                        {
                            "verdict": "request_changes",
                            "summary": "Missing behavior: add the additional regression case",
                            "tests": tests,
                        }
                    )
                return httpx.Response(200, json=response)

            async def review():
                provider = OpenAIProvider(store.blobs, cfg, transport=httpx.MockTransport(endpoint))
                try:
                    return await run_review(
                        store,
                        cfg,
                        task,
                        sandbox,
                        [repository],
                        provider=provider,
                        progress_path=path.with_name("progress.json"),
                    )
                finally:
                    await provider.close()

            return asyncio.run(review())
        finally:
            store.close()

    server = BrowserServer(
        root,
        Path("config/browser.yaml"),
        port=0,
        runner=runner,
        verifier_path="examples/configs/openai-reviewer.yaml",
        allowed_roots=[repository],
    )
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        tid = server.threads.create("Loop integration")
        source_id = "f" * 32
        directory = server.jobs.directory / source_id
        directory.mkdir(mode=0o700)
        publish(
            directory / "status.json",
            {
                "job_id": source_id,
                "thread_id": tid,
                "created": 0,
                "status": "completed",
                "run_id": source_run,
                "kind": "answer",
                "mode": "coding",
                "model": "local",
                "provider": "ollama",
                "question": "Improve the value implementation",
                "answer": "Candidate",
                "profile_name": "coder.yaml",
                "git_workspace": manager.public(reviewed["workspace_id"]),
            },
        )
        server.threads.add_exchange(
            tid, "Improve the value implementation", "Candidate", source_id, source_run, "local"
        )
        with httpx.Client(
            base_url=url, headers={"Origin": url}, trust_env=False, timeout=30
        ) as client:
            login(server, client)
            payload = {
                "workspace_id": reviewed["workspace_id"],
                "profile_name": "coder.yaml",
                "authorize_paid": True,
                "reviewer_model_id": "openai:gpt-6-luna",
                "execution_mode": "persistent",
            }
            if outcome == "paid_exhausted":
                payload["max_paid_reviews"] = 1
            if start_callback is None:
                started = client.post(f"/api/threads/{tid}/loops", json=payload)
                assert started.status_code == 202, started.text
                loop_id = started.json()["loop_id"]
            else:
                loop_id = start_callback(server, tid, payload)
            deadline = time.monotonic() + 100
            while time.monotonic() < deadline:
                state = client.get(f"/api/threads/{tid}/loops").json()[0]
                if state["status"] != "running":
                    break
                time.sleep(0.1)
            expected = "approved" if outcome == "approved" else "tests_passed_unverified"
            assert state["status"] == expected, state
            assert state["loop_id"] == loop_id
            expected_local = 6 if outcome == "five_paid_exhausted" else 2
            expected_paid = (
                5 if outcome == "five_paid_exhausted" else (2 if outcome == "approved" else 1)
            )
            assert local_count == expected_local and review_count == expected_paid
            assert len(set(containers)) == 1
            assert state["paid_tokens"] == 330 * review_count
            assert state["live_usage"]["measured_openai_total"] == 330 * review_count
            assert state["local_tokens"] == expected_local * 60
            assert (repository / "value.py").read_text() == "VALUE = 1\n"
            assert (project / "value.py").read_text() == f"VALUE = {expected_local + 2}\n"
            assert (
                len(
                    [
                        p
                        for p in (root / "control/containers").glob("ws_*.json")
                        if json.loads(p.read_text())["state"] != "REMOVED"
                    ]
                )
                == 1
            )
            details = client.get(f"/api/threads/{tid}/workspaces").json()["workspaces"][0]
            assert details["container"]["id"] == containers[0]
            assert reviewed["workspace_id"] in details["container"]["name"]
            assert len(details["attempts"]) == 1 + local_count + review_count
            assert len({h["run_id"] for h in state["history"]}) == local_count + review_count
            stopped = client.post(
                f"/api/threads/{tid}/workspaces/{reviewed['workspace_id']}/stop-container",
                json={"container_id": containers[0]},
            )
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()["removed"] == [containers[0]]
            assert (project / "value.py").read_text() == f"VALUE = {expected_local + 2}\n"
            events = client.get(f"/api/threads/{tid}/events").json()
            assert any(
                e["event_type"] == "container.removed"
                and e["data"].get("workspace_id") == reviewed["workspace_id"]
                for e in events
            )
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
        for path in (root / "control/containers").glob("ws_*.json"):
            record = json.loads(path.read_text())
            if record["state"] != "REMOVED":
                asyncio.run(
                    sweep(
                        root,
                        record["image"],
                        load_config(Path("config/coder.yaml")).execution,
                        workspace_id=record["workspace_id"],
                    )
                )


@pytest.mark.parametrize("outcome", ["approved", "paid_exhausted", "five_paid_exhausted"])
def test_actual_browser_jobs_loop_reuses_workspace_and_stops(
    candidate, request, monkeypatch, outcome
):  # noqa: F811
    exercise_loop(candidate, request, monkeypatch, outcome)

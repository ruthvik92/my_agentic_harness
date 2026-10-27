"""Execution mode is a validated per-job override, not a mutation of profile defaults."""

import json
import shutil
from pathlib import Path

import pytest
from test_browser_web import completed, login, running


@pytest.mark.parametrize("override", ["persistent", "ephemeral", None])
@pytest.mark.parametrize("profile", ["coder.yaml", "analog.yaml"])
def test_browser_freezes_execution_choice_without_rewriting_profile(tmp_path, override, profile):
    cfgdir = tmp_path / "configs"
    cfgdir.mkdir()
    for name in ("browser.yaml", "coder.yaml", "analog.yaml"):
        shutil.copy2(Path("config") / name, cfgdir / name)
    source = tmp_path / "source"
    source.mkdir()
    original = (cfgdir / profile).read_bytes()
    if profile == "analog.yaml":
        (source / "manual.pdf").write_bytes(b"%PDF-1.4 test fixture")
    captured = []

    def runner(path):
        captured.append(json.loads(path.with_name("config.json").read_text()))
        return {"status": "completed_unverified", "answer": "Ready", "run_id": None}

    with running(tmp_path / "state", runner, cfgdir, source) as (server, client):
        login(server, client)
        tid = client.post("/api/threads", json={"title": "Execution choice"}).json()["thread_id"]
        payload = {"profile_name": profile, "workspace": str(source), "question": "Inspect"}
        if profile == "analog.yaml":
            payload.update(pdf="manual.pdf", page=1)
        if override is not None:
            payload["execution_mode"] = override
        response = client.post(f"/api/threads/{tid}/ask", json=payload)
        assert response.status_code == 202, response.text
        job = completed(client, response.json()["job_id"])
        expected = override or "ephemeral"
        assert job["status"] == "completed"
        assert job["execution_mode"] == expected
        assert captured[0]["execution"]["execution_mode_default"] == expected
        assert captured[0]["execution"]["container_network_enabled"] is False
        saved = client.get(f"/api/threads/{tid}").json()
        assert saved["messages"][-1]["execution_mode"] == expected
        assert (cfgdir / profile).read_bytes() == original
        catalog = client.get("/api/configs").json()["profiles"]
        coder = next(p for p in catalog if p["name"] == profile)
        assert coder["execution"]["execution_mode_default"] == "ephemeral"
        # Another submission without an override keeps the YAML default.
        default_payload = {k: v for k, v in payload.items() if k != "execution_mode"}
        default_payload["question"] = "Next task"
        default = client.post(f"/api/threads/{tid}/ask", json=default_payload)
        assert default.status_code == 202, default.text
        assert completed(client, default.json()["job_id"])["execution_mode"] == "ephemeral"


@pytest.mark.parametrize("override", ["always", "", None, True, [], {}])
def test_invalid_execution_mode_is_rejected_before_job_creation(tmp_path, override):
    cfgdir = tmp_path / "configs"
    cfgdir.mkdir()
    for name in ("browser.yaml", "coder.yaml"):
        shutil.copy2(Path("config") / name, cfgdir / name)
    source = tmp_path / "source"
    source.mkdir()

    def unexpected(_):
        pytest.fail("invalid execution settings must not invoke a runner")

    with running(tmp_path / "state", unexpected, cfgdir, source) as (server, client):
        login(server, client)
        tid = client.post("/api/threads", json={"title": "Invalid choice"}).json()["thread_id"]
        response = client.post(f"/api/threads/{tid}/ask", json={
            "profile_name": "coder.yaml", "workspace": str(source), "question": "Inspect",
            "execution_mode": override,
        })
        assert response.status_code == 400
        assert "execution_mode" in response.json()["error"]
        assert server.jobs.recent() == []


def test_no_tools_profile_cannot_request_persistent_execution(tmp_path):
    cfgdir = tmp_path / "configs"
    cfgdir.mkdir()
    shutil.copy2(Path("config/browser.yaml"), cfgdir / "browser.yaml")
    with running(tmp_path / "state", lambda _: {}, cfgdir, tmp_path) as (server, client):
        login(server, client)
        tid = client.post("/api/threads", json={"title": "Chat"}).json()["thread_id"]
        response = client.post(f"/api/threads/{tid}/ask", json={
            "profile_name": "browser.yaml", "question": "Hello", "execution_mode": "persistent",
        })
        assert response.status_code == 400
        assert "tool-enabled" in response.json()["error"]


def test_browser_persistent_choice_reuses_actual_docker_keeper(tmp_path, request):
    import asyncio

    from local_agent.config import load_config
    from local_agent.doctor import sandbox_config
    from local_agent.executor.docker import DockerExecutor
    from local_agent.mobile.browser_runtime import run_browser
    from local_agent.models.scripted import ScriptedProvider
    from local_agent.storage.database import Store
    from local_agent.workspace.manager import Workspaces

    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    cfgdir = tmp_path / "configs"
    cfgdir.mkdir()
    for name in ("coder.yaml", "browser.yaml"):
        shutil.copy2(Path("config") / name, cfgdir / name)
    source = tmp_path / "source"
    source.mkdir()
    state = tmp_path / "state"
    observed = []

    def runner(path):
        config = load_config(path.with_name("config.json"))
        assert config.execution.execution_mode_default == "persistent"
        provider = ScriptedProvider(responses=tuple(
            {"text": "", "tool_calls": [{"name": "run_command", "arguments": {
                "argv": ["python", "-c", code],
            }}], "finish_status": "tool_calls"}
            for code in (
                "from pathlib import Path; Path('/tmp/browser-state').write_text('kept')",
                "from pathlib import Path; assert Path('/tmp/browser-state').read_text()=='kept'",
            )
        ) + ({"text": "Persistent state verified", "tool_calls": [], "finish_status": "stop"},))
        store = Store(state)

        async def execute():
            try:
                result = await run_browser(store, config, json.loads(path.read_text()),
                                           {**sandbox_config(), "image": image}, provider=provider)
                for event in store.events(result["run_id"]):
                    if event.event_type == "execution.finished":
                        observed.append(store.blobs.json(event.data["result_ref"]))
                return result
            finally:
                executor = DockerExecutor(store, Workspaces(state), image, settings=config.execution)
                manager = executor.make_manager(lambda *_: None)
                for manifest in manager.directory.glob("ws_*.json"):
                    await manager.stop(manifest.stem)

        try:
            return asyncio.run(execute())
        finally:
            store.close()

    with running(state, runner, cfgdir, source) as (server, client):
        login(server, client)
        tid = client.post("/api/threads", json={"title": "Persistent Docker"}).json()["thread_id"]
        response = client.post(f"/api/threads/{tid}/ask", json={
            "profile_name": "coder.yaml", "workspace": str(source), "question": "Check state",
            "execution_mode": "persistent",
        })
        assert response.status_code == 202, response.text
        job = completed(client, response.json()["job_id"])
        assert job["status"] == "completed", job
        assert job["execution_mode"] == "persistent"
    persistent = [r for r in observed if r["execution_mode"] == "persistent"]
    assert len(persistent) == 2
    assert persistent[0]["container_id"] == persistent[1]["container_id"]
    assert all(r["status"] == "succeeded" for r in observed)

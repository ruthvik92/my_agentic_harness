"""Browser interface: config editor and selected coder profile job."""

import json
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from local_agent.config import load_config
from local_agent.mobile.web import BrowserServer

CONFIG_SOURCE = Path("config")


@contextmanager
def running(root, runner, config_dir, workspace):
    server = BrowserServer(
        root,
        config_dir / "browser.yaml",
        host="127.0.0.1",
        port=0,
        runner=runner,
        config_dir=config_dir,
        allowed_roots=[workspace],
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with httpx.Client(
            base_url=url, headers={"Origin": url}, trust_env=False, timeout=5
        ) as client:
            yield server, client
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def login(server, client):
    reply = client.post("/api/login", json={"code": server.pairing_code})
    assert reply.status_code == 200, reply.text
    cookie = reply.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def completed(client, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.02)
    pytest.fail("job did not finish")


def test_config_editor_and_selected_coder_job(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = tmp_path / "state"
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    for name in ("browser.yaml", "coder.yaml"):
        shutil.copy(CONFIG_SOURCE / name, config_dir / name)

    captured = []

    def runner(path):
        request = json.loads(path.read_text())
        config = json.loads(path.parent.joinpath("config.json").read_text())
        captured.append((request, config))
        return {
            "status": "completed_unverified",
            "answer": "ok",
            "run_id": None,
            "audit": {"ok": True},
            "workspace": "isolated-copy",
            "diff_ref": "blob:stub",
        }

    with running(state, runner, config_dir, workspace) as (server, client):
        # Public assets and pre-pairing auth boundary.
        helper = client.get("/config-controls.js")
        assert helper.status_code == 200
        assert helper.headers["content-type"].startswith("application/javascript")
        locations = client.get("/workspace-results.js")
        assert locations.status_code == 200
        assert locations.headers["content-type"].startswith("application/javascript")
        assert client.get("/api/configs").status_code == 401

        login(server, client)

        info = client.get("/api/info").json()
        assert info["interface"] == "browser"
        assert info["default_profile"] == "browser.yaml"

        # Profile catalog lists both example configs as valid agents.
        profiles = client.get("/api/configs").json()["profiles"]
        by_name = {p["name"]: p for p in profiles}
        assert by_name["browser.yaml"]["kind"] == "agent"
        assert by_name["browser.yaml"]["valid"] is True
        assert by_name["coder.yaml"]["kind"] == "agent"
        assert by_name["coder.yaml"]["valid"] is True

        # Config editor: create, hash-guarded update, stale and invalid saves.
        browser_raw = (config_dir / "browser.yaml").read_text()
        clone = client.post(
            "/api/configs/save", json={"name": "clone.yaml", "content": browser_raw}
        )
        assert clone.status_code == 200, clone.text
        clone_body = clone.json()
        assert clone_body["content"] == browser_raw
        clone_hash = clone_body["hash"]
        assert clone_body["metadata"]["name"] == "clone.yaml"

        duplicate = client.post(
            "/api/configs/save", json={"name": "clone.yaml", "content": browser_raw}
        )
        assert duplicate.status_code == 409

        updated_raw = browser_raw + "\n# edited via config editor\n"
        updated = client.post(
            "/api/configs/save",
            json={"name": "clone.yaml", "content": updated_raw, "expected_hash": clone_hash},
        )
        assert updated.status_code == 200, updated.text
        updated_body = updated.json()
        assert updated_body["content"] == updated_raw
        updated_hash = updated_body["hash"]
        assert updated_hash != clone_hash

        stale = client.post(
            "/api/configs/save",
            json={"name": "clone.yaml", "content": browser_raw, "expected_hash": clone_hash},
        )
        assert stale.status_code == 409
        current = client.get("/api/configs/clone.yaml").json()
        assert current["content"] == updated_raw

        invalid = client.post(
            "/api/configs/save",
            json={"name": "broken.yaml", "content": "schema_version: 99\n"},
        )
        assert invalid.status_code == 400

        # Thread + selected coder profile job.
        thread = client.post("/api/threads", json={"title": "coder job"})
        assert thread.status_code == 201, thread.text
        thread_id = thread.json()["thread_id"]

        ask = client.post(
            f"/api/threads/{thread_id}/ask",
            json={
                "profile_name": "coder.yaml",
                "question": "summarize the workspace",
                "workspace": str(workspace),
            },
        )
        assert ask.status_code == 202, ask.text
        job_id = ask.json()["job_id"]

        # Explicit image and cross-provider override are rejected before any model call.
        bad_image = client.post(
            f"/api/threads/{thread_id}/ask",
            json={
                "profile_name": "coder.yaml",
                "question": "with image",
                "workspace": str(workspace),
                "image": None,
            },
        )
        assert bad_image.status_code == 400

        cross_provider = client.post(
            f"/api/threads/{thread_id}/ask",
            json={
                "profile_name": "coder.yaml",
                "question": "override provider",
                "workspace": str(workspace),
                "model_id": "openai:x",
            },
        )
        assert cross_provider.status_code == 400

        job = completed(client, job_id)
        assert job["status"] == "completed"
        assert job["answer"] == "ok"
        assert job["audit"] == {"ok": True}
        assert job["workspace"] == "isolated-copy"
        assert job["source_workspace"] == str(workspace)
        assert job["diff_ref"] == "blob:stub"
        # Frozen config matches the coder profile; tools preserved; coding mode.
        expected_config = load_config(config_dir / "coder.yaml").model_dump(mode="json")
        assert job["profile_name"] == "coder.yaml"
        assert job["tools"] == expected_config["tools"]
        assert job["config_hash"]
        assert job["mode"] == "coding"

        request, config = captured[0]
        assert config == expected_config
        assert request["mode"] == "coding"
        assert request["workspace"] == str(workspace)
        assert request["question"] == "summarize the workspace"
        assert "history" in request
        assert "profile_name" not in request

        # Saved thread carries the frozen profile fields on the final assistant turn.
        saved = client.get(f"/api/threads/{thread_id}").json()
        assistant = [m for m in saved["messages"] if m.get("role") == "assistant"]
        final = assistant[-1]
        assert final["profile_name"] == job["profile_name"]
        assert final["tools"] == job["tools"]
        assert final["config_hash"] == job["config_hash"]
        assert final["workspace"] == job["workspace"]
        assert final["source_workspace"] == str(workspace)
        # Simulate an older stored reply, whose location exists only in its job record.
        raw = server.threads.get(thread_id)
        for message in raw["messages"]:
            message.pop("workspace", None)
            message.pop("source_workspace", None)
        server.threads.update(thread_id, messages=raw["messages"])
        reopened = client.get(f"/api/threads/{thread_id}").json()
        old_reply = next(m for m in reopened["messages"] if m["role"] == "assistant")
        assert old_reply["workspace"] == "isolated-copy"
        assert old_reply["source_workspace"] == str(workspace)

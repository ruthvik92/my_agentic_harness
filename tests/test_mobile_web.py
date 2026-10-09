"""Controller acceptance checks for phone authentication and queued submissions."""

import base64
import json
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from test_mobile_runtime import screenshot

from local_agent.mobile.web import PhoneServer


@contextmanager
def running(root, runner):
    server = PhoneServer(root, Path("config/phone.yaml"), host="127.0.0.1", port=0, runner=runner)
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
        if job["status"] not in ("running", "queued"):
            return job
        time.sleep(0.02)
    pytest.fail("job did not finish")


def raw_post(server, client, headers):
    authority = f"127.0.0.1:{server.server_port}"
    token = client.cookies.get("phone_session")
    request = (
        f"POST /api/ask HTTP/1.1\r\nHost: {authority}\r\n"
        f"Origin: http://{authority}\r\nCookie: phone_session={token}\r\n"
        f"Content-Type: application/json\r\n{headers}\r\n\r\n"
    )
    with socket.create_connection(("127.0.0.1", server.server_port), timeout=5) as connection:
        connection.sendall(request.encode())
        return int(connection.makefile("rb").readline().split()[1])


def test_pairing_access_boundaries_and_submission(tmp_path):
    captured = []

    def runner(path):
        captured.append((path, json.loads(path.read_text())))
        return {
            "status": "completed_unverified",
            "answer": "<script>plain answer</script>",
            "run_id": None,
        }

    with running(tmp_path / "state", runner) as (server, client):
        page = client.get("/")
        assert page.status_code == 200
        assert server.pairing_code not in page.text
        assert "nonce-" in page.headers["content-security-policy"]
        assert "NONCE_VALUE" not in page.text
        helper = client.get("/thread-controls.js")
        assert helper.status_code == 200
        assert helper.headers["content-type"].startswith("application/javascript")
        assert "catalogOptions" in helper.text
        for path in ("/api/info", "/api/jobs", "/api/jobs/" + "a" * 32):
            assert client.get(path).status_code == 401
        assert client.post("/api/ask", json={"question": "hello"}).status_code == 401
        assert client.post("/api/login", json={"code": "wrong"}).status_code == 401
        login(server, client)
        assert raw_post(server, client, "Content-Length: 6291457") == 413
        assert raw_post(server, client, "Content-Length: -1") == 411
        assert raw_post(server, client, "Content-Length: 1\r\nContent-Length: 1") == 411
        assert raw_post(server, client, "Transfer-Encoding: chunked") == 400
        assert client.get("/api/info").json()["model"] == "qwen3.8:27b"
        assert not client.get("/api/info").json()["restart_required"]
        assert client.get("/api/info", headers={"Host": "attacker.example"}).status_code == 403
        assert (
            client.post(
                "/api/ask", json={"question": "hi"}, headers={"Origin": "http://attacker.example"}
            ).status_code
            == 403
        )
        assert client.get("/api/info", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert (
            client.post(
                "/api/ask", content="{", headers={"Content-Type": "application/json"}
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/ask", content="{}", headers={"Content-Type": "text/plain"}
            ).status_code
            == 415
        )
        assert client.post("/api/ask", json={"question": "hi", "command": "no"}).status_code == 400
        image = base64.b64encode(screenshot()).decode()
        history = [
            {"role": "user", "content": "Earlier question"},
            {"role": "assistant", "content": "Earlier answer"},
        ]
        response = client.post(
            "/api/ask", json={"question": "Follow up", "image": image, "history": history}
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]
        job = completed(client, job_id)
        assert job["status"] == "completed", job
        assert job["answer"] == "<script>plain answer</script>"
        assert job["model"] == "qwen3.8:27b"
        assert image not in json.dumps(job)
        assert captured[0][1]["history"] == history
        assert captured[0][1]["image"] == image
        second = client.post("/api/ask", json={"question": "Another"}).json()["job_id"]
        assert completed(client, second)["status"] == "completed"
        assert captured[0][0] != captured[1][0]
        assert captured[0][0].stat().st_mode & 0o077 == 0
        assert client.get("/api/jobs/../../config/phone.yaml").status_code in (403, 404)

    def unexpected(path):
        pytest.fail("completed job was silently replayed after restart")

    interrupted_id = "b" * 32
    interrupted = tmp_path / "state" / "phone" / "jobs" / interrupted_id
    interrupted.mkdir(mode=0o700)
    (interrupted / "status.json").write_text(
        json.dumps({"job_id": interrupted_id, "status": "running", "created": 0})
    )
    with running(tmp_path / "state", unexpected) as (server, client):
        login(server, client)
        assert completed(client, job_id)["answer"] == "<script>plain answer</script>"
        assert completed(client, interrupted_id)["status"] == "interrupted"


def test_failed_audit_is_not_reported_as_completed(tmp_path):
    def runner(path):
        return {"status": "completed_unverified", "answer": "Draft", "audit": {"ok": False}}

    with running(tmp_path / "state", runner) as (server, client):
        login(server, client)
        job_id = client.post("/api/ask", json={"question": "Hello"}).json()["job_id"]
        job = completed(client, job_id)
        assert job["status"] == "failed"
        assert "audit" in job["error"]


def test_assets_stay_with_loaded_server_and_report_updates(tmp_path, monkeypatch):
    with running(tmp_path / "state", lambda _: {}) as (server, client):
        original = client.get("/").text
        monkeypatch.setitem(server.asset_paths, "/", SimpleNamespace(read_bytes=lambda: b"new UI"))
        page = client.get("/").text
        # The per-response nonce changes, while the served application remains pinned.
        assert "model-select" in original and "model-select" in page
        assert "new UI" not in page
        login(server, client)
        assert client.get("/api/info").json()["restart_required"]


def test_bounded_queue_and_interrupted_restart(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def runner(path):
        entered.set()
        assert release.wait(5)
        return {"status": "completed_unverified", "answer": "OK"}

    with running(tmp_path / "state", runner) as (server, client):
        login(server, client)
        try:
            first = client.post("/api/ask", json={"question": "First"})
            assert first.status_code == 202
            assert entered.wait(2)
            accepted = []
            for index in range(8):
                response = client.post("/api/ask", json={"question": str(index)})
                if response.status_code == 202:
                    accepted.append(response.json()["job_id"])
                else:
                    assert response.status_code == 429, response.text
            assert len(accepted) <= 3
        finally:
            release.set()
        assert completed(client, first.json()["job_id"])["status"] == "completed"

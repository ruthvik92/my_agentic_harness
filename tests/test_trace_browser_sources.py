"""Integration tests for multi-source trace browser API (local_agent.observability.browser)."""

import asyncio
import json
import threading

import httpx
import pytest

from local_agent.observability.browser import TraceServer
from local_agent.observability.sources import SourceCatalog
from local_agent.runtime.loop import simulate
from local_agent.storage.database import Store


def start_server(root):
    srv = TraceServer(root, 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, thread


def stop_server(srv, thread):
    srv.shutdown()
    srv.server_close()
    thread.join()


def base_url(srv):
    return f"http://127.0.0.1:{srv.server_port}"


def post_source(client, location, project=None, origin=None, ctype="application/json"):
    headers = {"Content-Type": ctype}
    if origin is not None:
        headers["Origin"] = origin
    body = {"location": location}
    if project is not None:
        body["project"] = project
    return client.post("/api/sources", content=json.dumps(body), headers=headers)


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "root1"
    srv, thread = start_server(root)
    yield srv
    stop_server(srv, thread)


def test_sources_lifecycle(server, tmp_path):
    root1 = server.data_root
    store1 = Store(root1)
    run1 = asyncio.run(simulate(store1))
    store1.close()
    root2 = tmp_path / "root2"
    store2 = Store(root2)
    run2 = asyncio.run(simulate(store2))
    store2.close()
    with httpx.Client(base_url=base_url(server), trust_env=False) as client:
        r = post_source(client, str(root2), "proj2", origin=base_url(server))
        assert r.status_code == 201
        src = r.json()
        assert src["id"] and src["root"] == str(root2)
        listing = client.get("/api/sources").json()
        by_root = {s["root"]: s for s in listing}
        assert by_root[str(root1)]["project"] == root1.name
        assert by_root[str(root2)]["project"] == "proj2"
        runs = client.get("/api/runs").json()
        ids = {row["id"] for row in runs}
        assert run1["run_id"] in ids and run2["run_id"] in ids
        tagged = {row["id"]: row for row in runs}
        assert tagged[run2["run_id"]]["source_id"] == src["id"]
        assert tagged[run2["run_id"]]["project"] == "proj2"
        ev = client.get(f"/api/runs/{run2['run_id']}", params={"source": src["id"]}).json()
        assert ev["run"]["manifest_ref"] and ev["events"]
        assert client.get(f"/api/runs/{run2['run_id']}/audit", params={"source": src["id"]}).json()[
            "ok"
        ]
        evref = ev["run"]["manifest_ref"]
        evd = client.get(
            f"/api/runs/{run2['run_id']}/evidence/{evref[7:]}", params={"source": src["id"]}
        ).json()
        assert evd["ref"] == evref and evd["bytes"] > 0 and "content" in evd
        assert client.get(f"/api/runs/{run1['run_id']}").json()["run"]["manifest_ref"]
        foreign = Store(root2)
        blob = foreign.blobs.put(b"foreign")
        foreign.close()
        assert (
            client.get(
                f"/api/runs/{run2['run_id']}/evidence/{blob[7:]}", params={"source": src["id"]}
            ).status_code
            == 403
        )
        assert client.get("/api/runs/nope", params={"source": src["id"]}).status_code == 404
        assert (
            client.get(f"/api/runs/{run2['run_id']}", params={"source": "unknown"}).status_code
            == 404
        )
        db = root2 / "control" / "agent.db"
        if db.exists():
            db.unlink()


def test_post_origin_and_body_validation(server, tmp_path):
    root2 = tmp_path / "root2"
    store2 = Store(root2)
    asyncio.run(simulate(store2))
    store2.close()
    with httpx.Client(base_url=base_url(server), trust_env=False) as client:
        loc = str(tmp_path / "x")
        assert post_source(client, loc, origin=None).status_code == 403
        assert post_source(client, loc, origin="http://evil.example").status_code == 403
        assert (
            post_source(client, loc, origin=base_url(server), ctype="text/plain").status_code == 400
        )
        null_proj = client.post(
            "/api/sources",
            json={"location": str(root2), "project": None},
            headers={"Origin": base_url(server)},
        )
        assert null_proj.status_code == 400
        nonstring = client.post(
            "/api/sources", json={"location": 123}, headers={"Origin": base_url(server)}
        )
        assert nonstring.status_code == 400
        cross = client.post(
            "/api/sources",
            json={"location": str(root2), "project": "proj2"},
            headers={"Origin": base_url(server), "Sec-Fetch-Site": "cross-site"},
        )
        assert cross.status_code == 403
        bad = client.post(
            "/api/sources",
            content=b"{not json",
            headers={"Origin": base_url(server), "Content-Type": "application/json"},
        )
        assert bad.status_code == 400
        big = client.post(
            "/api/sources",
            content=b"x" * 9000,
            headers={"Origin": base_url(server), "Content-Type": "application/json"},
        )
        assert big.status_code == 413
        r = post_source(client, str(root2), "p2", origin=base_url(server))
        assert r.status_code == 201
        catalog = SourceCatalog(server.data_root)
        assert any(s["root"] == str(root2) for s in catalog.sources())


def test_broken_source_keeps_default_visible(server, tmp_path):
    root1 = server.data_root
    store1 = Store(root1)
    run1 = asyncio.run(simulate(store1))
    store1.close()
    root2 = tmp_path / "root2"
    store2 = Store(root2)
    store2.close()
    with httpx.Client(base_url=base_url(server), trust_env=False) as client:
        r = post_source(client, str(root2), origin=base_url(server))
        assert r.status_code == 201
        sid = r.json()["id"]
        db = root2 / "control" / "agent.db"
        if db.exists():
            db.unlink()
        listing = client.get("/api/sources").json()
        entry = next(s for s in listing if s["id"] == sid)
        assert entry.get("error")
        assert client.get(f"/api/runs/{run1['run_id']}").status_code == 200

"""Readable evidence retains failures and enforces per-job output ownership."""

import asyncio
from types import SimpleNamespace

import pytest
from test_mobile_web import login, running

from local_agent.executor.mock import MockExecutor
from local_agent.mobile.diagnostics import describe_job, describe_run, execution_output
from local_agent.runtime.loop import simulate
from local_agent.storage.database import Store


class LongOutput(MockExecutor):
    async def execute(self, request):
        if request.tool == "run_command":
            self.dispatched.append(request)
            return {
                "output": "failure\n" + "x" * 10000 + "\nEND OF FAILURE",
                "exit_code": 1,
                "status": "failed",
            }
        return await super().execute(request)


@pytest.fixture
def evidence(tmp_path):
    store = Store(tmp_path / "data")
    first = asyncio.run(simulate(store, executor=LongOutput()))
    second = asyncio.run(simulate(store))
    yield store, first["run_id"], second["run_id"]
    store.close()


def test_timeline_rejections_denials_and_retained_output(evidence):
    store, run_id, foreign = evidence
    data = describe_run(store, run_id)
    assert data["counts"] == {
        "model_requests": 3,
        "tool_calls": 4,
        "failed_tools": 3,
        "context_compactions": 0,
    }
    assert [a["status"] for a in data["actions"]] == ["succeeded", "failed", "rejected", "denied"]
    failed = data["actions"][1]
    assert failed["preview_truncated"]
    output = execution_output(store, run_id, failed["execution_id"])
    assert output["text"].endswith("END OF FAILURE")
    assert len(output["text"]) > len(failed["cause"]) >= 2000
    assert not output["capture_limit_reached"]
    with pytest.raises(ValueError, match="does not belong"):
        execution_output(store, foreign, failed["execution_id"])
    job = describe_job(
        store,
        {"run_id": foreign, "job_id": "a" * 32, "workspace_review": {"checks_run_id": run_id}},
    )
    assert job["checks"][0]["run_id"] == run_id


def test_historical_budget_summary_does_not_claim_tests_never_ran(evidence):
    store, run_id, _ = evidence
    events = store.events(run_id)
    events[-1] = events[-1].model_copy(update={"data": {"reason": {"detail": "model turns"}}})
    facade = SimpleNamespace(
        db=store.db,
        blobs=store.blobs,
        events=lambda _: events,
        run=lambda _: {**dict(store.run(run_id)), "status": "budget_exhausted"},
    )
    data = describe_run(facade, run_id, action_limit=1)
    assert "Model-turn limit reached: 3/" in data["summary"]
    assert "model-requested commands are listed below" in data["summary"]
    assert data["actions_omitted"] == 3
    assert len(data["actions"]) == 1
    job = describe_job(facade, {
        "job_id": "a" * 32, "run_id": run_id,
        "workspace_review": {"project_tests": {"status": "passed", "run_id": run_id}},
    })
    assert "No independent controller test result" not in job["summary"]
    assert "Independent controller checks: passed" in job["summary"]
    assert job["tests"][0]["status"] == "passed"


def test_process_limit_cause_precedes_raw_output_and_counts_as_failure(evidence):
    store, run_id, _ = evidence
    row = store.db.execute(
        "SELECT result_ref FROM execution_attempts WHERE result_ref IS NOT NULL ORDER BY rowid"
    ).fetchall()
    target = next(r[0] for r in row if store.blobs.json(r[0])["status"] == "failed")
    original = store.blobs.json
    usage = {"pids": {"after": {"current": 128, "limit": 128}}}

    def read(ref):
        value = original(ref)
        return ({**value, "status": "process_limit", "error": "Docker process/thread limit reached (128 tasks)",
                 "resource_usage": usage} if ref == target else value)

    facade = SimpleNamespace(db=store.db, events=store.events, run=store.run,
                             blobs=SimpleNamespace(json=read, read=store.blobs.read))
    data = describe_run(facade, run_id)
    action = next(a for a in data["actions"] if a["status"] == "process_limit")
    assert action["cause"].startswith("Docker process/thread limit reached")
    assert action["resource_usage"] == usage
    assert action["preview_truncated"]
    assert data["counts"]["failed_tools"] == 3


def test_authenticated_output_routes_and_live_run_resolution(evidence):
    store, run_id, foreign = evidence
    action = describe_run(store, run_id)["actions"][1]
    job_id, other_id = "a" * 32, "b" * 32
    jobs = {
        job_id: {"job_id": job_id, "run_id": None},
        other_id: {"job_id": other_id, "run_id": foreign},
    }
    with running(store.root, lambda _: {}) as (server, client):
        server.jobs.get = jobs.get
        server.usage_jobs = lambda: [{"job_id": job_id, "run_id": run_id}]
        diagnostic = f"/api/jobs/{job_id}/diagnostics"
        output = f"/api/jobs/{job_id}/executions/{action['execution_id']}/output"
        assert client.get(diagnostic).status_code == 401
        assert client.get(output).status_code == 401
        login(server, client)
        reply = client.get(diagnostic)
        assert reply.status_code == 200, reply.text
        assert reply.json()["run_id"] == run_id
        assert reply.json()["job_id"] == job_id
        reply = client.get(output)
        assert reply.status_code == 200, reply.text
        assert reply.json()["text"].endswith("END OF FAILURE")
        assert client.get(output.replace(job_id, other_id)).status_code == 404
        assert client.get(f"/api/jobs/{'c' * 32}/diagnostics").status_code == 404
        jobs[job_id] = {"job_id": job_id}
        server.usage_jobs = lambda: []
        assert client.get(diagnostic).status_code == 404

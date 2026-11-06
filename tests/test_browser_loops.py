import copy
from types import SimpleNamespace

import pytest
from test_review_repair import repair_server  # noqa: F401
from test_workspace_review import candidate, review_config  # noqa: F401

from local_agent.mobile.loops import DEFAULTS, Loops
from local_agent.workspace.git import GitWorktrees
from local_agent.workspace.manager import Workspaces


@pytest.fixture
def loop_case(repair_server, monkeypatch):  # noqa: F811
    server, tid, _, jobs, captured, report, project = repair_server
    ws = report["target"]["workspace_id"]
    cfg = review_config(monkeypatch)
    monkeypatch.setenv(cfg.api_key_env, "test-only-key")
    server.models.select_reviewer = lambda *_a, **_k: cfg
    server.jobs.recent = lambda **_: list(reversed(list(jobs.values())))
    server.usage_jobs = lambda: list(jobs.values())
    counter = 0

    def submit(request, *, config, metadata):
        nonlocal counter
        counter += 1
        job_id = f"{counter + 100:032x}"
        jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "model": config.model,
            "provider": config.provider,
            "created": counter,
            "run_id": None,
            **metadata,
        }
        captured.append((copy.deepcopy(request), config, copy.deepcopy(metadata)))
        return job_id

    server.jobs.submit = submit
    group = {
        "workspace_id": ws,
        "git_workspace": {
            "repository": report["target"]["repository"],
            "working_directory": ".",
        },
        "execution_mode": "persistent",
    }
    monkeypatch.setattr("local_agent.mobile.loops.view", lambda *_: {"workspaces": [group]})

    def submit_review(server, thread_id, payload, *, config_override, extra_metadata):
        job_id = submit(
            payload,
            config=config_override,
            metadata={
                "thread_id": thread_id,
                "kind": "workspace_review",
                **extra_metadata,
            },
        )
        server.threads.update(thread_id, pending_job=job_id)
        return job_id

    monkeypatch.setattr("local_agent.mobile.loops.submit_workspace_review", submit_review)
    server.loops = Loops(server)
    payload = {"workspace_id": ws, "profile_name": "coder.yaml", "authorize_paid": True}

    def finish(loop_id, *, passed=True, approve=False, vary=True, unknown=False):
        state = server.loops.load(loop_id)
        job = jobs[state["active_job_id"]]
        run_id = "run_" + job["job_id"]
        job.update(status="completed", run_id=run_id, audit={"ok": True}, error=None)
        if job["loop_stage"] == "local":
            manager = GitWorktrees(Workspaces(server.root))
            record = manager.load(ws)
            record.update(
                run_id=run_id,
                state="ready_for_review",
                candidate_tree=str(len(captured)) if vary else "unchanged",
            )
            manager.save(record)
            job.update(
                git_workspace=manager.public(ws),
                project_tests={"status": "passed" if passed else "test_failed", "audit": {"ok": True}},
                token_usage={"totals": {"measured_local_total": 50}},
            )
        else:
            job.update(
                workspace_review={
                    "status": "approved" if approve else "changes_requested",
                    "verdict": {
                        "verdict": "approve" if approve else "request_changes",
                        "summary": "Fix the missing case",
                    },
                    "checks_passed": approve,
                    "audit": {"ok": True},
                    "checks_audit": {"ok": True},
                    "inspected_files_and_diff": True,
                    "review_copy_unchanged": True,
                    "checks_copy_unchanged": True,
                    "target": {
                        "candidate_commit": state["reviewed_candidate"],
                        "source_run_id": state["reviewed_source_run"],
                    },
                    "checks": [
                        {"status": "failed", "exit_code": 1, "output": "Missing regression case"}
                    ],
                },
                token_usage={
                    "totals": {
                        "measured_openai_total": 200,
                        "unknown_openai_requests": int(unknown),
                    }
                },
            )
        server.loops.after(job)
        return server.loops.load(loop_id)

    return server, tid, payload, jobs, captured, finish


def test_default_five_paid_reviews_then_local_only_success(loop_case):
    server, tid, payload, jobs, captured, finish = loop_case
    assert DEFAULTS["max_paid_reviews"] == 5
    state = server.loops.start(tid, payload)
    loop_id = state["loop_id"]
    assert captured[0][1].execution.execution_mode_default == "persistent"
    assert "CRLF" in str(captured[0][0]["task_context"]["latest_review"])
    for n in range(5):
        state = finish(loop_id, passed=True)
        assert state["paid_attempts"] == n + 1
        assert state["stage"] == "review"
        state = finish(loop_id)
        assert state["stage"] == "local"
    assert state["paid_attempts"] == 5
    state = finish(loop_id)
    assert state["status"] == "tests_passed_unverified"
    assert state["paid_tokens"] == 1000
    assert len([j for j in jobs.values() if j.get("loop_stage") == "review"]) == 5
    assert len([j for j in jobs.values() if j.get("loop_stage") == "local"]) == 6
    assert all(
        req.get("continue_workspace_id") == payload["workspace_id"]
        for req, _, meta in captured
        if meta.get("loop_stage") == "local"
    )
    assert captured[-1][0]["task_context"]["paid_reviews_remaining"] == 0
    assert "Missing regression case" in str(captured[-1][0]["task_context"]["latest_review"])


def test_loop_stops_early_on_evidence_backed_approval(loop_case):
    server, tid, payload, jobs, _, finish = loop_case
    state = server.loops.start(tid, payload)
    finish(state["loop_id"])
    approved = finish(state["loop_id"], approve=True)
    assert approved["status"] == "approved" and approved["paid_attempts"] == 1
    count = len(jobs)
    previous = next(j for j in jobs.values() if j.get("loop_stage") == "review")
    server.loops.after(previous)
    assert len(jobs) == count  # duplicate callback cannot enqueue or bill again


@pytest.mark.parametrize(
    "mode", ["stop", "deadline", "cycles", "stalled", "unknown_usage", "restart"]
)
def test_loop_guards_do_not_keep_scheduling(loop_case, mode):
    server, tid, payload, jobs, _, finish = loop_case
    if mode in {"cycles", "stalled"}:
        payload["max_paid_reviews"] = 0
    if mode == "cycles":
        payload["max_local_cycles"] = 1
    state = server.loops.start(tid, payload)
    loop_id = state["loop_id"]
    if mode == "stop":
        server.loops.stop(tid, loop_id)
        final = finish(loop_id)
        assert final["status"] == "stopped" and final["paid_attempts"] == 0
    elif mode == "deadline":
        state["deadline"] = 0
        server.loops.save(state)
        assert finish(loop_id)["status"] == "time_limit"
    elif mode == "cycles":
        assert finish(loop_id, passed=False)["status"] == "cycle_limit"
    elif mode == "stalled":
        for _ in range(3):
            final = finish(loop_id, passed=False, vary=False)
        assert final["status"] == "stalled"
    elif mode == "unknown_usage":
        finish(loop_id)
        final = finish(loop_id, unknown=True)
        assert final["paid_disabled"]
        final = finish(loop_id)
        assert final["status"] == "tests_passed_unverified" and final["paid_attempts"] == 1
    else:
        finish(loop_id)
        count = len(jobs)
        server.loops = Loops(server)
        assert server.loops.load(loop_id)["status"] == "interrupted"
        assert len(jobs) == count
        assert server.loops.load(loop_id)["paid_attempts"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"authorize_paid": False},
        {"max_paid_reviews": 21},
        {"max_paid_reviews": True},
        {"model_id": "openai:gpt-6.1-sol"},
        {"workspace": "/forged"},
    ],
)
def test_start_validates_authorization_limits_and_local_model(loop_case, change):
    server, tid, payload, jobs, captured, _ = loop_case
    with pytest.raises(ValueError):
        server.loops.start(tid, {**payload, **change})
    assert not captured


def test_paid_request_budget_reserves_input_output_and_blocks_unknown_retry():
    from local_agent.runtime.agent import Agent, BudgetExhausted

    data = {
        "request": {"provider": "openai"},
        "response": {"usage": {"prompt_tokens": 30, "completion_tokens": 20}},
    }
    rows = [("request", "response")]
    agent = SimpleNamespace(
        config=SimpleNamespace(provider="openai", paid_token_limit=100, output_reserve_tokens=20),
        store=SimpleNamespace(
            db=SimpleNamespace(execute=lambda *_: rows),
            blobs=SimpleNamespace(json=lambda key: data[key]),
        ),
        run_id="run_budget",
    )
    snapshot = SimpleNamespace(token_estimate=40)
    with pytest.raises(BudgetExhausted, match="allowance"):
        Agent.check_paid_budget(agent, snapshot)
    agent.config.paid_token_limit = 120
    Agent.check_paid_budget(agent, snapshot)
    rows[0] = ("request", None)
    with pytest.raises(BudgetExhausted, match="unknown"):
        Agent.check_paid_budget(agent, snapshot)
    rows[0] = ("request", "response")
    data["response"]["usage"] = {}
    with pytest.raises(BudgetExhausted, match="unknown"):
        Agent.check_paid_budget(agent, snapshot)


def test_job_is_publicly_complete_only_after_callback_persists(tmp_path):
    import threading
    import time
    from pathlib import Path

    from local_agent.config import load_config
    from local_agent.mobile.jobs import Jobs

    entered, release = threading.Event(), threading.Event()

    def callback(job):
        assert jobs.get(job["job_id"])["status"] == "completed"
        entered.set()
        release.wait(5)

    jobs = Jobs(
        tmp_path,
        Path("config/browser.yaml"),
        load_config(Path("config/browser.yaml")),
        runner=lambda _: {"status": "completed_unverified", "answer": "Done"},
        on_result=callback,
    )
    try:
        job_id = jobs.submit({"question": "Test"})
        assert entered.wait(5)
        assert jobs.get(job_id)["status"] == "running"
        release.set()
        for _ in range(100):
            if jobs.get(job_id)["status"] == "completed":
                break
            time.sleep(0.01)
        assert jobs.get(job_id)["status"] == "completed"
    finally:
        release.set()
        jobs.close()


@pytest.mark.parametrize('timed_out', [False, True])
def test_controller_error_keeps_the_progress_run_and_workspace(tmp_path, timed_out):
    import asyncio
    import json
    import subprocess
    import time
    from pathlib import Path

    from local_agent.config import load_config
    from local_agent.mobile.jobs import Jobs
    from local_agent.runtime.loop import simulate
    from local_agent.storage.database import Store

    store = Store(tmp_path)
    result = asyncio.run(simulate(store))
    manifest = store.blobs.json(store.run(result["run_id"])["manifest_ref"])
    store.close()

    def runner(path):
        path.with_name("progress.json").write_text(json.dumps({"run_id": result["run_id"]}))
        if timed_out:
            raise subprocess.TimeoutExpired(['controller'], 25)
        raise RuntimeError("Controller timed out before returning JSON")

    jobs = Jobs(
        tmp_path,
        Path("config/browser.yaml"),
        load_config(Path("config/browser.yaml")),
        runner=runner,
    )
    try:
        job_id = jobs.submit({"question": "Test"})
        for _ in range(200):
            job = jobs.get(job_id)
            if job["status"] == "failed":
                break
            time.sleep(0.01)
        assert job["status"] == "failed"
        assert job["run_id"] == result["run_id"]
        assert job["workspace_id"] == manifest["workspace_id"]
        assert "timed out" in job["error"]
        if timed_out:
            assert job['timeout_recovery'] == {'status': result['status'], 'retired': False}
    finally:
        jobs.close()


def failed_local(server, loop_id, jobs):
    state = server.loops.load(loop_id)
    job = jobs[state['active_job_id']]
    job.update(status='failed',run_id=None,error='Ollama HTTP status 500: invalid tool call arguments',
               token_usage={'totals':{'measured_local_total':100}})
    server.loops.after(job)
    return server.loops.load(loop_id)


@pytest.mark.parametrize('unknown', [False, True])
def test_failed_local_rescue_is_advisory_bounded_and_budgeted(loop_case, unknown):
    server, tid, payload, jobs, captured, _ = loop_case
    state = server.loops.start(tid, {**payload,'max_paid_reviews':1})
    lid=state['loop_id']
    state=failed_local(server,lid,jobs)
    assert state['stage']=='local' and state['paid_attempts']==0
    state=failed_local(server,lid,jobs)
    assert state['stage']=='diagnostic' and state['paid_attempts']==1
    assert state['diagnostic_attempts']==1
    request,cfg,metadata=captured[-1]
    assert request['mode']=='chat' and not request['history']
    assert cfg.tools==() and cfg.limits.max_model_turns==1
    assert cfg.paid_token_limit==state['limits']['paid_token_budget']
    assert 'no filesystem' in request['question']
    assert metadata['loop_stage']=='diagnostic'
    job=jobs[state['active_job_id']]
    job.update(status='completed',answer='Use cwd=project and read current file hash before replacing.',
               token_usage={'totals':{'measured_openai_total':200,'unknown_openai_requests':int(unknown)}})
    server.loops.after(job)
    state=server.loops.load(lid)
    assert state['status']=='running' and state['stage']=='local'
    assert state['paid_tokens']==200 and state['paid_attempts']==1
    assert state['last_review']['verified'] is False
    assert state['last_review']['kind']=='advisory_diagnosis'
    assert state['paid_disabled'] is unknown
    assert 'cwd=project' in str(captured[-1][0]['task_context']['latest_review'])
    count=len(jobs)
    server.loops.after(job)
    assert len(jobs)==count  # duplicate callback cannot repeat diagnosis
    state=failed_local(server,lid,jobs)
    assert state['paid_attempts']==1
    assert len([j for j in jobs.values() if j.get('loop_stage')=='diagnostic'])==1


def test_no_paid_diagnosis_without_allowance_or_when_stopped(loop_case):
    server, tid, payload, jobs, _, _=loop_case
    state=server.loops.start(tid,{**payload,'max_paid_reviews':0,'authorize_paid':False})
    lid=state['loop_id']
    failed_local(server,lid,jobs)
    state=failed_local(server,lid,jobs)
    assert state['paid_attempts']==0
    assert not any(j.get('loop_stage')=='diagnostic' for j in jobs.values())
    server.loops.stop(tid,lid)
    state=failed_local(server,lid,jobs)
    assert state['status']=='stopped' and state['paid_attempts']==0


def test_failed_independent_checks_do_not_spend_paid_attempts(loop_case):
    server, tid, payload, jobs, captured, finish = loop_case
    payload['max_local_cycles'] = 2
    state = server.loops.start(tid, payload)
    state = finish(state['loop_id'], passed=False)
    assert state['stage'] == 'local' and state['paid_attempts'] == 0
    state = finish(state['loop_id'], passed=False)
    assert state['status'] == 'cycle_limit' and state['paid_attempts'] == 0
    assert not any(job.get('loop_stage') == 'review' for job in jobs.values())


def test_unchanged_tree_and_evidence_do_not_trigger_another_paid_review(loop_case):
    server, tid, payload, jobs, captured, finish = loop_case
    state = server.loops.start(tid, payload)
    state = finish(state['loop_id'], vary=False)
    assert state['paid_attempts'] == 1
    state = finish(state['loop_id'])  # paid reviewer requests a change
    assert state['stage'] == 'local'
    state = finish(state['loop_id'], vary=False)
    assert state['status'] == 'review_blocked'
    assert state['paid_attempts'] == 1
    assert 'already reviewed' in state['review_eligibility']['reason']


def test_local_stall_stops_loop_without_paid_rescue(loop_case):
    server, tid, payload, jobs, captured, finish = loop_case
    state = server.loops.start(tid, payload)
    job = jobs[state['active_job_id']]
    job.update(status='failed', error='Local stalled', run_id=None,
               repair_progress={'decision': 'local_stalled', 'mode': 'enforce'})
    server.loops.after(job)
    state = server.loops.load(state['loop_id'])
    assert state['status'] == 'local_stalled' and state['paid_attempts'] == 0
    assert not any(job.get('loop_stage') in {'review', 'diagnostic'} for job in jobs.values())


def test_pre_run_failure_keeps_original_error_instead_of_unknown_run(loop_case):
    from local_agent.storage.database import Store

    server, tid, payload, jobs, captured, _ = loop_case
    state = server.loops.start(tid, payload)
    store = Store(server.root)
    store.close()
    job = jobs[state['active_job_id']]
    job.update(status='failed', run_id='run_' + 'a' * 32,
               error='Previous task is active; stop or finish it before continuing')
    server.loops.after(job)
    result = server.loops.load(state['loop_id'])
    assert result['status'] == 'blocked'
    assert 'Previous task is active' in result['reason']
    assert 'before a durable run was created' in result['reason']
    assert 'unknown run' not in result['reason']
    assert result['paid_attempts'] == 0
    assert len(captured) == 1



def completion_payload(payload, **extra):
    return {**payload, 'mode': 'completion', 'authorize_paid': False, 'max_paid_reviews': 0, **extra}


@pytest.mark.parametrize("mode", ["completion", "approval"])
def test_loop_retains_history_limit_across_attempts(loop_case, mode):
    server, tid, payload, _, captured, finish = loop_case
    state = server.loops.start(tid, {
        **payload, "mode": mode, "authorize_paid": False,
        "max_paid_reviews": 0, "n_last_chats": 2,
    })
    first = captured[-1][0]["task_context"]["attempts"][0]["run_id"]
    for _ in range(3):
        assert state["n_last_chats"] == 2
        context = captured[-1][0]["task_context"]
        assert context["n_last_chats"] == captured[-1][2]["n_last_chats"] == 2
        assert context["attempts"][0]["run_id"] == first
        assert len(context["attempts"]) <= 2
        previous_run = "run_" + state["active_job_id"]
        state = finish(state["loop_id"], passed=False)
        assert state["status"] == "running"
        assert captured[-1][0]["task_context"]["attempts"][-1]["run_id"] == previous_run
    server.loops.stop(tid, state["loop_id"])


@pytest.mark.parametrize("value", [True, 0, 101, "3", 2.5, None])
def test_loop_rejects_invalid_history_limit_before_submission(loop_case, value):
    server, tid, payload, _, captured, _ = loop_case
    with pytest.raises(ValueError, match="n_last_chats"):
        server.loops.start(tid, {**payload, "n_last_chats": value})
    assert not captured


def test_completion_requires_published_candidate_checks_and_both_audits(loop_case):
    server, tid, payload, jobs, captured, finish = loop_case
    state = server.loops.start(tid, completion_payload(payload, run_limit_minutes=7))
    assert state['run_timeout_seconds'] == 420
    assert captured[-1][1].limits.run_timeout_seconds <= 420
    state = finish(state['loop_id'])
    assert state['status'] == 'complete'
    assert state['reason'] == 'Complete — checks passed; not reviewer-approved.'
    assert state['paid_attempts'] == 0
    assert not any(j.get('loop_stage') != 'local' for j in jobs.values() if j.get('loop_id'))


@pytest.mark.parametrize('broken', ['candidate', 'checks_audit', 'run_audit', 'checks', 'stale'])
def test_completion_rejects_incomplete_evidence(loop_case, broken):
    server, tid, payload, jobs, _, _ = loop_case
    state = server.loops.start(tid, completion_payload(payload, max_local_cycles=1))
    job = jobs[state['active_job_id']]
    manager = GitWorktrees(Workspaces(server.root))
    record = manager.load(payload['workspace_id'])
    record.update(run_id='run_new', candidate_tree='tree')
    manager.save(record)
    job.update(status='completed', run_id='run_new', audit={'ok': True},
               git_workspace=manager.public(payload['workspace_id']),
               project_tests={'status': 'passed', 'audit': {'ok': True}})
    if broken == 'candidate':
        job['git_workspace']['candidate_commit'] = None
    elif broken == 'checks_audit':
        job['project_tests']['audit'] = {'ok': False}
    elif broken == 'run_audit':
        job['audit'] = {'ok': False}
    elif broken == 'checks':
        job['project_tests']['status'] = 'no_test_plan'
    else:
        record['run_id'] = 'run_other'
        manager.save(record)
    server.loops.after(job)
    final = server.loops.load(state['loop_id'])
    assert final['status'] == 'budget_exhausted'
    assert final['completion_blocker']
    assert final['paid_attempts'] == 0


@pytest.mark.parametrize('extra', [{'authorize_paid': True}, {'max_paid_reviews': 1},
                                 {'reviewer_model_id': 'openai:forbidden'}])
def test_completion_rejects_paid_settings_before_model_selection(loop_case, extra):
    server, tid, payload, _, captured, _ = loop_case
    server.models.select_reviewer = lambda *_a, **_kw: pytest.fail('paid reviewer selected')
    with pytest.raises(ValueError, match='local-only'):
        server.loops.start(tid, completion_payload(payload, **extra))
    assert not captured


def test_completion_failures_never_invoke_paid_diagnosis_even_with_forged_allowance(loop_case):
    server, tid, payload, jobs, _, _ = loop_case
    server.models.select_reviewer = lambda *_a, **_kw: pytest.fail('paid reviewer selected')
    state = server.loops.start(tid, completion_payload(payload))
    lid = state['loop_id']
    # A restored state must still guard both entry points independently.
    state.update(paid_authorized=True)
    state['limits']['max_paid_reviews'] = 5
    server.loops.save(state)
    server.loops.queue_diagnosis(state)
    failed_local(server, lid, jobs)
    final = failed_local(server, lid, jobs)
    assert final['stage'] == 'local' and final['paid_attempts'] == 0
    assert not any(j.get('loop_stage') in {'review', 'diagnostic'} for j in jobs.values())


def test_attempt_runtime_inherits_profile_and_is_capped_by_remaining_budget(loop_case):
    import time

    server, tid, payload, _, captured, _ = loop_case
    expected = server.profiles.load('coder.yaml').limits.run_timeout_seconds
    state = server.loops.start(tid, completion_payload(payload))
    assert state['run_timeout_seconds'] == expected
    state['deadline'] = time.time() + 35
    server.threads.update(tid, pending_job=None)
    server.loops.queue_local(state)
    assert 1 <= captured[-1][1].limits.run_timeout_seconds <= 35
    assert captured[-1][2]['loop_deadline'] == state['deadline']


def test_completion_stop_restart_and_budget_do_not_replay_jobs(loop_case):
    server, tid, payload, jobs, _, finish = loop_case
    state = server.loops.start(tid, completion_payload(payload))
    lid = state['loop_id']
    count = len(jobs)
    assert server.loops.stop(tid, lid)['status'] == 'interrupted'
    assert finish(lid)['status'] == 'interrupted'
    assert len(jobs) == count
    server.threads.update(tid, pending_job=None)
    state = server.loops.start(tid, completion_payload(payload))
    server.loops = Loops(server)
    assert server.loops.load(state['loop_id'])['status'] == 'interrupted'
    assert len(jobs) == count + 1


def test_unresolved_checks_changes_and_nondeterminism_survive_next_attempt(loop_case):
    server, tid, payload, jobs, captured, _ = loop_case
    state = server.loops.start(tid, completion_payload(payload))
    lid = state['loop_id']
    for n in range(2):
        state = server.loops.load(lid)
        job = jobs[state['active_job_id']]
        job.update(status='failed', run_id=None, error=f'assert score == {n}',
                   project_tests={'status': 'test_failed', 'commands': [
                       {'argv': ['pytest'], 'status': 'failed', 'output': f'AssertionError: {n}'}]})
        server.loops.after(job)
    state = server.loops.load(lid)
    assert state['possible_nondeterminism']
    context = captured[-1][0]['task_context']
    assert context['unresolved_checks'][0]['argv'] == ['pytest']
    assert 'nondeterminism' in context['recovery_plan']
    assert context['git_history']['sandbox'].startswith('Project copy')
    # Varying text alone does not indefinitely reset the stall detector.
    state = failed_local(server, lid, jobs)
    # Test status changed once; continued identical status must eventually stop.
    for _ in range(3):
        if state['status'] != 'running':
            break
        state = failed_local(server, lid, jobs)
    assert state['status'] == 'stalled'

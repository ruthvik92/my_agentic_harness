import asyncio

import pytest

from local_agent.executor.mock import MockExecutor
from local_agent.mobile.timeout_recovery import retire_timed_out_run
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.runtime.loop import simulate
from local_agent.storage.database import Store
from local_agent.storage.locks import run_lock


class ControllerCrash(BaseException):
    pass


class CrashingProvider(ScriptedProvider):
    async def generate(self, request):
        raise ControllerCrash()


class CrashingExecutor(MockExecutor):
    async def execute(self, request):
        raise ControllerCrash()


@pytest.mark.parametrize('pending', [False, True])
def test_killed_controller_is_retired_without_inference_or_replaying_executions(tmp_path, monkeypatch, pending):
    store = Store(tmp_path)
    with pytest.raises(ControllerCrash):
        asyncio.run(simulate(store, **(
            {'executor': CrashingExecutor()} if pending else {'provider': CrashingProvider()}
        )))
    run_id = store.db.execute('SELECT id FROM runs').fetchone()[0]
    assert store.run(run_id)['status'] == 'running'
    before = store.db.execute('SELECT COUNT(*) FROM model_requests').fetchone()[0]
    cleanup = []

    async def emergency_cleanup(self, run):
        cleanup.append(run)

    monkeypatch.setattr('local_agent.executor.docker.DockerExecutor.emergency_cleanup', emergency_cleanup)
    result = retire_timed_out_run(tmp_path, run_id)
    assert result['retired'] is True
    assert result['status'] == ('needs_reconciliation' if pending else 'budget_exhausted')
    assert bool(result['pending_execution_ids']) is pending
    assert cleanup == ([run_id] if pending else [])
    assert store.db.execute('SELECT COUNT(*) FROM model_requests').fetchone()[0] == before
    if not pending:
        assert audit(store, run_id)['ok']
    assert retire_timed_out_run(tmp_path, run_id)['retired'] is False
    store.close()


def test_timeout_recovery_refuses_to_touch_an_active_controller(tmp_path):
    store = Store(tmp_path)
    with run_lock(store.control), pytest.raises(RuntimeError, match='another coding run'):
        retire_timed_out_run(tmp_path, 'run_' + 'a' * 32)
    store.close()

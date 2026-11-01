"""Task limits are operator grants; exhaustion is kernel evidence, never stderr guessing."""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from local_agent.contracts import ExecutionSettings
from local_agent.executor import worker
from local_agent.executor.docker import DockerExecutor, docker
from local_agent.executor.resources import PidsMonitor, exhausted
from local_agent.observability.audit import audit
from local_agent.policy.engine import LEGACY_OFFLINE_HASH, offline_evaluate
from local_agent.runtime.tool_results import result_preview
from local_agent.tools.registry import normalize


@pytest.mark.parametrize('bad', [True, '256', 128.0, 63, 1025, 0, -1])
def test_operator_pid_limit_is_strict_and_bounded(bad):
    with pytest.raises(ValidationError):
        ExecutionSettings(container_pids_limit=bad)


def test_limits_reach_creation_worker_normalization_and_policy():
    assert ExecutionSettings().container_pids_limit == 128
    settings = ExecutionSettings(container_pids_limit=256)
    executor = DockerExecutor(None, None, 'sha256:' + 'a' * 64, settings=settings)
    args = executor.create_args(Path('/workspace'))
    assert args[args.index('--pids-limit') + 1] == '256'
    assert worker.validate_execution_options({'pids_limit': 256})['pids_limit'] == 256
    with pytest.raises(ValueError):
        worker.validate_execution_options({'pids_limit': True})
    request = normalize('run_command', {'argv': ['true']}, pids_limit=256)
    assert request['effective_limits']['pids'] == 256
    assert offline_evaluate('call_' + 'a' * 32, request, 'blob://' + 'b' * 64,
                            ('run_command',)).verdict == 'allow'
    assert offline_evaluate('call_' + 'a' * 32, request, 'blob://' + 'b' * 64,
                            ('run_command',), policy_hash=LEGACY_OFFLINE_HASH).verdict == 'deny'
    with pytest.raises(ValueError):
        normalize('run_command', {'argv': ['true'], 'pids_limit': 1024})


def test_monitor_reads_actual_bound_cgroup_and_ignores_historical_hits(tmp_path):
    cid = 'a' * 64
    proc = tmp_path / 'proc/123'
    proc.mkdir(parents=True)
    (proc / 'cgroup').write_text('0::/system.slice/docker-' + cid + '.scope\n')
    root = tmp_path / 'cgroup'
    group = root / 'system.slice' / ('docker-' + cid + '.scope')
    group.mkdir(parents=True)
    for name, value in {'current': '4', 'max': '128', 'events': 'max 428', 'peak': '134'}.items():
        (group / ('pids.' + name)).write_text(value)
    monitor = PidsMonitor({'Id': cid, 'State': {'Pid': 123}}, proc_root=proc.parent, cgroup_root=root)
    before = monitor.sample()
    assert before['max_events'] == 428 and before['peak'] == 134
    assert not exhausted(before, before, failed=True)
    assert not exhausted(before, {**before, 'max_events': 429}, failed=False)
    assert exhausted(before, {**before, 'max_events': 429}, failed=True)
    assert exhausted(before, {**before, 'current': 128}, failed=True)
    assert not exhausted(before, None, failed=True)
    (group / 'pids.current').write_text('129')
    assert monitor.sample()['current'] == 129
    (proc / 'cgroup').write_text('0::/unrelated\n')
    forged = PidsMonitor({'Id': cid, 'State': {'Pid': 123}}, proc_root=proc.parent, cgroup_root=root)
    assert forged.sample() is None
    assert forged.unavailable


def test_process_limit_feedback_includes_diagnosis_and_unknown_side_effects():
    result = SimpleNamespace(status='process_limit', exit_code=1, preview='raw failure',
                             output_ref='blob://' + 'a' * 64, truncated=False,
                             error='Docker process/thread limit reached (128 tasks)',
                             resource_usage={'pids': {'current': 128}}, side_effect_status='unknown')
    feedback = result_preview(None, result, 'run_command')
    assert feedback['error'] == result.error
    assert feedback['resource_usage'] == result.resource_usage
    assert feedback['side_effect_status'] == 'unknown'


@pytest.mark.parametrize('limit', [128, 256])
def test_attestation_and_cleanup_accept_only_exact_operator_limits(tmp_path, monkeypatch, limit):
    from local_agent.executor.maintenance import cleanup_attestor

    monkeypatch.setattr(os, 'getuid', lambda: 1000)
    monkeypatch.setattr(os, 'getgid', lambda: 1000)
    workspace = tmp_path / 'workspace'
    host = dict(ReadonlyRootfs=True, NetworkMode='none', Privileged=False, CapDrop=['ALL'],
                SecurityOpt=['no-new-privileges'], Memory=4096 * 1024**2,
                MemorySwap=4096 * 1024**2, NanoCpus=4_000_000_000, PidsLimit=limit,
                PidMode='', Devices=[], DeviceRequests=[], Tmpfs={'/tmp': 'rw'})
    info = {'Image': 'sha256:' + 'a' * 64, 'HostConfig': host,
            'Config': {'User': '1000:1000'},
            'Mounts': [{'Source': str(workspace), 'Destination': '/workspace', 'RW': True}]}
    executor = DockerExecutor(None, None, info['Image'], settings=ExecutionSettings(container_pids_limit=limit))
    assert executor.attest(info, workspace)['checks']['pids']
    assert cleanup_attestor(None, None)(info, workspace)['checks']['pids']
    host['PidsLimit'] += 1
    with pytest.raises(RuntimeError, match='pids'):
        executor.attest(info, workspace)


def test_worker_attests_configured_task_limit(tmp_path, monkeypatch):
    from test_worker_execution_options import _make_cgroup_dir, _make_status_file

    status = _make_status_file(tmp_path)
    group = _make_cgroup_dir(tmp_path)
    (group / 'pids.max').write_text('256\n')
    real_open = open

    def fake_open(path, *a, **kw):
        if path == '/proc/self/status':
            return real_open(status)
        if str(path).startswith('/sys/fs/cgroup/'):
            return real_open(group / str(path).split('/')[-1])
        return real_open(path, *a, **kw)

    monkeypatch.setattr(worker, 'open', fake_open, raising=False)
    monkeypatch.setattr(worker.os, 'getuid', lambda: 1000)
    worker.attest_limits(pids_limit=256)
    with pytest.raises(RuntimeError):
        worker.attest_limits(pids_limit=128)


@pytest.mark.parametrize('already_full', [False, True])
@pytest.mark.parametrize('limit', [64, 128])
def test_real_exhaustion_recycles_keeper_without_replaying_mutation(tmp_path, request, already_full, limit):
    from conftest import Sandbox

    from local_agent.observability.spans import Spans

    image = request.config.getoption('--docker-image')
    if not image:
        pytest.skip('requires --docker-image')
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'count').write_text('')
    spans = Spans()
    settings = ExecutionSettings(execution_mode_default='persistent', container_pids_limit=limit)
    fill = '''import threading,time
threads=[]
try:
 while True:
  t=threading.Thread(target=time.sleep,args=(30,),daemon=True);t.start();threads.append(t)
except RuntimeError:
 pass
time.sleep(30)
'''
    with spans.boundary('test.process-limit'):
        sandbox = Sandbox(tmp_path / 'data', source, image, settings=settings)
        try:
            async def scenario():
                ordinary = await sandbox.execute('run_command', {'argv': ['python', '-c', 'raise SystemExit(1)']})
                assert ordinary.status == 'failed'
                keeper = ordinary.container_id
                if already_full:
                    await docker('exec', '-d', keeper, 'python', '-c', fill)
                    for _ in range(100):
                        sample = PidsMonitor(await sandbox.executor.inspect(keeper)).sample()
                        if sample and sample['current'] >= limit:
                            break
                        await asyncio.sleep(.05)
                    else:
                        pytest.fail('controlled exhaustion did not fill the cgroup')
                    code = "from pathlib import Path; p=Path('count');p.write_text(p.read_text()+'X')"
                else:
                    code = "from pathlib import Path; p=Path('count');p.write_text(p.read_text()+'X')\n" + fill
                result = await sandbox.execute('run_command', {'argv': ['python', '-c', code], 'cwd': 'project', 'timeout_seconds': 10})
                assert result.status == 'process_limit', result
                assert result.side_effect_status == 'unknown'
                assert 'not replayed' in result.error
                assert result.resource_usage['pids']['after']['limit'] == limit
                assert sandbox.executor.make_manager(lambda *_: None).load(sandbox.workspace_id)['state'] == 'REMOVED'
                later = await sandbox.execute('run_command', {'argv': ['python', '-c', "from pathlib import Path; print(Path('count').read_text())"], 'cwd': 'project'})
                assert later.status == 'succeeded', later
                assert later.container_id != keeper
                assert (sandbox.path / 'project/count').read_text() == ('' if already_full else 'X')
                assert (await sandbox.executor.inspect(later.container_id))['Image'] == image
                events = sandbox.store.events(sandbox.run_id)
                assert any(e.event_type == 'execution.resource_limited' and e.data.get('resource') == 'pids' for e in events)
                report = audit(sandbox.store, sandbox.run_id)
                assert report['ok'], report['errors']
            asyncio.run(scenario())
        finally:
            asyncio.run(sandbox.executor.make_manager(lambda *_: None).stop(sandbox.workspace_id))
            sandbox.store.close()
            spans.shutdown()

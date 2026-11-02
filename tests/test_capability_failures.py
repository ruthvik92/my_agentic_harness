"""Command diagnoses route recovery without guessing installs or replaying mutations."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from test_environment_requests import agent, call, docker  # noqa: F401

from local_agent.environments.browser_support import stage
from local_agent.observability.audit import audit
from local_agent.runtime.capability_failures import (
    cached,
    diagnose,
    fixed_context,
    guidance,
    record,
)


@pytest.mark.parametrize('status,code,output,kind', [
    ('failed', 1, "Error: Cannot find module 'ws'\ncode: MODULE_NOT_FOUND", 'missing_dependency'),
    ('failed', 1, "ModuleNotFoundError: No module named 'playwright'", 'missing_dependency'),
    ('failed', 127, 'chromium: command not found', 'missing_executable'),
    ('failed', 1, 'FileNotFoundError: tests/input.json', 'missing_path'),
    ('failed', 1, 'AssertionError: expected score 10', 'test_failure'),
    ('process_limit', None, 'Cannot find module ws', 'process_limit'),
    ('timeout', 124, 'FAILED', 'timeout'),
    ('failed', -9, '', 'command_error'),
    ('cancelled', None, '', 'cancelled'),
    ('output_limit', None, '', 'output_limit'),
    ('succeeded', 0, 'AssertionError in a documentation example', 'none'),
    ('failed', 1, '{"runner":"harness_browser_test","status":"invalid_plan"}', 'invalid_plan'),
])
def test_failure_routes(status, code, output, kind):
    failure = diagnose(status, code, output)
    assert failure['kind'] == kind
    if kind in {'missing_executable', 'missing_dependency'}:
        assert failure['next_action'] == 'prepare_environment'
        assert 'Changing cwd' in guidance(failure)
        assert 'arbitrary package' in guidance(failure)


def test_browser_alternative_only_advertised_when_verified():
    assert diagnose('failed', 1, 'Docker process/thread limit reached')['kind'] == 'command_error'
    failure = diagnose('failed', 1, "Cannot find module 'ws'")
    assert 'already verified' not in guidance(failure)
    message = guidance(failure, {'capabilities': {'browser_interaction': {'available': True}}})
    assert '/workspace/tools/harness_browser_test.py' in message


@pytest.mark.parametrize('output', [
    "Error: Cannot find module '/workspace/project/scratch/find_seed.js'\nMODULE_NOT_FOUND",
    "Error: Cannot find module './helper.js'\nMODULE_NOT_FOUND",
    "Error: Cannot find module '../js/game.js'\nMODULE_NOT_FOUND",
    "Error: Cannot find module 'scratch/helper.js'\nMODULE_NOT_FOUND",
    "Error: Cannot find module 'C:\\work\\helper.js'\nMODULE_NOT_FOUND",
    "Error: ENOENT: no such file or directory, open '/workspace/js/leaderboard.js'",
])
def test_local_files_are_not_cached_as_missing_dependencies(output):
    failure = diagnose('failed', 1, output)
    assert failure['kind'] == 'missing_path'
    assert failure['next_action'] == 'inspect_arguments'
    hint = guidance(failure)
    assert "cwd='project'" in hint
    assert '/workspace/scratch/helper.js' in hint
    assert 'prepare_environment' not in hint


@pytest.mark.parametrize('output', [
    "Error: Cannot find module 'ws'\nMODULE_NOT_FOUND",
    "Error: Cannot find package '@scope/package' imported from /workspace/project/test.mjs",
    "ModuleNotFoundError: No module named 'pydantic'",
])
def test_external_dependencies_direct_model_to_docker_preparation(output):
    failure = diagnose('failed', 1, output)
    assert failure['kind'] == 'missing_dependency'
    assert failure['next_action'] == 'prepare_environment'
    hint = guidance(failure)
    for field in ('environment_inventory', 'prepare_environment', 'runtimes',
                  'python_packages', 'dependency_manifests', 'project/package-lock.json'):
        assert field in hint


def test_missing_runtime_launch_is_distinct_from_a_missing_script_input():
    output = json.dumps({'error': 'FileNotFoundError',
                         'detail': "[Errno 2] No such file or directory: 'node'"})
    failure = diagnose('failed', 1, output, arguments={'argv': ['node', 'tests/check.js']})
    assert failure['kind'] == 'missing_executable'
    assert failure['subject'] == 'node'
    assert failure['next_action'] == 'prepare_environment'
    assert 'runtimes' in guidance(failure)
    # The same filename alone does not prove that the executable was absent.
    failure = diagnose('failed', 1, output, arguments={'argv': ['python', 'check.py']})
    assert failure['kind'] == 'missing_path'
    failure = diagnose('failed', 1, "FileNotFoundError: [Errno 2] No such file or directory: 'node'",
                       arguments={'argv': ['node', 'tests/check.js']})
    assert failure['kind'] == 'missing_path'


@pytest.mark.parametrize('detail', [None, [], {}, 123])
def test_untrusted_missing_file_report_cannot_break_diagnostics(detail):
    output = json.dumps({'error': 'FileNotFoundError', 'detail': detail})
    assert diagnose('failed', 1, output, arguments={'argv': ['node']})['kind'] == 'missing_path'


def test_preparation_clears_dependency_memory_and_keeps_workspace(agent, docker):  # noqa: F811
    args = {'argv': ['python', '-c', 'import pydantic'], 'cwd': 'project'}
    result = SimpleNamespace(output_ref=agent.store.blobs.put(b'missing pydantic'),
                             execution_id='test', status='failed')
    record(agent, args, result, diagnose('failed', 1, "No module named 'pydantic'"))
    assert cached(agent, args)
    before = (agent.path / 'project/keep.txt').read_bytes()
    _, prepared = asyncio.run(call(agent, 'prepare_environment', {
        'reason': 'The selected project requires pydantic',
        'python_packages': ['pydantic==2.13.4'],
    }))
    assert prepared.status == 'succeeded'
    assert agent.store.blobs.json(prepared.output_ref)['status'] == 'ready'
    assert not cached(agent, args)
    assert (agent.path / 'project/keep.txt').read_bytes() == before
    assert any(command[0] == 'build' for command in docker[0])
    assert audit(agent.store, agent.run_id)['ok']


def test_negative_memory_invalidates_with_source_image_and_success(agent):  # noqa: F811
    args = {'argv': ['node', '-e', "require('ws')"], 'cwd': 'project'}
    result = SimpleNamespace(output_ref=agent.store.blobs.put(b'missing ws'), execution_id='test', status='failed')
    record(agent, args, result, diagnose('failed', 1, "Cannot find module 'ws'"))
    assert cached(agent, args)
    assert fixed_context(agent)
    assert not cached(agent, {**args, 'cwd': 'project/sub'})
    assert not cached(agent, {**args, 'argv': ['node', '--version']})
    old = agent.sandbox['image']
    agent.sandbox['image'] = 'sha256:' + 'f' * 64
    assert not cached(agent, args)
    agent.sandbox['image'] = old
    file = agent.path / 'project/keep.txt'
    original = file.read_bytes()
    file.write_text('source changed')
    assert not cached(agent, args)
    file.write_bytes(original)
    assert cached(agent, args)
    result.status = 'succeeded'
    record(agent, {'argv': ['node', '--version']}, result, diagnose('succeeded', 0, 'v18'))
    assert cached(agent, args), 'pure probes must not erase known missing dependencies'
    record(agent, {'argv': ['python', 'setup.py']}, result, diagnose('succeeded', 0, 'installed'))
    assert not cached(agent, args)
    assert not fixed_context(agent)


def test_skip_is_audited_without_execution(agent):  # noqa: F811
    args = {'argv': ['node', '-e', "require('ws')"], 'cwd': 'project'}
    result = SimpleNamespace(output_ref=agent.store.blobs.put(b'missing ws'), execution_id='test', status='failed')
    record(agent, args, result, diagnose('failed', 1, "Cannot find module 'ws'"))
    preview, executed = asyncio.run(call(agent, 'run_command', args))
    assert executed is None and preview['executed'] is False
    assert preview['status'] == 'environment_blocked'
    assert audit(agent.store, agent.run_id)['ok']
    assert agent.store.db.execute('SELECT COUNT(*) FROM execution_attempts').fetchone()[0] == 0


def test_runner_staging_preserves_original_source_on_resume(agent, monkeypatch):  # noqa: F811
    from local_agent.environments import browser_support
    stage(agent)
    original = (agent.path / 'tools/harness_browser_test.py').read_bytes()
    monkeypatch.setattr(browser_support, 'runner_source', lambda: b'changed later version')
    (agent.path / 'tools/harness_browser_test.py').write_text('model changed helper')
    stage(agent)
    assert (agent.path / 'tools/harness_browser_test.py').read_bytes() == original


def test_staging_does_not_follow_model_created_hardlink(agent):  # noqa: F811
    import os

    target = agent.path / 'project/keep.txt'
    original = target.read_bytes()
    os.link(target, agent.path / 'tools/harness_browser_test.py')
    stage(agent)
    assert target.read_bytes() == original
    assert (agent.path / 'tools/harness_browser_test.py').stat().st_ino != target.stat().st_ino


def test_negative_memory_and_skipped_call_survive_controller_resume(tmp_path, request):
    from pathlib import Path

    from local_agent.config import load_config
    from local_agent.doctor import sandbox_config
    from local_agent.models.scripted import ScriptedProvider
    from local_agent.runtime.agent import Agent
    from local_agent.storage.database import Store

    image = request.config.getoption('--docker-image')
    if not image:
        pytest.skip('requires --docker-image')
    source = tmp_path / 'source'
    source.mkdir()
    script = {'text': '', 'tool_calls': [{'name': 'run_command', 'arguments': {
        'argv': ['python', '-c', 'import definitely_missing_harness_capability']}}],
        'finish_status': 'tool_calls'}

    class Interrupted(BaseException):
        pass

    class FirstController(Agent):
        async def dispatch(self, *args, **kwargs):
            preview, result = await super().dispatch(*args, **kwargs)
            if preview.get('executed') is False:
                raise Interrupted()
            return preview, result

    cfg = load_config(Path('config/coder.yaml')).model_copy(update={'project_tests': False})
    store = Store(tmp_path / 'data')
    sandbox = {**sandbox_config(), 'image': image}
    first = FirstController(store, cfg, sandbox, provider=ScriptedProvider([script, script]))
    try:
        with pytest.raises(Interrupted):
            asyncio.run(first.run(source, 'Record unavailable dependency and report blocker'))
        provider = ScriptedProvider([script, {'text': 'Environment blocker recorded',
                                             'tool_calls': [], 'finish_status': 'stop'}])
        second = Agent(store, cfg, sandbox, provider=provider)
        result = asyncio.run(second.run(None, '', resume_run_id=first.run_id))
        assert result['status'] == 'completed_unverified', result
        events = store.events(first.run_id)
        skips = [e for e in events if e.event_type == 'tool.skipped'
                 and e.data.get('reason') == 'unchanged_unavailable_capability']
        assert len(skips) == 2
        assert sum(e.event_type == 'capability.failure' and bool(e.data.get('key')) for e in events) == 1
        assert audit(store, first.run_id)['ok']
        messages = store.blobs.json(provider.requests[0].context_ref)['messages']
        assert any('Recorded unavailable capabilities' in m.get('content', '') for m in messages)
        assert any('unchanged_unavailable_capability' in m.get('content', '') for m in messages if m['role'] == 'tool')
    finally:
        store.close()


def test_interaction_capability_requires_a_passed_probe(agent, docker, monkeypatch):  # noqa: F811
    from local_agent.environments import service
    from local_agent.storage.blobs import canonical

    original = service.Commands.run
    probes = []

    async def run(self, args, **kwargs):
        if '--self-test' in args:
            probes.append(args)
            return canonical({'runner': 'harness_browser_test', 'version': 1, 'status': 'passed', 'steps': []})
        return await original(self, args, **kwargs)

    monkeypatch.setattr(service.Commands, 'run', run)
    _, result = asyncio.run(call(agent, 'environment_inventory', {}))
    inventory = agent.store.blobs.json(result.output_ref)
    # Environment tools wrap their payload; inspect the controller's inventory attribute.
    assert inventory
    assert agent.environment_inventory['capabilities']['browser_interaction']['available'] is True
    assert agent.environment_inventory['capabilities']['browser_dom_dump']['tested'] is False
    _, result = asyncio.run(call(agent, 'environment_inventory', {}))
    assert agent.environment_inventory['capabilities']['browser_interaction']['cached'] is True
    assert len(probes) == 1
    assert audit(agent.store, agent.run_id)['ok']


def test_dom_launcher_alone_does_not_establish_interactions(agent, docker):  # noqa: F811
    asyncio.run(call(agent, 'environment_inventory', {}))
    capabilities = agent.environment_inventory['capabilities']
    assert capabilities['browser_dom_dump']['available']
    assert not capabilities['browser_interaction']['available']


def test_interactive_preparation_rejects_unverified_image(agent, docker):  # noqa: F811
    import json

    original = agent.sandbox['image']
    _, result = asyncio.run(call(agent, 'prepare_environment', {
        'reason': 'Need real keyboard regression', 'capabilities': ['browser_interaction']}))
    payload = json.loads(result.preview)
    assert payload['status'] == 'environment_blocked'
    assert agent.sandbox['image'] == original
    assert not any(e.event_type == 'environment.selected' for e in agent.store.events(agent.run_id))


def test_cached_preparation_rechecks_interactions(agent, docker, monkeypatch):  # noqa: F811
    import json

    from local_agent.environments import service
    from local_agent.storage.blobs import canonical

    original = service.Commands.run

    async def run(self, args, **kwargs):
        if '--self-test' in args:
            return canonical({'runner': 'harness_browser_test', 'version': 1, 'status': 'passed', 'steps': []})
        return await original(self, args, **kwargs)

    monkeypatch.setattr(service.Commands, 'run', run)
    args = {'reason': 'Need real keyboard regression', 'capabilities': ['browser_interaction']}
    _, result = asyncio.run(call(agent, 'prepare_environment', args))
    assert json.loads(result.preview)['status'] == 'ready'

    async def unavailable(*_args):
        return {'tools': {}, 'capabilities': {'browser_interaction': {'available': False}}}

    monkeypatch.setattr(service, 'probe', unavailable)
    _, result = asyncio.run(call(agent, 'prepare_environment', args))
    payload = json.loads(result.preview)
    assert payload['status'] == 'environment_blocked'
    assert 'Cached image failed' in payload['error']

"""Validate the actual browser protocol, keyboard input, deadlines and failure signals."""
import json
import subprocess

import pytest

from local_agent.environments.browser_support import runner_source
from local_agent.environments.browser_testing import validate


@pytest.mark.parametrize('plan', [
    {'version': True, 'steps': [{'action': 'reload'}]},
    {'version': 1, 'steps': []},
    {'version': 1, 'steps': [{'action': 'shell', 'argv': 'echo bad'}]},
    {'version': 1, 'steps': [{'action': ['invalid']}]},
    {'version': 1, 'steps': [{'action': 'click', 'selector': 'button', 'extra': 'ignored'}]},
    {'version': 1, 'steps': [{'action': 'fill', 'selector': 'input'}]},
    {'version': 1, 'steps': [{'action': 'assert', 'expression': 1}]},
])
def test_invalid_plans(plan):
    with pytest.raises(ValueError):
        validate(plan)


def docker_run(image, *args):
    result = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
        '--pids-limit', '128', '--memory', '512m', '--cpus', '2',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m', '--entrypoint', 'python',
        image, '-I', '-c', runner_source().decode(), *args], capture_output=True, text=True, timeout=40)
    return result, json.loads(result.stdout)


def test_browser_real_interaction_or_explicit_missing_runtime(request):
    image = request.config.getoption('--docker-image')
    if not image:
        pytest.skip('requires --docker-image')
    result, report = docker_run(image, '--self-test', '--timeout', '12')
    if report['status'] == 'missing_executable':
        assert result.returncode == 1 and not report['steps']
    else:
        assert result.returncode == 0, (report, result.stderr)
        assert report['status'] == 'passed' and len(report['steps']) == 8


@pytest.mark.parametrize('expression,expected', [('false', 'test_failure'), ('new Promise(()=>{})', 'timeout')])
def test_browser_assertion_and_hung_script_are_nonzero(request, expression, expected):
    image = request.config.getoption('--docker-image')
    if not image:
        pytest.skip('requires --docker-image')
    # Plan is read via /proc/self/fd/0 so no host/project mount is needed.
    plan = {'version': 1, 'steps': [{'action': 'assert', 'expression': expression}]}
    result = subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'none', '--read-only',
        '--pids-limit', '128', '--memory', '512m', '--cpus', '2',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m', '--entrypoint', 'python',
        image, '-I', '-c', runner_source().decode(), '--plan', '/dev/stdin', '--timeout', '3'],
        input=json.dumps(plan), capture_output=True, text=True, timeout=20)
    report = json.loads(result.stdout)
    assert result.returncode != 0
    assert report['status'] in {expected, 'missing_executable'}, report
    assert report['failed_step'] == 0


@pytest.mark.parametrize('mode,expected', [('pass', 'passed'), ('assert', 'test_failed'),
                                          ('hang', 'timeout'), ('invalid', 'collection_error')])
def test_controller_replays_committed_browser_plan(tmp_path, request, mode, expected):
    import asyncio
    from pathlib import Path

    from local_agent.config import load_config
    from local_agent.doctor import sandbox_config
    from local_agent.storage.database import Store
    from local_agent.testing.checks import run_checks
    from local_agent.testing.plans import resolve

    image = request.config.getoption('--docker-image')
    if not image:
        pytest.skip('requires --docker-image')
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'page.html').write_text('<title>Test browser replay</title>')
    expression = {'pass': 'document.title === "Test browser replay"',
                  'assert': 'false', 'hang': 'new Promise(()=>{})', 'invalid': 'true'}[mode]
    plan = {'version': 1, 'steps': [
        {'action': 'navigate', 'url': 'file:///workspace/project/page.html'},
        {'action': 'assert', 'expression': expression}]}
    if mode == 'invalid':
        plan['steps'][1]['action'] = 'unsupported'
    (project / 'browser-flow.json').write_text(json.dumps(plan))
    command = ['python', '/workspace/tools/harness_browser_test.py', '--plan',
               '/workspace/project/browser-flow.json', '--timeout', '3']
    contract = {'version': 1, 'install_project': False, 'commands': [{'argv': command, 'cwd': '.'}]}
    config = load_config(Path('config/coder.yaml')).model_copy(update={'project_tests': False})
    store = Store(tmp_path / 'data')
    try:
        report, result, _ = asyncio.run(run_checks(store, config, project,
            resolve(project, contract=contract), {**sandbox_config(), 'image': image}))
        assert report['audit']['ok'], report
        if report['status'] == 'environment_blocked' and mode != 'invalid':
            assert 'missing_executable' in report['commands'][0]['output'], report
        else:
            assert report['status'] == expected, report
        assert report['commands'][0]['exit_code'] == (0 if report['status'] == 'passed' else 1 if mode != 'invalid' else 2)
        assert (project / 'page.html').read_text() == '<title>Test browser replay</title>'
    finally:
        store.close()

"""Real Docker repair recovery with model responses fixed for reproducibility."""

import asyncio
from pathlib import Path

import pytest
from test_workspace_review import candidate  # noqa: F401

from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.mobile.browser_runtime import run_browser
from local_agent.mobile.diagnostics import describe_run
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.runtime.loop import simulate
from local_agent.storage.database import Store
from local_agent.workspace.git import GitWorktrees
from local_agent.workspace.manager import Workspaces
from local_agent.workspace.review import capture_target


@pytest.mark.parametrize('outcome', ['stall', 'batch_stall', 'recover', 'observe'])
def test_local_repair_recovers_or_stops_before_full_budget(candidate, request, outcome):  # noqa: F811
    image = request.config.getoption('--docker-image')
    if image is None:
        pytest.skip('requires --docker-image')
    root, repository, project, reviewed = candidate
    seed = Store(root)
    seed_run = asyncio.run(simulate(seed))['run_id']
    manager = GitWorktrees(Workspaces(root))
    record = manager.load(reviewed['workspace_id'])
    record['run_id'] = seed_run
    manager.save(record)
    reviewed = capture_target(root, reviewed['workspace_id'], reviewed['candidate_commit'], [repository], '.')
    seed.close()
    cfg = load_config(Path('config/coder.yaml'))
    cfg = cfg.model_copy(update={
        'limits': cfg.limits.model_copy(update={'max_model_turns': 24}),
        'repair_progress': cfg.repair_progress.model_copy(update={
            'mode': 'observe' if outcome == 'observe' else 'enforce',
            'probe_allowance': 2, 'recovery_allowance': 2, 'max_recoveries': 1,
        }),
    })
    original = (project / 'new.txt').read_text()
    calls = []

    def tool(name, args):
        calls.append({'text': '', 'tool_calls': [{'name': name, 'arguments': args}],
                      'finish_status': 'tool_calls'})

    for i in range(2 if outcome == 'recover' else 4):
        tool('run_command', {'argv': ['python', '-c', f'print(hasattr(str, "property{i}"))']})
    if outcome == 'batch_stall':
        for i in range(4, 14):
            tool('run_command', {'argv': ['python', '-c', f'print(hasattr(str, "property{i}"))']})
        calls = [{'text': '', 'tool_calls': [call for item in calls for call in item['tool_calls']],
                  'finish_status': 'tool_calls'}]
    if outcome == 'recover':
        tool('run_command', {'argv': ['python', '-B', '-c',
            'from pathlib import Path; Path("test_review_case.py").write_text("from pathlib import Path\\ndef test_review_case():\\n assert Path(\\\"new.txt\\\").read_text() == \\\"fixed\\\"\\n")']})
        tool('run_command', {'argv': ['python', '-m', 'pytest', '-q']})
        tool('run_command', {'argv': ['python', '-B', '-c',
                                     'from pathlib import Path; Path("new.txt").write_text("fixed")']})
        tool('run_command', {'argv': ['python', '-m', 'pytest', '-q']})
    calls.append({'text': 'Reproduced and fixed the saved finding.' if outcome == 'recover'
                         else 'No repair was made.', 'tool_calls': [], 'finish_status': 'stop'})
    provider = ScriptedProvider(calls)
    context = {'review_job_id': 'b' * 32, 'target': reviewed,
               'evidence': {'original_task': 'Preserve the expected text behavior',
                            'verdict': 'new.txt must contain fixed; add regression coverage.'},
               'source_run_ids': [reviewed['source_run_id']]}
    task = {'mode': 'coding', 'workspace': str(repository),
            'continue_workspace_id': reviewed['workspace_id'], 'working_directory': '.',
            'question': 'Fix the saved review finding.', 'repair_context': context}
    store = Store(root)
    try:
        result = asyncio.run(run_browser(store, cfg, task,
                                         {**sandbox_config(), 'image': image}, provider=provider))
        assert store.db.execute('SELECT 1 FROM runs WHERE id=?', (result['run_id'],)).fetchone(), result
        assert audit(store, result['run_id'])['ok'], result
        ledger = result['repair_progress']
        assert ledger['recoveries'] == 1
        if outcome in {'stall', 'batch_stall'}:
            assert result['status'] == 'local_stalled', result
            assert len(provider.requests) == (1 if outcome == 'batch_stall' else 4)
            assert (project / 'new.txt').read_text() == original
            assert describe_run(store, result['run_id'])['repair_progress']['decision'] == 'local_stalled'
        else:
            assert result['status'] == 'completed_unverified', result
            assert result['project_tests']['status'] == 'passed'
            if outcome == 'recover':
                assert 'new.txt' in ledger['changed_paths']
                assert any(check['exit_code'] == 1 for check in ledger['checks'])
                assert any(check['exit_code'] == 0 for check in ledger['checks'])
            else:
                assert ledger['mode'] == 'observe' and not ledger['changed_paths']
        assert (repository / 'value.py').read_text() == 'VALUE = 1\n'
        if outcome != 'batch_stall':
            messages = store.blobs.json(provider.requests[2].context_ref)['messages']
            assert any('Recovery required' in m.get('content', '') for m in messages)
            assert any('repair-ledger.json' in m.get('content', '') for m in messages)
        events = [e for e in store.events(result['run_id']) if e.event_type == 'repair.progress']
        saved = store.blobs.json(events[-1].data['state_ref'])
        assert saved['actions'] == ledger['actions']
    finally:
        store.close()


def test_resume_retains_repair_recoveries_and_does_not_repeat_probes(candidate, request):  # noqa: F811
    from local_agent.mobile.browser_agent import BrowserAgent

    image = request.config.getoption('--docker-image')
    if image is None:
        pytest.skip('requires --docker-image')
    root, repository, project, reviewed = candidate
    store = Store(root)
    seed_run = asyncio.run(simulate(store))['run_id']
    manager = GitWorktrees(Workspaces(root))
    record = manager.load(reviewed['workspace_id'])
    record['run_id'] = seed_run
    manager.save(record)
    reviewed = capture_target(root, reviewed['workspace_id'], reviewed['candidate_commit'], [repository], '.')
    cfg = load_config(Path('config/coder.yaml'))
    cfg = cfg.model_copy(update={'repair_progress': cfg.repair_progress.model_copy(update={
        'probe_allowance': 2, 'recovery_allowance': 2, 'max_recoveries': 1,
    })})
    context = {'review_job_id': 'b' * 32, 'target': reviewed, 'source_run_ids': [seed_run],
               'evidence': {'verdict': 'Fix the saved text behavior'}}

    def responses(start):
        return [{'text': '', 'tool_calls': [{'name': 'run_command', 'arguments': {
            'argv': ['python', '-c', f'print(hasattr(str, "property{i}"))']}}],
                 'finish_status': 'tool_calls'} for i in range(start, start + 2)]

    class ControllerInterrupted(BaseException):
        pass

    class FirstController(BrowserAgent):
        checkpoints = 0

        def checkpoint(self):
            super().checkpoint()
            self.checkpoints += 1
            if self.checkpoints == 2:
                raise ControllerInterrupted()

    sandbox = {**sandbox_config(), 'image': image}
    first = FirstController(store, cfg, sandbox, provider=ScriptedProvider(responses(0)),
                            request={'question': 'Fix the finding'}, repair_context=context,
                            workspace_options={'continue_workspace_id': reviewed['workspace_id'],
                                               'working_directory': '.'})
    try:
        with pytest.raises(ControllerInterrupted):
            asyncio.run(first.run(repository, 'Fix the finding'))
        assert store.run(first.run_id)['status'] == 'running'
        second_provider = ScriptedProvider(responses(2))
        manifest = store.blobs.json(store.run(first.run_id)['manifest_ref'])
        recorded_sandbox = store.blobs.json(manifest['config_ref'])['sandbox']
        resumed = BrowserAgent(store, cfg, recorded_sandbox, provider=second_provider)
        result = asyncio.run(resumed.run(None, '', resume_run_id=first.run_id))
        assert result['status'] == 'local_stalled', result
        assert result['repair_progress']['actions'] == 4
        assert result['repair_progress']['recoveries'] == 1
        assert len(second_provider.requests) == 2
        assert audit(store, first.run_id)['ok']
        assert (project / 'new.txt').read_text() == 'candidate file'
    finally:
        store.close()

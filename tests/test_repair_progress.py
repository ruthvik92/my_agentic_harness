"""Cross-domain evidence guards, recovery limits, and paid-review eligibility."""

import copy

import pytest

from local_agent.contracts import RepairProgressSettings
from local_agent.mobile.review_findings import normalize
from local_agent.mobile.review_gates import eligible, evidence_key
from local_agent.runtime.repair_progress import RepairProgress, command_kind, source_state


def action(index, argv=None, *, tool='run_command', status='succeeded', exit_code=0):
    return {'sequence': index, 'tool': tool,
            'arguments': {'argv': argv} if argv else {'path': f'project/module_{index}.py'},
            'status': status, 'exit_code': exit_code, 'output_ref': None}


def policy(**overrides):
    return RepairProgressSettings(**{'inspection_allowance': 6, 'probe_allowance': 2,
                                    'recovery_allowance': 2, 'max_recoveries': 1, **overrides})


def test_distinct_successful_probes_trigger_bounded_recovery():
    guard = RepairProgress(policy(), {'app.js': 'initial'}, [])
    probes = [action(i, ['node', '-e', f'console.log(typeof globalThis.Property{i})'])
              for i in range(1, 41)]
    decisions = []
    for item in probes:
        decisions.append(guard.observe([item], {'app.js': 'initial'}))
        if decisions[-1] == 'local_stalled':
            break
    assert decisions == ['continue', 'recover', 'continue', 'local_stalled']
    assert guard.state['recoveries'] == 1 and guard.state['actions'] == 4
    assert not guard.state['changed_paths']


@pytest.mark.parametrize('argv,kind', [
    (['python', '-c', 'import shutil; print(shutil.which("cargo"))'], 'capability_probe'),
    (['node', '-e', 'console.log(typeof globalThis.Anything)'], 'capability_probe'),
    (['cargo', '--version'], 'capability_probe'),
    (['python', '-m', 'pytest', '-q'], 'validation_attempt'),
    (['node', 'tests/test_input.js'], 'validation_attempt'),
    (['node', '--test'], 'validation_attempt'),
    (['python', '-c', 'from app import f; assert f(1) == 2; print("ok")'], 'validation_attempt'),
    (['node', '-e', 'assert.strictEqual(f(1), 2); console.log("ok")'], 'validation_attempt'),
    (['python', '-c', 'print(f(1))'], 'command'),
    (['pytest', '--help'], 'capability_probe'),
    (['git', 'log', '--', 'tests/test_app.py'], 'command'),
    (['cat', 'tests/test_app.js'], 'command'),
    (['cargo', 'test'], 'validation_attempt'),
    (['go', 'test', './...'], 'validation_attempt'),
    (['python', '-c', 'from pathlib import Path; Path("app.py").write_text("x")'], 'command'),
])
def test_task_signals_are_language_independent(argv, kind):
    assert command_kind(argv) == kind


def test_command_edits_and_test_evidence_advance_but_claims_do_not(tmp_path):
    (tmp_path / 'app.py').write_text('VALUE = 1\n')
    initial = source_state(tmp_path)
    guard = RepairProgress(policy(), initial, [])
    guard.observe([action(1, tool='write_file')], initial)
    assert guard.state['last_milestone'] == 0
    (tmp_path / 'app.py').write_text('VALUE = 2\n')
    changed = source_state(tmp_path)
    guard.observe([action(2, ['python', '-c', 'edit source'])], changed)
    assert guard.state['stage'] == 'repair'
    assert guard.state['changed_paths'] == ['app.py']
    guard.observe([action(3, ['pytest', '-q'], status='failed', exit_code=1)], changed)
    assert guard.state['stage'] == 'reproduction'
    assert guard.state['last_milestone'] == 3
    guard.observe([action(4, ['pytest', '-q'], status='failed', exit_code=1)], changed)
    assert guard.state['last_milestone'] == 3
    assert guard.public()['checks'][-1]['independent'] is False


def test_ledger_restores_without_resetting_recovery_or_double_counting():
    guard = RepairProgress(policy(), {'config.json': 'x'}, [])
    items = [action(i, ['python', '-c', f'print(hasattr(str, \"property{i}\"))']) for i in (1, 2)]
    assert guard.observe(items, {'config.json': 'x'}) == 'recover'
    restored = RepairProgress(policy(), {}, [], restored=copy.deepcopy(guard.state))
    more = items + [action(i, ['python', '-c', f'print(hasattr(str, \"property{i}\"))']) for i in (3, 4)]
    assert restored.observe(more, {'config.json': 'x'}) == 'local_stalled'
    assert restored.state['actions'] == 4
    assert restored.state['recoveries'] == 1


def test_long_investigation_and_observation_policy_are_configurable():
    guard = RepairProgress(policy(mode='observe', inspection_allowance=100), {'app.py': 'x'}, [])
    items = [action(i, tool='read_file') for i in range(1, 41)]
    assert guard.observe(items, {'app.py': 'x'}) == 'continue'
    assert len(guard.public()['reads']) == 16
    assert guard.public()['mode'] == 'observe'


def test_file_measurement_ignores_caches_and_rejects_links(tmp_path):
    (tmp_path / 'app.py').write_text('x')
    before = source_state(tmp_path)
    (tmp_path / '__pycache__').mkdir()
    (tmp_path / '__pycache__/app.pyc').write_bytes(b'cache')
    assert source_state(tmp_path) == before
    (tmp_path / 'link').symlink_to(tmp_path.parent)
    with pytest.raises(ValueError, match='symlink'):
        source_state(tmp_path)
    (tmp_path / 'link').unlink()
    with pytest.raises(ValueError, match='byte limit'):
        source_state(tmp_path, max_bytes=0)


def job_and_record():
    job = {'status': 'completed', 'audit': {'ok': True}, 'run_id': 'run_new',
           'git_workspace': {'candidate_commit': 'commit_new'},
           'project_tests': {'status': 'passed', 'audit': {'ok': True},
                             'plan': {'hash': 'plan'},
                             'commands': [{'argv': ['pytest', '-q'], 'cwd': '.',
                                           'status': 'passed', 'exit_code': 0,
                                           'counts': {'collected': 5}}]}}
    record = {'candidate_tree': 'tree', 'run_id': 'run_new', 'candidate_commit': 'commit_new'}
    return job, record


def test_duplicate_review_gate_uses_content_and_evidence_not_run_ids():
    job, record = job_and_record()
    allowed, _, key = eligible(job, record, [])
    assert allowed
    job['run_id'], record['run_id'] = 'run_another', 'run_another'
    job['git_workspace']['candidate_commit'] = record['candidate_commit'] = 'new_no_change_commit'
    job['project_tests']['run_id'] = 'run_checks_another'
    assert not eligible(job, record, [key])[0]
    job['project_tests']['commands'][0]['counts']['collected'] = 6
    assert eligible(job, record, [key])[0]  # new independent evidence can resolve a no-code finding
    record['candidate_tree'] = 'changed_tree'
    assert eligible(job, record, [key])[0]


@pytest.mark.parametrize('failure', ['test_failed', 'unaudited', 'incomplete', 'moved'])
def test_failed_or_stale_candidates_never_qualify_for_paid_review(failure):
    job, record = job_and_record()
    if failure == 'test_failed':
        job['project_tests']['status'] = 'test_failed'
    elif failure == 'unaudited':
        job['project_tests']['audit']['ok'] = False
    elif failure == 'incomplete':
        job['status'] = 'failed'
    else:
        record['run_id'] = 'run_other'
    assert not eligible(job, record, [])[0]


def test_findings_handoff_accepts_legacy_and_preserves_acceptance_criteria():
    legacy = normalize(None, 'Preserve line endings')
    assert legacy[0]['id'] == normalize(None, 'Preserve line endings')[0]['id']
    finding = {'id': 'F1', 'location': 'app.py:10', 'observed': 'Drops trailing newline',
               'expected': 'Preserve trailing newline', 'impact': 'Incorrect output',
               'acceptance': ['Exercise a file with a trailing newline']}
    assert normalize([finding]) == [finding]
    with pytest.raises(ValueError, match='unique'):
        normalize([finding, finding])
    with pytest.raises(ValueError):
        normalize([{**finding, 'acceptance': []}])


def test_evidence_fingerprint_ignores_output_timing_and_run_ids():
    job, record = job_and_record()
    before = evidence_key(record['candidate_tree'], job['project_tests'])
    job['project_tests'].update(run_id='run_different', output='passed in 0.05 seconds')
    assert evidence_key(record['candidate_tree'], job['project_tests']) == before


def test_a_diagnosed_setup_blocker_is_evidence_but_repeated_setup_is_not():
    guard = RepairProgress(policy(), {'app.py': 'x'}, [])
    first = action(1, tool='prepare_environment', status='failed', exit_code=1)
    first['arguments'] = {'runtimes': ['node']}
    guard.observe([first], {'app.py': 'x'})
    assert guard.state['stage'] == 'blocked'
    assert guard.state['last_milestone'] == 1
    guard.observe([{**first, 'sequence': 2}], {'app.py': 'x'})
    assert guard.state['last_milestone'] == 1
    assert len(guard.public()['setup']) == 1

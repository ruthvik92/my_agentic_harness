"""Explicit, isolated Ollama repair trials; never reviews remotely or merges a result.

Run with uv run --locked python scripts/check_local_repairs.py --help.
Each invocation makes one bounded local coding attempt and preserves its evidence.
"""

import argparse
import asyncio
import json
from pathlib import Path

from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.mobile.browser_runtime import run_browser
from local_agent.mobile.diagnostics import describe_run
from local_agent.mobile.review_findings import normalize
from local_agent.models.factory import create_provider
from local_agent.runtime.loop import simulate
from local_agent.storage.database import Store
from local_agent.workspace.git import GitWorktrees, git
from local_agent.workspace.manager import Workspaces, copy_tree
from local_agent.workspace.review import capture_target


def prepare_case(root, case, game_source):
    repo = root / 'source'
    if repo.exists():
        raise ValueError('Use a new output directory for each trial; existing evidence is preserved')
    if case == 'game':
        if game_source is None:
            raise ValueError('--game-source is required for the game trial')
        copy_tree(game_source, repo, exclude=('.git', '__pycache__', '.pytest_cache', 'node_modules'))
        finding = {
            'id': 'keyboard-input', 'location': 'js/game.js document keydown handler',
            'observed': 'Gameplay shortcuts handle keydown events from the player-name input. Space restarts GAME_OVER before saving; Enter saves and then bubbles to restart; arrows interfere with editing.',
            'expected': 'Typing/editing the name does not trigger gameplay shortcuts; saving a name does not restart the game.',
            'impact': 'Unsaved scores can be lost and normal name editing is broken.',
            'acceptance': ['Add a regression exercising name-input key handling and event propagation.',
                           'Space, arrow keys and A/D allow normal editing without restarting.',
                           'Enter saves once without restarting; restart still works outside the input.'],
        }
        js_checks = "import pathlib,subprocess,sys; paths=sorted(pathlib.Path('tests').glob('test_*.js')); codes=[subprocess.run(['node',str(p)]).returncode for p in paths]; sys.exit(0 if paths and not any(codes) else 1)"
        contract = {'version': 1, 'install_project': False, 'prepare_dependencies': False,
                    'commands': [{'argv': ['python', '-m', 'pytest', 'tests/', '-q'], 'cwd': '.'},
                                 {'argv': ['python', '-c', js_checks], 'cwd': '.'}]}
        (repo / '.local-agent-tests.json').write_text(json.dumps(contract))
    else:
        repo.mkdir(parents=True)
        (repo / 'clamp.py').write_text('def clamp(value, lower, upper):\n    return max(lower, value)\n')
        (repo / 'test_clamp.py').write_text('from clamp import clamp\ndef test_lower_bound():\n    assert clamp(-2, 0, 10) == 0\ndef test_inside():\n    assert clamp(4, 0, 10) == 4\n')
        finding = {'id': 'upper-bound', 'location': 'clamp.py:2',
                   'observed': 'clamp(20, 0, 10) returns 20.', 'expected': 'Values above upper return upper.',
                   'impact': 'The function does not implement its documented bounds.',
                   'acceptance': ['Add a regression for values above upper.',
                                  'Preserve the existing lower-bound and inside-range behavior.']}
    git('-C', repo, 'init', '-b', 'main')
    git('-C', repo, 'add', '.')
    git('-C', repo, 'commit', '-m', 'Isolated repair trial baseline')
    return repo, finding


async def trial(args):
    args.output.mkdir(parents=True, exist_ok=True)
    repo, finding = prepare_case(args.output, args.case, args.game_source)
    if args.finding_file:
        finding = normalize([json.loads(args.finding_file.read_text())])[0]
    cfg = load_config(Path('config/coder.yaml'))
    cfg = cfg.model_copy(update={
        'model': args.model, 'window_tokens': 65536, 'output_reserve_tokens': 8192,
        'environment': cfg.environment.model_copy(update={'allow_network': False}),
        'limits': cfg.limits.model_copy(update={'max_model_turns': 40, 'max_attempted_tool_calls': 60,
                                              'run_timeout_seconds': 600, 'model_timeout_seconds': 180}),
        'repair_progress': cfg.repair_progress.model_copy(update={'mode': args.mode}),
    })
    sandbox = {**sandbox_config(), 'image': args.image}
    store = Store(args.output / 'data')
    try:
        seed = (await simulate(store))['run_id']
        manager = GitWorktrees(Workspaces(store.root))
        ws, workspace = manager.workspaces.create_coding(repo, seed)
        snapshot = args.output / 'initial-snapshot'
        copy_tree(workspace / 'project', snapshot, exclude=('.git',))
        record = manager.finalize(ws, snapshot)
        reviewed = capture_target(store.root, ws, record['candidate_commit'], [repo], '.')
        context = {'review_job_id': '0' * 32, 'target': reviewed, 'source_run_ids': [seed],
                   'evidence': {'original_task': 'Repair the reviewed behavior while preserving current functionality.',
                                'verdict': finding['observed'] + ' ' + finding['expected'],
                                'findings': [finding]}}
        request = {'mode': 'coding', 'workspace': str(repo), 'continue_workspace_id': ws,
                   'working_directory': '.', 'repair_context': context,
                   'question': 'Fix the saved review findings. First inspect scratch/repair-review.json and only the relevant implementation/test paths. Add a failing regression, make a focused repair, and rerun relevant suites and the controller helper. Use the known environment inventory rather than probing every possible runtime API. Do not change the test contract, merge, or invoke paid services. If interactive verification is unavailable, report the limitation.'}
        (args.output / 'task.json').write_text(json.dumps(request, indent=2))
        (args.output / 'config.json').write_text(json.dumps(cfg.model_dump(mode='json'), indent=2))
        # Explicit provider avoids an additional model-based capability probe; this tag is supplied by the operator.
        provider = create_provider(store.blobs, cfg)
        result = await run_browser(store, cfg, request, sandbox, provider=provider,
                                   progress_path=args.output / 'progress.json')
        (args.output / 'result.json').write_text(json.dumps(result, indent=2))
        diagnostic = describe_run(store, result['run_id'])
        (args.output / 'diagnostics.json').write_text(json.dumps(diagnostic, indent=2))
        print(json.dumps({'case': args.case, 'model': cfg.model, 'run_id': result['run_id'],
                          'status': result['status'], 'error': result.get('error'),
                          'tests': (result.get('project_tests') or {}).get('status'),
                          'progress': result.get('repair_progress'), 'usage': diagnostic['usage'],
                          'model_requests': diagnostic['counts']['model_requests']}, indent=2))
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, choices=['python', 'game'])
    parser.add_argument('--model', required=True, help='Exact installed Ollama model tag')
    parser.add_argument('--image', required=True, help='Immutable trusted sandbox image ID')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--game-source', type=Path)
    parser.add_argument('--finding-file', type=Path, help='Optional saved finding for a bounded follow-up trial')
    parser.add_argument('--mode', choices=['observe', 'enforce'], default='enforce')
    args = parser.parse_args()
    args.output = args.output.resolve()
    asyncio.run(trial(args))


if __name__ == '__main__':
    main()

"""Reviewer test selection requires execution evidence and project-local replay."""

import asyncio
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_agent.mobile.reviewer_tests import selected_tests
from local_agent.mobile.workspace_review import test_argv as parse_command


def captured(argv, cwd="project", *, status="succeeded", exit_code=0):
    return {"tool": "run_command", "status": status, "exit_code": exit_code,
            "arguments_ref": {"argv": argv, "cwd": cwd}}


@pytest.fixture
def store():
    return SimpleNamespace(blobs=SimpleNamespace(json=lambda ref: ref))


def test_commands_use_full_captured_arguments_and_deduplicate(store, tmp_path):
    (tmp_path / "nested").mkdir()
    argv = ["node", "tests/test_leaderboard.js", *[str(i) for i in range(20)]]
    item = {"argv": argv, "cwd": "project/nested"}
    assert selected_tests(store, tmp_path, [item, item], [captured(argv, item["cwd"])]) == [
        {"argv": argv, "cwd": "nested"}
    ]


@pytest.mark.parametrize("observation", [[], [captured(["node", "other.js"])],
    [captured(["node", "test.js"], exit_code=1)],
    [captured(["node", "test.js"], status="failed")],
    [captured(["node", "test.js"], cwd="project/elsewhere")]])
def test_prose_or_failed_wrong_command_is_not_execution(store, tmp_path, observation):
    with pytest.raises(ValueError, match="no successful captured"):
        selected_tests(store, tmp_path, [{"argv": ["node", "test.js"], "cwd": "project"}],
                       observation)


@pytest.mark.parametrize("cwd", ["scratch", "/tmp", "project/../scratch", "project/.",
                                  "project/linked"])
def test_replay_cannot_leave_project(store, tmp_path, cwd):
    (tmp_path / "linked").symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(ValueError):
        selected_tests(store, tmp_path, [{"argv": ["node", "test.js"], "cwd": cwd}], [])


@pytest.mark.parametrize("value", [None, [], [{}], [{"argv": "node test.js", "cwd": "project"}],
                                   [{"argv": ["node", "\x00"], "cwd": "project"}]])
def test_invalid_or_missing_selection_cannot_approve(store, tmp_path, value):
    with pytest.raises(ValueError):
        selected_tests(store, tmp_path, value, [])


def test_empty_command_means_discover_tests():
    assert parse_command("") is None
    assert parse_command(" auto ") is None
    assert parse_command("node tests/test_leaderboard.js") == ["node", "tests/test_leaderboard.js"]
    with pytest.raises(ValueError):
        parse_command(" " * 2049)


def test_legacy_candidate_environment_can_fall_back(tmp_path):
    from local_agent.environments.service import selected
    from local_agent.storage.database import Store

    with closing(Store(tmp_path / "data")) as store:
        assert selected(store, "run_legacy") == {}


def test_environment_blocker_is_audited_before_reviewer_starts(tmp_path):
    from local_agent.config import load_config
    from local_agent.storage.database import Store
    from local_agent.testing.checks import run_checks
    from local_agent.testing.plans import resolve

    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname="unprepared"\nversion="1"\ndependencies=["missing-package"]\n'
    )
    with closing(Store(tmp_path / "data")) as store:
        report, result, _ = asyncio.run(run_checks(
            store, load_config(Path("config/coder.yaml")), project, resolve(project),
            {"image": "sha256:" + "a" * 64},
        ))
        assert report["status"] == "environment_blocked"
        assert "uv.lock" in report["error"]
        assert report["audit"]["ok"]
        assert result["status"] == "failed"


def test_report_context_keeps_progress_after_compaction_and_removes_tools(tmp_path):
    from local_agent.config import load_config
    from local_agent.mobile.review_context import ReviewContext
    from local_agent.mobile.review_instructions import REVIEW_TOOLS
    from local_agent.storage.blobs import digest
    from local_agent.storage.database import Store

    cfg = load_config(Path('examples/configs/openai-reviewer.yaml')).model_copy(update={
        'instructions_version': 'workspace-review-v1', 'tools': REVIEW_TOOLS,
        'window_tokens': 16384, 'output_reserve_tokens': 4096,
    })
    with closing(Store(tmp_path / 'data')) as store:
        agent = SimpleNamespace(store=store, config=cfg, report_only=True)
        ledger = 'RECORDED PROGRESS: node tests/test_leaderboard.js exited 0; 20 passed'
        fixed = [{'role': 'system', 'content': 'Produce JSON report now.'},
                 {'role': 'user', 'content': ledger}]
        builder = ReviewContext(agent)
        snapshot, _ = builder.build(fixed, [[{'role': 'user', 'content': 'x' * 50000}]])
        wire = store.blobs.json(snapshot.payload_ref)
        assert 'input' in wire and 'messages' not in wire
        assert any(item.get('content') == ledger for item in wire['input'])
        assert snapshot.exclusions
        assert not wire.get('tools') and not snapshot.tool_definitions
        assert snapshot.payload_hash == digest(store.blobs.read(snapshot.payload_ref))
        assert wire['reasoning'] == {'effort': 'medium'}


def test_progress_retains_full_command_results_and_read_pagination(tmp_path):
    from local_agent.mobile.review_context import progress
    from local_agent.storage.blobs import canonical
    from local_agent.storage.database import Store

    with closing(Store(tmp_path / 'data')) as store:
        output = store.blobs.put_json({'content_hash': 'hash', 'next_line': 100})
        args = store.blobs.put_json({'path': 'scratch/review.diff', 'line_offset': 0})
        read = {'tool': 'read_file', 'status': 'succeeded', 'arguments_ref': args,
                'output_ref': output}
        command = {'argv': ['node', 'tests/test_leaderboard.js'], 'cwd': 'project'}
        cmd = {'tool': 'run_command', 'status': 'succeeded', 'exit_code': 0,
               'arguments_ref': store.blobs.put_json(command), 'output_ref': output,
               'output': '20 passed'}
        result = progress(store, [read, cmd, read, cmd])
        assert result['read_pages'] == [{'path': 'scratch/review.diff', 'line_offset': 0,
                                         'next_line': 100, 'content_hash': 'hash'}]
        assert result['commands'][0]['executions'] == 2
        assert result['commands'][0]['argv'] == command['argv']
        assert result['commands'][0]['output_preview'] == '20 passed'
        assert len(canonical(progress(store, [read, cmd] * 100))) <= 10000


def test_repeated_work_triggers_report_without_counting_duplicate_context_builds():
    from copy import deepcopy

    from local_agent.mobile.review_context import ProgressTracker

    tracker = ProgressTracker()
    summary = {'read_pages': [{'path': 'project/game.js', 'next_line': 100}],
               'commands': [{'argv': ['node', 'tests/test_leaderboard.js'], 'cwd': 'project',
                             'status': 'succeeded', 'exit_code': 0, 'executions': 1}]}
    tracker.update(1, summary)
    tracker.update(1, summary)
    assert tracker.stalled == 0
    repeated = deepcopy(summary)
    repeated['commands'][0]['executions'] = 2
    repeated['commands'][0]['output_preview'] = 'a different duration'
    tracker.update(2, repeated)
    assert tracker.stalled == 1
    tracker.update(3, repeated)
    assert tracker.stalled == 2
    repeated['read_pages'].append({'path': 'project/other.js', 'next_line': 100})
    tracker.update(4, repeated)
    assert tracker.stalled == 0

"""Host Git worktree provenance, publication and protection of the source checkout."""

import pytest

from local_agent.workspace.git import GitWorktrees, git
from local_agent.workspace.manager import Workspaces, copy_tree


@pytest.fixture
def repository(tmp_path):
    source = tmp_path / "repo"
    source.mkdir()
    git("-C", source, "init", "-b", "main")
    (source / "calculator.py").write_text("def add(a, b):\n    return a - b\n")
    (source / "remove.txt").write_text("remove me")
    (source / ".gitignore").write_text("ignored/\n")
    git("-C", source, "add", ".")
    git("-C", source, "commit", "-m", "Initial project")
    return source


def test_branch_publishes_committed_snapshot_without_touching_dirty_source(repository, tmp_path):
    base = git("-C", repository, "rev-parse", "HEAD").decode().strip()
    original = repository / "calculator.py"
    original.write_text("pending host edits\n")
    (repository / "untracked.txt").write_text("keep this too")
    workspaces = Workspaces(tmp_path / "data")
    ws, root = workspaces.create_coding(repository, "run_test")
    manager = GitWorktrees(workspaces)
    record = manager.public(ws)
    assert record["base_branch"] == "main" and record["base_commit"] == base
    assert record["source_dirty"] is True
    assert record["branch"] == "agent/" + ws
    project = root / "project"
    assert "a - b" in (project / "calculator.py").read_text()
    assert not (project / "untracked.txt").exists()
    assert git("-C", repository, "symbolic-ref", "--short", "HEAD").strip() == b"main"
    (project / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
    (project / "remove.txt").unlink()
    (project / "new.bin").write_bytes(b"\x00binary\xff")
    (project / "ignored").mkdir()
    (project / "ignored/cache").write_text("do not commit")
    snapshot = tmp_path / "snapshot"
    copy_tree(project, snapshot, exclude=(".git",))
    result = manager.finalize(ws, snapshot)
    assert result["state"] == "ready_for_review"
    commit = result["candidate_commit"]
    assert commit != base
    assert b"a + b" in git("-C", repository, "show", commit + ":calculator.py")
    assert git("-C", repository, "show", commit + ":new.bin") == b"\x00binary\xff"
    assert b"remove.txt" not in git("-C", repository, "ls-tree", "-r", "--name-only", commit)
    assert b"ignored/cache" not in git("-C", repository, "ls-tree", "-r", "--name-only", commit)
    assert original.read_text() == "pending host edits\n"
    assert (repository / "untracked.txt").read_text() == "keep this too"
    assert git("-C", repository, "rev-parse", "HEAD").decode().strip() == base
    # Host index reflects the published branch; a retry returns the same candidate commit.
    assert git("-C", project, "diff", "--cached", "--name-only").strip() == b""
    assert manager.finalize(ws, snapshot)["candidate_commit"] == commit
    # The branch is directly reviewable and mergeable in the source repository.
    original.write_text("def add(a, b):\n    return a - b\n")
    git("-C", repository, "merge", "--ff-only", record["branch"])
    assert "a + b" in original.read_text()


def test_noop_branch_and_independent_runs(repository, tmp_path):
    workspaces = Workspaces(tmp_path / "data")
    manager = GitWorktrees(workspaces)
    first, root = workspaces.create_coding(repository, "run_first")
    second, _ = workspaces.create_coding(repository, "run_second")
    assert first != second
    snapshot = tmp_path / "snapshot"
    copy_tree(root / "project", snapshot, exclude=(".git",))
    result = manager.finalize(first, snapshot)
    assert result["candidate_commit"] == result["base_commit"]
    assert manager.public(second)["state"] == "editing"


def test_host_hooks_and_filters_never_execute(repository, tmp_path):
    marker = tmp_path / "host-code-executed"
    (repository / ".gitattributes").write_text("*.py filter=evil\n")
    git("-C", repository, "add", ".gitattributes")
    git("-C", repository, "commit", "-m", "Attribute policy")
    executable = "touch " + str(marker)
    git("-C", repository, "config", "filter.evil.clean", executable)
    git("-C", repository, "config", "filter.evil.smudge", executable)
    hook = repository / ".git/hooks/post-checkout"
    hook.write_text("#!/bin/sh\n" + executable + "\n")
    hook.chmod(0o700)
    workspaces = Workspaces(tmp_path / "data")
    ws, root = workspaces.create_coding(repository, "run_filters")
    assert not marker.exists()
    assert "a - b" in (root / "project/calculator.py").read_text()
    (root / "project/calculator.py").write_text("def add(a,b): return a+b\n")
    snapshot = tmp_path / "snapshot"
    copy_tree(root / "project", snapshot, exclude=(".git",))
    result = GitWorktrees(workspaces).finalize(ws, snapshot)
    assert not marker.exists()
    assert b"a+b" in git("-C", repository, "show", result["candidate_commit"] + ":calculator.py")


def test_changed_branch_or_marker_cannot_be_published(repository, tmp_path):
    workspaces = Workspaces(tmp_path / "data")
    manager = GitWorktrees(workspaces)
    ws, root = workspaces.create_coding(repository, "run_integrity")
    snapshot = tmp_path / "snapshot"
    copy_tree(root / "project", snapshot, exclude=(".git",))
    (root / "project/.git").write_text("gitdir: /untrusted\n")
    with pytest.raises(RuntimeError, match="marker changed"):
        manager.finalize(ws, snapshot)


def test_symlink_and_subdirectory_behavior(repository, tmp_path):
    workspaces = Workspaces(tmp_path / "data")
    folder = repository / "subdir"
    folder.mkdir()
    (folder / "plain.py").write_text("pass\n")
    ws, root = workspaces.create_coding(folder, "run_copy")
    assert workspaces.git_info(ws) is None
    assert (root / "project/plain.py").is_file()
    (repository / "link").symlink_to("calculator.py")
    git("-C", repository, "add", "link")
    git("-C", repository, "commit", "-m", "Symlink")
    with pytest.raises(ValueError, match="symlinks/submodules"):
        workspaces.create_coding(repository, "run_symlink")


def test_copy_does_not_follow_a_replaced_project_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("host-only")
    link = tmp_path / "project"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink root"):
        copy_tree(link, tmp_path / "candidate")
    assert not (tmp_path / "candidate/secret").exists()


def test_publication_resumes_after_ref_update_without_duplicate_commit(repository, tmp_path, monkeypatch):
    workspaces = Workspaces(tmp_path / "data")
    manager = GitWorktrees(workspaces)
    ws, root = workspaces.create_coding(repository, "run_crash")
    (root / "project/new.txt").write_text("candidate")
    snapshot = tmp_path / "snapshot"
    copy_tree(root / "project", snapshot, exclude=(".git",))
    save = manager.save

    def fail_after_ref(record):
        if record["state"] == "ready_for_review":
            raise OSError("crash after branch publication")
        save(record)

    monkeypatch.setattr(manager, "save", fail_after_ref)
    with pytest.raises(OSError, match="crash"):
        manager.finalize(ws, snapshot)
    pending = manager.load(ws)
    assert pending["state"] == "publishing"
    monkeypatch.setattr(manager, "save", save)
    recovered = manager.finalize(ws, snapshot)
    assert recovered["candidate_commit"] == pending["candidate_commit"]
    assert recovered["state"] == "ready_for_review"


def test_host_changes_to_agent_branch_are_not_overwritten(repository, tmp_path):
    workspaces = Workspaces(tmp_path / "data")
    ws, root = workspaces.create_coding(repository, "run_concurrent")
    manager = GitWorktrees(workspaces)
    info = manager.public(ws)
    snapshot = tmp_path / "snapshot"
    copy_tree(root / "project", snapshot, exclude=(".git",))
    tree = git("-C", repository, "rev-parse", "HEAD^{tree}").decode().strip()
    other = git("-C", repository, "commit-tree", tree, "-p", info["base_commit"],
                input=b"Reviewer changed branch\n").decode().strip()
    git("-C", repository, "update-ref", "refs/heads/" + info["branch"], other)
    with pytest.raises(RuntimeError, match="moved outside"):
        manager.finalize(ws, snapshot)
    assert git("-C", repository, "rev-parse", info["branch"]).decode().strip() == other

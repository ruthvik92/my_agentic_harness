"""Host validation and literal commit export for workspace review and explicit merges."""

import hashlib
from pathlib import Path

from local_agent.workspace.git import MAX_BYTES, MAX_FILES, GitWorktrees, command, git, read_literal
from local_agent.workspace.manager import IMPORT_EXCLUDES, Workspaces
from local_agent.workspace.options import check_directory


def entries(repository, commit):
    result, total = [], 0
    for entry in filter(
        None, git("-C", repository, "ls-tree", "-r", "-l", "-z", commit).split(b"\0")
    ):
        header, name = entry.split(b"\t", 1)
        mode, kind, oid, size = header.split()
        path = Path(name.decode("utf-8"))
        if (
            mode not in (b"100644", b"100755")
            or kind != b"blob"
            or path.is_absolute()
            or any(part in {"..", ".git", *IMPORT_EXCLUDES} for part in path.parts)
        ):
            raise ValueError("Review requires regular committed files without excluded paths")
        total += int(size)
        result.append((path, mode, oid))
        if total > MAX_BYTES or len(result) > MAX_FILES:
            raise ValueError("Review candidate exceeds export limits")
    return result


def require_clean(repository, commit):
    """Compare literal bytes; never run clean filters or trust index stat-cache flags."""
    if git(
        "-C",
        repository,
        "diff",
        "--cached",
        "--name-only",
        "--no-ext-diff",
        "--no-textconv",
        commit,
        "--",
    ).strip():
        raise ValueError("Checkout has staged changes; commit or move them before proceeding")
    untracked = git("-C", repository, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    if any(name and not any(part in IMPORT_EXCLUDES for part in Path(name.decode()).parts)
           for name in untracked):
        raise ValueError("Checkout has untracked files; move them before proceeding")
    for path, mode, oid in entries(repository, commit):
        try:
            data, info = read_literal(repository, path, MAX_BYTES)
        except (ValueError, OSError) as exc:
            raise ValueError("Checkout differs from its committed candidate") from exc
        hashed = hashlib.new("sha1" if len(oid) == 40 else "sha256")
        hashed.update(b"blob " + str(len(data)).encode() + b"\0" + data)
        if hashed.hexdigest().encode() != oid or bool(info.st_mode & 0o111) != (mode == b"100755"):
            raise ValueError("Checkout has pending file changes; commit or move them first")


def target(root, workspace_id, candidate, allowed_roots):
    manager = GitWorktrees(Workspaces(root))
    record = manager.load(workspace_id)
    if not record or record["state"] != "ready_for_review":
        raise ValueError("Choose a published managed Git candidate")
    manager.verify(record)
    if not candidate or candidate != record.get("candidate_commit"):
        raise ValueError("Candidate changed; reload the result and review the new commit")
    repository = Path(record["repository"])
    if repository.is_symlink() or not any(
        repository.resolve().is_relative_to(Path(allowed).resolve()) for allowed in allowed_roots
    ):
        raise ValueError("Review repository is outside the server's allowed roots")
    require_clean(Path(record["worktree"]), candidate)
    return record


def capture_target(root, workspace_id, candidate, allowed_roots, directory):
    record = target(root, workspace_id, candidate, allowed_roots)
    check_directory(Path(record["worktree"]), directory)
    repository = Path(record["repository"])
    branch = git("-C", repository, "symbolic-ref", "--short", "HEAD").decode().strip()
    if branch != record["base_branch"]:
        raise ValueError("Source branch changed; select the intended checkout before review")
    source_head = git("-C", repository, "rev-parse", "HEAD").decode().strip()
    diff_base = git("-C", repository, "merge-base", source_head, candidate).decode().strip()
    return {
        "workspace_id": workspace_id,
        "candidate_commit": candidate,
        "diff_base_commit": diff_base,
        "base_commit": record["base_commit"],
        "source_run_id": record["run_id"],
        "repository": str(repository),
        "source_branch": branch,
        "source_head": source_head,
        "working_directory": directory,
    }


def export_candidate(record, candidate, destination):
    destination.mkdir(mode=0o700)
    for path, mode, oid in entries(record["repository"], candidate):
        output = destination / path
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        output.write_bytes(command(record, "cat-file", "blob", oid.decode()))
        output.chmod(0o700 if mode == b"100755" else 0o600)


def merge_candidate(root, reviewed, allowed_roots):
    """Only a clean, unchanged source branch may fast-forward to the reviewed object."""
    record = target(root, reviewed["workspace_id"], reviewed["candidate_commit"], allowed_roots)
    if record["run_id"] != reviewed["source_run_id"]:
        raise ValueError("Workspace was continued after review; review it again")
    repository = Path(record["repository"])
    if str(repository) != reviewed["repository"]:
        raise ValueError("Review repository identity changed")
    branch = git("-C", repository, "symbolic-ref", "--short", "HEAD").decode().strip()
    head = git("-C", repository, "rev-parse", "HEAD").decode().strip()
    if branch != reviewed["source_branch"] or head != reviewed["source_head"]:
        raise ValueError("Source branch moved after review; review against its current HEAD")
    if head == reviewed["candidate_commit"]:
        raise ValueError("Candidate has no changes to merge")
    require_clean(repository, head)
    # Inspect effective local/included config before Git can perform any checkout.
    config = git("-C", repository, "config", "--includes", "--null", "--list")
    for item in config.split(b"\0"):
        key = item.split(b"\n", 1)[0].lower()
        if key.startswith(b"filter.") or key in (
            b"core.sparsecheckout",
            b"core.sparsecheckoutcone",
        ):
            raise ValueError(
                "Merge requires a checkout without configured filters or sparse checkout"
            )
    if any(
        line[:1] == b"S" or line[:1].islower()
        for line in git("-C", repository, "ls-files", "-v").splitlines()
    ):
        raise ValueError(
            "Merge requires an index without skip-worktree or assume-unchanged entries"
        )
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        path = git("-C", repository, "rev-parse", "--git-path", name).decode().strip()
        if (repository / path).exists():
            raise ValueError("Finish the existing Git operation before merging")
    git("-C", repository, "merge-base", "--is-ancestor", head, reviewed["candidate_commit"])
    # merge --ff-only protects against divergence; no hooks, filters, submodules or remote operations.
    git(
        "-c",
        "submodule.recurse=false",
        "-c",
        "merge.autostash=false",
        "-C",
        repository,
        "merge",
        "--ff-only",
        "--no-edit",
        "--no-autostash",
        "--no-overwrite-ignore",
        reviewed["candidate_commit"],
    )
    after = git("-C", repository, "rev-parse", "HEAD").decode().strip()
    if after != reviewed["candidate_commit"]:
        raise RuntimeError("Merge did not reach the reviewed commit; inspect the checkout")
    return {"status": "merged", "commit": after, "branch": branch, "repository": str(repository)}

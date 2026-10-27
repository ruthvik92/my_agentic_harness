"""Host-owned Git worktrees. No hooks, filters, signing or model-supplied Git argv."""

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

from local_agent.executor.lifecycle import publish
from local_agent.storage.blobs import private_directory

MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 100000
PUBLIC_FIELDS = (
    "repository", "base_branch", "base_commit", "branch", "worktree",
    "candidate_commit", "source_dirty", "state",
)


def read_literal(root, relative, limit):
    """Read a bounded regular file without following any directory or leaf symlink."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        opened = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(opened, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Git candidate contains a nonregular file")
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise ValueError("Git file exceeds import budget")
            return data, info
    finally:
        os.close(fd)


def git(*args, input=None, index=None):
    # Never inherit Git overrides, credentials, global aliases or executable hooks.
    env = {
        "PATH": os.defpath, "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_AUTHOR_NAME": "Local Agent", "GIT_AUTHOR_EMAIL": "local-agent@localhost",
        "GIT_COMMITTER_NAME": "Local Agent", "GIT_COMMITTER_EMAIL": "local-agent@localhost",
    }
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
         "-c", "commit.gpgsign=false", *map(str, args)],
        input=input, capture_output=True, env=env, timeout=60, check=False,
    )
    if result.returncode:
        raise RuntimeError("Host Git operation failed: " + result.stderr.decode(errors="replace")[:2000])
    if len(result.stdout) > MAX_BYTES:
        raise ValueError("Git output exceeds import budget")
    return result.stdout


def command(record, *args, input=None, index=None, tree=None):
    return git(
        "--git-dir=" + record["git_dir"], "--work-tree=" + str(tree or record["worktree"]),
        *args, input=input, index=index,
    )


class GitWorktrees:
    def __init__(self, workspaces):
        self.workspaces = workspaces
        self.directory = workspaces.root.parent / "control" / "git-workspaces"

    def path(self, workspace_id):
        self.workspaces.path(workspace_id)
        return self.directory / (workspace_id + ".json")

    def load(self, workspace_id):
        path = self.path(workspace_id)
        try:
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "r") as stream:
                record = json.load(stream)
        except FileNotFoundError:
            return None
        if (
            record.get("workspace_id") != workspace_id
            or record.get("worktree") != str(self.workspaces.path(workspace_id) / "project")
            or record.get("branch") != "agent/" + workspace_id
        ):
            raise ValueError("Git worktree identity mismatch")
        return record

    def save(self, record):
        publish(self.path(record["workspace_id"]), record)

    def public(self, workspace_id):
        record = self.load(workspace_id)
        return {key: record.get(key) for key in PUBLIC_FIELDS} if record else None

    def prepare(self, source, workspace_id, run_id):
        source = source.resolve(strict=True)
        # Selecting a subdirectory of a Git repo must not unexpectedly import the entire repo.
        if not (source / ".git").exists():
            return None
        top = Path(os.fsdecode(git("-C", source, "rev-parse", "--show-toplevel")).strip()).resolve()
        if top != source:
            raise ValueError("Select the Git repository root for worktree execution")
        base = git("-C", source, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        branch = git("-C", source, "rev-parse", "--abbrev-ref", "HEAD").decode().strip()
        entries = git("-C", source, "ls-tree", "-r", "-l", "-z", "--full-tree", base).split(b"\0")
        from local_agent.workspace.manager import IMPORT_EXCLUDES

        files, total = [], 0
        for entry in filter(None, entries):
            header, name = entry.split(b"\t", 1)
            mode, kind, oid, size = header.split()
            path = Path(name.decode("utf-8"))
            if (mode not in {b"100644", b"100755"} or kind != b"blob"
                    or path.is_absolute() or any(p in (".", "..") for p in path.parts)):
                raise ValueError("Git worktrees require regular tracked files; symlinks/submodules unsupported")
            if any(p in IMPORT_EXCLUDES for p in path.parts):
                raise ValueError("Tracked cache/development directories must be removed before a Git run")
            total += int(size)
            files.append((path, mode, oid))
        if total > MAX_BYTES or len(files) > MAX_FILES:
            raise ValueError("Git repository exceeds import budget")
        # git status/diff against working files can invoke clean filters. Compare literal
        # bytes instead, and use Git only to enumerate staged/untracked paths.
        dirty = bool(git("-C", source, "diff", "--cached", "--name-only", "--no-ext-diff",
                         "--no-textconv", base, "--")) or bool(
            git("-C", source, "ls-files", "--others", "--exclude-standard", "-z")
        )
        for path, mode, oid in files:
            try:
                data, info = read_literal(source, path, MAX_BYTES)
                hashed = hashlib.new("sha1" if len(oid) == 40 else "sha256")
                hashed.update(b"blob " + str(len(data)).encode() + b"\0" + data)
                dirty |= hashed.hexdigest().encode() != oid
                dirty |= bool(info.st_mode & 0o111) != (mode == b"100755")
            except (OSError, ValueError):
                dirty = True
        project = self.workspaces.path(workspace_id) / "project"
        record = {
            "workspace_id": workspace_id, "run_id": run_id, "repository": str(source),
            "base_branch": None if branch == "HEAD" else branch,
            "base_commit": base, "branch": "agent/" + workspace_id,
            "worktree": str(project), "candidate_commit": None, "source_dirty": dirty,
            "state": "preparing",
        }
        self.save(record)
        try:
            git("-C", source, "worktree", "add", "--no-checkout", "-b", record["branch"], project, base)
            record["git_dir"] = git("-C", project, "rev-parse", "--absolute-git-dir").decode().strip()
            record["git_marker"] = (project / ".git").read_text()
            # Materialize literal committed blobs: checkout/smudge filters never execute on the host.
            for path, mode, oid in files:
                destination = project / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as stream:
                    stream.write(git("-C", source, "cat-file", "blob", oid.decode()))
                destination.chmod(0o700 if mode == b"100755" else 0o600)
            command(record, "read-tree", base)
            record["state"] = "editing"
            self.save(record)
            return record
        except BaseException:
            record["state"] = "preparation_failed"
            self.save(record)
            raise

    def verify(self, record):
        project = Path(record["worktree"])
        if project.is_symlink() or not project.is_dir():
            raise RuntimeError("Git worktree directory changed; inspect before continuing")
        marker = project / ".git"
        data, _ = read_literal(project, Path(".git"), 16384)
        if marker.is_symlink() or data.decode() != record["git_marker"]:
            raise RuntimeError("Git worktree marker changed; inspect before continuing")
        if command(record, "symbolic-ref", "HEAD").decode().strip() != "refs/heads/" + record["branch"]:
            raise RuntimeError("Git worktree branch changed; inspect before continuing")
        head = command(record, "rev-parse", "refs/heads/" + record["branch"]).decode().strip()
        if head not in {record["base_commit"], record.get("candidate_commit")}:
            raise RuntimeError("Agent branch moved outside the harness; inspect before continuing")

    def finalize(self, workspace_id, snapshot):
        """Publish an already captured candidate, using a private index and literal blob writes."""
        record = self.load(workspace_id)
        if not record:
            return None
        self.verify(record)
        private_directory(self.directory)
        with tempfile.TemporaryDirectory(dir=self.directory) as tmp:
            index = Path(tmp) / "index"
            command(record, "read-tree", record["base_commit"], index=index)
            names = command(
                record, "ls-files", "--cached", "--others", "--exclude-per-directory=.gitignore", "-z",
                tree=snapshot, index=index,
            ).split(b"\0")
            updates, total = [], 0
            if len(names) > MAX_FILES:
                raise ValueError("Git candidate has too many files")
            for name in sorted(set(filter(None, names))):
                relative = Path(name.decode("utf-8"))
                if relative.is_absolute() or any(p in {"..", ".git"} for p in relative.parts):
                    raise ValueError("Invalid candidate Git path")
                path = snapshot / relative
                try:
                    path.lstat()
                except FileNotFoundError:
                    updates.append(b"0 " + b"0" * len(record["base_commit"]) + b"\t" + name + b"\0")
                    continue
                data, info = read_literal(snapshot, relative, MAX_BYTES - total)
                total += len(data)
                if total > MAX_BYTES:
                    raise ValueError("Git candidate exceeds import budget")
                oid = command(record, "hash-object", "-w", "--no-filters", "--stdin", input=data).strip()
                mode = b"100755" if info.st_mode & 0o111 else b"100644"
                updates.append(mode + b" " + oid + b"\t" + name + b"\0")
            command(record, "update-index", "-z", "--index-info", input=b"".join(updates), index=index)
            tree = command(record, "write-tree", index=index).decode().strip()
        if record.get("candidate_commit"):
            if record.get("candidate_tree") != tree:
                raise RuntimeError("Published candidate differs from captured snapshot")
        else:
            parent_tree = command(record, "rev-parse", record["base_commit"] + "^{tree}").decode().strip()
            commit = record["base_commit"] if tree == parent_tree else command(
                record, "commit-tree", tree, "-p", record["base_commit"],
                input=("Agent changes for " + record["run_id"] + "\n").encode(),
            ).decode().strip()
            record.update(candidate_commit=commit, candidate_tree=tree, state="publishing")
            self.save(record)  # Recovery knows the exact intended object before the ref changes.
        head = command(record, "rev-parse", "refs/heads/" + record["branch"]).decode().strip()
        if head != record["candidate_commit"]:
            command(record, "update-ref", "refs/heads/" + record["branch"],
                    record["candidate_commit"], record["base_commit"])
        command(record, "read-tree", record["candidate_commit"])
        record["state"] = "ready_for_review"
        self.save(record)
        return self.public(workspace_id)

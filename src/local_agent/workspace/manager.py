import os
import stat
from pathlib import Path

from local_agent.contracts import new_id
from local_agent.storage.blobs import private_directory

MAX_IMPORT_BYTES = 256 * 1024 * 1024
IMPORT_EXCLUDES = frozenset({
    ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".tool-build", ".browser-build", ".config-cleanup", ".config-consolidation",
    ".executor-review", ".executor-fixes",
})


def copy_tree(source: Path, target: Path, *, exclude=(), budget=MAX_IMPORT_BYTES):
    """Trusted provisioning only. Never follow source symlinks or copy special files."""
    if source.is_symlink():
        raise ValueError("repository copy rejects a symlink root")
    fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return _copy_directory(fd, target, exclude, budget)
    finally:
        os.close(fd)


def _copy_directory(source_fd, target, exclude, budget):
    count = 0
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    for entry in os.scandir(source_fd):
        if entry.name in exclude:
            continue
        dest = target / entry.name
        if entry.is_symlink():
            raise ValueError(f"repository import rejects symlinks: {entry.name}")
        if entry.is_dir(follow_symlinks=False):
            child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source_fd)
            try:
                count += _copy_directory(child, dest, exclude, budget - count)
            finally:
                os.close(child)
        elif entry.is_file(follow_symlinks=False):
            fd = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source_fd)
            try:
                mode = os.fstat(fd).st_mode
                if not stat.S_ISREG(mode):
                    raise ValueError("repository contains a special file")
                with os.fdopen(fd, "rb", closefd=False) as src, dest.open("xb") as out:
                    while chunk := src.read(65536):
                        count += len(chunk)
                        if count > budget:
                            raise ValueError("workspace import exceeds size limit")
                        out.write(chunk)
                dest.chmod(0o700 if mode & 0o111 else 0o600)
            finally:
                os.close(fd)
        else:
            raise ValueError(f"repository import rejects special file: {entry.name}")
        if count > budget:
            raise ValueError("workspace import exceeds size limit")
    return count


class Workspaces:
    def __init__(self, data_root: Path):
        self.root = data_root / "sandboxes"
        private_directory(self.root)

    def create(self, source: Path) -> tuple[str, Path]:
        source = source.resolve(strict=True)
        if self.root.resolve().is_relative_to(source):
            raise ValueError("data root must be outside the imported repository")
        workspace_id = new_id("ws")
        root = self.root / workspace_id
        private_directory(root)
        for name in ("memory", "tools", "scratch", "outputs"):
            private_directory(root / name)
        copy_tree(
            source,
            root / "project",
            exclude=IMPORT_EXCLUDES,
        )
        return workspace_id, root

    def create_coding(self, source: Path, run_id: str, *, base_ref="HEAD") -> tuple[str, Path]:
        source = source.resolve(strict=True)
        if not (source / ".git").exists():
            if base_ref != "HEAD":
                raise ValueError("Selecting a starting revision requires a Git repository root")
            return self.create(source)
        if self.root.resolve().is_relative_to(source):
            raise ValueError("data root must be outside the imported repository")
        workspace_id = new_id("ws")
        root = self.root / workspace_id
        private_directory(root)
        for name in ("memory", "tools", "scratch", "outputs"):
            private_directory(root / name)
        from local_agent.workspace.git import GitWorktrees

        GitWorktrees(self).prepare(source, workspace_id, run_id, base_ref=base_ref)
        return workspace_id, root

    def git_info(self, workspace_id):
        from local_agent.workspace.git import GitWorktrees

        return GitWorktrees(self).public(workspace_id)

    def path(self, workspace_id: str, *, allow_missing: bool = False) -> Path:
        from pydantic import TypeAdapter

        from local_agent.contracts import ID

        TypeAdapter(ID).validate_python(workspace_id)
        path = self.root / workspace_id
        # Cleanup may validate a now-missing workspace's mount identity; execution may not.
        if path.is_symlink() or (not path.is_dir() and not (allow_missing and not path.exists())):
            raise ValueError("workspace missing or invalid")
        return path

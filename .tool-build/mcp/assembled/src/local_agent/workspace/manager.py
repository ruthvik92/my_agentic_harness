import os
import stat
from pathlib import Path

from local_agent.contracts import new_id
from local_agent.storage.blobs import private_directory

MAX_IMPORT_BYTES = 256 * 1024 * 1024


def copy_tree(source: Path, target: Path, *, exclude=(), budget=MAX_IMPORT_BYTES):
    """Trusted provisioning only. Never follow source symlinks or copy special files."""
    count = 0
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    for entry in os.scandir(source):
        if entry.name in exclude:
            continue
        dest = target / entry.name
        if entry.is_symlink():
            raise ValueError(f"repository import rejects symlinks: {entry.name}")
        if entry.is_dir(follow_symlinks=False):
            count += copy_tree(Path(entry.path), dest, exclude=exclude, budget=budget - count)
        elif entry.is_file(follow_symlinks=False):
            fd = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError("repository contains a special file")
                with os.fdopen(fd, "rb", closefd=False) as src, dest.open("xb") as out:
                    while chunk := src.read(65536):
                        count += len(chunk)
                        if count > budget:
                            raise ValueError("workspace import exceeds size limit")
                        out.write(chunk)
                dest.chmod(0o700 if entry.stat(follow_symlinks=False).st_mode & 0o111 else 0o600)
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
            source, root / "project", exclude=(".git", ".venv", "__pycache__", ".pytest_cache")
        )
        return workspace_id, root

    def path(self, workspace_id: str) -> Path:
        from pydantic import TypeAdapter

        from local_agent.contracts import ID

        TypeAdapter(ID).validate_python(workspace_id)
        path = self.root / workspace_id
        if path.is_symlink() or not path.is_dir():
            raise ValueError("workspace missing or invalid")
        return path

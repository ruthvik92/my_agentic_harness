"""Workspace-relative, symlink-safe file access helpers (stdlib only)."""
import contextlib
import errno
import fcntl
import os
import stat

_APPROVED = ("project", "memory", "tools", "scratch", "outputs")


def _validate(path):
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty string")
    if "\x00" in path or "\\" in path:
        raise ValueError("path contains forbidden characters")
    if os.path.isabs(path) or path.startswith("/"):
        raise ValueError("absolute paths are not allowed")
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError("empty, '.', or '..' components are not allowed")
    if parts[0] not in _APPROVED:
        raise ValueError("first component must be one of %s" % (_APPROVED,))
    if len(parts) < 2:
        raise ValueError("file path must have at least two components")
    return parts


def _open_dir(path, dir_fd=None):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        return os.open(path, flags, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno == errno.ENOTDIR:
            raise ValueError("component is not a directory")
        raise


@contextlib.contextmanager
def parent_fd(path, root="/workspace", create=False):
    parts = _validate(path)
    leaf = parts[-1]
    dirs = parts[:-1]
    fds = []
    try:
        root_fd = _open_dir(root)
        fds.append(root_fd)
        for name in dirs:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            if create:
                try:
                    fd = os.open(name, flags | os.O_CREAT, 0o700, dir_fd=fds[-1])
                except OSError as exc:
                    if exc.errno == errno.EEXIST:
                        fd = _open_dir(name, fds[-1])
                    else:
                        raise
            else:
                fd = _open_dir(name, fds[-1])
            fds.append(fd)
        yield fds[-1], leaf
    finally:
        for fd in reversed(fds):
            os.close(fd)


def read_bytes(path, limit=131072, root="/workspace"):
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    parts = _validate(path)
    leaf = parts[-1]
    with parent_fd(path, root=root) as (fd, name):
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            leaf_fd = os.open(name, flags, dir_fd=fd)
        except OSError as exc:
            if exc.errno == errno.EISDIR:
                raise ValueError("leaf is a directory")
            raise
        try:
            st = os.fstat(leaf_fd)
            if not stat.S_ISREG(st.st_mode):
                raise ValueError("leaf is not a regular file")
            if st.st_size > limit:
                raise ValueError("file exceeds limit")
            data = os.read(leaf_fd, limit + 1)
            if len(data) > limit:
                raise ValueError("file exceeds limit")
            return data
        finally:
            os.close(leaf_fd)

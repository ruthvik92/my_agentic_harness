"""Persistent registry storage for tool registrations (stdlib only)."""
import contextlib
import errno
import os
import re

from .registry_records import decode_record, encode_record
from .workspace_io import parent_fd, read_bytes

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_BUILTINS = frozenset((
    "read_file", "write_file", "patch_file", "list_files", "search_files",
    "git_diff", "run_command", "register_tool", "execute_tool", "view_image",
    "render_pdf_region",
))
_MAX_ENTRIES = 32
_REL_PATH = "tools/.registry"


def _validate_name(name):
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ValueError("invalid registry name")
    if name in _BUILTINS:
        raise ValueError("name collides with a builtin tool")


def _fsync_dir(fd):
    try:
        os.fsync(fd)
    except OSError:
        pass


def write_registration(data, root="/workspace"):
    record = decode_record(data)
    name = record["metadata"].get("name")
    _validate_name(name)
    payload = encode_record(record["metadata"], record["code"])
    with parent_fd(_REL_PATH, root=root, create=True) as (dir_fd, _):
        try:
            if len([e for e in os.listdir(dir_fd) if e.endswith(".json")]) >= _MAX_ENTRIES:
                raise ValueError("registry is full")
            try:
                os.lstat(name + ".json", dir_fd=dir_fd)
                raise ValueError("entry already exists")
            except FileNotFoundError:
                pass
            tmp = ".tmp-%d-%d" % (os.getpid(), os.urandom(4).hex())
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=dir_fd)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(tmp, name + ".json", src_dir_fd=dir_fd, dst_dir_fd=dir_fd,
                        follow_symlinks=False)
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(tmp, dir_fd=dir_fd)
            _fsync_dir(dir_fd)
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                raise ValueError("entry already exists") from exc
            raise
    return {"name": name, "path": _REL_PATH + "/" + name + ".json"}


def read_registration(name, root="/workspace"):
    _validate_name(name)
    data = read_bytes(_REL_PATH + "/" + name + ".json", limit=524288, root=root)
    record = decode_record(data)
    if record["metadata"].get("name") != name:
        raise ValueError("stored metadata name does not match requested name")
    return record

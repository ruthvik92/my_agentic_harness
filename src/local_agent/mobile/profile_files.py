"""Safe profile file name validation and bounded text reading."""
import fcntl
import hashlib
import os
import re
import secrets
import stat

_MAX_SIZE = 65536
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*\.(?:yaml|yml|json)$")


def check_name(name):
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise ValueError("invalid profile file name")
    if len(name.rsplit(".", 1)[0]) > 64:
        raise ValueError("profile file stem too long")
    return name


def read_text(directory, name):
    check_name(name)
    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except OSError:
        os.close(dir_fd)
        raise
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > _MAX_SIZE:
            raise ValueError("unsafe profile file")
        data = os.read(fd, _MAX_SIZE + 1)
        if len(data) > _MAX_SIZE:
            raise ValueError("profile file too large")
        return data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("unsafe profile file") from exc
    finally:
        os.close(fd)
        os.close(dir_fd)


def _sha256_hex(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def atomic_save(directory, name, content, expected_hash=None):
    check_name(name)
    if not isinstance(content, str) or not content:
        raise ValueError("content must be a nonempty string")
    raw = content.encode("utf-8")
    if len(raw) > _MAX_SIZE:
        raise ValueError("content too large")

    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock_fd = None
    temp_name = None
    try:
        lock_fd = os.open(
            ".profiles.lock",
            os.O_RDWR | os.O_NOFOLLOW | os.O_CREAT,
            0o600,
            dir_fd=dir_fd,
        )
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        try:
            st = os.lstat(name, dir_fd=dir_fd)
        except FileNotFoundError:
            st = None
        if expected_hash is None:
            if st is not None:
                raise FileExistsError("profile already exists")
        else:
            if not isinstance(expected_hash, str):
                raise ValueError("expected_hash must be a string or None")
            if st is None:
                raise FileExistsError("profile does not exist")
            if not stat.S_ISREG(st.st_mode):
                raise ValueError("unsafe profile file")
            if st.st_size > _MAX_SIZE:
                raise ValueError("profile file too large")
            with os.fdopen(os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd), "rb") as f:
                existing = f.read(_MAX_SIZE + 1)
            if len(existing) > _MAX_SIZE:
                raise ValueError("profile file too large")
            if _sha256_hex(existing) != expected_hash:
                raise FileExistsError("stale expected_hash")

        count = 0
        for entry in os.listdir(dir_fd):
            if entry == name or entry.startswith("."):
                continue
            if not _NAME_RE.fullmatch(entry):
                continue
            if len(entry.rsplit(".", 1)[0]) > 64:
                continue
            count += 1
        if expected_hash is None and count >= 128:
            raise ValueError("too many profile files")

        temp_name = ".tmp.%d.%s" % (os.getpid(), secrets.token_hex(16))
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=dir_fd,
        )
        try:
            view = memoryview(raw)
            while view:
                written = os.write(temp_fd, view)
                view = view[written:]
            os.fsync(temp_fd)
        finally:
            os.close(temp_fd)

        if expected_hash is None:
            try:
                os.link(temp_name, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            except FileExistsError as exc:
                raise FileExistsError("profile already exists") from exc
            os.unlink(temp_name, dir_fd=dir_fd)
        else:
            os.replace(temp_name, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        temp_name = None
        os.fsync(dir_fd)
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except OSError:
                pass
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        os.close(dir_fd)
    return _sha256_hex(raw)

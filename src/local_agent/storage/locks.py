import fcntl
import os
from contextlib import contextmanager

from local_agent.storage.blobs import private_directory


@contextmanager
def run_lock(control):
    """One active coding run per data root; OS releases the lease after a crash."""
    private_directory(control / "locks")
    fd = os.open(
        control / "locks" / "active-run.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another coding run owns this data root") from exc
        yield
    finally:
        os.close(fd)

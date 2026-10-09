"""Snapshot a workspace PDF into a temporary file (stdlib only)."""
import hashlib
import os
import tempfile
from contextlib import contextmanager

from .workspace_io import read_bytes

_LIMIT = 64 * 1024 * 1024


@contextmanager
def snapshot_pdf(path, root="/workspace"):
    if not isinstance(path, str) or not path.startswith("project/"):
        raise ValueError("path must be a non-empty string starting with 'project/'")
    data = read_bytes(path, limit=_LIMIT, root=root)
    if b"%PDF-" not in data[:1024]:
        raise ValueError("missing %PDF- header within first 1024 bytes")
    handle = tempfile.NamedTemporaryFile(dir="/tmp", suffix=".pdf", delete=False)
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        yield handle.name, "sha256:" + hashlib.sha256(data).hexdigest()
    finally:
        if not handle.closed:
            handle.close()
        try:
            os.unlink(handle.name)
        except OSError:
            pass

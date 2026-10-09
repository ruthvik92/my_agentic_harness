"""Content-addressed publication with Linux file and directory fsync."""

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

from pydantic import BaseModel

MAX_BLOB_BYTES = 10 * 1024 * 1024


def canonical(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise ValueError(f"protected directory must be owned by current user: {path}")
    path.chmod(0o700)


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class BlobStore:
    def __init__(self, root: Path, *, readonly: bool = False):
        self.root = root
        self.readonly = readonly
        self.budget = None
        self.budget_refs = set()
        if not readonly:
            private_directory(root)
            fsync_directory(root.parent)

    def begin_budget(self, limit):
        self.budget = limit
        self.budget_refs = set()

    def end_budget(self):
        self.budget = None
        self.budget_refs = set()

    def path(self, ref: str) -> Path:
        if not re.fullmatch(r"blob://[0-9a-f]{64}", ref):
            raise ValueError("invalid evidence reference")
        return self.root / ref[7:]

    def put(self, data: bytes) -> str:
        if self.readonly:
            raise PermissionError("read-only evidence store")
        if len(data) > MAX_BLOB_BYTES:
            raise ValueError("evidence exceeds per-blob limit")
        ref = "blob://" + hashlib.sha256(data).hexdigest()
        if self.budget is not None and ref not in self.budget_refs:
            if len(data) > self.budget:
                raise OSError("run evidence budget exhausted; audit capture unavailable")
            self.budget -= len(data)
            self.budget_refs.add(ref)
        target = self.path(ref)
        if target.exists():
            self.read(ref)
            return ref
        fd, name = tempfile.mkstemp(prefix=".publish-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), 0o400)
                os.fsync(stream.fileno())
            # link publishes without ever replacing existing immutable evidence.
            try:
                os.link(name, target)
            except FileExistsError:
                self.read(ref)
            fsync_directory(self.root)
        finally:
            os.unlink(name)
            fsync_directory(self.root)
        return ref

    def put_json(self, value: object) -> str:
        return self.put(canonical(value))

    def read(self, ref: str) -> bytes:
        fd = os.open(self.path(ref), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("evidence must be a regular file")
            data = stream.read(MAX_BLOB_BYTES + 1)
        if len(data) > MAX_BLOB_BYTES or digest(data)[7:] != ref[7:]:
            raise ValueError(f"evidence hash/size mismatch: {ref}")
        return data

    def json(self, ref: str):
        return json.loads(self.read(ref))

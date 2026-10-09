"""Persistent catalog of trace sources for the local trace viewer."""

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
from pathlib import Path

from local_agent.storage.database import Store

MAX_PROJECT = 120
MAX_LOCATION = 4096
_RUN_ID = re.compile(r"^run_[0-9a-f]{8,}$")


def _source_id(root: Path) -> str:
    return hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]


def _normalize(location: str) -> Path:
    """Map a supported input location to its data root.

    Only the exact structural layouts of a trace data root are accepted:

        ROOT/control/agent.db
        ROOT/control/runs/run_ID/events.jsonl
        ROOT/control
        ROOT/control/runs
        ROOT/control/runs/run_ID
    """
    path = Path(location).expanduser().resolve()
    if path.is_file():
        if path.name == "agent.db" and path.parent.name == "control":
            return path.parent.parent
        if (
            path.name == "events.jsonl"
            and path.parent.name.startswith("run_")
            and path.parent.parent.name == "runs"
            and path.parent.parent.parent.name == "control"
        ):
            return path.parent.parent.parent.parent
        raise ValueError(f"unsupported file: {location}")
    if path.name == "control":
        return path.parent
    if (
        path.name == "runs"
        and path.parent.name == "control"
        and (path.parent / "agent.db").is_file()
    ):
        return path.parent.parent
    if (
        _RUN_ID.match(path.name)
        and path.parent.name == "runs"
        and path.parent.parent.name == "control"
        and (path.parent.parent / "agent.db").is_file()
    ):
        return path.parent.parent.parent
    return path


def _validate_project(project: str) -> str:
    if not isinstance(project, str) or not project.strip():
        raise ValueError(f"project must be 1-{MAX_PROJECT} characters")
    if len(project) > MAX_PROJECT:
        raise ValueError(f"project must be 1-{MAX_PROJECT} characters")
    return project


def _validate_project_arg(project: str) -> str:
    if not isinstance(project, str):
        raise ValueError(f"project must be 1-{MAX_PROJECT} characters")
    return _validate_project(project)


def _validate_location(location: str) -> Path:
    if not isinstance(location, str) or not location or len(location) > MAX_LOCATION:
        raise ValueError(f"location must be 1-{MAX_LOCATION} characters")
    root = _normalize(location)
    if not root.is_absolute():
        raise ValueError(f"source location must be an absolute path: {location}")
    if not root.is_dir():
        raise ValueError(f"source location does not exist: {location}")
    db = root / "control" / "agent.db"
    if not db.is_file():
        # A data root may legitimately contain an analysis directory; the
        # missing database is the real problem, not the analysis outputs.
        raise ValueError(f"no trace database at {db}")
    try:
        store = Store(root, readonly=True)
    except (sqlite3.Error, ValueError, OSError) as exc:
        raise ValueError(f"invalid trace database at {db}: {exc}") from exc
    store.close()
    return root


class SourceCatalog:
    def __init__(self, default_root: Path):
        self.default_root = Path(default_root).expanduser().resolve()
        self.path = self.default_root / "control" / "trace-sources.json"
        self._lock = threading.RLock()
        self._sources = self._load()

    def _default_source(self) -> dict:
        return {
            "id": _source_id(self.default_root),
            "root": str(self.default_root),
            "project": self.default_root.name,
        }

    def _load(self) -> list:
        if not self.path.is_file():
            return [self._default_source()]
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("catalog must be a list")
            sources = []
            seen = set()
            for entry in raw:
                if not isinstance(entry, dict):
                    raise ValueError("catalog entries must be objects")
                root_raw = entry["root"]
                if not isinstance(root_raw, str) or not root_raw:
                    raise ValueError("catalog root must be a string")
                if not Path(root_raw).is_absolute():
                    raise ValueError("catalog root must be absolute")
                root = Path(root_raw).expanduser().resolve()
                project = entry["project"]
                if not isinstance(project, str) or not project.strip():
                    raise ValueError("invalid project in catalog")
                if len(project) > MAX_PROJECT:
                    raise ValueError("invalid project in catalog")
                source_id = entry["id"]
                if not isinstance(source_id, str) or _source_id(root) != source_id:
                    raise ValueError("catalog id does not match root")
                if source_id in seen:
                    continue
                seen.add(source_id)
                sources.append({"id": source_id, "root": str(root), "project": project})
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"malformed source catalog at {self.path}: {exc}") from exc
        if not any(s["id"] == self._default_source()["id"] for s in sources):
            sources.insert(0, self._default_source())
        return sources

    def _persist(self) -> None:
        with self._lock:
            self.default_root.parent.mkdir(parents=True, exist_ok=True)
            control = self.default_root / "control"
            control.mkdir(parents=True, exist_ok=True)
            os.chmod(control, 0o700)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(control), prefix=".trace-sources-", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self._sources, fh, indent=2)
                    fh.write("\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                os.chmod(tmp_name, 0o600)
                os.replace(tmp_name, self.path)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise

    def sources(self) -> list:
        with self._lock:
            out = []
            for source in self._sources:
                row = dict(source)
                try:
                    _validate_location(row["root"])
                except ValueError as exc:
                    row["error"] = str(exc)
                out.append(row)
            return out

    def add(self, location: str, project: str = "") -> dict:
        root = _validate_location(location)
        source_id = _source_id(root)
        with self._lock:
            existing = None
            for source in self._sources:
                if source["id"] == source_id:
                    existing = source
                    break
            if existing is not None:
                if project:
                    new_project = _validate_project_arg(project)
                elif not isinstance(project, str):
                    raise ValueError(f"project must be 1-{MAX_PROJECT} characters")
                else:
                    new_project = existing["project"]
                original = [dict(source) for source in self._sources]
                prospective = [dict(source) for source in self._sources]
                for source in prospective:
                    if source["id"] == source_id:
                        source["project"] = new_project
                        break
                try:
                    self._sources = prospective
                    self._persist()
                except Exception:
                    self._sources = original
                    raise
                return {
                    "id": source_id,
                    "root": str(root),
                    "project": new_project,
                }
            if project:
                project = _validate_project_arg(project)
            elif not isinstance(project, str):
                raise ValueError(f"project must be 1-{MAX_PROJECT} characters")
            else:
                project = _validate_project(root.name)
            source = {"id": source_id, "root": str(root), "project": project}
            original = [dict(source) for source in self._sources]
            prospective = list(original)
            prospective.append(source)
            try:
                self._sources = prospective
                self._persist()
            except Exception:
                self._sources = original
                raise
            return dict(source)

    def list_runs(self) -> list:
        rows = []
        for source in self.sources():
            root = Path(source["root"])
            try:
                store = Store(root, readonly=True)
            except (sqlite3.Error, ValueError, OSError):
                continue
            try:
                for run in store.db.execute("SELECT id, status, created_utc FROM runs"):
                    rows.append(
                        {
                            "id": run["id"],
                            "status": run["status"],
                            "created_utc": run["created_utc"],
                            "source_id": source["id"],
                            "project": source["project"],
                            "source_root": str(root),
                        }
                    )
            except (sqlite3.Error, OSError):
                continue
            finally:
                store.close()
        rows.sort(key=lambda r: r["created_utc"], reverse=True)
        return rows

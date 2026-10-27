"""High-level profile catalog, read, validate, load, and save operations."""
import os
import tempfile
import threading
from pathlib import Path

import yaml

from local_agent.config import AgentConfig, load_config
from local_agent.mobile.profile_files import atomic_save, check_name, read_text
from local_agent.mobile.profile_validation import validate_profile
from local_agent.storage.blobs import digest

_MAX_PROFILES = 128
_ERROR_LIMIT = 500


def _error_message(exc):
    message = str(exc)
    if len(message) > _ERROR_LIMIT:
        message = message[:_ERROR_LIMIT]
    return message


class Profiles:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _profile_names(self):
        names = []
        for entry in os.listdir(self.directory):
            if not entry.endswith((".yaml", ".yml", ".json")):
                continue
            try:
                check_name(entry)
            except ValueError:
                continue
            path = self.directory / entry
            if path.is_symlink():
                continue
            if not path.is_file():
                continue
            names.append(entry)
        names.sort()
        return names[:_MAX_PROFILES]

    def catalog(self):
        entries = []
        for name in self._profile_names():
            entry = {"name": name, "kind": "sandbox" if name == "sandbox.json" else "agent"}
            try:
                content = read_text(str(self.directory), name)
                meta = validate_profile(name, content)
                entry.update(meta)
                entry["hash"] = digest(content.encode("utf-8"))
                entry["valid"] = True
            except Exception as exc:
                entry["valid"] = False
                entry["error"] = _error_message(exc)
            entries.append(entry)
        return {"profiles": entries, "directory": str(self.directory)}

    def read(self, name):
        check_name(name)
        content = read_text(str(self.directory), name)
        entry = {
            "name": name,
            "content": content,
            "hash": digest(content.encode("utf-8")),
        }
        try:
            entry["metadata"] = validate_profile(name, content)
            entry["metadata"]["valid"] = True
        except Exception as exc:
            entry["metadata"] = {
                "name": name,
                "kind": "sandbox" if name == "sandbox.json" else "agent",
                "valid": False,
                "error": _error_message(exc),
            }
        return entry

    def validate(self, name, content):
        check_name(name)
        meta = validate_profile(name, content)
        meta["valid"] = True
        return meta

    def load(self, name):
        check_name(name)
        if name == "sandbox.json":
            raise ValueError("sandbox.json cannot be loaded as an agent profile")
        content = read_text(str(self.directory), name)
        validate_profile(name, content)
        parsed = yaml.safe_load(content)
        if not isinstance(parsed, dict):
            raise ValueError("Profile must be a dictionary")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", encoding="utf-8", delete=False
        ) as temp:
            temp.write(content)
            temp.flush()
            temp_path = Path(temp.name)
        try:
            config = load_config(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)
        if not isinstance(config, AgentConfig):
            raise ValueError("Profile did not load as an AgentConfig")
        return config

    def save(self, name, content, expected_hash=None):
        check_name(name)
        with self.lock:
            validate_profile(name, content)
            atomic_save(str(self.directory), name, content, expected_hash=expected_hash)
            return self.read(name)

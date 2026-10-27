"""Coding task selection and directory validation shared by CLI and browser."""

import os
from pathlib import Path

FIELDS = ("base_ref", "continue_workspace_id", "working_directory")


def task_arguments(name, arguments, directory):
    key = {"run_command": "cwd", "git_diff": "repository"}.get(name)
    if key and directory != ".":
        return {key: "project/" + directory, **arguments}
    return arguments


def validate_options(value):
    unknown = set(value) - set(FIELDS)
    if unknown:
        raise ValueError("Unknown workspace options")
    result = {}
    for key, item in value.items():
        if not isinstance(item, str) or not item.strip() or "\x00" in item or len(item) > 1024:
            raise ValueError(f"{key} must be a non-empty string")
        result[key] = item.strip()
    if result.get("continue_workspace_id"):
        from pydantic import TypeAdapter

        from local_agent.contracts import ID

        TypeAdapter(ID).validate_python(result["continue_workspace_id"])
        if "base_ref" in result:
            raise ValueError("Continue task cannot select a new starting revision")
    directory = result.get("working_directory", ".")
    if directory != "." and (
        directory.startswith("/") or "\\" in directory
        or any(p in {"", ".", "..", ".git"} for p in directory.split("/"))
    ):
        raise ValueError("working_directory must be a repository-relative directory")
    return result


def check_directory(project: Path, directory: str):
    """Require an existing directory, without traversing symlinks."""
    fd = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in (() if directory == "." else directory.split("/")):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
    except OSError as exc:
        raise ValueError("Working subdirectory must exist and contain no symlinks") from exc
    finally:
        os.close(fd)

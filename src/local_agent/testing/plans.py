"""Resolve one reusable test contract; project commands execute only in Docker."""

import json
import tomllib
from pathlib import Path

from local_agent.storage.blobs import canonical, digest
from local_agent.workspace.git import read_literal
from local_agent.workspace.options import check_directory, validate_options

CONTRACT = ".local-agent-tests.json"


def read_config(project, path):
    raw, _ = read_literal(project, path, 1024 * 1024)
    return json.loads(raw)


def resolve(project, directory=".", *, contract=None, override=None, discover_contract=True):
    project = Path(project)
    metadata = project_metadata(project)
    packaged = bool(metadata.get("build-system"))
    directory = validate_options({"working_directory": directory})["working_directory"]
    check_directory(project, directory)
    document, origin = contract, None
    if document is None and discover_contract:
        current = Path(directory)
        while True:
            path = current / CONTRACT
            if (project / path).exists():
                document = read_config(project, path)
                origin = str(path)
                break
            if current == Path("."):
                break
            current = current.parent
    if document is not None:
        if (
            not isinstance(document, dict)
            or set(document)
            - {
                "version",
                "commands",
                "install_project",
                "timeout_seconds",
                "dependency_network",
                "prepare_dependencies",
                "dependency_groups",
                "dependency_extras",
            }
            or document.get("version") != 1
        ):
            raise ValueError("Invalid project test contract")
        commands = document.get("commands")
        install = document.get("install_project", packaged)
        timeout = document.get("timeout_seconds", 120)
        scope = str(Path(origin).parent) if origin else "."
    else:
        python = (
            (project / "pyproject.toml").is_file()
            or any((project / directory).glob("*.py"))
            or (project / directory / "tests").is_dir()
        )
        commands = [{"argv": ["python", "-m", "pytest", "-q"], "cwd": directory}] if python else []
        install = packaged
        timeout, scope = 120, "."
    if type(install) is not bool or type(timeout) is not int or not 1 <= timeout <= 240:
        raise ValueError("Invalid test setup or timeout")
    if override:
        commands = [{"argv": override, "cwd": directory}]
    if not isinstance(commands, list) or len(commands) > 8:
        raise ValueError("Test contract commands must be a list of at most eight checks")
    validated = []
    for item in commands:
        if not isinstance(item, dict) or set(item) != {"argv", "cwd"}:
            raise ValueError("Each test command needs argv and cwd")
        argv = item["argv"]
        if (
            not isinstance(argv, list)
            or not argv
            or len(argv) > 128
            or any(not isinstance(v, str) or not v or "\x00" in v or len(v) > 4096 for v in argv)
        ):
            raise ValueError("Invalid test command arguments")
        relative = validate_options({"working_directory": item["cwd"]})["working_directory"]
        cwd = str(Path(scope) / relative) if origin else relative
        check_directory(project, cwd)
        validated.append({"argv": argv, "cwd": cwd})
    network = document.get("dependency_network", "auto") if document is not None else "auto"
    if network not in {"auto", "never"}:
        raise ValueError("dependency_network must be auto or never")
    prepare_deps = (
        document.get("prepare_dependencies", install)
        if document is not None
        else bool(
            packaged
            or metadata.get("project", {}).get("dependencies")
            or metadata.get("dependency-groups")
        )
    )
    if type(prepare_deps) is not bool:
        raise ValueError("prepare_dependencies must be boolean")
    import re

    groups = (
        document.get("dependency_groups", [])
        if document is not None
        else (["test"] if "test" in metadata.get("dependency-groups", {}) else [])
    )
    extras = (
        document.get("dependency_extras", [])
        if document is not None
        else (
            ["test"]
            if "test" in metadata.get("project", {}).get("optional-dependencies", {})
            else []
        )
    )
    for names in (groups, extras):
        if (
            not isinstance(names, list)
            or len(names) > 16
            or any(
                not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name)
                for name in names
            )
        ):
            raise ValueError(
                "Dependency groups/extras must be a bounded list of package group names"
            )
    result = {
        "version": 1,
        "dependency_groups": groups,
        "dependency_extras": extras,
        "prepare_dependencies": prepare_deps,
        "dependency_network": network,
        "origin": origin or "automatic Python detection",
        "commands": validated,
        "install_project": install,
        "timeout_seconds": timeout,
        "network": "none",
    }
    result["hash"] = digest(canonical(result))
    return result


def project_metadata(project):
    path = Path(project) / "pyproject.toml"
    if not path.exists():
        return {}
    raw, _ = read_literal(Path(project), Path("pyproject.toml"), 1024 * 1024)
    return tomllib.loads(raw.decode())


def seal(plan):
    return {
        **plan,
        "hash": digest(canonical({key: value for key, value in plan.items() if key != "hash"})),
    }

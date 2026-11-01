"""Dependency-only preparation images; test/model containers remain offline."""

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

from local_agent.executor.lifecycle import publish
from local_agent.storage.blobs import canonical, digest, private_directory
from local_agent.workspace.git import read_literal


def _run(argv, *, cwd=None, timeout=600, env=None):
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(
            "Test environment preparation failed: " + result.stderr[:2000] + result.stderr[-500:]
        )
    return result.stdout


def prepare(root, project, plan, sandbox):
    if not plan["install_project"] and not plan.get("prepare_dependencies"):
        return {
            **sandbox,
            "test_environment": {"image": sandbox["image"], "network_used": False, "kind": "base"},
        }
    project = Path(project)
    pyproject_bytes, _ = read_literal(project, Path("pyproject.toml"), 1024 * 1024)
    metadata = tomllib.loads(pyproject_bytes.decode())
    backend = metadata.get("build-system", {}).get("requires", ["setuptools>=77"])
    for requirement in backend:
        if not isinstance(requirement, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:[<>=!~][A-Za-z0-9.*+<>=!~, -]+)?",
            requirement,
        ):
            raise ValueError(
                "Test build requirements must use public registry package names and version constraints"
            )
    lock = project / "uv.lock"
    lock_bytes = (
        read_literal(project, Path("uv.lock"), 8 * 1024 * 1024)[0]
        if lock.exists() or lock.is_symlink()
        else b""
    )
    requires = metadata.get("project", {}).get("dependencies", [])
    development = metadata.get("dependency-groups", {})
    if (requires or development) and not lock.is_file():
        raise ValueError(
            "Test environment blocked: commit uv.lock for reproducible project/test dependencies"
        )
    selected = sandbox.get("prepared_environment", {})
    fingerprints = selected.get("manifest_hashes", {})
    if (not plan.get("dependency_groups") and not plan.get("dependency_extras")
            and fingerprints.get("project/pyproject.toml") == digest(pyproject_bytes)
            and fingerprints.get("project/uv.lock") == digest(lock_bytes)):
        return {**sandbox, "test_environment": {
            "image": sandbox["image"], "network_used": False, "kind": "model-prepared",
            "key": selected["key"],
        }}
    key = digest(
        canonical(
            {
                "base": sandbox["image"],
                "pyproject": pyproject_bytes.decode(),
                "lock": lock_bytes.decode(),
                "version": 2,
                "groups": plan.get("dependency_groups", []),
                "extras": plan.get("dependency_extras", []),
            }
        )
    )
    cache = Path(root) / "control/test-environments" / key[7:]
    private_directory(cache)
    record = cache / "environment.json"
    if record.exists():
        cached = json.loads(record.read_text())
        try:
            _run(["docker", "image", "inspect", cached["image"]])
            return {
                **sandbox,
                "image": cached["image"],
                "test_environment": {**cached, "cache_hit": True, "network_used": False},
            }
        except RuntimeError:
            pass
    if plan.get("dependency_network") == "never":
        raise ValueError(
            "Test environment blocked: dependency image is not cached and dependency_network is never"
        )
    requirements = ""
    if lock.exists():
        uv = shutil.which("uv") or "/home/ruthvik/.local/bin/uv"
        with tempfile.TemporaryDirectory(dir=cache) as exported:
            exported = Path(exported)
            (exported / "pyproject.toml").write_bytes(pyproject_bytes)
            (exported / "uv.lock").write_bytes(lock_bytes)
            requirements = _run(
                [
                    uv,
                    "export",
                    "--frozen",
                    "--no-emit-project",
                    "--no-header",
                    "--no-annotate",
                    *[
                        arg
                        for group in plan.get("dependency_groups", [])
                        for arg in ("--group", group)
                    ],
                    *[
                        arg
                        for extra in plan.get("dependency_extras", [])
                        for arg in ("--extra", extra)
                    ],
                ],
                cwd=exported,
                env={
                    "PATH": os.defpath,
                    "UV_OFFLINE": "1",
                    "UV_PYTHON_DOWNLOADS": "never",
                    "HOME": str(exported),
                },
            )
        if re.search(r"https?://|file:|git\+|(?:^|\s)-e\s|\s@\s|--index-url", requirements):
            raise ValueError(
                "Test environment blocked: URL/local dependency sources require explicit environment provisioning"
            )
    base_tag = "local-agent-test-base:" + sandbox["image"].split(":", 1)[1]
    _run(["docker", "tag", sandbox["image"], base_tag])
    # Only exported dependency specifications enter this build; no project code, hooks or secrets.
    with tempfile.TemporaryDirectory(dir=cache) as build:
        build = Path(build)
        (build / "requirements.txt").write_text(requirements)
        (build / "Dockerfile").write_text(
            "FROM " + base_tag + "\nUSER root\nCOPY requirements.txt /tmp/test-requirements.txt\n"
            "RUN python -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --no-cache-dir setuptools==80.9.0 wheel==0.45.1\n"
            + (
                "RUN python -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --no-cache-dir "
                + " ".join("'" + r.replace("'", "'\\''") + "'" for r in backend)
                + "\n"
                if backend
                else ""
            )
            + (
                "RUN python -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --no-cache-dir --require-hashes -r /tmp/test-requirements.txt\n"
                if requirements.strip()
                else ""
            )
            + "USER "
            + str(os.getuid())
            + ":"
            + str(os.getgid())
            + "\n"
        )
        # A cache miss is the only network-enabled phase. Agent and check executors never use it.
        image = (
            _run(
                ["docker", "build", "--quiet", "--pull=false", "--network=default", str(build)],
                timeout=900,
            )
            .strip()
            .splitlines()[-1]
        )
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise RuntimeError("Dependency image was not pinned by an immutable image ID")
    frozen = _run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python",
            image,
            "-m",
            "pip",
            "freeze",
        ]
    )
    cached = {
        "image": image,
        "base_image": sandbox["image"],
        "key": key,
        "network_used": True,
        "requirements_hash": digest(requirements.encode()),
        "installed": frozen,
        "kind": "locked-dependencies",
    }
    publish(record, cached)
    return {**sandbox, "image": image, "test_environment": cached}


async def prepare_environment(root, project, plan, sandbox):
    return await asyncio.to_thread(prepare, root, project, plan, sandbox)

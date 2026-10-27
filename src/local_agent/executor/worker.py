"""Trusted stdlib-only worker. Run with python -I -S inside the sandbox image."""

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from contextlib import ExitStack, contextmanager

ROOT = "/workspace"
MAX_FILE = 1048576
ALLOWED = {"project", "memory", "tools", "scratch", "outputs"}
TRUSTED = "/opt/local-agent"


def content_hash(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def parts(path):
    value = path.split("/")
    if (
        not path
        or path.startswith("/")
        or "\x00" in path
        or "\\" in path
        or any(p in ("", ".", "..") for p in value)
        or value[0] not in ALLOWED
    ):
        raise ValueError("invalid workspace path")
    return value


@contextmanager
def directory(path, create=False):
    fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts(path):
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


@contextmanager
def parent(path, create=False):
    value = parts(path)
    if len(value) < 2:
        raise ValueError("file must be under an approved directory")
    with directory("/".join(value[:-1]), create) as fd:
        yield fd, value[-1]


def read_at(fd, name):
    opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(opened, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("not a regular file")
        data = stream.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise ValueError("file exceeds typed read/edit limit")
        return data


def replace_at(fd, name, data, expected_hash=None, create_only=False):
    if len(data) > MAX_FILE:
        raise ValueError("file exceeds size limit")
    previous = None
    try:
        previous = read_at(fd, name)
    except FileNotFoundError:
        if not create_only:
            raise
    if create_only and previous is not None:
        raise ValueError("create-only target already exists")
    if not create_only and content_hash(previous) != expected_hash:
        raise ValueError("expected hash conflict")
    temp = ".local-agent-" + uuid.uuid4().hex
    opened = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(opened, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if create_only:
            os.link(temp, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        else:
            os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temp, dir_fd=fd)
        except FileNotFoundError:
            pass
    return {
        "previous_hash": content_hash(previous) if previous is not None else None,
        "content_hash": content_hash(data),
        "bytes": len(data),
    }


def walk(fd, prefix, depth):
    # Iterator avoids materializing an attacker-controlled tree on the host.
    with os.scandir(fd) as entries:
        for entry in entries:
            if entry.name == ".git":
                continue
            path = prefix + "/" + entry.name
            info = entry.stat(follow_symlinks=False)
            yield (
                path,
                "symlink"
                if stat.S_ISLNK(info.st_mode)
                else ("directory" if stat.S_ISDIR(info.st_mode) else "file"),
            )
            if depth and stat.S_ISDIR(info.st_mode):
                child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    yield from walk(child, path, depth - 1)
                finally:
                    os.close(child)


def operate(tool, args, environment=None):
    if tool == "register_tool":
        if TRUSTED not in sys.path:
            sys.path.insert(0, TRUSTED)
        from toolkit.register import register_tool
        return register_tool(args)
    if tool == "execute_tool":
        if TRUSTED not in sys.path:
            sys.path.insert(0, TRUSTED)
        from toolkit.execute import execute_tool
        return execute_tool(args)
    if tool == "render_pdf_region":
        if TRUSTED not in sys.path:
            sys.path.insert(0, TRUSTED)
        from toolkit.pdf_render import render_pdf_region
        return render_pdf_region(args)
    if tool == "view_image":
        if TRUSTED not in sys.path:
            sys.path.insert(0, TRUSTED)
        from toolkit.image_info import view_image
        return view_image(args)
    if tool == "read_file":
        with parent(args["path"]) as (fd, name):
            data = read_at(fd, name)
        text = data.decode("utf-8")
        if "\x00" in text:
            raise ValueError("binary file")
        lines = text.splitlines(keepends=True)
        start, limit = args.get("line_offset", 0), args.get("line_limit", 100)
        return {
            "content": "".join(lines[start : start + limit]),
            "content_hash": content_hash(data),
            "line_offset": start,
            "next_line": start + limit if len(lines) > start + limit else None,
        }
    if tool in {"write_file", "patch_file"}:
        with parent(args["path"], create=tool == "write_file") as (fd, name):
            if tool == "write_file":
                return replace_at(
                    fd,
                    name,
                    args["content"].encode(),
                    args.get("expected_hash"),
                    args.get("create_only", True),
                )
            previous = read_at(fd, name)
            if content_hash(previous) != args["expected_hash"]:
                raise ValueError("expected hash conflict")
            text = previous.decode("utf-8")
            if text.count(args["old_text"]) != 1:
                raise ValueError("patch requires one exact match")
            return replace_at(
                fd,
                name,
                text.replace(args["old_text"], args["new_text"]).encode(),
                args["expected_hash"],
            )
    if tool in {"list_files", "search_files"}:
        found = []
        offset = args.get("offset", 0)
        total = 0
        with directory(args["directory"]) as fd:
            for path, kind in walk(fd, args["directory"], args.get("depth", 10)):
                if tool == "list_files":
                    total += 1
                    if total <= offset:
                        continue
                    found.append({"path": path, "kind": kind})
                elif kind == "file":
                    try:
                        with parent(path) as (pfd, name):
                            text = read_at(pfd, name).decode("utf-8")
                        for index, line in enumerate(text.splitlines(), 1):
                            if args["query"] in line:
                                found.append({"path": path, "line": index, "text": line[:2048]})
                                if len(found) > args["limit"]:
                                    break
                    except (ValueError, OSError, UnicodeError):
                        continue
                if len(found) > args["limit"]:
                    return {
                        "matches": found[: args["limit"]],
                        "truncated": True,
                        "next_offset": offset + args["limit"] if tool == "list_files" else None,
                    }
        return {"matches": found, "truncated": False, "next_offset": None}
    if tool in {"run_command", "git_diff"}:
        cwd = args.get("cwd", args.get("repository", "project"))
        with ExitStack() as cleanup, directory(cwd) as fd:
            if tool == "run_command":
                argv = args["argv"]
                if args.get("helper_manifest"):
                    manifest_path = args["helper_manifest"]
                    if not manifest_path.startswith("tools/"):
                        raise ValueError("helper manifests must be under tools")
                    with parent(manifest_path) as (mfd, name):
                        manifest_bytes = read_at(mfd, name)
                    manifest = json.loads(manifest_bytes)
                    entrypoint = manifest["entrypoint"]
                    if (
                        manifest.get("schema_version") != 1
                        or argv != entrypoint
                        or len(argv) != 2
                        or argv[0] != "python"
                        or not argv[1].startswith("tools/")
                        or cwd != "tools"
                    ):
                        raise ValueError("helper requires exact Python entrypoint and cwd tools")
                    code_path = argv[1]
                    with parent(code_path) as (cfd, name):
                        code = read_at(cfd, name)
                    # Execute the same captured bytes we hashed, isolated from mutable imports.
                    temporary = cleanup.enter_context(
                        tempfile.TemporaryDirectory(prefix="local-agent-helper-", dir="/tmp")
                    )
                    captured = os.path.join(temporary, "helper.py")
                    with open(captured, "xb") as stream:
                        stream.write(code)
                    print(
                        "LOCAL_AGENT_HELPER:"
                        + json.dumps(
                            {
                                "manifest_hash": content_hash(manifest_bytes),
                                "code_hash": content_hash(code),
                                "version": str(manifest.get("version", ""))[:128],
                                "manifest_path": manifest_path,
                                "code_path": code_path,
                                "requested_capabilities_ignored": True,
                            }
                        ),
                        flush=True,
                    )
                    argv = ["python", "-I", "-B", captured]
            else:
                argv = [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "diff.external=",
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--",
                    *[
                        os.path.relpath("/workspace/" + path, "/workspace/" + cwd)
                        for path in args.get("paths", [])
                    ],
                ]
            base_env = {
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": "/tmp",
                "LANG": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
            }
            if environment:
                base_env.update(environment)
            result = subprocess.run(
                argv,
                cwd=f"/proc/self/fd/{fd}",
                check=False,
                env=base_env,
            )
            return result.returncode
    raise ValueError("unknown tool")


ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FIXED_SAFETY_ENV = frozenset(
    {
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_GLOBAL",
        "PYTHONDONTWRITEBYTECODE",
        "PATH",
        "HOME",
    }
)
MAX_ENV_ENTRIES = 64
MAX_ENV_VALUE_LEN = 8192


def _strict_int(value, field, low, high):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid {field}: must be an integer")
    if value < low or value > high:
        raise ValueError(f"invalid {field}: out of range")
    return value


def validate_execution_options(value):
    """Validate the host-injected '_execution' object.

    Returns a normalized dict with memory_mb, cpu_cores, environment.
    Never echoes environment values in error messages.
    """
    if value is None:
        return {"memory_mb": 4096, "cpu_cores": 4, "environment": {}}
    if not isinstance(value, dict):
        raise ValueError("invalid _execution: must be an object")
    allowed = {"memory_mb", "cpu_cores", "environment"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError("invalid _execution: unknown options")
    memory_mb = _strict_int(
        value.get("memory_mb", 4096), "memory_mb", 64, 4096
    )
    cpu_cores = _strict_int(value.get("cpu_cores", 4), "cpu_cores", 1, 4)
    env = value.get("environment", {})
    if not isinstance(env, dict):
        raise ValueError("invalid environment: must be an object")
    if len(env) > MAX_ENV_ENTRIES:
        raise ValueError("invalid environment: too many entries")
    normalized = {}
    for key, val in env.items():
        if not isinstance(key, str) or not ENV_KEY_RE.fullmatch(key):
            raise ValueError("invalid environment key")
        if "\x00" in key:
            raise ValueError("invalid environment key")
        if key in FIXED_SAFETY_ENV:
            raise ValueError("invalid environment key: fixed safety variable")
        if not isinstance(val, str):
            raise ValueError("invalid environment value: must be a string")
        if "\x00" in val:
            raise ValueError("invalid environment value")
        if len(val) > MAX_ENV_VALUE_LEN:
            raise ValueError("invalid environment value: too long")
        normalized[key] = val
    return {"memory_mb": memory_mb, "cpu_cores": cpu_cores, "environment": normalized}


def main():
    request = json.loads(sys.stdin.buffer.read(2 * MAX_FILE))
    options = validate_execution_options(request.get("_execution"))
    attest_limits(memory_mb=options["memory_mb"], cpu_cores=options["cpu_cores"])
    result = operate(request["tool"], request["arguments"], environment=options["environment"])
    if isinstance(result, int):
        return result
    print(json.dumps(result, ensure_ascii=False))
    return 0


def attest_limits(memory_mb=4096, cpu_cores=4):
    with open("/proc/self/status") as stream:
        status = dict(line.split(":", 1) for line in stream if ":" in line)
    checks = {
        "nonroot": os.getuid() != 0,
        "no_new_privileges": status["NoNewPrivs"].strip() == "1",
        "capabilities": int(status["CapEff"].strip(), 16) == 0,
        "seccomp": status["Seccomp"].strip() == "2",
    }
    expected = {
        "memory.max": str(memory_mb * 1024 * 1024),
        "memory.swap.max": "0",
        "pids.max": "128",
    }
    for name, value in expected.items():
        with open("/sys/fs/cgroup/" + name) as stream:
            checks[name] = stream.read().strip() == value
    with open("/sys/fs/cgroup/cpu.max") as stream:
        quota, period = stream.read().split()
        checks["cpu.max"] = quota != "max" and int(quota) / int(period) == cpu_cores
    if not all(checks.values()):
        raise RuntimeError("effective kernel sandbox protections unavailable")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}))
        sys.exit(1)

"""Tests for worker execution options: validation, env merging, attestation."""

import json
import types

import pytest

from local_agent.executor import worker

# ---------------------------------------------------------------------------
# validate_execution_options: defaults and happy path
# ---------------------------------------------------------------------------


def test_defaults_when_none():
    result = worker.validate_execution_options(None)
    assert result == {"memory_mb": 4096, "cpu_cores": 4, "environment": {}}


def test_defaults_when_empty_dict():
    result = worker.validate_execution_options({})
    assert result == {"memory_mb": 4096, "cpu_cores": 4, "environment": {}}


def test_valid_full_options():
    result = worker.validate_execution_options(
        {
            "memory_mb": 2048,
            "cpu_cores": 2,
            "environment": {"FOO": "bar", "_X": "1"},
        }
    )
    assert result["memory_mb"] == 2048
    assert result["cpu_cores"] == 2
    assert result["environment"] == {"FOO": "bar", "_X": "1"}


def test_boundary_values():
    result = worker.validate_execution_options(
        {"memory_mb": 64, "cpu_cores": 1}
    )
    assert result["memory_mb"] == 64
    assert result["cpu_cores"] == 1
    result = worker.validate_execution_options(
        {"memory_mb": 4096, "cpu_cores": 4}
    )
    assert result["memory_mb"] == 4096
    assert result["cpu_cores"] == 4


# ---------------------------------------------------------------------------
# validate_execution_options: type strictness
# ---------------------------------------------------------------------------


def test_rejects_non_dict():
    for bad in (42, "str", [1], True, b"bytes"):
        with pytest.raises(ValueError, match="must be an object"):
            worker.validate_execution_options(bad)


def test_rejects_unknown_options():
    with pytest.raises(ValueError, match="unknown options"):
        worker.validate_execution_options({"memory_mb": 1024, "extra": 1})
    with pytest.raises(ValueError, match="unknown options"):
        worker.validate_execution_options({"bogus": True})


def test_rejects_bool_for_memory_mb():
    with pytest.raises(ValueError, match="must be an integer"):
        worker.validate_execution_options({"memory_mb": True})
    with pytest.raises(ValueError, match="must be an integer"):
        worker.validate_execution_options({"memory_mb": False})


def test_rejects_bool_for_cpu_cores():
    with pytest.raises(ValueError, match="must be an integer"):
        worker.validate_execution_options({"cpu_cores": True})


def test_rejects_float_for_memory_mb():
    with pytest.raises(ValueError, match="must be an integer"):
        worker.validate_execution_options({"memory_mb": 1024.0})


def test_rejects_string_for_cpu_cores():
    with pytest.raises(ValueError, match="must be an integer"):
        worker.validate_execution_options({"cpu_cores": "2"})


def test_rejects_out_of_range_memory_mb():
    with pytest.raises(ValueError, match="out of range"):
        worker.validate_execution_options({"memory_mb": 63})
    with pytest.raises(ValueError, match="out of range"):
        worker.validate_execution_options({"memory_mb": 4097})
    with pytest.raises(ValueError, match="out of range"):
        worker.validate_execution_options({"memory_mb": -1})


def test_rejects_out_of_range_cpu_cores():
    with pytest.raises(ValueError, match="out of range"):
        worker.validate_execution_options({"cpu_cores": 0})
    with pytest.raises(ValueError, match="out of range"):
        worker.validate_execution_options({"cpu_cores": 5})


# ---------------------------------------------------------------------------
# validate_execution_options: environment validation
# ---------------------------------------------------------------------------


def test_rejects_non_dict_environment():
    with pytest.raises(ValueError, match="must be an object"):
        worker.validate_execution_options({"environment": "nope"})
    with pytest.raises(ValueError, match="must be an object"):
        worker.validate_execution_options({"environment": [1, 2]})


def test_rejects_too_many_entries():
    env = {f"K{i}": "v" for i in range(65)}
    with pytest.raises(ValueError, match="too many entries"):
        worker.validate_execution_options({"environment": env})


def test_accepts_exactly_64_entries():
    env = {f"K{i}": "v" for i in range(64)}
    result = worker.validate_execution_options({"environment": env})
    assert len(result["environment"]) == 64


def test_rejects_invalid_key_start():
    with pytest.raises(ValueError, match="invalid environment key"):
        worker.validate_execution_options({"environment": {"1BAD": "v"}})
    with pytest.raises(ValueError, match="invalid environment key"):
        worker.validate_execution_options({"environment": {"-BAD": "v"}})
    with pytest.raises(ValueError, match="invalid environment key"):
        worker.validate_execution_options({"environment": {"": "v"}})


def test_rejects_invalid_key_chars():
    with pytest.raises(ValueError, match="invalid environment key"):
        worker.validate_execution_options({"environment": {"BAD-KEY": "v"}})
    with pytest.raises(ValueError, match="invalid environment key"):
        worker.validate_execution_options({"environment": {"BAD.KEY": "v"}})


def test_rejects_non_string_key():
    with pytest.raises(ValueError, match="invalid environment key"):
        worker.validate_execution_options({"environment": {123: "v"}})


def test_rejects_fixed_safety_env_keys():
    for key in (
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_GLOBAL",
        "PYTHONDONTWRITEBYTECODE",
        "PATH",
        "HOME",
    ):
        with pytest.raises(ValueError, match="fixed safety variable"):
            worker.validate_execution_options({"environment": {key: "evil"}})


def test_rejects_non_string_value():
    with pytest.raises(ValueError, match="must be a string"):
        worker.validate_execution_options({"environment": {"FOO": 42}})
    with pytest.raises(ValueError, match="must be a string"):
        worker.validate_execution_options({"environment": {"FOO": True}})
    with pytest.raises(ValueError, match="must be a string"):
        worker.validate_execution_options({"environment": {"FOO": None}})


def test_rejects_nul_in_value():
    with pytest.raises(ValueError, match="invalid environment value"):
        worker.validate_execution_options({"environment": {"FOO": "a\x00b"}})


def test_rejects_oversized_value():
    with pytest.raises(ValueError, match="too long"):
        worker.validate_execution_options(
            {"environment": {"FOO": "x" * 8193}}
        )


def test_accepts_max_length_value():
    result = worker.validate_execution_options(
        {"environment": {"FOO": "x" * 8192}}
    )
    assert len(result["environment"]["FOO"]) == 8192


def test_error_does_not_echo_secret_value():
    secret = "SUPER_SECRET_TOKEN_abc123"
    with pytest.raises(ValueError) as exc_info:
        worker.validate_execution_options({"environment": {"PATH": secret}})
    # The secret value must not appear in the exception message
    assert secret not in str(exc_info.value)


def test_error_does_not_echo_oversized_value():
    secret = "A" * 9000
    with pytest.raises(ValueError) as exc_info:
        worker.validate_execution_options({"environment": {"FOO": secret}})
    assert secret not in str(exc_info.value)


# ---------------------------------------------------------------------------
# operate: environment merging for run_command
# ---------------------------------------------------------------------------


@pytest.fixture
def root(tmp_path, monkeypatch):
    for name in worker.ALLOWED:
        (tmp_path / name).mkdir()
    monkeypatch.setattr(worker, "ROOT", str(tmp_path))
    return tmp_path


def test_run_command_merges_environment(root, monkeypatch):
    captured = {}

    def fake_run(argv, cwd=None, check=False, env=None):
        captured["env"] = env
        captured["argv"] = argv
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    result = worker.operate(
        "run_command",
        {"argv": ["echo", "hi"]},
        environment={"MY_VAR": "hello"},
    )
    assert result == 0
    # Fixed safety env is present
    assert captured["env"]["PATH"] == "/usr/local/bin:/usr/bin:/bin"
    assert captured["env"]["HOME"] == "/tmp"
    assert captured["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert captured["env"]["GIT_CONFIG_NOSYSTEM"] == "1"
    assert captured["env"]["GIT_CONFIG_GLOBAL"] == "/dev/null"
    # Merged user env is present
    assert captured["env"]["MY_VAR"] == "hello"


def test_run_command_without_environment(root, monkeypatch):
    captured = {}

    def fake_run(argv, cwd=None, check=False, env=None):
        captured["env"] = env
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    result = worker.operate("run_command", {"argv": ["echo", "hi"]})
    assert result == 0
    # No user env keys
    assert "MY_VAR" not in captured["env"]
    # Fixed safety env still present
    assert captured["env"]["PATH"] == "/usr/local/bin:/usr/bin:/bin"


def test_operate_two_args_still_works(root, monkeypatch):
    """Preserve tests calling operate with 2 args (no environment keyword)."""
    captured = {}

    def fake_run(argv, cwd=None, check=False, env=None):
        captured["env"] = env
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    result = worker.operate("run_command", {"argv": ["true"]})
    assert result == 0


# ---------------------------------------------------------------------------
# attest_limits: configurable with mocked cgroup files
# ---------------------------------------------------------------------------


def _make_status_file(tmp_path):
    status = tmp_path / "status"
    status.write_text(
        "Name:\tworker\n"
        "NoNewPrivs:\t1\n"
        "CapEff:\t0000000000000000\n"
        "Seccomp:\t2\n"
    )
    return status


def _make_cgroup_dir(tmp_path, memory_mb=4096, cpu_cores=4):
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.max").write_text(str(memory_mb * 1024 * 1024) + "\n")
    (cgroup / "memory.swap.max").write_text("0\n")
    (cgroup / "pids.max").write_text("128\n")
    (cgroup / "cpu.max").write_text(f"{cpu_cores * 100000} 100000\n")
    return cgroup


def test_attest_limits_defaults_pass(tmp_path, monkeypatch):
    status = _make_status_file(tmp_path)
    cgroup = _make_cgroup_dir(tmp_path, memory_mb=4096, cpu_cores=4)

    def fake_open(path, *a, **kw):
        if path == "/proc/self/status":
            return open(str(status))
        if path.startswith("/sys/fs/cgroup/"):
            name = path.split("/")[-1]
            return open(str(cgroup / name))
        return open(path, *a, **kw)

    monkeypatch.setattr(worker, "open", fake_open, raising=False)
    monkeypatch.setattr(worker.os, "getuid", lambda: 1000)
    worker.attest_limits()  # should not raise


def test_attest_limits_custom_values(tmp_path, monkeypatch):
    status = _make_status_file(tmp_path)
    cgroup = _make_cgroup_dir(tmp_path, memory_mb=2048, cpu_cores=2)

    def fake_open(path, *a, **kw):
        if path == "/proc/self/status":
            return open(str(status))
        if path.startswith("/sys/fs/cgroup/"):
            name = path.split("/")[-1]
            return open(str(cgroup / name))
        return open(path, *a, **kw)

    monkeypatch.setattr(worker, "open", fake_open, raising=False)
    monkeypatch.setattr(worker.os, "getuid", lambda: 1000)
    worker.attest_limits(memory_mb=2048, cpu_cores=2)  # should not raise


def test_attest_limits_mismatch_fails(tmp_path, monkeypatch):
    status = _make_status_file(tmp_path)
    cgroup = _make_cgroup_dir(tmp_path, memory_mb=4096, cpu_cores=4)

    def fake_open(path, *a, **kw):
        if path == "/proc/self/status":
            return open(str(status))
        if path.startswith("/sys/fs/cgroup/"):
            name = path.split("/")[-1]
            return open(str(cgroup / name))
        return open(path, *a, **kw)

    monkeypatch.setattr(worker, "open", fake_open, raising=False)
    monkeypatch.setattr(worker.os, "getuid", lambda: 1000)
    with pytest.raises(RuntimeError, match="sandbox protections"):
        worker.attest_limits(memory_mb=2048, cpu_cores=4)


def test_attest_limits_noargs_still_works(tmp_path, monkeypatch):
    """Preserve tests calling attest_limits with no args."""
    status = _make_status_file(tmp_path)
    cgroup = _make_cgroup_dir(tmp_path, memory_mb=4096, cpu_cores=4)

    def fake_open(path, *a, **kw):
        if path == "/proc/self/status":
            return open(str(status))
        if path.startswith("/sys/fs/cgroup/"):
            name = path.split("/")[-1]
            return open(str(cgroup / name))
        return open(path, *a, **kw)

    monkeypatch.setattr(worker, "open", fake_open, raising=False)
    monkeypatch.setattr(worker.os, "getuid", lambda: 1000)
    worker.attest_limits()  # no args, defaults 4096/4


# ---------------------------------------------------------------------------
# main: end-to-end protocol with _execution
# ---------------------------------------------------------------------------


def test_main_with_execution_options(tmp_path, monkeypatch, capsys):
    """Simulate main() reading a request with _execution from stdin."""
    for name in worker.ALLOWED:
        (tmp_path / name).mkdir()
    monkeypatch.setattr(worker, "ROOT", str(tmp_path))

    status = _make_status_file(tmp_path)
    cgroup = _make_cgroup_dir(tmp_path, memory_mb=1024, cpu_cores=2)

    def fake_open(path, *a, **kw):
        if path == "/proc/self/status":
            return open(str(status))
        if path.startswith("/sys/fs/cgroup/"):
            name = path.split("/")[-1]
            return open(str(cgroup / name))
        return open(path, *a, **kw)

    monkeypatch.setattr(worker, "open", fake_open, raising=False)
    monkeypatch.setattr(worker.os, "getuid", lambda: 1000)

    request = {
        "tool": "run_command",
        "arguments": {"argv": ["true"]},
        "_execution": {
            "memory_mb": 1024,
            "cpu_cores": 2,
            "environment": {"TEST_VAR": "val"},
        },
    }
    monkeypatch.setattr(
        worker.sys, "stdin", types.SimpleNamespace(buffer=types.SimpleNamespace(read=lambda n: json.dumps(request).encode()))
    )

    captured = {}

    def fake_run(argv, cwd=None, check=False, env=None):
        captured["env"] = env
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    rc = worker.main()
    assert rc == 0
    assert captured["env"]["TEST_VAR"] == "val"


def test_main_without_execution_options(tmp_path, monkeypatch):
    """Legacy request without _execution retains default behavior."""
    for name in worker.ALLOWED:
        (tmp_path / name).mkdir()
    monkeypatch.setattr(worker, "ROOT", str(tmp_path))

    status = _make_status_file(tmp_path)
    cgroup = _make_cgroup_dir(tmp_path, memory_mb=4096, cpu_cores=4)

    def fake_open(path, *a, **kw):
        if path == "/proc/self/status":
            return open(str(status))
        if path.startswith("/sys/fs/cgroup/"):
            name = path.split("/")[-1]
            return open(str(cgroup / name))
        return open(path, *a, **kw)

    monkeypatch.setattr(worker, "open", fake_open, raising=False)
    monkeypatch.setattr(worker.os, "getuid", lambda: 1000)

    request = {"tool": "run_command", "arguments": {"argv": ["true"]}}
    monkeypatch.setattr(
        worker.sys, "stdin", types.SimpleNamespace(buffer=types.SimpleNamespace(read=lambda n: json.dumps(request).encode()))
    )

    captured = {}

    def fake_run(argv, cwd=None, check=False, env=None):
        captured["env"] = env
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    rc = worker.main()
    assert rc == 0
    assert "TEST_VAR" not in captured["env"]


def test_environment_key_rejects_trailing_newline():
    with pytest.raises(ValueError):
        worker.validate_execution_options({"environment": {"FOO\n": "value"}})

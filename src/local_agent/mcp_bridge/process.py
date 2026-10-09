import asyncio
import os
import signal
from pathlib import Path
from typing import Dict

MAX_OUTPUT = 8 * 1024 * 1024


async def _cleanup_process(proc: asyncio.subprocess.Process) -> None:
    """Kill and wait for a process group, handling already-exited processes."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), 2)
    except asyncio.TimeoutError:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), 2)
    except asyncio.TimeoutError:
        pass


async def run_cli(argv: list[str], cwd: Path, timeout: float) -> Dict[str, bytes]:
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": os.environ.get("HOME", str(Path.home())),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONPATH": str(cwd / "src"),
    }
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        await _cleanup_process(proc)
        raise
    except asyncio.CancelledError:
        await _cleanup_process(proc)
        raise
    except ProcessLookupError:
        raise
    else:
        if len(stdout) > MAX_OUTPUT or len(stderr) > MAX_OUTPUT:
            raise ValueError("Output exceeds 8MiB")
        return {"stdout": stdout, "stderr": stderr, "exit_code": proc.returncode}

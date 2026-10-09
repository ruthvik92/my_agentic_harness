import asyncio
import os
import sys
from pathlib import Path

import pytest

from local_agent.mcp_bridge.process import run_cli

CHILD_CODE = (
    "import os, time\n"
    "from pathlib import Path\n"
    "Path(r'PIDFILE').write_text(str(os.getpid()))\n"
    "time.sleep(30)\n"
)


def test_run_cli_terminates_child_on_timeout_and_cancel(tmp_path: Path, mode: str) -> None:
    pidfile = tmp_path / "child.pid"
    argv = [sys.executable, "-c", CHILD_CODE.replace("PIDFILE", str(pidfile))]
    timeout = 0.3 if mode == "timeout" else 30.0
    pid: int | None = None

    async def scenario() -> None:
        nonlocal pid
        task = asyncio.create_task(run_cli(argv, tmp_path, timeout))
        deadline = asyncio.get_event_loop().time() + 2.0
        while not pidfile.exists():
            if asyncio.get_event_loop().time() > deadline:
                raise AssertionError("child never wrote its pidfile")
            await asyncio.sleep(0.01)
        pid = int(pidfile.read_text())
        if mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(asyncio.TimeoutError):
                await task

    try:
        asyncio.run(scenario())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        if pid is not None:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                os.kill(pid, 9)


@pytest.fixture(params=["timeout", "cancel"])
def mode(request: pytest.FixtureRequest) -> str:
    return request.param

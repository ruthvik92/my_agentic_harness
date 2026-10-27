import asyncio
import copy
import json
import re
from types import SimpleNamespace

import pytest

from local_agent.contracts import ExecutionSettings
from local_agent.executor.lifecycle import ExecutionManager, lease

IMAGE = "sha256:" + "a" * 64
WS = "ws_" + "1" * 32
WS2 = "ws_" + "2" * 32


class FakeDocker:
    def __init__(self):
        self.containers = {}
        self.calls = []
        self.fail_remove = False
        self.removing = None
        self.allow_remove = None

    async def __call__(self, *args, **kwargs):
        self.calls.append(args)
        op = args[0]
        if op == "inspect":
            return json.dumps([self.containers[args[1]]] if args[1] in self.containers else []).encode()
        if op == "ps":
            filters = [a[6:] for a in args if a.startswith("label=")]
            return "\n".join(
                cid for cid, info in self.containers.items()
                if all(info["Config"]["Labels"].get(f.split("=", 1)[0]) == f.split("=", 1)[1]
                       for f in filters)
            ).encode()
        if op == "create":
            cid = f"{len([c for c in self.calls if c[0] == 'create']):064x}"
            labels = dict(args[i + 1].split("=", 1) for i, a in enumerate(args) if a == "--label")
            self.containers[cid] = {
                "Id": cid, "Image": IMAGE, "Config": {"Labels": labels},
                "State": {"Running": False, "Status": "created"},
            }
            return cid.encode()
        cid = args[-1]
        if op == "start":
            self.containers[cid]["State"] = {"Running": True, "Status": "running"}
        elif op in ("kill", "stop"):
            self.containers[cid]["State"] = {"Running": False, "Status": "exited"}
        elif op == "rm":
            if self.fail_remove:
                raise RuntimeError("injected rm failure")
            if self.removing:
                self.removing.set()
                await self.allow_remove.wait()
            del self.containers[cid]
        else:
            raise AssertionError(args)
        return b""


@pytest.fixture
def setup(tmp_path):
    control = tmp_path / "control"
    control.mkdir()
    for ws in (WS, WS2):
        (tmp_path / ws).mkdir()

    def path(ws, *, allow_missing=False):
        if not isinstance(ws, str) or not re.fullmatch(r"ws_[0-9a-f]{32}", ws):
            raise ValueError("invalid workspace")
        result = tmp_path / ws
        if not result.is_dir() and not allow_missing:
            raise ValueError("unknown workspace")
        return result

    docker, events = FakeDocker(), []
    settings = ExecutionSettings(persistent_container_idle_timeout=1, max_persistent_containers=2)
    store, workspaces = SimpleNamespace(control=control), SimpleNamespace(path=path)

    def create():
        return ExecutionManager(
            store, workspaces, IMAGE, settings, docker=docker,
            attest=lambda info, workspace: None, emit=lambda kind, data: events.append((kind, data)),
        )
    return create, docker, events


def test_reuse_isolation_capacity_and_restart(setup):
    create, docker, _ = setup

    async def scenario():
        manager = create()
        async with manager.session(WS, "run1", "exec1", []):
            first = manager.load(WS)["container_id"]
        async with create().session(WS, "run2", "exec2", []) as reused:
            assert reused["container_id"] == first
            assert reused["run_id"] == "run2"
        async with manager.session(WS2, "run3", "exec3", []) as second:
            assert second["container_id"] != first
        assert len(docker.containers) == 2
        manager.settings = manager.settings.model_copy(update={"max_persistent_containers": 1})
        await manager.stop(WS2)
        with pytest.raises(RuntimeError, match="capacity"):
            async with manager.session(WS2, "run4", "exec4", []):
                pass
    asyncio.run(scenario())


def test_timeout_removal_stays_removed_and_crashed_execution_recreated(setup):
    create, docker, _ = setup

    async def scenario():
        manager = create()
        async with manager.session(WS, "run", "exec", []) as record:
            cid = record["container_id"]
            await manager.terminate(WS, cid)
        assert manager.load(WS)["state"] == "REMOVED"
        assert cid not in docker.containers
        async with manager.session(WS, "run", "exec2", []) as record:
            second = record["container_id"]
        crashed = manager.load(WS)
        crashed.update(state="EXECUTING", active_execution_id="lost")
        manager.save(crashed)
        async with create().session(WS, "run", "exec3", []) as record:
            assert record["container_id"] != second
        assert second not in docker.containers
    asyncio.run(scenario())


def test_concurrency_cleanup_holds_lock_and_wait_cancellation(setup):
    create, docker, _ = setup

    async def scenario():
        manager = create()
        async with manager.session(WS, "run", "exec", []) as record:
            cid = record["container_id"]
            assert await create().cleanup_idle() == []
            entered = asyncio.Event()

            async def waiting():
                async with create().session(WS, "run", "waiter", []):
                    entered.set()

            waiter = asyncio.create_task(waiting())
            await asyncio.sleep(0.08)
            assert not entered.is_set()
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
        record = manager.load(WS)
        record["last_used_at"] = "2000-01-01T00:00:00+00:00"
        manager.save(record)
        docker.removing, docker.allow_remove = asyncio.Event(), asyncio.Event()
        cleanup = asyncio.create_task(create().cleanup_idle())
        await asyncio.wait_for(docker.removing.wait(), 1)
        waiter = asyncio.create_task(waiting())
        await asyncio.sleep(0.08)
        assert not entered.is_set()
        docker.allow_remove.set()
        assert await cleanup == [cid]
        await asyncio.wait_for(waiter, 1)
        assert entered.is_set()
    asyncio.run(scenario())


def test_owned_orphans_and_foreign_container_are_distinguished(setup):
    create, docker, _ = setup

    async def scenario():
        manager = create()
        async with manager.session(WS, "run", "exec", []) as record:
            original = record["container_id"]
        duplicate = copy.deepcopy(docker.containers[original])
        duplicate["Id"] = "f" * 64
        docker.containers[duplicate["Id"]] = duplicate
        foreign = copy.deepcopy(duplicate)
        foreign["Id"] = "e" * 64
        foreign["Config"]["Labels"]["local-agent.owner"] = "foreign"
        docker.containers[foreign["Id"]] = foreign
        assert await manager.cleanup_idle() == [duplicate["Id"]]
        assert manager.load(WS)["container_id"] == original
        assert original in docker.containers and foreign["Id"] in docker.containers
        manager.path(WS).unlink()
        assert await manager.cleanup_idle() == [original]
        assert foreign["Id"] in docker.containers
    asyncio.run(scenario())


def test_cleanup_failure_and_ownership_attestation_fail_closed(setup):
    create, docker, events = setup

    async def scenario():
        manager = create()
        async with manager.session(WS, "run", "exec", []) as record:
            cid = record["container_id"]
        docker.fail_remove = True
        with pytest.raises(RuntimeError, match="injected"):
            await manager.stop(WS)
        assert any(kind == "container.cleanup_failed" for kind, _ in events)
        assert manager.load(WS)["state"] != "REMOVED"
        docker.fail_remove = False
        docker.containers[cid]["Config"]["Labels"]["local-agent.owner"] = "foreign"
        with pytest.raises(PermissionError):
            async with manager.session(WS, "run", "exec2", []):
                pass
        assert len(docker.containers) == 1
        with pytest.raises(ValueError):
            await manager.stop("../elsewhere")
    asyncio.run(scenario())


def test_audit_failure_releases_lease_and_stops_execution(setup):
    create, docker, _ = setup

    async def scenario():
        manager = create()
        async with manager.session(WS, "run", "exec", []):
            pass

        def fail(*_):
            raise OSError("audit unavailable")

        manager.emit = fail
        with pytest.raises(OSError):
            async with manager.session(WS, "run", "exec2", []):
                pytest.fail("execution must not begin without audit")
        async with lease(manager.directory / (WS + ".lock"), wait=False):
            pass
    asyncio.run(scenario())


def test_recovery_stop_does_not_kill_a_later_execution(setup):
    create, docker, _ = setup

    async def scenario():
        manager = create()
        async with manager.session(WS, "run", "exec", []) as record:
            cid = record["container_id"]
        assert not await manager.stop(WS, expected_container_id="other")
        assert docker.containers[cid]["State"]["Running"]
        record = manager.load(WS)
        record["active_execution_id"] = "newer"
        manager.save(record)
        assert not await manager.stop(WS, expected_container_id=cid, expected_execution_id="old")
        assert docker.containers[cid]["State"]["Running"]
    asyncio.run(scenario())


def test_recovery_does_not_stop_later_completed_command(setup):
    create, docker, _ = setup

    async def scenario():
        manager = create()
        async with manager.session(WS, "old-run", "old-exec", []) as record:
            cid = record["container_id"]
        async with manager.session(WS, "new-run", "new-exec", []):
            pass
        assert not await manager.stop(WS, expected_container_id=cid, expected_execution_id="old-exec")
        assert docker.containers[cid]["State"]["Running"]
    asyncio.run(scenario())

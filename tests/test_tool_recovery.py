"""Valid Docker execution after rejected arguments and an observed failing test."""

import asyncio
from pathlib import Path

import pytest

from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.runtime.agent import Agent
from local_agent.storage.blobs import digest
from local_agent.storage.database import Store


def test_rejection_feedback_can_recover_without_relaxing_guards(tmp_path, request):
    image = request.config.getoption("--docker-image")
    if not image:
        pytest.skip("requires --docker-image")
    repo = tmp_path / "source"
    repo.mkdir()
    original = "def add(a,b):\n    return a-b\n"
    (repo / "calculator.py").write_text(original)
    (repo / "test_calculator.py").write_text(
        "from calculator import add\ndef test_add():\n assert add(2,3)==5\n"
    )

    def step(name, args):
        return {
            "text": "",
            "tool_calls": [{"name": name, "arguments": args}],
            "finish_status": "tool_calls",
        }

    def patch(before, after):
        return step(
            "patch_file",
            {
                "path": "project/calculator.py",
                "old_text": before.splitlines()[-1].strip(),
                "new_text": after.splitlines()[-1].strip(),
                "expected_hash": digest(before.encode()),
            },
        )

    first = original.replace("a-b", "a*b")
    second = original.replace("a-b", "a/b")
    correct = original.replace("a-b", "a+b")
    check = step("run_command", {"argv": ["python", "-m", "pytest", "-q"], "cwd": "project"})
    provider = ScriptedProvider(
        responses=[
            step("run_command", {"argv": ["python", "-m", "pytest", "-q"], "cwd": "."}),
            check,
            step("read_file", {"path": "project/calculator.py"}),
            step(
                "write_file",
                {
                    "path": "project/calculator.py",
                    "content": "unsafe replacement",
                    "create_only": False,
                },
            ),
            patch(original, first),
            check,
            patch(first, second),
            check,
            patch(second, correct),
            check,
            {"text": "Actual regression now passes", "tool_calls": [], "finish_status": "stop"},
        ]
    )
    store = Store(tmp_path / "data")
    cfg = load_config(Path("config/coder.yaml")).model_copy(update={"project_tests": False})
    try:
        result = asyncio.run(
            Agent(store, cfg, {**sandbox_config(), "image": image}, provider=provider).run(
                repo, "Fix calculator"
            )
        )
        assert result["status"] == "completed_unverified", result
        assert audit(store, result["run_id"])["ok"]
        after_bad_cwd = store.blobs.json(provider.requests[1].context_ref)["messages"]
        assert any(
            "cwd='project'" in m.get("content", "") for m in after_bad_cwd if m["role"] == "tool"
        )
        after_bad_write = store.blobs.json(provider.requests[4].context_ref)["messages"]
        assert any(
            "expected_hash" in m.get("content", "") and "correction" in m.get("content", "")
            for m in after_bad_write
            if m["role"] == "tool"
        )
        results = [
            store.blobs.json(e.data["result_ref"])
            for e in store.events(result["run_id"])
            if e.event_type == "execution.finished"
        ]
        checks = [r for r in results if "passed" in r["preview"] or "failed" in r["preview"]]
        assert sum(r["exit_code"] == 1 and "1 failed" in r["preview"] for r in checks) == 3
        assert any(r["exit_code"] == 0 and "1 passed" in r["preview"] for r in checks)
        assert (repo / "calculator.py").read_text() == original
        events = store.events(result["run_id"])
        assert sum(e.event_type == "tool.rejected" for e in events) == 2
    finally:
        store.close()


@pytest.mark.parametrize("failures", [1, 2])
def test_only_one_local_malformed_response_repair(tmp_path, request, failures):
    from local_agent.models.ollama import ProviderResponseError

    image = request.config.getoption("--docker-image")
    if not image:
        pytest.skip("requires --docker-image")
    source = tmp_path / "source"
    source.mkdir()
    store = Store(tmp_path / "data")

    class BrokenThenDone(ScriptedProvider):
        def __init__(self):
            super().__init__(
                responses=[{"text": "Done", "tool_calls": [], "finish_status": "stop"}]
            )
            self.broken = 0
            self.snapshots = []

        async def generate(self, request):
            self.snapshots.append(store.blobs.json(request.context_ref))
            if self.broken < failures:
                self.broken += 1
                ref = store.blobs.put_json(
                    {"error": "invalid tool call arguments: unexpected end of JSON input"}
                )
                raise ProviderResponseError(
                    "Ollama HTTP status 500: invalid tool call arguments",
                    ref,
                    recoverable_tool_error=True,
                )
            return await super().generate(request)

    provider = BrokenThenDone()
    cfg = load_config(Path("config/coder.yaml")).model_copy(update={"project_tests": False})
    try:
        result = asyncio.run(
            Agent(store, cfg, {**sandbox_config(), "image": image}, provider=provider).run(
                source, "Record bounded recovery"
            )
        )
        assert result["status"] == ("completed_unverified" if failures == 1 else "failed")
        events = store.events(result["run_id"])
        retries = [
            e
            for e in events
            if e.event_type == "retry.decided"
            and e.data.get("rule") == "local-tool-response-repair-v1"
        ]
        assert len(retries) == 1
        assert len(provider.snapshots) == 2
        assert any(
            "exactly one small tool call" in m.get("content", "")
            for m in provider.snapshots[1]["messages"]
        )
        assert audit(store, result["run_id"])["ok"]
    finally:
        store.close()

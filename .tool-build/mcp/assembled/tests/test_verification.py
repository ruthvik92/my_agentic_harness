import asyncio
from pathlib import Path

import pytest

from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.models.scripted import ScriptedProvider
from local_agent.runtime.agent import Agent
from local_agent.storage.blobs import digest
from local_agent.storage.database import Store


def test_editable_tests_do_not_prove_success(tmp_path, request):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    source = Path("tests/fixtures/broken_repo")
    provider = ScriptedProvider(
        responses=(
            {
                "text": "Weakening tests",
                "tool_calls": [
                    {
                        "name": "write_file",
                        "arguments": {
                            "path": "project/test_calculator.py",
                            "content": "def test_add():\n    assert True\n",
                            "create_only": False,
                            "expected_hash": digest((source / "test_calculator.py").read_bytes()),
                        },
                    }
                ],
                "finish_status": "tool_calls",
            },
            {"text": "Done", "tool_calls": [], "finish_status": "stop"},
        )
    )
    store = Store(tmp_path / "data")
    result = asyncio.run(
        Agent(
            store,
            load_config(Path("config/coder.yaml")),
            {**sandbox_config(), "image": image},
            provider=provider,
        ).run(source, "Fix add", verify_fixture=True)
    )
    assert result["status"] == "failed", result
    checks = [e for e in store.events(result["run_id"]) if e.event_type == "completion.verified"]
    assert checks and not checks[0].data["passed"]
    store.close()

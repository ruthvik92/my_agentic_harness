import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = [
    "harness_capabilities",
    "harness_models",
    "harness_run_code",
    "harness_runs",
    "harness_trace",
    "harness_artifacts",
    "harness_screenshot",
    "harness_circuit",
]


def _payload(result):
    if result.structuredContent:
        return result.structuredContent
    text = "".join(block.text for block in result.content if getattr(block, "type", "") == "text")
    return json.loads(text)


def test_mcp_protocol(tmp_path):
    root = Path(__file__).resolve().parents[1]
    allow = tmp_path / "allowed"
    allow.mkdir()
    state = tmp_path / "state"

    env = {"PYTHONPATH": os.environ.get("PYTHONPATH", str(root / "src"))}
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "local_agent.mcp_bridge.stdio",
            "--data-root",
            str(state),
            "--allow-root",
            str(allow),
        ],
        env=env,
        cwd=str(root),
    )

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = [tool.name for tool in tools.tools]
                assert sorted(names) == sorted(EXPECTED_TOOLS)

                caps = _payload(await session.call_tool("harness_capabilities", {}))
                assert caps["provider"] == "ollama"
                assert caps["verifier_available"] is False

                runs = _payload(await session.call_tool("harness_runs", {}))
                assert runs["runs"] == []

                rejected = await session.call_tool(
                    "harness_run_code",
                    {"repo": str(tmp_path), "task": "Should be rejected"},
                )
                assert rejected.isError is True

                shot = await session.call_tool("harness_screenshot", {"question": "No image"})
                assert shot.isError is True

    asyncio.run(scenario())

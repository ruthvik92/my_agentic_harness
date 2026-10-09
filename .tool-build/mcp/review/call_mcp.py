"""Supervision utility: invoke the real MCP coding workflow in a fresh server."""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

harness, repo, task_file, result_file = map(Path, sys.argv[1:])

async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "local_agent.mcp_bridge.stdio", "--data-root",
              "/home/ruthvik/.local/share/local-agent-mcp", "--allow-root",
              "/home/ruthvik/my_agentic_harness"],
        env={"PYTHONPATH": str(harness / "src")},
        cwd=str(harness),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("harness_run_code", {
                "repo": str(repo), "task": task_file.read_text(), "model": "qwen3.8:27b"
            }, read_timeout_seconds=__import__('datetime').timedelta(seconds=1500))
            result_file.write_text(result.model_dump_json(indent=2))
            for block in result.content:
                if getattr(block, "type", None) == "text":
                    print(block.text)

asyncio.run(main())

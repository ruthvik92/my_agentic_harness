"""Trusted test driver: exits the controller process at a selected commit boundary."""

import asyncio
import json
import os
import sys
from pathlib import Path

from local_agent.config import load_config
from local_agent.contracts import ExecutionSettings
from local_agent.doctor import sandbox_config
from local_agent.models.scripted import ScriptedProvider
from local_agent.runtime.agent import Agent
from local_agent.storage.database import Store

root, point, image = sys.argv[1:4]
mode = sys.argv[4] if len(sys.argv) > 4 else "ephemeral"
source = Path(sys.argv[5]) if len(sys.argv) > 5 else Path(__file__).parent / "fixtures" / "broken_repo"
code = "from pathlib import Path; p=Path('count'); p.write_text((p.read_text() if p.exists() else '')+'X')"
if point == "after_container_launch":
    code += "; import time; time.sleep(30)"
provider = ScriptedProvider(
    responses=(
        {
            "text": "Perform one mutation",
            "tool_calls": [
                {"name": "run_command", "arguments": {"argv": ["python", "-I", "-c", code]}}
            ],
            "finish_status": "tool_calls",
        },
        {"text": "Done", "tool_calls": [], "finish_status": "stop"},
    )
)


def crash(boundary):
    if boundary == point:
        os._exit(86)



config = load_config(Path("config/coder.yaml"))
config = config.model_copy(update={"execution": ExecutionSettings(execution_mode_default=mode)})
store = Store(Path(root))
agent = Agent(
    store,
    config,
    {**sandbox_config(), "image": image},
    provider=provider,
    fault_hook=crash,
)
print(json.dumps(asyncio.run(agent.run(source, "Make one recorded mutation"))))

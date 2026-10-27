"""Trusted test driver: exits the controller process at a selected commit boundary."""

import asyncio
import json
import os
import sys
from pathlib import Path

from PIL import Image

from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.models.scripted import ScriptedProvider
from local_agent.runtime.agent import Agent
from local_agent.storage.database import Store

root, point, image = sys.argv[1:]
source = Path(root).parent / "image-source"
source.mkdir(exist_ok=True)
Image.new("RGB", (16, 16), "white").save(source / "visible.png")
provider = ScriptedProvider(
    responses=(
        {
            "text": "Inspect visible.png once",
            "tool_calls": [
                {"name": "view_image", "arguments": {"path": "project/visible.png"}}
            ],
            "finish_status": "tool_calls",
        },
        {"text": "Done", "tool_calls": [], "finish_status": "stop"},
    )
)


def crash(boundary):
    if boundary == point:
        row = store.db.execute(
            "SELECT request_ref FROM execution_attempts ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row is not None and store.blobs.json(row["request_ref"])["tool"] == "view_image":
            os._exit(86)


store = Store(Path(root))
config = load_config(Path("config/coder.yaml"))
config = config.model_copy(
    update={"tools": tuple(dict.fromkeys((*config.tools, "view_image")))}
)
agent = Agent(
    store,
    config,
    {**sandbox_config(), "image": image},
    provider=provider,
    fault_hook=crash,
)
print(json.dumps(asyncio.run(agent.run(source, "Inspect visible.png once"))))

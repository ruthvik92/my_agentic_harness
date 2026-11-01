"""Native integration check for the browser-facing agent runtime."""

import asyncio
import base64
from pathlib import Path

import pytest
from test_mobile_runtime import screenshot

from local_agent.config import load_config
from local_agent.mobile.browser_agent import BrowserAgent
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.runtime.image_records import tool_images
from local_agent.storage.bundles import roots
from local_agent.storage.database import Store


def test_browser_uses_durable_runtime_and_audits(tmp_path, request):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    source = tmp_path / "source"
    source.mkdir()
    store = Store(tmp_path / "state")
    raw = screenshot()
    cfg = load_config(Path("config") / "browser.yaml")
    cfg = cfg.model_copy(update={"tools": ("view_image",)})
    provider = ScriptedProvider(
        responses=(
            {
                "text": "",
                "tool_calls": [
                    {"name": "view_image", "arguments": {"path": "scratch/browser-upload.png"}}
                ],
                "finish_status": "tool_calls",
            },
            {"text": "A test screenshot.", "tool_calls": [], "finish_status": "stop"},
        )
    )
    agent = BrowserAgent(
        store,
        cfg,
        {"image": image},
        provider=provider,
        request={"question": "Explain", "image": base64.b64encode(raw).decode()},
    )
    result = asyncio.run(agent.run(source, "Explain"))
    try:
        assert result["status"] == "completed_unverified", result
        assert result["answer"] == "A test screenshot."
        evidence, _ = roots(store, result["run_id"])
        assert store.blobs.put(raw) in evidence
        checked = audit(store, result["run_id"])
        assert checked["ok"], checked["errors"]
        assert any(e.event_type == "browser.prepared" for e in store.events(result["run_id"]))
        assert agent.prepared()["image_info"] == {
            "width": 16,
            "height": 16,
            "bytes": len(raw),
            "mime": "image/png",
        }
        assert agent.prepared()["image_path"] == "scratch/browser-upload.png"
        assert (agent.path / "scratch" / "browser-upload.png").is_file()
        snapshot = store.blobs.json(provider.requests[-1].context_ref)
        messages = store.blobs.json(snapshot["payload_ref"])["messages"]
        system = next(
            m
            for m in messages
            if m["role"] == "system"
            and "view_image" in m["content"]
            and "scratch/browser-upload.png" in m["content"]
        )
        assert "view_image" in system["content"]
        assert "scratch/browser-upload.png" in system["content"]
        assert "no filesystem or command tools" not in system["content"]
        assert any("images" in m for m in messages)
        assert len(tool_images(store, result["run_id"])) == 1
    finally:
        store.close()


def test_coding_browser_keeps_tool_guidance_despite_screenshot_override():
    from types import SimpleNamespace

    from local_agent.tools.guidance import GUIDE

    agent = object.__new__(BrowserAgent)
    agent.config = load_config(Path("config/coder.yaml"))
    agent.instructions = "Coding instructions"
    agent.working_directory = "."
    agent.test_plan = None
    agent.store = SimpleNamespace(blobs=SimpleNamespace(json=lambda _: []))
    agent.prepared = lambda: {"history_ref": "history", "image_ref": None}
    messages = agent.fixed_messages("Fix CRLF")
    assert any(m["role"] == "system" and m["content"] == GUIDE for m in messages)
    assert any("Task working directory: project" in m.get("content", "") for m in messages)
    assert not any("no filesystem or command tools" in m.get("content", "") for m in messages)

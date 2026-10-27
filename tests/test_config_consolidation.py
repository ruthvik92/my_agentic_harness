"""Public entry points use the three active profiles; optional review is explicit."""

import base64
import json
from pathlib import Path

import httpx
import pytest
from test_mobile_runtime import screenshot

from local_agent.cli import main
from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.mcp_bridge.profiles import choose
from local_agent.mobile.browser_agent import BrowserAgent
from local_agent.mobile.models import Models
from local_agent.mobile.profiles import Profiles
from local_agent.models.scripted import ScriptedProvider
from local_agent.storage.database import Store


def test_config_selector_contains_only_three_active_profiles_and_infrastructure():
    entries = Profiles(Path("config")).catalog()["profiles"]
    assert {entry["name"] for entry in entries} == {
        "browser.yaml", "analog.yaml", "coder.yaml", "sandbox.json",
    }
    assert all(entry["valid"] for entry in entries)
    assert {entry["mode"] for entry in entries if entry["kind"] == "agent"} == {
        "chat", "coding", "circuit",
    }


@pytest.mark.parametrize("kind,filename", [
    ("coding", "coder.yaml"), ("screenshot", "browser.yaml"), ("circuit", "analog.yaml"),
])
def test_mcp_uses_active_profile_without_legacy_config(kind, filename):
    expected = load_config(Path("config") / filename)
    catalog = {"models": [{
        "model": expected.model, "capabilities": ["completion", "tools", "vision"],
    }]}
    actual = choose(kind, None, catalog, Path.cwd())
    assert actual == expected


def test_reviewer_disabled_by_default_even_when_api_key_exists(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-for-implicit-review")

    def unexpected(*args, **kwargs):
        pytest.fail("disabled reviewer must not make a network request")

    monkeypatch.setattr(httpx, "Client", unexpected)
    models = Models(load_config(Path("config/browser.yaml")))
    reviewer = models.review_catalog()
    assert reviewer["enabled"] is False
    assert reviewer["models"] == []
    assert "--verifier-agent" in reviewer["reason"]
    with pytest.raises(ValueError, match="Reviewer disabled"):
        models.select_reviewer()


def test_default_screenshot_cli_runs_browser_profile_with_scripted_inference(
    tmp_path, request, monkeypatch, capsys,
):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    sandbox = {**sandbox_config(), "image": image}
    monkeypatch.setattr("local_agent.doctor.sandbox_config", lambda: sandbox)

    class ScriptedBrowser(BrowserAgent):
        def __init__(self, *args, **kwargs):
            assert args[1].instructions_version == "browser-v1"
            kwargs["provider"] = ScriptedProvider(responses=(
                {"text": "Screenshot captured", "tool_calls": [], "finish_status": "stop"},
            ))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("local_agent.mobile.browser_agent.BrowserAgent", ScriptedBrowser)
    source = tmp_path / "request.json"
    source.write_text(json.dumps({
        "question": "Explain", "image": base64.b64encode(screenshot()).decode(),
    }))
    root = tmp_path / "data"
    assert main(["--data-root", str(root), "screenshot", "--request", str(source)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["answer"] == "Screenshot captured"
    assert result["audit"]["ok"] is True
    store = Store(root, readonly=True)
    try:
        assert any(e.event_type == "browser.prepared" for e in store.events(result["run_id"]))
    finally:
        store.close()

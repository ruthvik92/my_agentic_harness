import pytest

from local_agent.contracts import AgentConfig
from local_agent.mcp_bridge import profiles

CASES = [
    ("coding", None, ["completion", "tools"], True),
    ("screenshot", None, ["completion", "vision"], True),
    ("circuit", None, ["completion", "tools", "vision"], True),
    ("coding", None, ["completion"], False),
    ("screenshot", None, ["completion", "tools"], False),
    ("circuit", None, ["completion", "vision"], False),
    ("coding", "missing", ["completion", "tools"], False),
    ("verifier", None, ["completion", "tools", "vision"], False),
]


@pytest.mark.parametrize("kind,model,caps,allowed", CASES)
def test_choose_routing(kind, model, caps, allowed, monkeypatch, tmp_path):
    cfg = AgentConfig(provider="ollama", model="local-test", instructions_hash="sha256:" + "0" * 64)
    monkeypatch.setattr(profiles, "load_config", lambda path: cfg)
    catalog = {"models": [{"model": "local-test", "capabilities": caps}]}
    if allowed:
        result = profiles.choose(kind, model, catalog, tmp_path)
        assert result.provider == "ollama"
        assert result.model == "local-test"
    else:
        with pytest.raises(ValueError):
            profiles.choose(kind, model, catalog, tmp_path)

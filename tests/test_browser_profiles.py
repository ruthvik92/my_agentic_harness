from pathlib import Path

import pytest

from local_agent.mobile.profiles import Profiles


def test_create_update_stale_and_invalid_preserve_bytes(tmp_path, monkeypatch):
    import local_agent.models.token_limits as token_limits

    calls = {"n": 0}

    def fake_fetch(config):
        calls["n"] += 1
        return {
            "show": {
                "model_info": {
                    "general.architecture": "test",
                    "test.context_length": 262144,
                }
            }
        }

    monkeypatch.setattr(token_limits, "fetch_limits_metadata", fake_fetch)

    profiles = Profiles(tmp_path)
    original = Path("config/browser.yaml").read_text()

    profiles.save("x.yaml", original)

    with pytest.raises(FileExistsError):
        profiles.save("x.yaml", original)

    original_hash = profiles.read("x.yaml")["hash"]
    updated = original + "\n# updated\n"
    profiles.save("x.yaml", updated, expected_hash=original_hash)

    updated_hash = profiles.read("x.yaml")["hash"]
    assert profiles.read("x.yaml")["content"] == updated

    with pytest.raises(FileExistsError):
        profiles.save("x.yaml", original, expected_hash=original_hash)

    assert profiles.read("x.yaml")["content"] == updated
    assert profiles.read("x.yaml")["hash"] == updated_hash

    with pytest.raises(ValueError):
        profiles.save("x.yaml", "[]", expected_hash=updated_hash)

    assert profiles.read("x.yaml")["content"] == updated
    assert profiles.read("x.yaml")["hash"] == updated_hash


def test_saved_result_preserves_name_content_hash_metadata(tmp_path, monkeypatch):
    import local_agent.models.token_limits as token_limits

    calls = {"n": 0}

    def fake_fetch(config):
        calls["n"] += 1
        return {
            "show": {
                "model_info": {
                    "general.architecture": "test",
                    "test.context_length": 262144,
                }
            }
        }

    monkeypatch.setattr(token_limits, "fetch_limits_metadata", fake_fetch)

    profiles = Profiles(tmp_path)
    original = Path("config/browser.yaml").read_text()

    saved = profiles.save("x.yaml", original)
    assert saved["name"] == "x.yaml"
    assert saved["content"] == original
    assert saved["hash"] == profiles.read("x.yaml")["hash"]
    assert saved["metadata"]["valid"] is True
    assert saved["valid"] is True
    assert "provider_limits" in saved
    # entry.metadata must contain the checked report including provider_limits
    assert saved["metadata"]["provider_limits"] == saved["provider_limits"]

    # Structurally-valid config requesting window 524288 / output 65536
    # against a fake provider context of 262144 -> provider rejection, fetch once.
    calls["n"] = 0
    oversized_yaml = (
        "agent_id: test\n"
        "provider: ollama\n"
        "model: test-model\n"
        "instructions_version: browser-v1\n"
        "tools: []\n"
        "window_tokens: 524288\n"
        "output_reserve_tokens: 65536\n"
    )
    with pytest.raises(ValueError):
        profiles.save("oversized.yaml", oversized_yaml)
    assert calls["n"] == 1

    # Structurally invalid '[]' rejects before any HTTP fetch.
    calls["n"] = 0
    with pytest.raises(ValueError):
        profiles.save("bad.yaml", "[]")
    assert calls["n"] == 0

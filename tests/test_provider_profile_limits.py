from pathlib import Path

import pytest
import yaml

import local_agent.models.token_limits as token_limits
from local_agent.mobile.profiles import Profiles


def _fake_fetch(context_length):
    calls = {"n": 0}

    def fake_fetch(config):
        calls["n"] += 1
        return {
            "show": {
                "model_info": {
                    "general.architecture": "test",
                    "test.context_length": context_length,
                }
            }
        }

    return fake_fetch, calls


def test_explicit_validate_and_save_fetch_once(tmp_path, monkeypatch):
    fake_fetch, calls = _fake_fetch(262144)
    monkeypatch.setattr(token_limits, "fetch_limits_metadata", fake_fetch)

    profiles = Profiles(tmp_path)
    original = Path("config/browser.yaml").read_text()

    meta = profiles.validate("x.yaml", original)
    assert calls["n"] == 1
    assert meta["valid"] is True
    assert "provider_limits" in meta
    assert "message" in meta

    calls["n"] = 0
    saved = profiles.save("x.yaml", original)
    assert calls["n"] == 1
    assert saved["valid"] is True
    assert "provider_limits" in saved


def test_passive_catalog_read_load_fetch_zero(tmp_path, monkeypatch):
    fake_fetch, calls = _fake_fetch(262144)
    monkeypatch.setattr(token_limits, "fetch_limits_metadata", fake_fetch)

    profiles = Profiles(tmp_path)
    original = Path("config/browser.yaml").read_text()
    profiles.save("x.yaml", original)
    calls["n"] = 0

    catalog = profiles.catalog()
    assert calls["n"] == 0
    assert catalog["profiles"][0]["valid"] is True

    entry = profiles.read("x.yaml")
    assert calls["n"] == 0
    assert entry["metadata"]["valid"] is True

    config = profiles.load("x.yaml")
    assert calls["n"] == 0
    assert config is not None


def test_known_262144_context_accepts_limits(tmp_path, monkeypatch):
    fake_fetch, calls = _fake_fetch(262144)
    monkeypatch.setattr(token_limits, "fetch_limits_metadata", fake_fetch)

    profiles = Profiles(tmp_path)
    original = Path("config/browser.yaml").read_text()
    parsed = yaml.safe_load(original)
    parsed["window_tokens"] = 262144
    parsed["output_reserve_tokens"] = 65536
    content = yaml.safe_dump(parsed)

    meta = profiles.validate("x.yaml", content)
    assert meta["valid"] is True
    limits = meta["provider_limits"]["limits"]
    assert limits["context_window"] == 262144
    assert limits["max_output_tokens"] is None
    report = meta["provider_limits"]
    assert report["context_verified"] is True
    assert report["output_verified"] is False
    assert report["verified"] is False
    message = meta["message"]
    assert "196608" in message
    assert "65536" in message
    assert "unknown" in message
    assert parsed["model"] in message


def test_known_limit_violation_rejects_and_preserves_bytes(tmp_path, monkeypatch):
    fake_fetch, calls = _fake_fetch(131072)
    monkeypatch.setattr(token_limits, "fetch_limits_metadata", fake_fetch)

    profiles = Profiles(tmp_path)
    original = Path("config/browser.yaml").read_text()
    profiles.save("x.yaml", original)

    existing = profiles.read("x.yaml")
    existing_content = existing["content"]
    existing_hash = existing["hash"]

    parsed = yaml.safe_load(original)
    parsed["window_tokens"] = 262144
    parsed["output_reserve_tokens"] = 65536
    invalid_content = yaml.safe_dump(parsed)

    with pytest.raises(ValueError):
        profiles.save("x.yaml", invalid_content, expected_hash=existing_hash)

    after = profiles.read("x.yaml")
    assert after["content"] == existing_content
    assert after["hash"] == existing_hash

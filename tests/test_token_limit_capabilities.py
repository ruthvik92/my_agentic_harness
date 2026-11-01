"""Regression: ensure_capabilities validates token limits from already-fetched metadata."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_agent.config import load_config
from local_agent.models import capabilities
from local_agent.models.capabilities import ensure_capabilities


class FakeProvider:
    def __init__(self, metadata):
        self._metadata = metadata
        self.metadata_calls = 0
        self.closed = 0
        self.generate_calls = 0

    async def metadata(self, model):
        self.metadata_calls += 1
        return self._metadata

    async def close(self):
        self.closed += 1

    async def generate(self, *args, **kwargs):
        self.generate_calls += 1
        raise AssertionError("generate must not be called")


def _run(monkeypatch, metadata, window_tokens, reserve, provider="ollama"):
    fake = FakeProvider(metadata)
    monkeypatch.setattr(capabilities, "create_provider", lambda blobs, config: fake)
    config = load_config(Path("config/coder.yaml"))
    config = config.model_copy(
        update={
            "window_tokens": window_tokens,
            "output_reserve_tokens": reserve,
            "provider": provider,
        }
    )
    store = SimpleNamespace(blobs=object())
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(ensure_capabilities(store, config, {"image": "sha256:" + "0" * 64}))
    return fake, excinfo.value


def test_ollama_context_limit_rejected_before_probe(monkeypatch):
    metadata = {
        "installed": {"digest": "sha256:" + "1" * 64},
        "show": {
            "model_info": {
                "general.architecture": "test",
                "test.context_length": 262144,
            }
        },
    }
    fake, error = _run(monkeypatch, metadata, 524288, 65536)
    message = str(error)
    assert "524288" in message
    assert "262144" in message
    assert fake.metadata_calls == 1
    assert fake.closed == 1
    assert fake.generate_calls == 0


def test_openai_output_limit_rejected_before_probe(monkeypatch):
    metadata = {
        "installed": {"digest": "sha256:" + "2" * 64},
        "openai": {
            "model_record": {
                "context_window": 262144,
                "max_output_tokens": 4096,
            }
        },
    }
    fake, error = _run(monkeypatch, metadata, 16384, 8192, provider="openai")
    message = str(error)
    assert "8192" in message
    assert "4096" in message
    assert fake.metadata_calls == 1
    assert fake.closed == 1
    assert fake.generate_calls == 0

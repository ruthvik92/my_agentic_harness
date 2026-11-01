"""Offline tests for token-limit runtime validation at startup and resume."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from local_agent.config import load_config
from local_agent.contracts import ContextSnapshot, ModelRequest, new_id
from local_agent.models.ollama import OllamaProvider
from local_agent.policy.engine import OFFLINE_HASH
from local_agent.runtime.agent import Agent
from local_agent.runtime.context import ContextBuilder
from local_agent.runtime.recovery import restore
from local_agent.storage.blobs import digest
from local_agent.storage.database import Store


def _make_fake_provider(context_length=262144, max_output_tokens=None, provider="ollama"):
    """A fake provider that is NOT a ScriptedProvider."""

    class FakeProvider:
        def __init__(self):
            self.generate_calls = 0
            self.metadata_calls = 0
            self.requested_models = []

        async def metadata(self, model):
            self.metadata_calls += 1
            self.requested_models.append(model)
            result = {
                "installed": {"digest": "sha256:" + "1" * 64},
            }
            if provider == "openai":
                record = {
                    "id": model,
                    "context_window": context_length,
                }
                if max_output_tokens is not None:
                    record["max_output_tokens"] = max_output_tokens
                result["openai"] = {"model_record": record}
            else:
                info = {
                    "general.architecture": "test",
                    "test.context_length": context_length,
                }
                if max_output_tokens is not None:
                    info["test.max_output_tokens"] = max_output_tokens
                result["show"] = {"model_info": info}
            return result

        async def generate(self, request):
            self.generate_calls += 1
            raise AssertionError("generate must not be called")

        async def close(self):
            pass

    return FakeProvider()


def _base_config():
    return load_config(Path("config/coder.yaml"))


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state")
    yield s
    s.close()


class TestStartupValidation:
    def test_known_context_violation_rejected(self, tmp_path, store):
        """window_tokens exceeds known context window -> failed before Docker/workspace."""
        cfg = _base_config().model_copy(
            update={"window_tokens": 524288, "output_reserve_tokens": 16384}
        )
        fake = _make_fake_provider(context_length=262144)
        sandbox = {"image": "sha256:" + "0" * 64}
        agent = Agent(store, cfg, sandbox, provider=fake)

        # Create a real tmp source directory with a sentinel file
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "sentinel.txt").write_text("hello")

        result = asyncio.run(agent.run(str(source_dir), "test-task"))
        assert result["status"] == "failed"
        assert "exceeds known context window" in result["error"]
        assert fake.generate_calls == 0
        # No workspace created
        assert not hasattr(agent, "workspace_id")
        # No-mutation: source dir untouched, no .git, sentinel unchanged
        assert not (source_dir / ".git").exists()
        assert (source_dir / "sentinel.txt").read_text() == "hello"
        # Metadata lookup used the exact configured model
        assert fake.requested_models == [cfg.model]

    def test_known_output_violation_rejected(self, tmp_path, store):
        """output_reserve_tokens exceeds provider max_output_tokens -> rejected."""
        cfg = _base_config().model_copy(
            update={
                "provider": "openai",
                "window_tokens": 65536,
                "output_reserve_tokens": 16384,
            }
        )
        # Provider reports max_output_tokens=8192, which is less than reserve 16384
        fake = _make_fake_provider(context_length=262144, max_output_tokens=8192, provider="openai")
        sandbox = {"image": "sha256:" + "0" * 64}
        agent = Agent(store, cfg, sandbox, provider=fake)

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "sentinel.txt").write_text("hello")

        result = asyncio.run(agent.run(str(source_dir), "test-task"))
        assert result["status"] == "failed"
        assert "8192" in result["error"]
        assert "16384" in result["error"]
        assert "workspace_id" not in result["error"]
        assert fake.generate_calls == 0
        # No-mutation: source dir untouched, no .git, sentinel unchanged
        assert not (source_dir / ".git").exists()
        assert (source_dir / "sentinel.txt").read_text() == "hello"
        # Metadata lookup used the exact configured model
        assert fake.requested_models == [cfg.model]

    def test_effective_model_override(self, tmp_path, store):
        """The effective config model is used for metadata lookup; rejection before workspace."""
        cfg = _base_config().model_copy(
            update={
                "model": "override-small",
                "window_tokens": 65536,
                "output_reserve_tokens": 16384,
            }
        )
        # Provider reports context 32768 for the override model, less than window 65536
        fake = _make_fake_provider(context_length=32768)
        sandbox = {"image": "sha256:" + "0" * 64}
        agent = Agent(store, cfg, sandbox, provider=fake)

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "sentinel.txt").write_text("hello")

        result = asyncio.run(agent.run(str(source_dir), "test-task"))
        assert result["status"] == "failed"
        assert "exceeds known context window" in result["error"]
        assert fake.generate_calls == 0
        # The metadata call must have used the override model name
        assert "override-small" in fake.requested_models
        assert not hasattr(agent, "workspace_id")
        # No-mutation: source dir untouched, no .git, sentinel unchanged
        assert not (source_dir / ".git").exists()
        assert (source_dir / "sentinel.txt").read_text() == "hello"
        # Metadata lookup used the exact override model
        assert fake.requested_models == [cfg.model]


class TestResumeValidation:
    def test_restore_preflight_rejection(self, tmp_path, store, monkeypatch):
        """restore() rejects when window exceeds known context before workspace work."""
        cfg = _base_config().model_copy(
            update={"window_tokens": 524288, "output_reserve_tokens": 16384}
        )
        fake = _make_fake_provider(context_length=262144)
        sandbox = {"image": "sha256:" + "0" * 64}

        # Set up blobs with config and manifest
        config_dict = {
            "model_metadata": {"scripted": False},
            "sandbox": sandbox,
            "agent": cfg.model_dump(mode="json"),
            "policy_hash": OFFLINE_HASH,
        }
        config_ref = store.blobs.put_json(config_dict)
        config_hash = digest(store.blobs.read(config_ref))
        manifest = {
            "config_ref": config_ref,
            "config_hash": config_hash,
            "model_identity": "sha256:" + "1" * 64,
            "workspace_id": "ws-test",
        }
        manifest_ref = store.blobs.put_json(manifest)

        # Monkeypatch store methods
        store.run = lambda run_id: {"status": "running", "manifest_ref": manifest_ref}
        store.events = lambda run_id: [SimpleNamespace(event_id="unused")]

        # Monkeypatch roots to return empty
        import local_agent.storage.bundles as bundles

        monkeypatch.setattr(bundles, "roots", lambda store, run_id: ([], set()))

        # Set budget large enough
        store.blobs.begin_budget(10 * 1024 * 1024)

        agent = SimpleNamespace(
            store=store,
            config=cfg,
            sandbox=sandbox,
            provider=fake,
        )

        with pytest.raises(ValueError, match="exceeds known context window"):
            asyncio.run(restore(agent, "run-test"))


class TestContextBuilderWireValues:
    def test_build_returns_snapshot_and_ref(self, tmp_path, store):
        """ContextBuilder.build returns (ContextSnapshot, STRING blob reference)."""
        cfg = _base_config().model_copy(
            update={"window_tokens": 262144, "output_reserve_tokens": 65536}
        )
        builder = ContextBuilder(store.blobs, cfg)
        fixed = [{"role": "user", "content": "hello"}]
        snapshot, ref = builder.build(fixed, [])
        assert isinstance(snapshot, ContextSnapshot)
        assert isinstance(ref, str)
        assert ref.startswith("blob://")
        # The blob reference resolves to the same payload_ref
        assert store.blobs.json(ref)["payload_ref"] == snapshot.payload_ref
        # Inspect the options in the payload
        payload = store.blobs.json(snapshot.payload_ref)
        options = payload["options"]
        assert options["num_ctx"] == 262144
        assert options["num_predict"] == 65536


class TestOllamaProviderParser:
    def test_70000_char_response(self, tmp_path, store):
        """OllamaProvider parses a 70000-char response with exact retained evidence."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/chat":
                body = json.dumps(
                    {
                        "done": True,
                        "message": {"role": "assistant", "content": "x" * 70000},
                        "prompt_eval_count": 1,
                        "eval_count": 1,
                    }
                )
                return httpx.Response(200, content=body.encode())
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        provider = OllamaProvider(store.blobs, transport=transport, require_tools=False)

        cfg = _base_config().model_copy(
            update={"window_tokens": 65536, "output_reserve_tokens": 16384}
        )
        builder = ContextBuilder(store.blobs, cfg)
        fixed = [{"role": "user", "content": "test"}]
        snapshot, ref = builder.build(fixed, [])

        request = ModelRequest(
            request_id=new_id("req"),
            run_id=new_id("run"),
            provider="ollama",
            model=cfg.model,
            context_ref=ref,
            options={},
            deadline_utc="2099-01-01T00:00:00Z",
            trace_id="1" * 32,
            parent_span_id="2" * 16,
        )

        response = asyncio.run(provider.generate(request))
        assert len(response.text) == 70000
        # Verify the original response is retained in blobs
        original = store.blobs.json(response.original_response_ref)
        assert original["done"] is True
        assert original["message"]["content"] == "x" * 70000
        assert original["prompt_eval_count"] == 1
        assert original["eval_count"] == 1

        asyncio.run(provider.close())

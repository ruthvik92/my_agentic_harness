"""Offline tests for model token-limit discovery, validation and lookup."""

import json
from types import SimpleNamespace

import httpx
import pytest

from local_agent.contracts import AgentConfig
from local_agent.models import token_limits
from local_agent.models.token_limits import (
    check_provider_limits,
    discover_limits,
    fetch_limits_metadata,
    validate_limits,
)

HASH = "sha256:" + "0" * 64
_REAL_CLIENT = httpx.Client


def config(**updates):
    base = dict(instructions_hash=HASH, provider="ollama", model="local-test")
    base.update(updates)
    return AgentConfig(**base)


class _RecordingTransport(httpx.BaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def handle_request(self, request):
        self.requests.append(request)
        return self.handler(request)


def _patch_client(monkeypatch, transport):
    """Replace ``token_limits.httpx.Client`` with a transport-injecting factory."""

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return _REAL_CLIENT(transport=transport, **kwargs)

    monkeypatch.setattr(token_limits.httpx, "Client", factory)


# ---------------------------------------------------------------------------
# discover_limits
# ---------------------------------------------------------------------------


def test_discover_ollama_architecture_context_length():
    metadata = {
        "show": {
            "model_info": {
                "general.architecture": "llama",
                "llama.context_length": 262144,
                "llama.num_ctx": 4096,
                "llama.num_predict": 2048,
            }
        }
    }
    result = discover_limits("ollama", metadata)
    assert result["context_window"] == 262144
    assert result["status"] == "known"
    assert result["max_output_tokens"] is None
    assert result["source"] == "ollama"


def test_discover_ollama_raw_show_payload():
    metadata = {
        "model_info": {
            "general.architecture": "qwen",
            "qwen.context_length": 131072,
        }
    }
    result = discover_limits("ollama", metadata)
    assert result["context_window"] == 131072
    assert result["status"] == "known"


def test_discover_ollama_unique_fallback_without_architecture():
    metadata = {
        "show": {
            "model_info": {
                "some.context_length": 65536,
            }
        }
    }
    result = discover_limits("ollama", metadata)
    assert result["context_window"] == 65536
    assert result["status"] == "known"


def test_discover_ollama_ambiguous_fallback_rejected():
    metadata = {
        "show": {
            "model_info": {
                "a.context_length": 65536,
                "b.context_length": 131072,
            }
        }
    }
    result = discover_limits("ollama", metadata)
    assert result["context_window"] is None
    assert result["status"] == "unknown"
    assert any("ambiguous" in w for w in result["warnings"])


def test_discover_ollama_rejects_bool_string_negative_zero():
    for bad in (True, "262144", -1, 0, 2.5):
        metadata = {
            "show": {
                "model_info": {
                    "general.architecture": "llama",
                    "llama.context_length": bad,
                }
            }
        }
        result = discover_limits("ollama", metadata)
        assert result["context_window"] is None, bad
        assert result["status"] == "unknown"


def test_discover_ollama_malformed_metadata():
    for bad in (None, "not-a-dict", 42, ["list"]):
        result = discover_limits("ollama", bad)
        assert result["context_window"] is None
        assert result["status"] == "unknown"
        assert isinstance(result["warnings"], list)


def test_discover_ollama_ignores_num_ctx_num_predict():
    metadata = {
        "show": {
            "model_info": {
                "general.architecture": "llama",
                "llama.num_ctx": 4096,
                "llama.num_predict": 2048,
            }
        }
    }
    result = discover_limits("ollama", metadata)
    assert result["context_window"] is None
    assert result["status"] == "unknown"


def test_discover_openai_wrapper_and_direct():
    record = {
        "id": "gpt-test",
        "context_window": 262144,
        "max_output_tokens": 32768,
    }
    wrapper = {"openai": {"model_record": record}}
    for metadata in (wrapper, record):
        result = discover_limits("openai", metadata)
        assert result["context_window"] == 262144
        assert result["max_output_tokens"] == 32768
        assert result["status"] == "known"


def test_discover_openai_context_length_and_max_completion_tokens():
    record = {"context_length": 131072, "max_completion_tokens": 16384}
    result = discover_limits("openai", {"openai": {"model_record": record}})
    assert result["context_window"] == 131072
    assert result["max_output_tokens"] == 16384


def test_discover_openai_unknown_when_fields_absent():
    result = discover_limits("openai", {"openai": {"model_record": {"id": "x"}}})
    assert result["context_window"] is None
    assert result["max_output_tokens"] is None
    assert result["status"] == "unknown"


def test_discover_openai_rejects_non_positive():
    record = {"context_window": 0, "max_output_tokens": -5}
    result = discover_limits("openai", record)
    assert result["context_window"] is None
    assert result["max_output_tokens"] is None


def test_discover_unknown_provider():
    result = discover_limits("scripted", {"whatever": 1})
    assert result["context_window"] is None
    assert result["status"] == "unknown"
    assert result["source"] == "none"


# ---------------------------------------------------------------------------
# validate_limits
# ---------------------------------------------------------------------------


def test_validate_accepts_262144_65536_with_known_context_unknown_output():
    cfg = config(window_tokens=262144, output_reserve_tokens=65536)
    metadata = {
        "show": {
            "model_info": {
                "general.architecture": "llama",
                "llama.context_length": 262144,
            }
        }
    }
    report = validate_limits(cfg, metadata)
    assert report["ok"] is True
    assert report["verified"] is False
    assert report["context_verified"] is True
    assert report["output_verified"] is False
    assert report["limits"]["context_window"] == 262144
    assert report["limits"]["max_output_tokens"] is None
    assert any("not certified" in w or "unknown" in w for w in report["warnings"])


def test_validate_context_violation():
    cfg = config(window_tokens=524288, output_reserve_tokens=65536)
    metadata = {
        "show": {
            "model_info": {
                "general.architecture": "llama",
                "llama.context_length": 262144,
            }
        }
    }
    report = validate_limits(cfg, metadata)
    assert report["ok"] is False
    assert any("524288" in e and "262144" in e for e in report["errors"])


def test_validate_output_violation():
    cfg = config(provider="openai", window_tokens=262144, output_reserve_tokens=65536)
    metadata = {
        "openai": {
            "model_record": {
                "context_window": 262144,
                "max_output_tokens": 32768,
            }
        }
    }
    report = validate_limits(cfg, metadata)
    assert report["ok"] is False
    assert any("65536" in e and "32768" in e for e in report["errors"])


def test_validate_unknown_context_legacy_allowed():
    cfg = config(window_tokens=8192, output_reserve_tokens=2048)
    report = validate_limits(cfg, {"show": {"model_info": {}}})
    assert report["ok"] is True
    assert report["verified"] is False
    assert any("legacy" in w for w in report["warnings"])


def test_validate_unknown_context_legacy_ceiling():
    cfg = config(window_tokens=131072, output_reserve_tokens=32768)
    report = validate_limits(cfg, {"show": {"model_info": {}}})
    assert report["ok"] is True
    assert report["verified"] is False


def test_validate_unknown_context_raised_rejected():
    cfg = config(window_tokens=262144, output_reserve_tokens=65536)
    report = validate_limits(cfg, {"show": {"model_info": {}}})
    assert report["ok"] is False
    assert any("cannot verify increased limits" in e for e in report["errors"])


def test_validate_unavailable_legacy_allowed():
    cfg = config(window_tokens=8192, output_reserve_tokens=2048)
    report = validate_limits(cfg, None, unavailable="connection refused")
    assert report["ok"] is True
    assert report["verified"] is False
    assert any("unavailable" in w for w in report["warnings"])


def test_validate_unavailable_raised_rejected():
    cfg = config(window_tokens=262144, output_reserve_tokens=65536)
    report = validate_limits(cfg, None, unavailable="connection refused")
    assert report["ok"] is False
    assert any("cannot verify increased limits" in e for e in report["errors"])


def test_validate_reserve_ge_window_rejected_even_with_known_context():
    # The contracts validator forbids reserve >= window, so exercise the
    # validate_limits structural check directly with a plain namespace.
    cfg = SimpleNamespace(
        provider="ollama",
        model="local-test",
        window_tokens=262144,
        output_reserve_tokens=262144,
    )
    metadata = {
        "show": {
            "model_info": {
                "general.architecture": "llama",
                "llama.context_length": 262144,
            }
        }
    }
    report = validate_limits(cfg, metadata)
    assert report["ok"] is False
    assert any("strictly less" in e for e in report["errors"])


# ---------------------------------------------------------------------------
# contracts structural bounds
# ---------------------------------------------------------------------------


def test_contracts_reserve_ge_window_rejected():
    with pytest.raises(ValueError):
        config(window_tokens=8192, output_reserve_tokens=8192)
    with pytest.raises(ValueError):
        config(window_tokens=8192, output_reserve_tokens=16384)


def test_contracts_structural_ceiling():
    with pytest.raises(ValueError):
        config(window_tokens=2097153)
    with pytest.raises(ValueError):
        config(output_reserve_tokens=2097153)


def test_contracts_accepts_262144_65536():
    cfg = config(window_tokens=262144, output_reserve_tokens=65536)
    assert cfg.window_tokens == 262144
    assert cfg.output_reserve_tokens == 65536


# ---------------------------------------------------------------------------
# fetch_limits_metadata (mocked transports)
# ---------------------------------------------------------------------------


def test_fetch_ollama_posts_exact_model(monkeypatch):
    transport = _RecordingTransport(
        lambda request: httpx.Response(
            200,
            content=json.dumps(
                {
                    "model_info": {
                        "general.architecture": "llama",
                        "llama.context_length": 262144,
                    }
                }
            ).encode(),
        )
    )
    _patch_client(monkeypatch, transport)
    cfg = config(provider="ollama", model="my-model:tag")
    metadata = fetch_limits_metadata(cfg)
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/api/show"
    assert json.loads(request.content) == {"model": "my-model:tag"}
    assert metadata["show"]["model_info"]["llama.context_length"] == 262144


def test_fetch_ollama_non_200_sanitized(monkeypatch):
    transport = _RecordingTransport(lambda request: httpx.Response(404, text="nope"))
    _patch_client(monkeypatch, transport)
    with pytest.raises(RuntimeError, match="HTTP 404"):
        fetch_limits_metadata(config(provider="ollama", model="missing"))


def test_fetch_ollama_malformed_body(monkeypatch):
    transport = _RecordingTransport(lambda request: httpx.Response(200, content=b"not-json"))
    _patch_client(monkeypatch, transport)
    with pytest.raises(RuntimeError, match="malformed"):
        fetch_limits_metadata(config(provider="ollama", model="m"))


def test_fetch_ollama_bounded_body(monkeypatch):
    big = b"x" * (token_limits.MAX_BODY_BYTES + 1)
    transport = _RecordingTransport(lambda request: httpx.Response(200, content=big))
    _patch_client(monkeypatch, transport)
    with pytest.raises(RuntimeError, match="malformed|exceeds"):
        fetch_limits_metadata(config(provider="ollama", model="m"))


def test_fetch_openai_gets_exact_model_and_header(monkeypatch):
    record = {"id": "gpt-test", "context_window": 262144, "max_output_tokens": 32768}
    transport = _RecordingTransport(
        lambda request: httpx.Response(200, content=json.dumps(record).encode())
    )
    _patch_client(monkeypatch, transport)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-123")
    cfg = config(
        provider="openai",
        model="gpt-test",
        base_url="https://api.example.com/v1",
        api_key_env="OPENAI_API_KEY",
    )
    metadata = fetch_limits_metadata(cfg)
    request = transport.requests[0]
    assert request.method == "GET"
    assert request.url.path == "/v1/models/gpt-test"
    assert request.headers["Authorization"] == "Bearer sk-secret-123"
    assert metadata["openai"]["model_record"]["context_window"] == 262144


def test_fetch_openai_404_falls_back_to_listing(monkeypatch):
    record = {"id": "gpt-test", "context_window": 131072}
    listing = {"data": [{"id": "other"}, record]}

    def handler(request):
        if request.url.path.endswith("/models/gpt-test"):
            return httpx.Response(404, text="not found")
        return httpx.Response(200, content=json.dumps(listing).encode())

    transport = _RecordingTransport(handler)
    _patch_client(monkeypatch, transport)
    cfg = config(
        provider="openai",
        model="gpt-test",
        base_url="http://127.0.0.1:11435/v1",
        api_key_env=None,
    )
    metadata = fetch_limits_metadata(cfg)
    assert metadata["openai"]["model_record"]["id"] == "gpt-test"


def test_fetch_openai_missing_model_distinguished(monkeypatch):
    transport = _RecordingTransport(
        lambda request: httpx.Response(
            200, content=json.dumps({"data": [{"id": "other"}]}).encode()
        )
    )
    _patch_client(monkeypatch, transport)
    cfg = config(
        provider="openai",
        model="missing-model",
        base_url="http://127.0.0.1:11435/v1",
        api_key_env=None,
    )
    with pytest.raises(RuntimeError, match="not found"):
        fetch_limits_metadata(cfg)


def test_fetch_openai_no_inference_endpoints(monkeypatch):
    transport = _RecordingTransport(
        lambda request: httpx.Response(200, content=json.dumps({"id": "gpt-test"}).encode())
    )
    _patch_client(monkeypatch, transport)
    cfg = config(
        provider="openai",
        model="gpt-test",
        base_url="http://127.0.0.1:11435/v1",
        api_key_env=None,
    )
    fetch_limits_metadata(cfg)
    for request in transport.requests:
        assert request.method == "GET"
        assert "chat/completions" not in request.url.path
        assert "responses" not in request.url.path
        assert "completions" not in request.url.path


def test_fetch_openai_no_credential_leak_in_error(monkeypatch):
    transport = _RecordingTransport(lambda request: httpx.Response(500, text="boom"))
    _patch_client(monkeypatch, transport)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-123")
    cfg = config(
        provider="openai",
        model="gpt-test",
        base_url="https://api.example.com/v1",
        api_key_env="OPENAI_API_KEY",
    )
    with pytest.raises(RuntimeError) as excinfo:
        fetch_limits_metadata(cfg)
    assert "sk-secret-123" not in str(excinfo.value)


def test_fetch_transport_error_sanitized(monkeypatch):
    class _FailingTransport(httpx.BaseTransport):
        def handle_request(self, request):
            raise httpx.ConnectError("connection refused")

    _patch_client(monkeypatch, _FailingTransport())
    with pytest.raises(RuntimeError, match="failed"):
        fetch_limits_metadata(config(provider="ollama", model="m"))


# ---------------------------------------------------------------------------
# check_provider_limits
# ---------------------------------------------------------------------------


def test_check_provider_limits_success(monkeypatch):
    monkeypatch.setattr(
        token_limits,
        "fetch_limits_metadata",
        lambda cfg: {
            "show": {
                "model_info": {
                    "general.architecture": "llama",
                    "llama.context_length": 262144,
                }
            }
        },
    )
    cfg = config(window_tokens=262144, output_reserve_tokens=65536)
    report = check_provider_limits(cfg)
    assert report["ok"] is True
    assert report["verified"] is False
    assert report["context_verified"] is True
    assert report["output_verified"] is False


def test_check_provider_limits_failure_degrades_to_legacy(monkeypatch):
    def boom(cfg):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(token_limits, "fetch_limits_metadata", boom)
    legacy = config(window_tokens=8192, output_reserve_tokens=2048)
    report = check_provider_limits(legacy)
    assert report["ok"] is True
    assert report["verified"] is False
    assert report["unavailable"]

    raised = config(window_tokens=262144, output_reserve_tokens=65536)
    report = check_provider_limits(raised)
    assert report["ok"] is False
    assert any("cannot verify increased limits" in e for e in report["errors"])

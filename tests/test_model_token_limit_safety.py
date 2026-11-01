"""Regression tests for token-limit safety: streaming caps, credential
sanitization, exact-ID matching, truthful verification flags, and zero-HTTP
behavior for unauthenticated remote endpoints.

All HTTP is mocked with bounded transports; no live provider, network or
inference is used.
"""

import json

import httpx
import pytest

from local_agent.contracts import AgentConfig
from local_agent.models import token_limits
from local_agent.models.token_limits import (
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
    def factory(**kwargs):
        kwargs.pop("transport", None)
        return _REAL_CLIENT(transport=transport, **kwargs)

    monkeypatch.setattr(token_limits.httpx, "Client", factory)


# ---------------------------------------------------------------------------
# Streaming body cap: iteration truly stops and the stream is closed
# ---------------------------------------------------------------------------


def test_streaming_body_over_cap_stops_iteration_and_closes(monkeypatch):
    """A >1MiB streamed body must stop iteration early and close the stream."""
    big = b"x" * (3 * token_limits.MAX_BODY_BYTES)
    seen = {"chunks": 0, "closed": False}

    class _BoundedStream(httpx.SyncByteStream):
        def __init__(self, data: bytes):
            self._data = data
            self._pos = 0

        def read(self, length: int | None = None) -> bytes:
            if length is None:
                chunk = self._data[self._pos :]
                self._pos = len(self._data)
            else:
                chunk = self._data[self._pos : self._pos + length]
                self._pos += len(chunk)
            seen["chunks"] += 1
            return chunk

        def __iter__(self):
            while self._pos < len(self._data):
                chunk = self.read(65536)
                if not chunk:
                    break
                yield chunk

    class _ClosingResponse(httpx.Response):
        def close(self):
            seen["closed"] = True
            super().close()

    def handler(request):
        return _ClosingResponse(
            200,
            content=_BoundedStream(big),
            headers={"content-length": str(len(big))},
        )

    transport = _RecordingTransport(handler)
    _patch_client(monkeypatch, transport)
    with pytest.raises(RuntimeError) as excinfo:
        fetch_limits_metadata(config(provider="ollama", model="m"))
    message = str(excinfo.value)
    assert "body_too_large" in message or "exceeds" in message
    # The reader must have stopped well before consuming the whole body.
    assert seen["chunks"] > 0
    assert seen["chunks"] < len(big) // 65536
    assert seen["closed"] is True


# ---------------------------------------------------------------------------
# Credential sanitization: sentinel secret must never leak
# ---------------------------------------------------------------------------


def test_timeout_error_does_not_leak_sentinel_secret(monkeypatch):
    """A TimeoutException must produce a sanitized category, no secret text."""
    sentinel = "sk-super-secret-sentinel-9f8e7d"

    class _TimeoutTransport(httpx.BaseTransport):
        def handle_request(self, request):
            raise httpx.ReadTimeout(f"timed out reading from {request.url} with key {sentinel}")

    _patch_client(monkeypatch, _TimeoutTransport())
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    cfg = config(
        provider="openai",
        model="gpt-test",
        base_url="http://127.0.0.1:11435/v1",
        api_key_env="OPENAI_API_KEY",
    )
    with pytest.raises(RuntimeError) as excinfo:
        fetch_limits_metadata(cfg)
    message = str(excinfo.value)
    assert sentinel not in message
    assert "timeout" in message
    # No URL or header text should leak.
    assert "127.0.0.1" not in message
    assert "Bearer" not in message


def test_connect_error_does_not_leak_url(monkeypatch):
    sentinel_url = "http://10.0.0.1:9999/secret-path"

    class _ConnectTransport(httpx.BaseTransport):
        def handle_request(self, request):
            raise httpx.ConnectError(f"failed to connect to {sentinel_url}")

    _patch_client(monkeypatch, _ConnectTransport())
    with pytest.raises(RuntimeError) as excinfo:
        fetch_limits_metadata(config(provider="ollama", model="m"))
    assert sentinel_url not in str(excinfo.value)
    assert "connection_error" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Exact-ID matching
# ---------------------------------------------------------------------------


def test_openai_record_id_mismatch_rejected(monkeypatch):
    """A record whose id does not match the requested model must be rejected."""
    transport = _RecordingTransport(
        lambda request: httpx.Response(
            200,
            content=json.dumps({"id": "other-model", "context_window": 262144}).encode(),
        )
    )
    _patch_client(monkeypatch, transport)
    cfg = config(
        provider="openai",
        model="gpt-test",
        base_url="http://127.0.0.1:11435/v1",
        api_key_env=None,
    )
    with pytest.raises(RuntimeError) as excinfo:
        fetch_limits_metadata(cfg)
    message = str(excinfo.value)
    assert "does not match" in message
    # The raw provider-returned id must never be echoed.
    assert "other-model" not in message


def test_openai_listing_malformed_data_not_list(monkeypatch):
    """A listing body where data is not a list must not crash."""
    transport = _RecordingTransport(
        lambda request: httpx.Response(200, content=json.dumps({"data": "not-a-list"}).encode())
    )
    _patch_client(monkeypatch, transport)
    cfg = config(
        provider="openai",
        model="gpt-test",
        base_url="http://127.0.0.1:11435/v1",
        api_key_env=None,
    )
    with pytest.raises(RuntimeError) as excinfo:
        fetch_limits_metadata(cfg)
    message = str(excinfo.value)
    assert "not found" in message or "malformed" in message
    # The raw provider-returned data value must never be echoed.
    assert "not-a-list" not in message
    # The raw provider-returned data value must never be echoed.
    assert "not-a-list" not in message
    # The raw provider-returned data value must never be echoed.
    assert "not-a-list" not in message
    # The raw provider-returned data value must never be echoed.
    assert "not-a-list" not in message
    # The raw provider-returned data value must never be echoed.
    assert "not-a-list" not in message


def test_openai_listing_data_none_does_not_crash(monkeypatch):
    transport = _RecordingTransport(
        lambda request: httpx.Response(200, content=json.dumps({"data": None}).encode())
    )
    _patch_client(monkeypatch, transport)
    cfg = config(
        provider="openai",
        model="gpt-test",
        base_url="http://127.0.0.1:11435/v1",
        api_key_env=None,
    )
    with pytest.raises(RuntimeError) as excinfo:
        fetch_limits_metadata(cfg)
    message = str(excinfo.value)
    assert "not found" in message or "malformed" in message


# ---------------------------------------------------------------------------
# Known output limit enforced even when context is unknown
# ---------------------------------------------------------------------------


def test_known_output_limit_rejects_even_with_unknown_context():
    """A known max_output_tokens violation must reject even if context is unknown."""
    cfg = config(
        provider="openai",
        window_tokens=8192,
        output_reserve_tokens=4096,
    )
    # context_window absent (unknown), but max_output_tokens is known and small.
    metadata = {"openai": {"model_record": {"max_output_tokens": 2048}}}
    report = validate_limits(cfg, metadata)
    assert report["ok"] is False
    assert any("4096" in e and "2048" in e for e in report["errors"])
    assert report["output_verified"] is False


def test_known_output_limit_allows_fitting_reserve_with_unknown_context():
    cfg = config(
        provider="openai",
        window_tokens=8192,
        output_reserve_tokens=1024,
    )
    metadata = {"openai": {"model_record": {"max_output_tokens": 2048}}}
    report = validate_limits(cfg, metadata)
    assert report["ok"] is True
    assert report["output_verified"] is True
    assert report["context_verified"] is False
    assert report["verified"] is False


# ---------------------------------------------------------------------------
# Conflicting maxima treated as unknown
# ---------------------------------------------------------------------------


def test_conflicting_context_maxima_unknown():
    record = {"context_window": 262144, "context_length": 131072}
    result = discover_limits("openai", {"openai": {"model_record": record}})
    assert result["context_window"] is None
    assert result["status"] == "unknown"
    assert any("conflicting" in w for w in result["warnings"])


def test_conflicting_output_maxima_unknown():
    record = {"max_output_tokens": 32768, "max_completion_tokens": 16384}
    result = discover_limits("openai", {"openai": {"model_record": record}})
    assert result["max_output_tokens"] is None
    assert any("conflicting" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# No-key remote performs zero HTTP
# ---------------------------------------------------------------------------


def test_no_key_remote_performs_zero_http(monkeypatch):
    """A remote (non-loopback) endpoint with no API key must not send HTTP."""
    transport = _RecordingTransport(lambda request: httpx.Response(200, content=b"{}"))
    _patch_client(monkeypatch, transport)
    # Ensure the env var is unset.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = config(
        provider="openai",
        model="gpt-test",
        base_url="https://api.example.com/v1",
        api_key_env="OPENAI_API_KEY",
    )
    with pytest.raises(RuntimeError, match="no API key"):
        fetch_limits_metadata(cfg)
    assert len(transport.requests) == 0


# ---------------------------------------------------------------------------
# Truthful verification flags
# ---------------------------------------------------------------------------


def test_verified_false_when_output_unknown_even_if_context_known():
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


def test_verified_true_only_when_both_known_and_fit():
    cfg = config(
        provider="openai",
        window_tokens=131072,
        output_reserve_tokens=16384,
    )
    metadata = {
        "openai": {
            "model_record": {
                "context_window": 262144,
                "max_output_tokens": 32768,
            }
        }
    }
    report = validate_limits(cfg, metadata)
    assert report["ok"] is True
    assert report["verified"] is True
    assert report["context_verified"] is True
    assert report["output_verified"] is True


def test_verified_false_when_context_violation():
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
    assert report["verified"] is False
    assert report["context_verified"] is False


def test_unavailable_report_has_truthful_flags():
    cfg = config(window_tokens=8192, output_reserve_tokens=2048)
    report = validate_limits(cfg, None, unavailable="timeout")
    assert report["ok"] is True
    assert report["verified"] is False
    assert report["context_verified"] is False
    assert report["output_verified"] is False
    assert report["unavailable"] == "timeout"


# ---------------------------------------------------------------------------
# Ollama non-string model_info keys handled safely
# ---------------------------------------------------------------------------


def test_ollama_non_string_model_info_keys_safe():
    metadata = {
        "show": {
            "model_info": {
                123: "not-a-string-key",
                "general.architecture": "llama",
                "llama.context_length": 131072,
            }
        }
    }
    result = discover_limits("ollama", metadata)
    assert result["context_window"] == 131072
    assert result["status"] == "known"


def test_ollama_non_string_keys_in_fallback_path_safe():
    metadata = {
        "show": {
            "model_info": {
                42: "ignored",
                "a.context_length": 65536,
            }
        }
    }
    result = discover_limits("ollama", metadata)
    assert result["context_window"] == 65536
    assert result["status"] == "known"


# ---------------------------------------------------------------------------
# Ollama non-200 status classification: 404 -> model_missing, 503 -> http_error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected_category",
    [
        (404, "model_missing"),
        (503, "http_error"),
    ],
)
def test_ollama_non_200_status_classification(monkeypatch, status, expected_category):
    """Only 404 is model_missing; other non-200 statuses are http_error.

    Uses MockTransport (no live HTTP) and check_provider_limits with a legacy
    config so the unavailable category is surfaced.
    """

    def handler(request):
        return httpx.Response(status, content=b"{}")

    transport = httpx.MockTransport(handler)
    _patch_client(monkeypatch, transport)

    # Legacy-sized defaults: policy intentionally accepts legacy-size
    # unavailable metadata with warnings.
    cfg = config(provider="ollama", model="m")
    report = token_limits.check_provider_limits(cfg)
    assert report["unavailable"] == expected_category
    assert report["ok"] is True
    assert report["verified"] is False

    # Raised window/reserve in the same scenario must be rejected.
    cfg_raised = config(
        provider="ollama",
        model="m",
        window_tokens=262144,
        output_reserve_tokens=65536,
    )
    report_raised = token_limits.check_provider_limits(cfg_raised)
    assert report_raised["unavailable"] == expected_category
    assert report_raised["ok"] is False

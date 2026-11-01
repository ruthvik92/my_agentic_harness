"""Read-only model token-limit discovery, validation and provider lookup.

Pure helpers (``discover_limits`` / ``validate_limits``) plus a synchronous,
read-only HTTP lookup (``fetch_limits_metadata``) that never performs
generation/chat/responses or inference.  Credentials are only ever placed in
request headers and are never logged or echoed into error messages; transport
failures are reported as fixed, sanitized categories only.
"""

from __future__ import annotations

import json
import os
from urllib.parse import quote

import httpx

from local_agent.models.openai import validate_endpoint

MAX_BODY_BYTES = 1024 * 1024  # 1 MiB captured body cap
REQUEST_TIMEOUT_SECONDS = 5.0
OLLAMA_ENDPOINT = "http://127.0.0.1:11434"

# Legacy profile ceilings that may be accepted when the context window is
# unknown (i.e. the profile predates verified limits).
LEGACY_WINDOW_MAX = 131072
LEGACY_RESERVE_MAX = 32768


def _positive_int(value) -> int | None:
    """Return ``value`` if it is a genuine positive int, else ``None``.

    Rejects booleans, strings, floats, zero, negatives and non-integers.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value <= 0:
        return None
    return value


def _ollama_raw(metadata) -> dict:
    """Return the raw ``/api/show`` payload from a raw or wrapped metadata."""
    if not isinstance(metadata, dict):
        return {}
    if "show" in metadata and isinstance(metadata["show"], dict):
        return metadata["show"]
    return metadata


def _openai_record(metadata) -> dict:
    """Return the OpenAI model record from a wrapper or direct record."""
    if not isinstance(metadata, dict):
        return {}
    openai = metadata.get("openai")
    if isinstance(openai, dict) and isinstance(openai.get("model_record"), dict):
        return openai["model_record"]
    return metadata


def discover_limits(provider: str, metadata) -> dict:
    """Pure helper: derive token limits from provider metadata.

    Returns a dict with ``context_window`` (positive int or ``None``),
    ``max_output_tokens`` (positive int or ``None``), ``source`` (str),
    ``status`` (``"known"`` / ``"unknown"``) and ``warnings`` (list[str]).

    Never fabricates limits or hardcodes model names.  ``num_ctx`` /
    ``num_predict`` defaults are explicitly NOT used as maxima.  Conflicting
    metadata fields are treated conservatively as unknown.
    """
    warnings: list[str] = []
    context_window: int | None = None
    max_output_tokens: int | None = None
    source = "none"

    provider = (provider or "").lower()

    if provider == "ollama":
        raw = _ollama_raw(metadata)
        source = "ollama"
        model_info = raw.get("model_info") if isinstance(raw, dict) else None
        if isinstance(model_info, dict):
            architecture = model_info.get("general.architecture")
            if isinstance(architecture, str) and architecture:
                key = f"{architecture}.context_length"
                context_window = _positive_int(model_info.get(key))
                if context_window is None:
                    warnings.append(
                        f"ollama model_info lacks a positive {key!r}; context window unknown"
                    )
            else:
                # No architecture: only a *unique* positive context_length is
                # trusted; ambiguous (multiple) or absent values are rejected.
                # Non-string keys are skipped safely.
                candidates = [
                    _positive_int(value)
                    for key, value in model_info.items()
                    if isinstance(key, str) and key.endswith(".context_length")
                ]
                positives = [c for c in candidates if c is not None]
                if len(positives) == 1:
                    context_window = positives[0]
                elif len(positives) > 1:
                    warnings.append(
                        "ollama model_info has multiple context_length values; "
                        "ambiguous fallback rejected, context window unknown"
                    )
                else:
                    warnings.append(
                        "ollama model_info has no architecture and no unique "
                        "positive context_length; context window unknown"
                    )
        else:
            warnings.append("ollama metadata has no model_info; context window unknown")
        # Ollama output maximum is separate and typically unknown.
        max_output_tokens = None
        warnings.append("ollama max_output_tokens is not certified; treated as unknown")

    elif provider == "openai":
        record = _openai_record(metadata)
        source = "openai"
        if isinstance(record, dict):
            context_window = _positive_int(record.get("context_window"))
            context_length = _positive_int(record.get("context_length"))
            if context_window is None:
                context_window = context_length
            if context_window is None:
                warnings.append(
                    "openai record lacks a positive context_window/context_length; "
                    "context window unknown"
                )
            elif context_length is not None and context_window != context_length:
                # Conflicting metadata: conservative, treat as unknown.
                warnings.append(
                    "openai record has conflicting context_window/context_length "
                    "values; context window treated as unknown"
                )
                context_window = None
            max_output_tokens = _positive_int(record.get("max_output_tokens"))
            max_completion = _positive_int(record.get("max_completion_tokens"))
            if max_output_tokens is None:
                max_output_tokens = max_completion
            if max_output_tokens is None:
                warnings.append(
                    "openai record lacks a positive max_output_tokens/"
                    "max_completion_tokens; output limit unknown"
                )
            elif max_completion is not None and max_output_tokens != max_completion:
                # Conflicting metadata: conservative, treat as unknown.
                warnings.append(
                    "openai record has conflicting max_output_tokens/"
                    "max_completion_tokens values; output limit treated as unknown"
                )
                max_output_tokens = None
        else:
            warnings.append("openai metadata has no model record; limits unknown")

    else:
        source = "none"
        warnings.append(f"provider {provider!r} has no limit discovery support")

    status = "known" if context_window is not None else "unknown"
    return {
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
        "source": source,
        "status": status,
        "warnings": warnings,
    }


def _report(
    errors, warnings, *, verified, context_verified, output_verified, limits, unavailable
) -> dict:
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "verified": verified,
        "context_verified": context_verified,
        "output_verified": output_verified,
        "limits": limits,
        "unavailable": unavailable,
    }


def validate_limits(config, metadata=None, *, unavailable: str | None = None) -> dict:
    """Validate configured window/reserve against discovered limits.

    Returns a report dict with ``ok`` (bool), ``errors`` (list[str]),
    ``warnings`` (list[str]), ``verified`` (bool), ``context_verified``
    (bool), ``output_verified`` (bool) and the discovered ``limits``.
    Callers MUST reject when ``ok`` is False.  ``verified`` is True only when
    both the context window and the output maximum are known and the
    configured values fit; unknown output never yields full verification.
    Structural ``reserve < window`` is always enforced.
    """
    errors: list[str] = []
    warnings: list[str] = []

    window = config.window_tokens
    reserve = config.output_reserve_tokens

    # Structural invariant, independent of provider knowledge.
    if reserve >= window:
        errors.append(
            f"output_reserve_tokens ({reserve}) must be strictly less than window_tokens ({window})"
        )

    if unavailable is not None:
        # Metadata lookup failed: fall back to legacy policy.
        if window <= LEGACY_WINDOW_MAX and reserve <= LEGACY_RESERVE_MAX:
            warnings.append(
                "limits metadata unavailable; legacy profile accepted without "
                f"verification ({unavailable})"
            )
        else:
            errors.append(
                "cannot verify increased limits: limits metadata unavailable "
                f"({unavailable}) and configured window/reserve exceed the "
                f"legacy ceiling (window<= {LEGACY_WINDOW_MAX}, "
                f"reserve<= {LEGACY_RESERVE_MAX})"
            )
        return _report(
            errors,
            warnings,
            verified=False,
            context_verified=False,
            output_verified=False,
            limits=discover_limits(config.provider, metadata),
            unavailable=unavailable,
        )

    limits = discover_limits(config.provider, metadata)
    warnings.extend(limits["warnings"])
    context_window = limits["context_window"]
    max_output_tokens = limits["max_output_tokens"]

    context_verified = False
    output_verified = False

    if context_window is not None:
        if window > context_window:
            errors.append(
                f"window_tokens ({window}) exceeds known context window "
                f"({context_window}) for model {config.model!r}"
            )
        else:
            context_verified = True
    else:
        # Context unknown: legacy policy only.
        if window <= LEGACY_WINDOW_MAX and reserve <= LEGACY_RESERVE_MAX:
            warnings.append("context window unknown; legacy profile accepted without verification")
        else:
            errors.append(
                "cannot verify increased limits: context window is unknown and "
                f"configured window/reserve exceed the legacy ceiling "
                f"(window<= {LEGACY_WINDOW_MAX}, reserve<= {LEGACY_RESERVE_MAX})"
            )

    # Output maximum is enforced independently of context knowledge.
    if max_output_tokens is not None:
        if reserve > max_output_tokens:
            errors.append(
                f"output_reserve_tokens ({reserve}) exceeds known max output "
                f"tokens ({max_output_tokens}) for model {config.model!r}"
            )
        else:
            output_verified = True
    else:
        warnings.append(
            "max output tokens is not certified; output reserve not verified "
            "against a provider maximum"
        )

    verified = context_verified and output_verified and not errors
    return _report(
        errors,
        warnings,
        verified=verified,
        context_verified=context_verified,
        output_verified=output_verified,
        limits=limits,
        unavailable=None,
    )


def _error_category(exc: Exception) -> str:
    """Fixed, sanitized error category; never echoes exception text."""
    if isinstance(exc, LimitsLookupError):
        return exc.category
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connection_error"
    if isinstance(exc, httpx.HTTPError):
        return "transport_error"
    return "unknown_error"


class LimitsLookupError(RuntimeError):
    """Trusted, fixed-category lookup failure.

    ``category`` is restricted to a small allowlist of safe reasons so that
    callers can distinguish model-missing, credential-missing, malformed
    bodies, timeouts and oversized bodies without ever echoing exception
    text, URLs, headers or response bodies.
    """

    ALLOWED_CATEGORIES = frozenset(
        {
            "model_missing",
            "credentials_missing",
            "malformed",
            "timeout",
            "body_too_large",
            "model_mismatch",
            "http_error",
            "connection_error",
            "transport_error",
            "unknown_error",
        }
    )

    def __init__(self, category: str, message: str):
        if category not in self.ALLOWED_CATEGORIES:
            category = "unknown_error"
        self.category = category
        super().__init__(message)


def _read_bounded(response, cap: int = MAX_BODY_BYTES) -> bytes:
    """Read a streamed response body up to ``cap`` bytes.

    Raises ``LimitsLookupError`` (fixed message, no body content) when the
    stream exceeds the cap.
    """
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        if not chunk:
            continue
        total += len(chunk)
        if total > cap:
            raise LimitsLookupError(
                "body_too_large",
                f"response body exceeds {cap} byte limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_json(body: bytes) -> dict:
    try:
        payload = json.loads(body)
    except ValueError:
        raise LimitsLookupError(
            "malformed", "response body is malformed (not valid JSON)"
        ) from None
    if not isinstance(payload, dict):
        raise LimitsLookupError("malformed", "response body is malformed (not a JSON object)")
    return payload


def _fetch_ollama(config) -> dict:
    model = config.model
    with httpx.Client(
        base_url=OLLAMA_ENDPOINT,
        trust_env=False,
        timeout=REQUEST_TIMEOUT_SECONDS,
    ) as client:
        try:
            with client.stream("POST", "/api/show", json={"model": model}) as response:
                if response.status_code != 200:
                    if response.status_code == 404:
                        raise LimitsLookupError(
                            "model_missing",
                            "ollama /api/show returned HTTP 404; model may not be installed",
                        )
                    raise LimitsLookupError(
                        "http_error",
                        f"ollama /api/show returned HTTP {response.status_code}",
                    )
                body = _read_bounded(response)
        except LimitsLookupError:
            raise
        except httpx.HTTPError as exc:
            raise LimitsLookupError(
                _error_category(exc),
                f"ollama /api/show request failed: {_error_category(exc)}",
            ) from None
    return {"show": _parse_json(body)}


def _fetch_openai(config) -> dict:
    model = config.model
    local = validate_endpoint(config.base_url)
    key = os.environ.get(config.api_key_env) if config.api_key_env else None
    if not local and not key:
        raise LimitsLookupError(
            "credentials_missing",
            "openai limits lookup unavailable: no API key configured for a remote endpoint",
        )
    headers = {"Authorization": "Bearer " + key} if key else {}
    base = config.base_url.rstrip("/")
    encoded_model = quote(model, safe="")
    with httpx.Client(
        base_url=base + "/",
        trust_env=False,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers=headers,
    ) as client:
        try:
            with client.stream("GET", f"models/{encoded_model}") as response:
                status = response.status_code
                if status == 200:
                    body = _read_bounded(response)
                elif status == 404:
                    body = None
                else:
                    raise LimitsLookupError(
                        "http_error",
                        f"openai model lookup returned HTTP {status}; "
                        f"model {model!r} may not exist",
                    )
        except LimitsLookupError:
            raise
        except httpx.HTTPError as exc:
            raise LimitsLookupError(
                _error_category(exc),
                f"openai model lookup failed: {_error_category(exc)}",
            ) from None

        if body is not None:
            payload = _parse_json(body)
            # A listing-shaped body (has a "data" list) is not a model record;
            # require an exact id match.
            if "data" in payload:
                data = payload.get("data")
                if not isinstance(data, list):
                    raise LimitsLookupError(
                        "malformed",
                        f"openai model listing malformed: model {model!r} not found",
                    )
                matches = [m for m in data if isinstance(m, dict) and m.get("id") == model]
                if len(matches) != 1:
                    raise LimitsLookupError(
                        "model_missing",
                        f"openai model {model!r} not found in listing",
                    )
                return {"openai": {"model_record": matches[0]}}
            if payload.get("id") != model:
                raise LimitsLookupError(
                    "model_mismatch",
                    f"openai model lookup returned a record whose id does not "
                    f"match the requested model {model!r}",
                )
            return {"openai": {"model_record": payload}}

        # 404: fall back to listing and exact match.
        try:
            with client.stream("GET", "models") as listing:
                if listing.status_code != 200:
                    raise LimitsLookupError(
                        "http_error",
                        f"openai model listing returned HTTP {listing.status_code}; "
                        f"model {model!r} not found",
                    )
                listing_body = _read_bounded(listing)
        except LimitsLookupError:
            raise
        except httpx.HTTPError as exc:
            raise LimitsLookupError(
                _error_category(exc),
                f"openai model listing failed: {_error_category(exc)}",
            ) from None
        data = _parse_json(listing_body).get("data")
        if not isinstance(data, list):
            raise LimitsLookupError(
                "malformed",
                f"openai model listing malformed: model {model!r} not found",
            )
        matches = [m for m in data if isinstance(m, dict) and m.get("id") == model]
        if len(matches) != 1:
            raise LimitsLookupError(
                "model_missing",
                f"openai model {model!r} not found in listing",
            )
        return {"openai": {"model_record": matches[0]}}


def fetch_limits_metadata(config) -> dict:
    """Synchronous read-only HTTP lookup of model limit metadata.

    Ollama: ``POST /api/show`` with the exact model.
    OpenAI: ``GET {base_url}/models/{model}`` (exact, URL-encoded), falling
    back to ``GET /models`` with an exact match.  No generation/chat/responses
    or inference endpoints are ever called.  Credentials are only placed in
    headers and never logged; transport errors are reported as fixed
    categories without exception text, URLs, headers or bodies.
    """
    provider = (config.provider or "").lower()

    if provider == "ollama":
        return _fetch_ollama(config)

    if provider == "openai":
        return _fetch_openai(config)

    raise LimitsLookupError("unknown_error", f"provider {provider!r} has no limit metadata lookup")


def check_provider_limits(config) -> dict:
    """Fetch metadata then validate; metadata failures degrade to legacy policy.

    Trusted lookup failures (``LimitsLookupError``) preserve their fixed,
    sanitized category so callers can distinguish model-missing,
    credential-missing, malformed, timeout, oversized-body and other
    categories.  Unexpected exceptions are collapsed to ``unknown_error``
    and never echo exception text, URLs, headers or response bodies.
    """
    try:
        metadata = fetch_limits_metadata(config)
    except LimitsLookupError as exc:
        return validate_limits(config, None, unavailable=exc.category)
    except Exception:  # noqa: BLE001 - sanitized, actionable
        return validate_limits(config, None, unavailable="unknown_error")
    return validate_limits(config, metadata)

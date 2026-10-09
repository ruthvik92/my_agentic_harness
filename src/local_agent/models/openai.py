"""OpenAI-compatible Chat Completions, with exact wire capture and external secrets."""

import json
import os
import time
from urllib.parse import urlparse

import httpx

from local_agent.contracts import ModelResponse
from local_agent.models.ollama import ProviderResponseError
from local_agent.storage.blobs import canonical, digest


def validate_endpoint(endpoint):
    url = urlparse(endpoint)
    local = url.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        url.username
        or url.password
        or url.query
        or url.fragment
        or not url.hostname
        or url.scheme not in {"http", "https"}
        or (url.scheme == "http" and not local)
    ):
        raise ValueError(
            "OpenAI base URL requires HTTPS or loopback HTTP, without URL credentials/query"
        )
    return local


class OpenAIProvider:
    def __init__(self, blobs, config, *, transport=None):
        local = validate_endpoint(config.base_url)
        key = os.environ.get(config.api_key_env) if config.api_key_env else None
        if not local and not key:
            raise ValueError(
                "Set the configured API key environment variable before using a remote provider"
            )
        self.blobs, self.config = blobs, config
        self.client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/") + "/",
            headers={"Authorization": "Bearer " + key} if key else {},
            trust_env=False,
            timeout=config.limits.model_timeout_seconds,
            transport=transport,
        )

    async def close(self):
        await self.client.aclose()

    async def metadata(self, model):
        response = await self.client.get("models")
        if response.status_code != 200:
            raise RuntimeError(f"OpenAI model listing failed: HTTP {response.status_code}")
        matches = [m for m in response.json()["data"] if m["id"] == model]
        if len(matches) != 1:
            raise ValueError("configured model must match an exact API model ID")
        return {
            "installed": {"name": model, "digest": digest(canonical(matches[0]))},
            "openai": {"base_url": self.config.base_url, "model_record": matches[0]},
            "reproducibility": "incomplete: API metadata hash does not identify model weights",
        }

    async def generate(self, request):
        snapshot = self.blobs.json(request.context_ref)
        payload = self.blobs.read(snapshot["payload_ref"])
        started = time.monotonic()
        data = bytearray()
        try:
            async with self.client.stream(
                "POST",
                "chat/completions",
                content=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                status = response.status_code
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 8 * 1024 * 1024:
                        ref = self.blobs.put(bytes(data[: 8 * 1024 * 1024]))
                        raise ProviderResponseError("OpenAI capture truncated at limit", ref)
        except httpx.HTTPError as exc:
            ref = self.blobs.put(bytes(data))
            raise ProviderResponseError(
                "OpenAI transport failed; captured body may be incomplete", ref
            ) from exc
        ref = self.blobs.put(bytes(data))
        if status != 200:
            message = f"OpenAI HTTP status {status}"
            try:
                error = json.loads(data).get("error") or {}
                if status == 429 and (
                    error.get("type") == "insufficient_quota"
                    or error.get("code") in {"insufficient_quota", "credit_balance_exhausted"}
                ):
                    message += ": API credit balance/quota exhausted. Check OpenAI project billing before requesting another review."
            except (ValueError, TypeError, AttributeError):
                pass
            raise ProviderResponseError(message, ref)
        try:
            raw = json.loads(data)
            normalized = normalize_response(raw)
            usage = raw.get("usage") or {}
            return ModelResponse.model_validate_json(
                canonical(
                    {
                        **normalized,
                        "request_id": request.request_id,
                        "original_response_ref": ref,
                        "client_duration_seconds": time.monotonic() - started,
                        "usage": {
                            **usage,
                            "prompt_eval_count": usage.get("prompt_tokens"),
                            "eval_count": usage.get("completion_tokens"),
                        },
                    }
                )
            )
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ProviderResponseError("invalid/incomplete OpenAI response", ref) from exc


def normalize_response(raw):
    if len(raw["choices"]) != 1:
        raise ValueError("exactly one completion choice required")
    choice = raw["choices"][0]
    if choice["finish_reason"] not in {"stop", "tool_calls"}:
        raise ValueError("completion did not finish normally")
    message = choice["message"]
    if message.get("refusal"):
        raise ValueError("provider refused the request")
    calls = []
    identifiers = set()
    for call in message.get("tool_calls") or []:
        if call["type"] != "function" or not call["id"] or call["id"] in identifiers:
            raise ValueError("invalid/duplicate tool call ID")
        identifiers.add(call["id"])
        # Malformed argument JSON remains a proposal so ordinary validation can reject it.
        arguments = call["function"]["arguments"]
        try:
            arguments = json.loads(arguments)
        except (ValueError, TypeError):
            pass
        calls.append(
            {"name": call["function"]["name"], "arguments": arguments, "provider_id": call["id"]}
        )
    if bool(calls) != (choice["finish_reason"] == "tool_calls"):
        raise ValueError("finish reason and calls disagree")
    return {
        "text": message.get("content") or "",
        "tool_calls": calls,
        "finish_status": "tool_calls" if calls else "stop",
    }


def wire_messages(messages):
    result = []
    for message in messages:
        role = message["role"]
        item = {"role": role, "content": message.get("content")}
        if role == "assistant" and message.get("tool_calls"):
            item["tool_calls"] = message["tool_calls"]
        if role == "tool":
            item["tool_call_id"] = message["tool_call_id"]
        result.append(item)
    return result

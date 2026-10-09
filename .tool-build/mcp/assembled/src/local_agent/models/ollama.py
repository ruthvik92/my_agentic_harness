"""Native non-streaming chat; exact request bytes and complete assistant messages."""

import json
import time
from urllib.parse import urlparse

import httpx

from local_agent.contracts import ModelRequest, ModelResponse
from local_agent.storage.blobs import canonical

USAGE_FIELDS = (
    "total_duration",
    "load_duration",
    "prompt_eval_count",
    "prompt_eval_duration",
    "eval_count",
    "eval_duration",
)


class ProviderResponseError(RuntimeError):
    def __init__(self, message, raw_ref):
        super().__init__(message)
        self.raw_ref = raw_ref


class OllamaProvider:
    def __init__(
        self,
        blobs,
        endpoint="http://127.0.0.1:11434",
        *,
        transport=None,
        timeout=180,
        require_tools=True,
    ):
        url = urlparse(endpoint)
        if (
            url.scheme != "http"
            or url.hostname not in {"localhost", "127.0.0.1", "::1"}
            or url.username
        ):
            raise ValueError("v0 model server must be local and credential-free")
        self.blobs = blobs
        self.require_tools = require_tools
        self.client = httpx.AsyncClient(
            base_url=endpoint, trust_env=False, transport=transport, timeout=timeout
        )

    async def close(self):
        await self.client.aclose()

    async def metadata(self, model):
        tags = (await self.client.get("/api/tags")).raise_for_status().json()["models"]
        matches = [tag for tag in tags if tag["name"] == model]
        if len(matches) != 1:
            raise ValueError("configured model must match an exact locally installed tag")
        show = (
            (await self.client.post("/api/show", json={"model": model})).raise_for_status().json()
        )
        version = (await self.client.get("/api/version")).raise_for_status().json()
        if self.require_tools and "tools" not in show.get(
            "capabilities", matches[0].get("capabilities", [])
        ):
            raise ValueError("model does not advertise tool calling")
        return {
            "installed": matches[0],
            "show": show,
            "ollama": version,
            "reproducibility": "identified" if matches[0].get("digest") else "incomplete",
        }

    async def generate(self, request: ModelRequest) -> ModelResponse:
        snapshot = self.blobs.json(request.context_ref)
        payload = self.blobs.read(snapshot["payload_ref"])
        started = time.monotonic()
        data = bytearray()
        response_status = None
        try:
            async with self.client.stream(
                "POST", "/api/chat", content=payload, headers={"Content-Type": "application/json"}
            ) as response:
                response_status = response.status_code
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 8 * 1024 * 1024:
                        raw_ref = self.blobs.put(bytes(data[: 8 * 1024 * 1024]))
                        raise ProviderResponseError(
                            "provider response capture truncated at limit", raw_ref
                        )
        except httpx.HTTPError as exc:
            raw_ref = self.blobs.put(bytes(data))
            raise ProviderResponseError(
                "provider transport failed; captured body may be incomplete", raw_ref
            ) from exc
        raw_ref = self.blobs.put(bytes(data))
        if response_status != 200:
            raise ProviderResponseError(f"Ollama HTTP status {response_status}", raw_ref)
        try:
            raw = json.loads(data)
            if raw.get("done_reason") == "length":
                raise ProviderResponseError(
                    f"Ollama output token limit reached (eval_count={raw.get('eval_count')}); partial response was not dispatched",
                    raw_ref,
                )
            if raw.get("error") or not raw.get("done"):
                raise ProviderResponseError("incomplete/failed Ollama response", raw_ref)
            message = raw["message"]
            calls = []
            for call in message.get("tool_calls", []):
                calls.append(
                    {
                        "name": call["function"]["name"],
                        "arguments": call["function"]["arguments"],
                        "provider_id": call.get("id"),
                    }
                )
            return ModelResponse.model_validate_json(
                canonical(
                    {
                        "request_id": request.request_id,
                        "text": message.get("content", ""),
                        "tool_calls": calls,
                        "finish_status": "tool_calls" if calls else "stop",
                        "usage": {key: raw.get(key) for key in USAGE_FIELDS},
                        "original_response_ref": raw_ref,
                        "client_duration_seconds": time.monotonic() - started,
                    }
                )
            )
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ProviderResponseError("invalid Ollama response shape", raw_ref) from exc

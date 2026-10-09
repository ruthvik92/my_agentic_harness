from local_agent.models.ollama import OllamaProvider
from local_agent.models.openai import OpenAIProvider


def create_provider(blobs, config):
    if config.provider == "ollama":
        return OllamaProvider(
            blobs, timeout=config.limits.model_timeout_seconds, require_tools=bool(config.tools)
        )
    if config.provider == "openai":
        return OpenAIProvider(blobs, config)
    raise ValueError("live runtime requires ollama or openai provider")


def assistant_message(raw, response):
    if "choices" in raw:
        return raw["choices"][0]["message"]
    return raw.get("message") or {
        "role": "assistant",
        "content": response.text,
        "tool_calls": [
            {"function": {"name": call.name, "arguments": call.arguments}}
            for call in response.tool_calls
        ],
    }


def tool_message(call, content):
    from local_agent.storage.blobs import canonical

    return {
        "role": "tool",
        "tool_name": call.name,
        "content": canonical(content).decode(),
        **({"tool_call_id": call.provider_id} if call.provider_id else {}),
    }

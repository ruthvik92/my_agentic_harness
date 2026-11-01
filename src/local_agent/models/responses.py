"""Stateless Responses function calling with exact output-item replay."""

import json


def uses_responses(config):
    return (
        config.base_url.rstrip("/") == "https://api.openai.com/v1"
        and bool(config.tools)
        and (
            config.instructions_version == "workspace-review-v1" or config.model.startswith("gpt-6")
        )
    )


def input_items(messages):
    items = []
    for message in messages:
        if message.get("response_output") is not None:
            # Reasoning/encrypted content, assistant phase and call IDs must survive tool turns.
            items.extend(message["response_output"])
            continue
        role = message["role"]
        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": message["content"],
                }
            )
            continue
        content = message.get("content")
        if isinstance(content, list):
            converted = []
            for part in content:
                if part["type"] == "text":
                    converted.append({"type": "input_text", "text": part["text"]})
                elif part["type"] == "image_url":
                    image = part["image_url"]
                    converted.append(
                        {
                            "type": "input_image",
                            "image_url": image["url"],
                            "detail": image.get("detail", "auto"),
                        }
                    )
                else:
                    raise ValueError("Unsupported Responses input content")
            content = converted
        if content:
            items.append({"role": role, "content": content})
        for call in message.get("tool_calls") or []:
            function = call["function"]
            arguments = function["arguments"]
            items.append(
                {
                    "type": "function_call",
                    "call_id": call["id"],
                    "name": function["name"],
                    "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
                }
            )
    return items


def payload(config, messages, tools):
    result = {
        "model": config.model,
        "input": input_items(messages),
        "max_output_tokens": config.output_reserve_tokens,
        "store": False,
        "stream": False,
        "include": ["reasoning.encrypted_content"],
        "tools": [{"type": "function", **tool["function"], "strict": False} for tool in tools],
    }
    if config.reasoning_effort is not None:
        result["reasoning"] = {"effort": config.reasoning_effort}
    return result


def normalize_response(raw):
    if raw.get("status") != "completed" or raw.get("error"):
        raise ValueError("Responses generation did not complete")
    text, calls, ids = [], [], set()
    for item in raw["output"]:
        kind = item["type"]
        if kind == "reasoning":
            continue
        if kind == "message":
            if item.get("role") != "assistant":
                raise ValueError("Unexpected Responses output role")
            for content in item["content"]:
                if content["type"] != "output_text":
                    raise ValueError("Responses refusal or unsupported output")
                text.append(content["text"])
        elif kind == "function_call":
            call_id = item["call_id"]
            if not call_id or call_id in ids:
                raise ValueError("Invalid/duplicate Responses function call ID")
            ids.add(call_id)
            arguments = item["arguments"]
            try:
                arguments = json.loads(arguments)
            except (ValueError, TypeError):
                pass
            calls.append({"name": item["name"], "arguments": arguments, "provider_id": call_id})
        else:
            raise ValueError("Unsupported Responses output item")
    if not calls and not any(text):
        raise ValueError("Responses generation supplied no answer or calls")
    return {
        "text": "\n".join(text),
        "tool_calls": calls,
        "finish_status": "tool_calls" if calls else "stop",
    }

"""Read-only token accounting from captured requests, responses and provider usage."""

import base64
import io
import math
from functools import lru_cache
from urllib.parse import urlparse

import tiktoken
from PIL import Image

from local_agent.mobile.token_totals import totals

DEFAULT_BASELINE = "gpt-4.1-2025-04-14"
RULE = "phone-openai-surrogate-v1"


@lru_cache(maxsize=8)
def encoding(model):
    return tiktoken.encoding_for_model(model)


def image_tokens(width, height, model, detail="auto"):
    """Official GPT-4.1 main/4o tile rules; unsupported image models stay unknown."""
    supported = (model == "gpt-4.1" or model.startswith("gpt-4.1-2025-")) or (
        model == "gpt-4o" or model.startswith("gpt-4o-2024-")
    )
    if not supported or detail not in {"auto", "low", "high"}:
        return None
    if detail == "low":
        return 85
    scale = min(1, 2048 / max(width, height))
    width, height = max(1, math.floor(width * scale)), max(1, math.floor(height * scale))
    scale = min(1, 768 / min(width, height))
    width, height = max(1, math.floor(width * scale)), max(1, math.floor(height * scale))
    return 85 + 170 * math.ceil(width / 512) * math.ceil(height / 512)


def estimate_openai(messages, answer, model):
    """Same text/visible answer surrogate; framing is an estimate, not API billing."""
    enc = encoding(model)

    def count(text):
        return len(enc.encode(text, disallowed_special=()))

    text_tokens, vision_tokens, image_count = 3, 0, 0

    def picture(data, detail="auto"):
        nonlocal vision_tokens, image_count
        if data.startswith("data:"):
            data = data.split(",", 1)[1]
        with Image.open(io.BytesIO(base64.b64decode(data, validate=True))) as image:
            cost = image_tokens(image.width, image.height, model, detail)
        if cost is None:
            raise ValueError("Unsupported baseline image token rules")
        vision_tokens += cost
        image_count += 1

    for message in messages:
        text_tokens += 3 + count(message.get("role", ""))
        if message.get("name"):
            text_tokens += 1 + count(message["name"])
        content = message.get("content")
        if isinstance(content, str):
            text_tokens += count(content)
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    text_tokens += count(part["text"])
                elif part.get("type") == "image_url":
                    image = part["image_url"]
                    picture(image["url"], image.get("detail", "auto"))
        for data in message.get("images", []):
            picture(data)
        if message.get("tool_calls"):
            raise ValueError("Tool-call baseline estimates are not supported in phone mode")
    if not isinstance(answer, str):
        raise ValueError("No captured visible response for the output-length surrogate")
    return {
        "input": text_tokens + vision_tokens,
        "output": count(answer),
        "image_tokens": vision_tokens,
        "images": image_count,
        "encoding": enc.name,
    }


def count_value(value):
    return value if type(value) is int and value >= 0 else None


def run_rows(store, run_id, kind, baseline):
    manifest = store.blobs.json(store.run(run_id)["manifest_ref"])
    config = store.blobs.json(manifest["config_ref"]).get("agent", {})
    local_endpoint = urlparse(config.get("base_url", "")).hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    failures = {
        e.data.get("request_id"): e.data.get("response_ref")
        for e in store.events(run_id)
        if e.event_type == "model.failed"
    }
    rows = []
    for record in store.db.execute("SELECT * FROM model_requests WHERE run_id=?", (run_id,)):
        request = store.blobs.json(record["request_ref"])
        if request["provider"] == "harness":
            continue
        route = "openai" if request["provider"] == "openai" and not local_endpoint else "local"
        response, raw = {}, {}
        if record["response_ref"]:
            response = store.blobs.json(record["response_ref"])
            raw = store.blobs.json(response["original_response_ref"])
        elif failures.get(record["id"]):
            try:
                raw = store.blobs.json(failures[record["id"]])
            except (ValueError, UnicodeError):
                pass
        usage = response.get("usage") or raw.get("usage") or {}
        if request["provider"] == "ollama" and not usage:
            usage = raw
        inp = usage.get("prompt_tokens", usage.get("prompt_eval_count"))
        out = usage.get("completion_tokens", usage.get("eval_count"))
        row = {
            "run_id": run_id,
            "request_id": record["id"],
            "kind": kind,
            "route": route,
            "model": config.get("model"),
            "input_tokens": count_value(inp),
            "output_tokens": count_value(out),
            "cached_tokens": count_value(
                (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
            ),
            "estimated_openai_input": None,
            "estimated_openai_output": None,
            "baseline_model": baseline,
            "rule": RULE,
        }
        if route == "local":
            context = store.blobs.json(request["context_ref"])
            answer = response.get("text")
            if not isinstance(answer, str):
                answer = (raw.get("message") or {}).get("content")
            try:
                estimated = estimate_openai(context["messages"], answer, baseline)
                row.update(
                    estimated_openai_input=estimated["input"],
                    estimated_openai_output=estimated["output"],
                    estimated_image_tokens=estimated["image_tokens"],
                    encoding=estimated["encoding"],
                )
            except Exception as exc:
                # A missing vocabulary/unsupported model must not hide actual billed usage.
                row["estimate_unavailable"] = type(exc).__name__
        rows.append(row)
    return rows


def job_usage(root, job, baseline=DEFAULT_BASELINE):
    from local_agent.storage.database import Store

    if not job.get("run_id"):
        return {"rule": RULE, "baseline_model": baseline, "rows": [], "totals": totals([])}
    store = Store(root, readonly=True)
    try:
        rows = run_rows(store, job["run_id"], job.get("kind", "answer"), baseline)
        return {"rule": RULE, "baseline_model": baseline, "rows": rows, "totals": totals(rows)}
    finally:
        store.close()


def summary(jobs, thread_id=None):
    rows, seen = [], set()
    for job in jobs:
        if thread_id is not None and job.get("thread_id") != thread_id:
            continue
        for row in (job.get("token_usage") or {}).get("rows", []):
            if row["request_id"] not in seen:
                seen.add(row["request_id"])
                rows.append(row)
    return {
        "rule": RULE,
        "baseline_models": sorted({r["baseline_model"] for r in rows}),
        "totals": totals(rows),
        "requests": rows,
        "assumptions": "Estimated all-OpenAI baseline performs the same non-review stages, "
        "using recorded prompts and local visible answers as output-length surrogates. "
        "Paid review is hybrid overhead, subtracted from savings. Chat framing is estimated; "
        "no hidden reasoning/caching/dollar savings are inferred. Unknown usage makes net savings unavailable.",
    }

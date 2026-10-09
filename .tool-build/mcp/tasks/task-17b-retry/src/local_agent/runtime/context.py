import math

from local_agent.contracts import ContextSnapshot
from local_agent.storage.blobs import MAX_BLOB_BYTES, canonical, digest
from local_agent.tools.registry import definitions


def contains_images(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "images" and item:
                return True
            if key == "image_url":
                return True
            if contains_images(item):
                return True
    elif isinstance(value, (list, tuple)):
        for item in value:
            if contains_images(item):
                return True
    return False


def estimate(payload):
    # Base64 bytes are transport, not text tokens. Use an explicit conservative image allowance;
    # actual provider input counts are checked before any model-proposed dispatch.
    images = 0

    def scrub(value):
        nonlocal images
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key == "images":
                    images += len(item)
                    result[key] = ["<image>"] * len(item)
                elif key == "image_url":
                    images += 1
                    result[key] = {"url": "<image>"}
                else:
                    result[key] = scrub(item)
            return result
        if isinstance(value, (tuple, list)):
            return [scrub(item) for item in value]
        return value

    cleaned = scrub(payload)
    return math.ceil(len(canonical(cleaned)) * 0.6) + images * 6144


class ContextBuilder:
    def __init__(self, blobs, config):
        self.blobs, self.config = blobs, config
        self.summary_ref = None

    def build(self, fixed, groups):
        tools = tuple(
            tool for tool in definitions() if tool["function"]["name"] in self.config.tools
        )

        def payload(chosen):
            messages = [*fixed, *[m for group in chosen for m in group]]
            if self.config.provider == "openai":
                from local_agent.models.openai import wire_messages

                result = {
                    "model": self.config.model,
                    "messages": wire_messages(messages),
                    "tools": tools,
                    "stream": False,
                    "store": False,
                    self.config.completion_token_field: self.config.output_reserve_tokens,
                }
                if self.config.reasoning_effort is not None:
                    result["reasoning_effort"] = self.config.reasoning_effort
                if not tools:
                    result.pop("tools")
                return result
            result = {
                "model": self.config.model,
                "messages": [*fixed, *[m for group in chosen for m in group]],
                "tools": tools,
                "stream": False,
                "think": False,
                "options": {
                    "num_ctx": self.config.window_tokens,
                    "num_predict": self.config.output_reserve_tokens,
                    "temperature": 0,
                },
            }
            if not tools:
                result.pop("tools")
            return result

        budget = self.config.window_tokens - self.config.output_reserve_tokens
        wire_budget = MAX_BLOB_BYTES - 65536

        def fits(wire):
            return (
                estimate(wire) <= budget
                and len(canonical(wire)) <= wire_budget
            )

        if not fits(payload([])):
            raise ValueError("fixed instructions and schemas exceed the input context budget")
        chosen = []
        excluded = []
        for index, group in enumerate(reversed(groups)):
            candidate = [group, *chosen]
            if fits(payload(candidate)):
                chosen = candidate
            else:
                if index == 0 and contains_images(group):
                    raise ValueError(
                        "latest image tool exchange exceeds context/transport budget; "
                        "request fewer or smaller crops"
                    )
                excluded.append({"source_ref": self.blobs.put_json(group), "reason": "over_budget"})
        self.summary_ref = None
        summary = None
        if excluded:
            summary = {
                "rule": "complete-exchanges-v1",
                "authority": "untrusted derived working memory",
                "omitted": [
                    {
                        "source_ref": item["source_ref"],
                        "source_hash": digest(self.blobs.read(item["source_ref"])),
                        "bytes": len(self.blobs.read(item["source_ref"])),
                    }
                    for item in reversed(excluded)
                ],
                "note": "Older complete exchanges were omitted. Original evidence is retained; retrieve run-owned tool outputs by evidence_ref.",
            }
            self.summary_ref = self.blobs.put_json(summary)
        wire = payload(chosen)
        if summary:
            # Compact index only: do not feed omitted prose back as authority.
            note = {
                "role": "user",
                "content": summary["note"]
                + f" Omitted {len(excluded)} groups; lineage {self.summary_ref}.",
            }
            augmented = {**wire, "messages": [*fixed, note, *[m for g in chosen for m in g]]}
            if self.config.provider == "openai":
                from local_agent.models.openai import wire_messages

                augmented["messages"] = wire_messages(augmented["messages"])
            if fits(augmented):
                wire = augmented
        ref = self.blobs.put_json(wire)
        snapshot = ContextSnapshot(
            messages=tuple(wire["messages"]),
            tool_definitions=tools,
            payload_ref=ref,
            payload_hash=digest(canonical(wire)),
            token_estimate=estimate(wire),
            provenance=tuple(
                {
                    "source_ref": self.blobs.put_json(item),
                    "source_hash": digest(canonical(item)),
                    "bytes": len(canonical(item)),
                    "reason": reason,
                }
                for item, reason in [
                    (fixed, "protected_instructions_and_task"),
                    (tools, "versioned_tool_schemas"),
                    *[(group, "recent_complete_exchange") for group in chosen],
                    *([(summary, "derived_compaction_lineage")] if summary else []),
                ]
            ),
            exclusions=tuple(excluded),
        )
        return snapshot, self.blobs.put_json(snapshot)

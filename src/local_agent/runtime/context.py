import json
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

        def inspection_key(group):
            """Identify identical successful reads, never tests or mutations."""
            if len(group) != 2 or group[0].get("role") != "assistant" or group[1].get("role") != "tool":
                return None
            calls = group[0].get("tool_calls", [])
            if len(calls) != 1:
                return None
            function = calls[0].get("function", {})
            name, args = function.get("name"), function.get("arguments", {})
            try:
                if isinstance(args, str):
                    args = json.loads(args)
                if name == "run_command":
                    argv = args.get("argv", [])
                    if len(argv) < 2 or argv[0] != "git" or argv[1] not in {"diff", "log", "show", "status"}:
                        return None
                elif name not in {"read_file", "list_files", "search_files", "git_diff"}:
                    return None
                result = json.loads(group[1].get("content", ""))
                if result.get("status") != "succeeded" or result.get("exit_code") not in {None, 0}:
                    return None
                return canonical([name, args, {k: result.get(k) for k in
                    ("evidence_ref", "preview", "error", "truncated")}])
            except (ValueError, TypeError, AttributeError):
                return None

        # Retain the newest complete exchange and all original evidence. Repeated
        # successful reads must not crowd out the failure the agent needs to fix.
        compact_groups, repeated, inspections = [], [], {}
        trailing_repeats = 0
        for group in groups:
            key = inspection_key(group)
            trailing_repeats = 0
            if key is None:
                # A command, edit, or other exchange can change what a read
                # means. Never coalesce across that boundary.
                inspections.clear()
            elif key in inspections:
                old_index, count = inspections[key]
                repeated.append({"source_ref": self.blobs.put_json(compact_groups[old_index]),
                                 "reason": "repeated_inspection"})
                compact_groups[old_index] = None
                trailing_repeats = count
            if key is not None:
                inspections[key] = (len(compact_groups), trailing_repeats + 1)
            compact_groups.append(group)
        compact_groups = [group for group in compact_groups if group is not None]

        def payload(chosen, note=None):
            messages = [*fixed, *([note] if note else []), *[m for group in chosen for m in group]]
            if trailing_repeats >= 2:
                messages.append({"role": "system", "content":
                    "Controller observation: the same successful inspection returned identical "
                    f"evidence {trailing_repeats + 1} times without intervening work. Repeating it provides no new "
                    "information. Use the retained result, address the unresolved failing check, "
                    "make a targeted change, or report a concrete blocker."})
            if self.config.provider == "openai":
                from local_agent.models.openai import wire_messages
                from local_agent.models.responses import payload as responses_payload
                from local_agent.models.responses import uses_responses

                if uses_responses(self.config):
                    return responses_payload(self.config, messages, tools)
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
                "messages": messages,
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
        excluded = list(repeated)
        for index, group in enumerate(reversed(compact_groups)):
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
            augmented = payload(chosen, note)
            if fits(augmented):
                wire = augmented
        ref = self.blobs.put_json(wire)
        snapshot = ContextSnapshot(
            messages=tuple(wire.get("input", wire.get("messages", []))),
            tool_definitions=tuple(wire.get("tools", [])),
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

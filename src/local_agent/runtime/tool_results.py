import json

from local_agent.executor.worker import read_payload


def _read_preview(store, result, base):
    """Keep structured read metadata visible even when JSON escaping expands it."""
    ref = result.stdout_ref or result.output_ref
    try:
        payload = json.loads(store.blobs.read(ref))
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
            return base
        if payload.get("source_ref"):
            data = store.blobs.read(payload["source_ref"])
            start = payload["byte_offset"]
            end = payload.get("next_byte_offset")
            summary = read_payload(data, start, len(data) if end is None else end,
                                   {"source_ref": payload["source_ref"]})
            base["preview"] = json.dumps(summary, ensure_ascii=False)
            base["truncated"] = summary["truncated"]
        elif result.truncated:
            # Results from an older worker can still have an oversized line page.
            # Keep its real hash/cursors, and point to retained evidence rather
            # than inventing a file byte cursor for a legacy line-only response.
            summary = {k: v for k, v in payload.items() if k != "content"}
            summary.update(content_preview_truncated=True,
                           continuation_hint=f"Read retained output with evidence_ref={ref} and byte_offset/byte_limit; the file page was too large for its preview.")
            content = payload["content"]
            low, high = 0, len(content)
            while low < high:
                middle = (low + high + 1) // 2
                summary["content"] = content[:middle]
                if len(json.dumps(summary, ensure_ascii=False).encode("utf-8")) <= 15000:
                    low = middle
                else:
                    high = middle - 1
            summary["content"] = content[:low]
            base["preview"] = json.dumps(summary, ensure_ascii=False)
    except (KeyError, ValueError, TypeError, OSError):
        return base
    return base


def result_preview(store, result, tool=None):
    base = {
        "status": result.status,
        "exit_code": result.exit_code,
        "preview": result.preview,
        "evidence_ref": result.output_ref,
        "truncated": result.truncated,
        "error": result.error,
        "resource_usage": result.resource_usage,
        "side_effect_status": result.side_effect_status,
    }
    if tool == "read_file" and result.status == "succeeded":
        return _read_preview(store, result, base)
    if tool != "register_tool" or result.status != "succeeded":
        return base
    ref = result.stdout_ref or result.output_ref
    if not ref:
        base["preview"] = "registration output could not be decoded; inspect evidence"
        base["truncated"] = False
        return base
    try:
        payload = json.loads(store.blobs.read(ref))
        metadata = payload["registered"]
        record = payload["record"]
        summary = {
            "registered": metadata["name"],
            "version": metadata["version"],
            "code_hash": record["code_hash"],
            "record_hash": record["record_hash"],
        }
    except Exception:
        base["preview"] = "registration output could not be decoded; inspect evidence"
        base["truncated"] = False
        return base
    base["preview"] = json.dumps(summary, sort_keys=True)
    base["truncated"] = False
    return base

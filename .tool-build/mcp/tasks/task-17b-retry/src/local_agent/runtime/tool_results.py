import json


def result_preview(store, result, tool=None):
    base = {
        "status": result.status,
        "exit_code": result.exit_code,
        "preview": result.preview,
        "evidence_ref": result.output_ref,
        "truncated": result.truncated,
    }
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

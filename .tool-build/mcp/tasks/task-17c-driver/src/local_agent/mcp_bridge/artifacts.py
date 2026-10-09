from pathlib import Path

from local_agent.storage.database import Store


def read_artifacts(
    data_root: Path,
    run_id: str,
    artifact_id: str | None = None,
    offset: int = 0,
    limit: int = 16000,
) -> dict:
    if offset < 0 or not (1 <= limit <= 16000):
        raise ValueError("Invalid offset or limit")
    store = Store(data_root, readonly=True)
    try:
        store.run(run_id)
        if artifact_id is None:
            rows = store.db.execute(
                "SELECT id,record_ref FROM artifacts WHERE run_id=? LIMIT 100", (run_id,)
            ).fetchall()
            records = []
            for row in rows:
                record = store.blobs.json(row["record_ref"])
                records.append(
                    {
                        "artifact_id": row["id"],
                        "run_id": run_id,
                        "blob_ref": record["blob_ref"],
                        "content_hash": record["content_hash"],
                        "mime": record["mime"],
                        "size": record["size"],
                        "workspace_origin": record["workspace_origin"],
                    }
                )
            return {"run_id": run_id, "artifacts": records}
        else:
            row = store.db.execute(
                "SELECT record_ref FROM artifacts WHERE run_id=? AND id=?", (run_id, artifact_id)
            ).fetchone()
            if not row:
                raise ValueError("Unknown artifact for this run")
            record = store.blobs.json(row["record_ref"])
            if record["mime"].startswith("text/") or record["mime"] == "application/json":
                body = store.blobs.read(record["blob_ref"]).decode("utf-8", errors="replace")
                text = body[offset : offset + limit]
                next_offset = min(offset + limit, len(body))
                return {
                    "artifact": record,
                    "text": text,
                    "offset": offset,
                    "next_offset": next_offset,
                    "total_chars": len(body),
                }
            return {"artifact": record}
    finally:
        store.close()

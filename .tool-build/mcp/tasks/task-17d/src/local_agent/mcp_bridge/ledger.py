from pathlib import Path

from local_agent.storage.database import Store


def list_runs(data_root: Path, limit: int = 20) -> dict:
    if not (1 <= limit <= 100):
        raise ValueError("limit must be between 1 and 100")
    if not (data_root / "control" / "agent.db").exists():
        return {"runs": []}
    store = Store(data_root, readonly=True)
    try:
        rows = store.db.execute(
            "SELECT id,status,manifest_ref,created_utc FROM runs ORDER BY created_utc DESC LIMIT ?",
            (limit,),
        ).fetchall()
        records = []
        for row in rows:
            manifest = store.blobs.json(row["manifest_ref"])
            config = store.blobs.json(manifest["config_ref"])["agent"]
            records.append(
                {
                    "id": row["id"],
                    "status": row["status"],
                    "created_utc": row["created_utc"],
                    "provider": config["provider"],
                    "model": config["model"],
                }
            )
        return {"runs": records}
    finally:
        store.close()

import json
from pathlib import Path

from local_agent.storage.database import Store


def read_trace(data_root: Path, run_id: str, after_seq: int = 0, limit: int = 50) -> dict:
    if not (0 <= after_seq and 1 <= limit <= 100):
        raise ValueError("Invalid after_seq or limit")
    store = Store(data_root, readonly=True)
    try:
        store.run(run_id)
        cursor = store.db.cursor()
        cursor.execute(
            "SELECT payload FROM events WHERE run_id=? AND run_seq>? ORDER BY run_seq LIMIT ?",
            (run_id, after_seq, limit),
        )
        events = [json.loads(row[0]) for row in cursor.fetchall()]
        next_after_seq = events[-1]["run_seq"] if events else after_seq
        return {"run_id": run_id, "events": events, "next_after_seq": next_after_seq}
    finally:
        store.close()

"""Descriptor lookup for tool image artifacts."""

DESCRIPTOR_MIME = "application/vnd.local-agent.tool-image+json"


def tool_images(store, run_id, execution_id=None):
    """Return descriptor rows for tool image artifacts of a run."""
    sql = "SELECT execution_id, record_ref FROM artifacts WHERE run_id=?"
    params = [run_id]
    if execution_id is not None:
        sql += " AND execution_id=?"
        params.append(execution_id)
    sql += " ORDER BY rowid"
    rows = store.db.execute(sql, params).fetchall()
    results = []
    for row in rows:
        record = store.blobs.json(row["record_ref"])
        if record.get("mime") != DESCRIPTOR_MIME:
            continue
        descriptor = store.blobs.json(record["blob_ref"])
        if descriptor.get("kind") != "tool_image":
            continue
        if descriptor.get("run_id") != run_id:
            continue
        if descriptor.get("execution_id") != row["execution_id"]:
            continue
        results.append(row)
    return results

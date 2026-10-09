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
        results.append(descriptor)
    return results


def save_artifact(agent, execution_id, path, data, mime):
    """Store artifact bytes and register an idempotent artifact record."""
    from local_agent.contracts import ArtifactRecord, new_id
    from local_agent.storage.blobs import digest

    ref = agent.store.blobs.put(data)
    sql = "SELECT record_ref FROM artifacts WHERE run_id=? AND execution_id=?"
    for row in agent.store.db.execute(sql, (agent.run_id, execution_id)).fetchall():
        record = agent.store.blobs.json(row["record_ref"])
        if record.get("blob_ref") == ref and record.get("mime") == mime:
            return ref
    record = ArtifactRecord(
        artifact_id=new_id("artifact"),
        run_id=agent.run_id,
        execution_id=execution_id,
        blob_ref=ref,
        content_hash=digest(data),
        mime=mime,
        size=len(data),
        workspace_origin=path,
    )
    agent.last = agent.store.register_artifact(record, causes=(agent.last.event_id,))
    return ref

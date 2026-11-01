"""Shared capability-probe container role and naming helpers.

Role is diagnostic metadata only; it never grants authority. Authority always
comes from durable execution records, protected run manifests and ownership
checks.
"""

from __future__ import annotations

PROBE_ROLE = "capability-probe"
TASK_ROLE = "task"


def container_role(store, run_id):
    """Classify a run as a capability probe or a normal task.

    The classification is derived ONLY from the protected run manifest:
    ``run(run_id) -> sqliteRow['manifest_ref'] -> blobs.json(ref)`` and then
    ``manifest['config_ref'] -> blobs.json(config_ref)`` and
    ``config['probe'] is True``. Missing or non-strict-True flags (including
    historical manifests without the flag) classify as a normal task.
    """
    row = store.run(run_id)
    manifest = store.blobs.json(row["manifest_ref"])
    config = store.blobs.json(manifest["config_ref"])
    return PROBE_ROLE if config.get("probe") is True else TASK_ROLE


def ephemeral_container_names(role, owner, execution_id):
    """Return the current and legacy ephemeral container names for a role.

    Probe containers use a human-recognizable name that includes the owner and
    the probe role, with the legacy name returned as a fallback so cleanup can
    find containers created before the probe naming scheme existed. Normal task
    ephemeral containers keep the existing ``local-agent-<execution_id>`` name.

    The pair may coincide for normal tasks (current == legacy); callers must
    deduplicate equal names before probing. The API stays a pair because the
    release path unpacks it.
    """
    if role == PROBE_ROLE:
        owner_hex = str(owner)[:12]
        current = f"local-agent-{owner_hex}-probe-{execution_id}"
    else:
        current = f"local-agent-{execution_id}"
    legacy = f"local-agent-{execution_id}"
    return current, legacy

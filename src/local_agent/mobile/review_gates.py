"""Controller evidence fingerprints for automatic paid-review eligibility."""

from local_agent.storage.blobs import canonical, digest


def evidence_key(tree, tests):
    commands = [{key: item.get(key) for key in ("argv", "cwd", "status", "exit_code", "counts")}
                for item in tests.get("commands", [])]
    environment = tests.get("environment") or {}
    return digest(canonical({"tree": tree, "commands": commands,
                             "plan": (tests.get("plan") or {}).get("hash"),
                             "environment": {k: environment.get(k) for k in ("image", "key")}}))


def eligible(job, record, receipts):
    tests = job.get("project_tests") or {}
    if job.get("status") != "completed" or not job.get("audit", {}).get("ok"):
        return False, "Local attempt did not complete with a valid audit", None
    if tests.get("status") != "passed" or not tests.get("audit", {}).get("ok"):
        return False, "Required independent checks have not passed with a valid audit", None
    git = job.get("git_workspace") or {}
    if not git.get("candidate_commit") or not (record or {}).get("candidate_tree"):
        return False, "No auditable published candidate is available", None
    if record.get("candidate_commit") != git["candidate_commit"] or record.get("run_id") != job.get("run_id"):
        return False, "Published candidate no longer belongs to this attempt", None
    key = evidence_key(record["candidate_tree"], tests)
    if key in receipts:
        return False, "Candidate content and independent verification evidence were already reviewed", key
    return True, "New candidate content or independent verification evidence; required checks passed", key

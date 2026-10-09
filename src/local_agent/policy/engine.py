from local_agent.contracts import PolicyDecision, new_id
from local_agent.storage.blobs import canonical, digest

POLICY = {
    "version": "m0-simulation-v1",
    "mode": "simulation",
    "read_file": "allow workspace paths validated by the registry",
    "run_command": "allow only the fixed fixture-test argv, cwd, and timeout",
    "network": False,
    "gpu": False,
}
POLICY_HASH = digest(canonical(POLICY))

OFFLINE_POLICY = {
    "version": "dev-offline-v1",
    "network": False,
    "gpu": False,
    "workspace_only": True,
    "limits": {"memory_mb": 4096, "cpu_cores": 4, "pids": 128},
    "command_authority": "arbitrary code inside the verified offline sandbox",
}
OFFLINE_HASH = digest(canonical(OFFLINE_POLICY))


def offline_evaluate(call_id, normalized, normalized_ref, allowlist):
    allowed = normalized["tool"] in allowlist
    return PolicyDecision(
        decision_id=new_id("policy"),
        call_id=call_id,
        verdict="allow" if allowed else "deny",
        rule_ids=("workspace.only", "sandbox.offline", "tool.allowlist"),
        policy_hash=OFFLINE_HASH,
        normalized_request_hash=digest(canonical(normalized)),
        normalized_request_ref=normalized_ref,
        reason="Granted offline sandbox capability."
        if allowed
        else "Tool outside configured allowlist.",
    )


def evaluate(call_id, normalized, normalized_ref, allowlist):
    args = normalized["arguments"]
    tool = normalized["tool"]
    allowed = tool in allowlist and (
        tool == "read_file"
        or (
            tool == "run_command"
            and args["argv"] == ["python", "-m", "pytest", "-q"]
            and args["cwd"] == "project"
            and args["timeout_seconds"] == 60
        )
    )
    return PolicyDecision(
        decision_id=new_id("policy"),
        call_id=call_id,
        verdict="allow" if allowed else "deny",
        rule_ids=("simulation.fixed-tools",),
        policy_hash=POLICY_HASH,
        normalized_request_hash=digest(canonical(normalized)),
        normalized_request_ref=normalized_ref,
        reason="Fixed M0 mock capability allowed." if allowed else "Outside fixed M0 mock profile.",
    )

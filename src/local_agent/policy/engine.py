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
    "environment_preparation": "controller-owned recipes; downloads require an explicit operator grant",
}
OFFLINE_HASH = digest(canonical(OFFLINE_POLICY))
# Retain the preceding policy for interrupted runs frozen at its 128-task ceiling.
LEGACY_OFFLINE_HASH = OFFLINE_HASH
OFFLINE_POLICY = {**OFFLINE_POLICY, "limits": {**OFFLINE_POLICY["limits"], "pids": 1024}}
OFFLINE_HASH = digest(canonical(OFFLINE_POLICY))


def offline_evaluate(call_id, normalized, normalized_ref, allowlist, *, policy_hash=OFFLINE_HASH):
    if policy_hash not in {OFFLINE_HASH, LEGACY_OFFLINE_HASH}:
        raise ValueError("unknown offline policy")
    ceiling = 128 if policy_hash == LEGACY_OFFLINE_HASH else 1024
    limits = normalized["effective_limits"]
    allowed = normalized["tool"] in allowlist and (
        type(limits["pids"]) is int and 1 <= limits["pids"] <= ceiling
        and limits["memory_mb"] <= 4096 and limits["cpu_cores"] <= 4
        and limits["network"] is False and limits["gpu"] is False
    )
    return PolicyDecision(
        decision_id=new_id("policy"),
        call_id=call_id,
        verdict="allow" if allowed else "deny",
        rule_ids=(("environment.declarative", "tool.allowlist")
                  if normalized["tool"] in {"environment_inventory", "prepare_environment"}
                  else ("workspace.only", "sandbox.offline", "tool.allowlist")),
        policy_hash=policy_hash,
        normalized_request_hash=digest(canonical(normalized)),
        normalized_request_ref=normalized_ref,
        reason=("Granted controller-managed environment capability."
                if normalized["tool"] in {"environment_inventory", "prepare_environment"}
                else "Granted offline sandbox capability.")
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

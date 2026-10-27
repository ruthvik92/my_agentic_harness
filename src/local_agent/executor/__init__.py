"""
Docker execution lifecycle

Container lifecycle belongs to the host harness. The LLM proposes tools; it cannot
choose Docker mounts, privileges, image IDs, or lifecycle operations.

The executor manages container creation, execution, and cleanup. It runs a trusted
worker in a secure, isolated environment with explicit environment variables.

The host maintains durable state and security attestation. Persistent keepers
survive across executions; ephemeral containers are destroyed after each run.

For scripted M0 simulation and tests, use MockExecutor to simulate execution
without Docker.
"""

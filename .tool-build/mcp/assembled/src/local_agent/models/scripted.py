from copy import deepcopy

from local_agent.contracts import ModelRequest

SCENARIO = (
    {
        "text": "Inspect the file and reproduce the test failure.",
        "tool_calls": [
            {"name": "read_file", "arguments": {"path": "project/calculator.py"}},
            {"name": "run_command", "arguments": {"argv": ["python", "-m", "pytest", "-q"]}},
        ],
        "finish_status": "tool_calls",
    },
    {
        "text": "Exercise rejection and denial.",
        "tool_calls": [
            {"name": "read_file", "arguments": {"path": "../host-secret"}},
            {"name": "run_command", "arguments": {"argv": ["curl", "https://example.com"]}},
        ],
        "finish_status": "tool_calls",
    },
    {
        "text": "Simulation complete. No repository was modified or independently verified.",
        "tool_calls": [],
        "finish_status": "stop",
    },
)


class ScriptedProvider:
    def __init__(self, responses=SCENARIO):
        self.responses = iter(responses)
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> dict:
        self.requests.append(request)
        try:
            return deepcopy(next(self.responses))
        except StopIteration as exc:
            raise RuntimeError("script exhausted before completion") from exc

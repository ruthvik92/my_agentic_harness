from local_agent.contracts import ExecutionRequest


class MockExecutor:
    """Returns fixed data; never opens source files, spawns processes, or runs code."""

    def __init__(self):
        self.dispatched: list[ExecutionRequest] = []

    async def execute(self, request: ExecutionRequest) -> dict:
        self.dispatched.append(request)
        if request.tool == "read_file":
            return {
                "output": "def add(a, b):\n    return a - b\n",
                "exit_code": None,
                "status": "succeeded",
            }
        return {
            "output": "FAILED test_add: expected 5, got -1 (scripted result)\n",
            "exit_code": 1,
            "status": "failed",
        }

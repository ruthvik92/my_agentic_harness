"""Protected held-out cases; never supplied by the editable project."""

import importlib.util
import json
import sys

suite = sys.argv[1] if len(sys.argv) > 1 else "calculator"
suites = {
    "calculator": (
        "calculator.py",
        "add",
        [
            ((2, 3), 5),
            ((-7, 2), -5),
            ((0, 0), 0),
            ((2.5, 1.25), 3.75),
            ((100, -100), 0),
        ],
    ),
    "mean": (
        "statistics_utils.py",
        "mean",
        [
            (([1, 2],), 1.5),
            (([-5, 2, 3],), 0),
            (([2.5, 3.5],), 3),
            (([7],), 7),
            (([],), ValueError),
        ],
    ),
    "clamp": (
        "bounds.py",
        "clamp",
        [
            ((5, 0, 10), 5),
            ((-5, -3, 2), -3),
            ((8, -3, 2), 2),
            ((1.5, 1, 2), 1.5),
            ((2, 2, 2), 2),
            ((1, 4, 2), ValueError),
        ],
    ),
}
filename, name, cases = suites[suite]
spec = importlib.util.spec_from_file_location("candidate", "/workspace/project/" + filename)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
function = getattr(module, name)
results = []
for args, expected in cases:
    try:
        results.append(function(*args) == expected)
    except Exception as exc:
        results.append(expected is ValueError and isinstance(exc, ValueError))
print(
    json.dumps(
        {
            "suite": suite,
            "verified": all(results),
            "tests_passed": sum(results),
            "tests_total": len(results),
        }
    )
)
sys.exit(0 if all(results) else 1)

"""Bounded findings for repair handoff; legacy prose remains readable."""

from local_agent.storage.blobs import canonical, digest

FIELDS = {"id", "location", "observed", "expected", "impact", "acceptance"}


def normalize(value, summary=""):
    if value is None:
        if not summary:
            return []
        return [{"id": "legacy-" + digest(summary.encode())[7:19], "location": "",
                 "observed": summary[:6000], "expected": "Resolve the saved review findings",
                 "impact": "See original review",
                 "acceptance": ["Resolve the saved finding and verify the relevant behavior against the original task"]}]
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("Review findings must be a list of at most eight items")
    result, ids = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) != FIELDS:
            raise ValueError("Each finding needs id, location, observed, expected, impact, acceptance")
        for key in FIELDS - {"acceptance"}:
            if not isinstance(item[key], str) or len(item[key]) > (128 if key == "id" else 2000):
                raise ValueError("Invalid finding text")
        if not item["id"] or item["id"] in ids or not item["observed"].strip():
            raise ValueError("Findings need unique IDs and observed behavior")
        acceptance = item["acceptance"]
        if item["id"].startswith("legacy-") and acceptance == []:
            item = {**item, "acceptance": ["Resolve the saved finding and verify the relevant behavior against the original task"]}
            acceptance = item["acceptance"]
        if (not isinstance(acceptance, list) or not 1 <= len(acceptance) <= 8
                or any(not isinstance(v, str) or not v.strip() or len(v) > 1000 for v in acceptance)):
            raise ValueError("Findings need bounded acceptance criteria")
        ids.add(item["id"])
        result.append(item)
    if len(canonical(result)) > 16000:
        raise ValueError("Findings exceed the bounded repair handoff")
    return result

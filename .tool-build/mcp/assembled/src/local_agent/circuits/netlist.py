"""Conservative deterministic SPICE draft; never invent active device models."""

import json


def compile_netlist(graph):
    lines = [
        "\n".join("* " + line for line in graph.title.splitlines()),
        "* UNREVIEWED DRAFT - not a verified/simulation-ready circuit",
        f"* Evidence: PDF pages {', '.join(map(str, graph.pages))}; coverage={graph.coverage}",
        "* Node names are schematic transcription hypotheses, not measurements.",
    ]
    omitted = []
    emitted = []
    for component in graph.components:
        evidence = f"page {component.evidence.page}, region {list(component.evidence.region)}"
        lines.append(f"* {component.ref}: {evidence}")
        if component.kind in {"R", "C", "L"} and component.connection_status == "observed":
            lines.append(f"{component.ref} {' '.join(component.nodes)} {component.value}")
            emitted.append(component.ref)
        else:
            reason = (
                component.uncertainty
                or "active device/connector requires explicit pin mapping and a reviewed model"
            )
            # Keep model-supplied text in comments, never directives or executable statements.
            lines.extend("* " + line for line in f"OMITTED {component.ref}: {reason}".splitlines())
            omitted.append(component.ref)
    lines.append("* No supply, stimulus, device model or analysis has been fabricated.")
    lines.append(".end")
    report = {
        "status": "draft_requires_review",
        "coverage": graph.coverage,
        "pages": list(graph.pages),
        "emitted_passives": emitted,
        "omitted_components": omitted,
        "unresolved": list(graph.unresolved),
        "simulation_ready": False,
        "topology_verified": False,
    }
    return "\n".join(lines) + "\n", report


def graph_schema():
    from local_agent.circuits.contracts import CircuitGraph

    return json.dumps(CircuitGraph.model_json_schema(), separators=(",", ":"))

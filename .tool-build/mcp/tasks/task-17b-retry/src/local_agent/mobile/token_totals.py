"""Controller correction of the harness draft: explicit baseline and unknown usage."""


def valid(value):
    return type(value) is int and value >= 0


def totals(rows):
    result = dict.fromkeys(
        (
            "measured_openai_input",
            "measured_openai_output",
            "measured_openai_total",
            "measured_openai_cached",
            "measured_local_input",
            "measured_local_output",
            "measured_local_total",
            "measured_review_tokens",
            "local_requests",
            "openai_requests",
            "unknown_openai_requests",
            "unknown_local_estimates",
            "unknown_local_usage",
        ),
        0,
    )
    avoided, paid_nonreview = 0, 0
    for row in rows:
        route = row["route"]
        if route not in {"local", "openai"}:
            raise ValueError("Unknown accounting route")
        result[route + "_requests"] += 1
        inp, out = row.get("input_tokens"), row.get("output_tokens")
        prefix = "measured_" + route
        for label, value in (("input", inp), ("output", out)):
            if valid(value):
                result[prefix + "_" + label] += value
        if valid(inp) and valid(out):
            result[prefix + "_total"] += inp + out
            if route == "openai":
                if row.get("kind") == "review":
                    result["measured_review_tokens"] += inp + out
                else:
                    paid_nonreview += inp + out
        else:
            result["unknown_openai_requests" if route == "openai" else "unknown_local_usage"] += 1
        if route == "openai":
            cached = row.get("cached_tokens")
            if valid(cached):
                result["measured_openai_cached"] += cached
        else:
            est_in, est_out = row.get("estimated_openai_input"), row.get("estimated_openai_output")
            if valid(est_in) and valid(est_out):
                avoided += est_in + est_out
            else:
                result["unknown_local_estimates"] += 1
    complete = not result["unknown_openai_requests"] and not result["unknown_local_estimates"]
    baseline = avoided + paid_nonreview if complete else None
    saved = baseline - result["measured_openai_total"] if complete else None
    result.update(
        estimated_avoided_openai_tokens=avoided if not result["unknown_local_estimates"] else None,
        estimated_all_openai_baseline=baseline,
        estimated_net_saved_tokens=saved,
        estimated_net_saved_percent=100 * saved / baseline if baseline else None,
    )
    return result

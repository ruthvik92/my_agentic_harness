"""Validated per-submission runtime overrides; profile files remain unchanged."""


def override(config, minutes):
    if minutes is None:
        return config
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        raise ValueError("Agent run limit must be an integer from 1 to 1440 minutes")
    return config.model_copy(
        update={"limits": config.limits.model_copy(update={"run_timeout_seconds": minutes * 60})}
    )

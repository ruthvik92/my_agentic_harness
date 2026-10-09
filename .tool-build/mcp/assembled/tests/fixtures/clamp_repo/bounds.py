def clamp(value, lower, upper):
    if lower > upper:
        raise ValueError("lower bound exceeds upper bound")
    return min(max(value, upper), lower)

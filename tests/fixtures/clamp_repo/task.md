Fix clamp(value, lower, upper) in bounds.py: return value when it is within the
inclusive bounds, lower when below them, upper when above them. Support negative
and fractional inputs; lower > upper must raise ValueError. Reproduce the failure,
repair the implementation and run tests.

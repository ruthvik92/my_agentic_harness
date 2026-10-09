Fix mean(values) in statistics_utils.py: return the arithmetic mean, preserving
fractional results and supporting negative numbers. Empty input must raise
ValueError. Reproduce the failure, repair the implementation and run tests.

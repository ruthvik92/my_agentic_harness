from statistics_utils import mean


def test_fractional_mean():
    assert mean([1, 2]) == 1.5

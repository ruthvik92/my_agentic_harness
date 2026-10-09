from bounds import clamp


def test_in_range():
    assert clamp(5, 0, 10) == 5

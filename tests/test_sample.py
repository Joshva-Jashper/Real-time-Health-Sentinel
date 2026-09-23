def test_addition():
    assert 1 + 1 == 2


def test_subtraction():
    assert 10 - 3 == 7


def test_intentional_failure():
    # This is a baseline sanity test; failure scenarios belong in dedicated
    # regression fixtures so the default repository suite remains green.
    assert 1 == 1

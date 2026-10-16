import time

import pytest

from matrix_ui.cron import Cron


def ts(h, m=0, s=0, day=5):      # Jan 2026; the 5th is a Monday
    return time.mktime((2026, 1, day, h, m, s, 0, 0, -1))


def test_fields_lists_ranges_steps():
    c = Cron("*/15 9-10,12 * * *")
    assert [c.fires(ts(h, m)) for h, m in [(9, 0), (9, 15), (9, 5), (10, 45), (11, 0), (12, 30)]] == [
        True, True, False, True, False, True]


def test_five_fields_fire_on_second_zero_only():
    assert Cron("* * * * *").fires(ts(1, 2, 0)) and not Cron("* * * * *").fires(ts(1, 2, 1))
    assert Cron("30 * * * * *").fires(ts(1, 2, 30))


def test_day_of_week_sunday_is_zero_or_seven():
    sunday = ts(8, day=11)
    assert Cron("0 8 * * 0").fires(sunday) and Cron("0 8 * * 7").fires(sunday) and not Cron("0 8 * * 1").fires(sunday)


def test_dom_or_dow_when_both_restricted():
    c = Cron("0 8 5 * 0")     # the 5th or any Sunday
    assert c.fires(ts(8, day=5)) and c.fires(ts(8, day=11)) and not c.fires(ts(8, day=6))


def test_active_window():
    c = Cron("0 */15 * * * *")
    assert c.active(ts(10, 0, 14), 15) and not c.active(ts(10, 0, 15), 15) and c.active(ts(10, 15), 15)


def test_next_firing():
    c = Cron("0 */15 * * * *")
    assert c.next(ts(10, 0, 0)) == ts(10, 15)           # strictly after
    assert c.next(ts(10, 7, 30)) == ts(10, 15)
    assert c.next(ts(10, 50)) == ts(11, 0)               # rolls into the next hour
    assert Cron("30 8 * * *").next(ts(9)) == ts(8, 30, day=6)    # tomorrow
    assert Cron("0 8 * * 0").next(ts(9)) == ts(8, day=11)         # next Sunday
    assert Cron("* * * * * *").next(ts(23, 59, 59)) == ts(0, day=6)


def test_next_skips_to_a_matching_date_or_gives_up():
    assert Cron("0 0 1 3 *").next(ts(0)) == time.mktime((2026, 3, 1, 0, 0, 0, 0, 0, -1))
    assert Cron("0 0 31 2 *").next(ts(0)) is None        # there is no Feb 31


@pytest.mark.parametrize("bad", ["", "* * *", "60 * * * *", "* 24 * * *", "*/0 * * * *", "a * * * *", "5-2 * * * *"])
def test_bad_expressions_raise(bad):
    with pytest.raises(ValueError):
        Cron(bad)

"""Cron expressions for `/app/schedule`: "min hour dom month dow", or "sec min hour dom month dow".

Each field is `*`, a number, a range `a-b`, a list `a,b-c`, or any of those with a step (`*/15`, `10-50/10`).
Day of week is 0-6 with 0 = Sunday (7 also means Sunday). As in classic cron, when both day-of-month and
day-of-week are restricted a day matches if either does.
"""
import datetime
import math
import time

RANGES = [(0, 59), (0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]    # sec, min, hour, dom, month, dow


def _field(text, lo, hi):
    values = set()
    for part in text.split(","):
        rng, _, step = part.partition("/")
        step = int(step) if step else 1
        if step < 1:
            raise ValueError(part)
        if rng == "*":
            a, b = lo, hi
        else:
            a, _, b = rng.partition("-")
            a = int(a)
            b = int(b) if b else (hi if step > 1 else a)
        if not lo <= a <= b <= hi:
            raise ValueError(part)
        values.update(range(a, b + 1, step))
    return values


class Cron:
    def __init__(self, expr):
        parts = str(expr).split()
        if len(parts) == 5:
            parts.insert(0, "0")
        if len(parts) != 6:
            raise ValueError(f"expected 5 or 6 fields, got {expr!r}")
        self.sec, self.min, self.hour, self.dom, self.month, self.dow = (
            _field(p, *r) for p, r in zip(parts, RANGES))
        self.dow = {d % 7 for d in self.dow}
        self._dom_any, self._dow_any = parts[3] == "*", parts[5] == "*"

    def fires(self, t):
        """True when the cron fires at the whole second `t` (epoch seconds, local time)."""
        lt = time.localtime(t)
        if lt.tm_sec not in self.sec or lt.tm_min not in self.min or lt.tm_hour not in self.hour:
            return False
        return self._day(lt.tm_mon, lt.tm_mday, lt.tm_wday)

    def _day(self, month, mday, wday):
        """True when the date matches; `wday` counts from Monday = 0, as `time.struct_time` and `date.weekday()` do."""
        if month not in self.month:
            return False
        dom, dow = mday in self.dom, (wday + 1) % 7 in self.dow
        if self._dom_any or self._dow_any:
            return dom and dow
        return dom or dow

    def next(self, t):
        """The first firing strictly after `t` (epoch seconds), or None if there is none in the next five years."""
        start = math.floor(t) + 1
        lt = time.localtime(start)
        first = day = datetime.date(lt.tm_year, lt.tm_mon, lt.tm_mday)
        for _ in range(366 * 5):
            if self._day(day.month, day.day, day.weekday()):
                for h in sorted(self.hour):
                    if day == first and h < lt.tm_hour:
                        continue
                    for m in sorted(self.min):
                        if day == first and (h, m) < (lt.tm_hour, lt.tm_min):
                            continue
                        for s in sorted(self.sec):
                            ts = time.mktime((day.year, day.month, day.day, h, m, s, 0, 0, -1))
                            if ts >= start and self.fires(ts):
                                return ts
            day += datetime.timedelta(days=1)
        return None

    def active(self, t, length):
        """True when some firing at `f` has f <= t < f + length (all in seconds)."""
        now = math.floor(t)
        return any(self.fires(now - s) for s in range(math.ceil(length)) if now - s > t - length)

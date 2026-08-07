"""Time as an injected dependency.

Nothing in this codebase calls ``datetime.now()``/``date.today()`` directly outside
this module. A ``Clock`` is threaded through anywhere "now" matters so tests can pass
a fixed clock instead of depending on ``freezegun`` or wall-clock time, and so cache
keys are forced to take an explicit ``as_of`` rather than reading time internally.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def today_utc(clock: Clock = utc_now) -> date:
    return clock().date()


def fixed_clock(at: datetime) -> Clock:
    return lambda: at

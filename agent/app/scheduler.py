"""Tiny asyncio scheduler: run a callable at HH:MM local time, every day or one day a week."""
import asyncio
import datetime as dt
import logging
from typing import Awaitable, Callable

log = logging.getLogger("agent.scheduler")


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def weekday_number(name: str) -> int | None:
    """"Mon", "monday", "Sundays" -> 0..6; "" -> None (every day). Raises on anything else."""
    name = name.strip().lower().rstrip("s")
    if not name:
        return None
    for i, day in enumerate(WEEKDAYS):
        if len(name) >= 3 and day.startswith(name):
            return i
    raise ValueError(f"not a day of the week: {name!r}")


def seconds_until(hhmm: str, now: dt.datetime | None = None, weekday: int | None = None) -> float:
    now = now or dt.datetime.now()
    hour, minute = (int(p) for p in hhmm.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if weekday is not None:
        target += dt.timedelta(days=(weekday - now.weekday()) % 7)
    if target <= now:
        target += dt.timedelta(days=1 if weekday is None else 7)
    return (target - now).total_seconds()


async def daily(hhmm: str, job: Callable[[], Awaitable[None]], weekday: int | None = None) -> None:
    """Run job at hhmm every day, or only on `weekday` (0 = Monday) when given."""
    while True:
        await asyncio.sleep(seconds_until(hhmm, weekday=weekday))
        try:
            await job()
        except Exception:  # one failed night must not kill the scheduler
            log.exception("scheduled job failed")

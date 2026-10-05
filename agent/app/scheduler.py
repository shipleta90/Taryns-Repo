"""Tiny asyncio scheduler: run a callable once a day at HH:MM local time."""
import asyncio
import datetime as dt
import logging
from typing import Awaitable, Callable

log = logging.getLogger("agent.scheduler")


def seconds_until(hhmm: str, now: dt.datetime | None = None) -> float:
    now = now or dt.datetime.now()
    hour, minute = (int(p) for p in hhmm.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()


async def daily(hhmm: str, job: Callable[[], Awaitable[None]]) -> None:
    while True:
        await asyncio.sleep(seconds_until(hhmm))
        try:
            await job()
        except Exception:  # one failed night must not kill the scheduler
            log.exception("scheduled job failed")

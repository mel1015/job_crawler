"""APScheduler 진입점. 매일 09:00/19:00 KST에 전체 사이트 크롤."""
from __future__ import annotations

import asyncio
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from .crawlers.registry import ACTIVE_SITES
from .logging_setup import setup_logging
from .pipeline import run as run_pipeline


async def _job(limit: int = 30) -> None:
    logger.info("scheduled crawl start")
    try:
        await run_pipeline(ACTIVE_SITES, limit=limit)
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=e).error(f"scheduled crawl failed: {e}")
    logger.info("scheduled crawl end")


async def _main_async() -> None:
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(_job, CronTrigger(hour="9,19", minute=0), id="daily_crawl")
    scheduler.start()
    logger.info("scheduler started (09:00, 19:00 KST)")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    scheduler.shutdown(wait=False)


def main() -> None:
    setup_logging()
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()

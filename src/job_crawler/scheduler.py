"""APScheduler 진입점. 매일 09:00/19:00 KST에 전체 사이트 크롤 후 자동 분석."""
from __future__ import annotations

import asyncio
import shutil
import signal
import subprocess
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from .crawlers.registry import ACTIVE_SITES
from .logging_setup import setup_logging
from .pipeline import run as run_pipeline
from .scoring.claude_batch import count_unscored_jobs
from .scoring.contract import build_analysis_prompt

# 리포지토리 루트 (이 파일 기준 4단계 상위)
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_analysis() -> None:
    """크롤 완료 후 Claude Code CLI로 미평가 공고 자동 분석."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        logger.warning("claude CLI not found — skipping auto-analysis")
        return

    unscored = count_unscored_jobs(days=1)
    if unscored == 0:
        logger.info("auto-analysis: 미평가 공고 없음, 스킵")
        return

    logger.info(f"auto-analysis: 미평가 {unscored}건 → claude -p 실행")
    try:
        result = subprocess.run(
            [claude_bin, "-p", build_analysis_prompt(days=1, limit=min(unscored, 50))],
            cwd=str(_REPO_ROOT),
            timeout=600,  # 최대 10분
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("auto-analysis: 완료")
        else:
            logger.warning(f"auto-analysis: 비정상 종료 (rc={result.returncode})\n{result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        logger.warning("auto-analysis: 타임아웃 (600s)")
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=e).error("auto-analysis: 실행 실패")
    finally:
        for pattern in ("_*", "*_tmp.py"):
            for f in _REPO_ROOT.glob(pattern):
                f.unlink(missing_ok=True)


async def _job(limit: int = 30) -> None:
    logger.info("scheduled crawl start")
    try:
        await run_pipeline(ACTIVE_SITES, max_results=limit)
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=e).error(f"scheduled crawl failed: {e}")
    logger.info("scheduled crawl end")

    # 크롤 완료 후 분석 (blocking이지만 스케줄러 루프와 분리된 스레드로 실행)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_analysis)


async def _main_async() -> None:
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(_job, CronTrigger(hour="9,19", minute=0), id="daily_crawl", misfire_grace_time=300)
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

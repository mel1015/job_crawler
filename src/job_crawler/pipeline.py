"""Crawl → dedupe → persist. LLM 평가는 온디맨드(대시보드)에서 별도 수행."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import and_, or_, select, update

from .config import get_settings
from .crawlers.base import BaseCrawler, JobDetail, JobSummary, SearchCriteria
from .crawlers.registry import ACTIVE_SITES, build_crawler
from .db.models import CrawlRun, Job
from .db.session import session_scope
from .filters.criteria import pass_filters
from .logging_setup import setup_logging


async def crawl_site(site: str, max_results: int) -> tuple[int, int, list[str]]:
    """키워드별로 각각 검색 → 결과 병합(dedupe) → 상세 조회 → DB upsert."""
    settings = get_settings()
    crawler: BaseCrawler = build_crawler(site)
    keywords = settings.roles_list or [""]

    errors: list[str] = []
    merged: dict[str, JobSummary] = {}
    try:
        for kw in keywords:
            criteria = SearchCriteria(
                keywords=[kw] if kw else [],
                regions=settings.regions_list,
                years_min=settings.desired_experience_min or None,
                years_max=settings.desired_experience_max or None,
                max_results=max_results,
            )
            try:
                summaries: list[JobSummary] = await crawler.search(criteria)
            except Exception as e:  # noqa: BLE001
                errors.append(f"search '{kw}': {e}")
                logger.warning(f"[{site}] search '{kw}' failed: {e}")
                continue
            logger.info(f"[{site}] kw='{kw}' returned {len(summaries)}")
            for s in summaries:
                if s.external_id not in merged:
                    merged[s.external_id] = s

        logger.info(f"[{site}] merged unique={len(merged)} across {len(keywords)} keywords")

        all_summaries = list(merged.values())
        fetched = len(all_summaries)
        filtered = [s for s in all_summaries if pass_filters(s)]
        logger.info(f"[{site}] passed filter={len(filtered)}/{fetched}")

        new_count = 0
        semaphore = asyncio.Semaphore(settings.crawl_concurrency)

        async def fetch_one(s: JobSummary) -> None:
            nonlocal new_count
            async with semaphore:
                try:
                    detail: JobDetail = await crawler.fetch_detail(s)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"detail {s.external_id}: {e}")
                    logger.warning(f"[{site}] detail failed {s.external_id}: {e}")
                    return
                if _upsert_job(detail):
                    new_count += 1

        await asyncio.gather(*[fetch_one(s) for s in filtered])
    finally:
        await crawler.aclose()

    _mark_closed_jobs(site)
    return fetched, new_count, errors


def _mark_closed_jobs(site: str) -> int:
    """마감 조건을 만족하는 공고를 is_closed=True로 마킹한다.

    두 조건 중 하나를 충족하면 마감 처리:
    - deadline_at이 설정됐고 now를 지난 경우 (마감일 경과)
    - deadline_at이 없고 last_seen_at이 14일 이상 갱신되지 않은 경우
      (마감일 정보가 없는 사이트에서 limit 제한 등으로 누락 시 false positive 방지)

    deadline_at이 미래로 설정된 공고는 last_seen_at 조건으로는 닫지 않는다.
    """
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    threshold = now - timedelta(days=14)
    with session_scope() as session:
        result = session.execute(
            update(Job)
            .where(
                Job.site == site,
                Job.is_closed == False,  # noqa: E712
                or_(
                    and_(Job.deadline_at.isnot(None), Job.deadline_at < now),
                    and_(Job.deadline_at.is_(None), Job.last_seen_at < threshold),
                ),
            )
            .values(is_closed=True)
        )
        count = result.rowcount
    if count:
        logger.info(f"[{site}] marked {count} job(s) as closed")
    return count


def _upsert_job(detail: JobDetail) -> bool:
    s = detail.summary
    with session_scope() as session:
        existing = session.execute(
            select(Job).where(Job.site == s.site, Job.external_id == s.external_id)
        ).scalar_one_or_none()
        if existing:
            existing.last_seen_at = datetime.utcnow()
            existing.title = s.title
            existing.company = s.company
            existing.location = s.location
            existing.body_text = detail.body_text
            existing.experience = detail.experience
            existing.salary = detail.salary
            existing.tech_stack = detail.tech_stack or None
            return False
        job = Job(
            site=s.site,
            external_id=s.external_id,
            url=s.url,
            title=s.title,
            company=s.company,
            location=s.location,
            posted_at=s.posted_at,
            experience=detail.experience,
            employment_type=detail.employment_type,
            salary=detail.salary,
            tech_stack=detail.tech_stack or None,
            body_text=detail.body_text,
            body_raw=detail.body_raw,
            deadline_at=detail.deadline_at,
        )
        session.add(job)
        return True


async def run(sites: list[str], max_results: int) -> None:
    for site in sites:
        run_id: int | None = None
        with session_scope() as session:
            run_row = CrawlRun(site=site)
            session.add(run_row)
            session.flush()
            run_id = run_row.id

        fetched, new_count, errors = 0, 0, []
        status = "ok"
        try:
            fetched, new_count, errors = await crawl_site(site, max_results)
        except Exception as e:  # noqa: BLE001
            status = "error"
            errors.append(str(e))
            logger.opt(exception=e).error(f"[{site}] pipeline failed")

        with session_scope() as session:
            run_row = session.get(CrawlRun, run_id)
            if run_row is not None:
                run_row.finished_at = datetime.utcnow()
                run_row.fetched = fetched
                run_row.new_jobs = new_count
                run_row.status = status if not errors else ("ok" if status == "ok" else "error")
                run_row.errors = errors or None

        logger.info(
            f"[{site}] done fetched={fetched} new={new_count} errors={len(errors)}"
        )


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="job_crawler pipeline")
    parser.add_argument("--site", action="append", help="사이트 이름 (반복 가능)")
    parser.add_argument("--limit", type=int, default=300, help="키워드당 최대 수집 건수")
    args = parser.parse_args()

    sites = args.site or ACTIVE_SITES
    asyncio.run(run(sites, args.limit))


if __name__ == "__main__":
    main()

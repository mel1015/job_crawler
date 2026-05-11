"""리멤버 커리어 크롤러.

POST https://career-api.rememberapp.co.kr/job_postings/search
인증 불필요. search.keywords 배열로 키워드 필터링.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseCrawler, JobDetail, JobSummary, SearchCriteria

SEARCH_URL = "https://career-api.rememberapp.co.kr/job_postings/search"
DETAIL_URL = "https://career-api.rememberapp.co.kr/job_postings/{job_id}"
JOB_URL = "https://career.rememberapp.co.kr/job/postings/{job_id}"


class RememberCrawler(BaseCrawler):
    site_name = "remember"
    PAGE_SIZE = 50

    def __init__(self, user_agent: str, request_delay_sec: float = 1.5):
        super().__init__(request_delay_sec=request_delay_sec)
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://career.rememberapp.co.kr",
                "Referer": "https://career.rememberapp.co.kr/",
            },
            timeout=20.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self._throttle()
        r = await self._client.post(url, json=payload)
        r.raise_for_status()
        return r.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def _get_json(self, url: str) -> dict[str, Any]:
        await self._throttle()
        r = await self._client.get(url)
        r.raise_for_status()
        return r.json()

    async def search(self, criteria: SearchCriteria) -> list[JobSummary]:
        search_body: dict[str, Any] = {
            "include_applied_job_posting": False,
        }
        if criteria.keywords:
            search_body["keywords"] = criteria.keywords
        if criteria.years_min is not None:
            search_body["min_experience"] = criteria.years_min
        if criteria.years_max is not None and criteria.years_max < 99:
            search_body["max_experience"] = criteria.years_max

        summaries: list[JobSummary] = []
        page = 1
        while len(summaries) < criteria.max_results:
            payload = {
                "sort": "starts_at_desc",
                "search": search_body,
                "page": page,
                "per": self.PAGE_SIZE,
            }
            try:
                data = await self._post_json(SEARCH_URL, payload)
            except httpx.HTTPError as e:
                logger.error(f"remember search failed at page={page}: {e}")
                break

            items = data.get("data") or []
            if not items:
                break
            for item in items:
                try:
                    summaries.append(self._parse_summary(item))
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"remember summary parse skipped: {e}")

            meta = data.get("meta") or {}
            total_pages = meta.get("total_pages") or meta.get("total_page") or 1
            if page >= total_pages or len(items) < self.PAGE_SIZE:
                break
            page += 1

        return summaries[: criteria.max_results]

    def _parse_summary(self, item: dict[str, Any]) -> JobSummary:
        job_id = str(item["id"])
        org = item.get("organization") or {}
        company = org.get("name") or "알수없음"
        addresses = item.get("addresses") or []
        location = None
        if addresses:
            addr = addresses[0]
            loc_parts = [addr.get("address_level1"), addr.get("address_level2")]
            location = " ".join(p for p in loc_parts if p) or None
        posted_raw = item.get("starts_at")
        posted_at = _parse_dt(posted_raw)
        return JobSummary(
            site=self.site_name,
            external_id=job_id,
            url=JOB_URL.format(job_id=job_id),
            title=item.get("title") or "제목없음",
            company=company,
            location=location,
            posted_at=posted_at,
        )

    async def fetch_detail(self, summary: JobSummary) -> JobDetail:
        try:
            data = await self._get_json(DETAIL_URL.format(job_id=summary.external_id))
        except httpx.HTTPError as e:
            logger.error(f"remember detail failed {summary.external_id}: {e}")
            return JobDetail(summary=summary, body_text="")

        item = data.get("data") or {}
        parts = [
            item.get("job_description"),
            "\n[자격 요건]\n" + item["qualifications"] if item.get("qualifications") else None,
            "\n[우대 사항]\n" + item["preferred_qualifications"] if item.get("preferred_qualifications") else None,
        ]
        body_text = "\n".join(p for p in parts if p)

        return JobDetail(
            summary=summary,
            body_text=body_text[:20000],
            body_raw=str(data)[:50000],
            experience=_fmt_years(item.get("min_experience"), item.get("max_experience")),
            deadline_at=_parse_dt(item.get("ends_at")),
        )


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except ValueError:
            continue
    return None


def _fmt_years(lo: Any, hi: Any) -> str | None:
    if lo is None and hi is None:
        return None
    if lo == 0 and (hi is None or hi == 0):
        return "신입"
    if hi is None or hi == 0:
        return f"{lo}년 이상"
    return f"{lo}~{hi}년"

"""원티드 크롤러.

공개 JSON API를 사용. 엔드포인트는 원티드 프론트에서 관찰되는 v4 경로를 따름.
스키마 변경에 대비해 파싱은 관대하게(.get/try) 처리.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseCrawler, JobDetail, JobSummary, SearchCriteria

SEARCH_URL = "https://www.wanted.co.kr/api/v4/jobs"
DETAIL_URL = "https://www.wanted.co.kr/api/v4/jobs/{job_id}"

# 원티드 지역 코드 매핑 (주요 지역만)
LOCATION_MAP = {
    "서울": "seoul.all",
    "경기": "gyeonggi.all",
    "판교": "gyeonggi.seongnam",
    "부산": "busan.all",
    "전국": "all",
}

class WantedCrawler(BaseCrawler):
    site_name = "wanted"

    def __init__(self, user_agent: str, request_delay_sec: float = 1.0):
        super().__init__(request_delay_sec=request_delay_sec)
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Referer": "https://www.wanted.co.kr/",
            },
            timeout=20.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        await self._throttle()
        r = await self._client.get(url, params=params)
        r.raise_for_status()
        return r.json()

    def _locations_param(self, regions: list[str]) -> list[str]:
        codes = []
        for r in regions:
            code = LOCATION_MAP.get(r)
            if code:
                codes.append(code)
        return codes or ["all"]

    PAGE_SIZE = 100

    async def search(self, criteria: SearchCriteria) -> list[JobSummary]:
        base_params: list[tuple[str, Any]] = [
            ("country", "kr"),
            ("job_sort", "job.latest_order"),
        ]
        for loc in self._locations_param(criteria.regions):
            base_params.append(("locations", loc))
        if criteria.years_min is not None:
            base_params.append(("years", criteria.years_min))
        if criteria.years_max is not None:
            base_params.append(("years", criteria.years_max))
        if criteria.keywords:
            base_params.append(("query", " ".join(criteria.keywords)))

        summaries: list[JobSummary] = []
        offset = 0
        while len(summaries) < criteria.max_results:
            params = base_params + [
                ("limit", self.PAGE_SIZE),
                ("offset", offset),
            ]
            try:
                data = await self._get_json(SEARCH_URL, params=params)
            except httpx.HTTPError as e:
                logger.error(f"wanted search failed at offset={offset}: {e}")
                break

            items = data.get("data") or data.get("jobs") or []
            if not items:
                break
            for it in items:
                try:
                    summary = self._parse_summary(it)
                    if not self._match_experience(it, criteria):
                        continue
                    summaries.append(summary)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"wanted summary parse skipped: {e}")
            if len(items) < self.PAGE_SIZE:
                break
            offset += self.PAGE_SIZE

        return summaries[: criteria.max_results]

    def _match_experience(self, item: dict[str, Any], criteria: SearchCriteria) -> bool:
        """공고의 연차 범위가 희망 범위와 겹치면 True. 미표기는 통과."""
        if criteria.years_min is None and criteria.years_max is None:
            return True
        lo = item.get("annual_from")
        hi = item.get("annual_to")
        if lo is None and hi is None:
            return True
        job_lo = lo if lo is not None else 0
        job_hi = hi if hi is not None else 99
        want_lo = criteria.years_min if criteria.years_min is not None else 0
        want_hi = criteria.years_max if criteria.years_max is not None else 99
        return not (job_hi < want_lo or job_lo > want_hi)

    def _parse_summary(self, it: dict[str, Any]) -> JobSummary:
        job_id = str(it.get("id") or it.get("job_id"))
        title = (
            it.get("position")
            or it.get("name")
            or it.get("title")
            or "제목없음"
        )
        company = (
            (it.get("company") or {}).get("name")
            if isinstance(it.get("company"), dict)
            else it.get("company_name")
        ) or "알수없음"
        address = it.get("address") or {}
        location = (
            address.get("location")
            if isinstance(address, dict)
            else None
        ) or it.get("location")
        posted_raw = it.get("due_time") or it.get("confirmed_at") or it.get("published_at")
        posted_at = _parse_dt(posted_raw)
        url = f"https://www.wanted.co.kr/wd/{job_id}"
        return JobSummary(
            site=self.site_name,
            external_id=job_id,
            url=url,
            title=title,
            company=company,
            location=location,
            posted_at=posted_at,
        )

    async def fetch_detail(self, summary: JobSummary) -> JobDetail:
        try:
            data = await self._get_json(DETAIL_URL.format(job_id=summary.external_id))
        except httpx.HTTPError as e:
            logger.error(f"wanted detail failed {summary.external_id}: {e}")
            return JobDetail(summary=summary, body_text="")

        job = data.get("job") or data.get("data", {}).get("job") or data
        detail = job.get("detail") or {}
        body_parts = [
            detail.get("intro"),
            "\n[주요 업무]\n" + (detail.get("main_tasks") or ""),
            "\n[자격 요건]\n" + (detail.get("requirements") or ""),
            "\n[우대 사항]\n" + (detail.get("preferred_points") or ""),
            "\n[혜택 및 복지]\n" + (detail.get("benefits") or ""),
        ]
        body_text = "\n".join([p for p in body_parts if p])
        skills = job.get("skill_tags") or []
        tech_stack = [s.get("title") if isinstance(s, dict) else str(s) for s in skills]

        return JobDetail(
            summary=summary,
            body_text=body_text,
            body_raw=str(data)[:50000],
            experience=_fmt_years(job.get("annual_from"), job.get("annual_to")),
            employment_type=job.get("employment_type"),
            salary=None,  # 원티드는 원문에 보상금 표기만
            tech_stack=[t for t in tech_stack if t],
            deadline_at=_parse_dt(job.get("due_time")),
        )


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt)
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

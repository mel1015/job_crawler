"""점핏(Jumpit) 크롤러. saramin 계열 개발자 특화 플랫폼.

공개 JSON API 사용. 엔드포인트: https://api.jumpit.co.kr/api/positions
상세: https://api.jumpit.co.kr/api/position/{id}
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseCrawler, JobDetail, JobSummary, SearchCriteria

SEARCH_URL = "https://api.jumpit.co.kr/api/positions"
DETAIL_URL = "https://api.jumpit.co.kr/api/position/{job_id}"
JOB_URL = "https://jumpit.saramin.co.kr/position/{job_id}"

LOCATION_MAP = {
    "서울": "서울",
    "경기": "경기",
    "판교": "경기",
    "부산": "부산",
}


class JumpitCrawler(BaseCrawler):
    site_name = "jumpit"
    PAGE_SIZE = 100

    def __init__(self, user_agent: str, request_delay_sec: float = 1.5):
        super().__init__(request_delay_sec=request_delay_sec)
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Referer": "https://jumpit.saramin.co.kr/",
            },
            timeout=20.0,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        await self._throttle()
        r = await self._client.get(url, params=params)
        r.raise_for_status()
        return r.json()

    def _careers_filter(self, criteria: SearchCriteria) -> dict[str, Any]:
        params: dict[str, Any] = {
            "sort": "reg_dt",
            "size": self.PAGE_SIZE,
        }
        if criteria.keywords:
            params["keyword"] = " ".join(criteria.keywords)
        if criteria.years_min is not None:
            params["minCareer"] = criteria.years_min
        if criteria.years_max is not None and criteria.years_max < 99:
            params["maxCareer"] = criteria.years_max
        # 지역 필터: 단일 값만 지원 (서울 우선)
        for region in criteria.regions:
            mapped = LOCATION_MAP.get(region)
            if mapped:
                params["location"] = mapped
                break
        return params

    async def search(self, criteria: SearchCriteria) -> list[JobSummary]:
        base_params = self._careers_filter(criteria)
        summaries: list[JobSummary] = []
        page = 1
        while len(summaries) < criteria.max_results:
            params = {**base_params, "page": page}
            try:
                data = await self._get_json(SEARCH_URL, params=params)
            except httpx.HTTPError as e:
                logger.error(f"jumpit search failed at page={page}: {e}")
                break

            result = data.get("result") or {}
            positions = result.get("positions") or []
            if not positions:
                break
            for pos in positions:
                try:
                    summaries.append(self._parse_summary(pos))
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"jumpit summary parse skipped: {e}")
            if len(positions) < self.PAGE_SIZE:
                break
            page += 1

        return summaries[: criteria.max_results]

    def _parse_summary(self, pos: dict[str, Any]) -> JobSummary:
        job_id = str(pos["id"])
        locations = pos.get("locations") or []
        location = locations[0] if locations else None
        closed_raw = pos.get("closedAt")
        posted_at = _parse_dt(closed_raw)
        return JobSummary(
            site=self.site_name,
            external_id=job_id,
            url=JOB_URL.format(job_id=job_id),
            title=re.sub(r"<[^>]+>", "", pos.get("title") or "제목없음"),
            company=pos.get("companyName") or "알수없음",
            location=location,
            posted_at=posted_at,
        )

    async def fetch_detail(self, summary: JobSummary) -> JobDetail:
        try:
            data = await self._get_json(DETAIL_URL.format(job_id=summary.external_id))
        except httpx.HTTPError as e:
            logger.error(f"jumpit detail failed {summary.external_id}: {e}")
            return JobDetail(summary=summary, body_text="")

        result = data.get("result") or {}
        parts = [
            result.get("responsibility"),
            "\n[자격 요건]\n" + (result.get("qualifications") or "") if result.get("qualifications") else None,
            "\n[우대 사항]\n" + (result.get("preferredRequirements") or "") if result.get("preferredRequirements") else None,
            "\n[복리후생]\n" + (result.get("welfares") or "") if result.get("welfares") else None,
        ]
        body_text = "\n".join(p for p in parts if p)
        raw_stacks = result.get("techStacks") or []
        tech_stack = [
            t["stack"] if isinstance(t, dict) else str(t)
            for t in raw_stacks if t
        ]
        career_lo = result.get("minCareer")
        career_hi = result.get("maxCareer")
        closed_raw = result.get("closedAt")
        deadline_at = _parse_dt(closed_raw)

        return JobDetail(
            summary=summary,
            body_text=body_text[:20000],
            body_raw=str(data)[:50000],
            experience=_fmt_years(career_lo, career_hi),
            tech_stack=[t for t in tech_stack if t],
            deadline_at=deadline_at,
        )


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).split("+")[0].split("Z")[0], fmt)
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

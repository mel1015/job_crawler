"""캐치(catch.co.kr) 크롤러. 대기업/공기업 채용 특화 플랫폼.

공개 JSON API 사용. Playwright 불필요.
Depth/AssignedTaskNameListString 필드로 IT 직군 1차 필터링.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseCrawler, JobDetail, JobSummary, SearchCriteria

SEARCH_URL = "https://www.catch.co.kr/api/v1.0/recruit/information/getRecruitList"
DETAIL_BASE = "https://www.catch.co.kr/NCS/RecruitInfoDetails"
DETAIL_API = "https://www.catch.co.kr/controls/recruitDetail/{rid}"

_IT_KEYWORDS = (
    "웹개발", "소프트웨어", "네트워크/서버", "데이터분석", "IT기획", "모바일앱",
    "개발", "developer", "engineer", "backend", "frontend", "서버", "데이터",
    "devops", "sre", "클라우드", "cloud", "dba", "qa", "보안", "security",
)


class CatchCrawler(BaseCrawler):
    site_name = "catch"

    def __init__(self, user_agent: str, request_delay_sec: float = 1.0):
        super().__init__(request_delay_sec=request_delay_sec)
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Referer": "https://www.catch.co.kr/",
            },
            timeout=15.0,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    PAGE_SIZE = 30

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def _get_json(self, params: dict[str, Any]) -> dict[str, Any]:
        await self._throttle()
        r = await self._client.get(SEARCH_URL, params=params)
        r.raise_for_status()
        return r.json()

    async def search(self, criteria: SearchCriteria) -> list[JobSummary]:
        keyword = " ".join(criteria.keywords) if criteria.keywords else "개발자"
        summaries: list[JobSummary] = []
        seen: set[str] = set()
        page = 1
        while len(summaries) < criteria.max_results:
            try:
                data = await self._get_json({
                    "Keyword": keyword,
                    "Sort": "0",
                    "curpage": str(page),
                    "pageSize": str(self.PAGE_SIZE),
                    "onRecruitYN": "Y",
                })
            except httpx.HTTPError as e:
                logger.error(f"catch search failed at page={page}: {e}")
                break
            items = data.get("recruitData") or []
            if not items:
                break
            for it in items:
                rid = str(it.get("RecruitID") or "")
                if not rid or rid in seen:
                    continue
                if not self._is_it_job(it):
                    continue
                seen.add(rid)
                summaries.append(self._parse_summary(it))
            if len(items) < self.PAGE_SIZE:
                break
            page += 1
        return summaries[: criteria.max_results]

    def _is_it_job(self, it: dict[str, Any]) -> bool:
        depth = it.get("Depth") or ""
        task = it.get("AssignedTaskNameListString") or ""
        title = it.get("RecruitTitle") or ""
        combined = f"{depth} {task} {title}".lower()
        return any(kw.lower() in combined for kw in _IT_KEYWORDS)

    def _parse_summary(self, it: dict[str, Any]) -> JobSummary:
        rid = str(it.get("RecruitID"))
        experience_parts = [it.get("ExperienceText"), it.get("ExperienceRange")]
        experience = " ".join(p for p in experience_parts if p) or None
        return JobSummary(
            site=self.site_name,
            external_id=rid,
            url=f"{DETAIL_BASE}/{rid}",
            title=it.get("RecruitTitle") or "제목없음",
            company=it.get("CompName") or "알수없음",
            location=it.get("WorkArea"),
            posted_at=_parse_dt(it.get("ApplyStartDatetime")),
        )

    async def fetch_detail(self, summary: JobSummary) -> JobDetail:
        url = DETAIL_API.format(rid=summary.external_id)
        try:
            await self._throttle()
            r = await self._client.get(url)
            r.raise_for_status()
            body_text = _extract_body(r.text)
        except httpx.HTTPError as e:
            logger.error(f"catch detail failed {summary.external_id}: {e}")
            return JobDetail(summary=summary, body_text="")
        return JobDetail(summary=summary, body_text=body_text[:20000])


def _extract_body(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script, style"):
        tag.decompose()
    for sel in (".btn_wrap", ".util_area", ".apply_area", "#header", "#footer", ".gnb"):
        for tag in soup.select(sel):
            tag.decompose()
    main = soup.select_one(".recruit_detail") or soup.select_one(".wrap_recruit_cont") or soup.body
    text = main.get_text("\n", strip=True) if main else soup.get_text("\n", strip=True)
    if not text:
        # 이미지로만 JD를 올린 공고 — 텍스트 추출 불가
        return "(이미지 공고 — 원문 링크에서 확인)"
    return text


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None

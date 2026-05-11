"""사람인 크롤러. Playwright는 핑거프린팅으로 차단되어 httpx로 HTML 직접 조회.

상세 페이지도 server-rendered 되므로 httpx로 조회. 실패 시 빈 본문.
"""
from __future__ import annotations

import re
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseCrawler, JobDetail, JobSummary, SearchCriteria

SEARCH_BASE = "https://www.saramin.co.kr/zf_user/search/recruit"
REGION_CODES = {
    "서울": "101000",
    "경기": "102000",
    "판교": "102000",
    "부산": "106000",
}

_SELECTORS = {
    "item": "div.item_recruit",
    "title_link": "h2.job_tit a",
    "company": "strong.corp_name a",
    "conditions": "div.job_condition span",
    "date": "span.job_day",
}


class SaraminCrawler(BaseCrawler):
    site_name = "saramin"

    def __init__(self, user_agent: str, request_delay_sec: float = 2.0):
        super().__init__(request_delay_sec=request_delay_sec)
        self._meta: dict[str, dict[str, str | None]] = {}
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "Referer": "https://www.saramin.co.kr/",
            },
            timeout=20.0,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def _get_html(self, url: str) -> str:
        await self._throttle()
        r = await self._client.get(url)
        r.raise_for_status()
        return r.text

    PAGE_SIZE = 50

    async def search(self, criteria: SearchCriteria) -> list[JobSummary]:
        loc_mcd = ",".join(
            {REGION_CODES[r] for r in criteria.regions if r in REGION_CODES}
        )
        base_params: dict[str, str] = {
            "searchType": "search",
            "searchword": " ".join(criteria.keywords) if criteria.keywords else "백엔드",
            "recruitSort": "reg_dt",
            "recruitPageCount": str(self.PAGE_SIZE),
        }
        if loc_mcd:
            base_params["loc_mcd"] = loc_mcd
        if criteria.years_min is not None and criteria.years_max is not None:
            base_params["exp_cd"] = "2"
            base_params["exp_min"] = str(criteria.years_min)
            base_params["exp_max"] = str(criteria.years_max)

        summaries: list[JobSummary] = []
        page = 1
        while len(summaries) < criteria.max_results:
            params = {**base_params, "recruitPage": str(page)}
            url = f"{SEARCH_BASE}?{urlencode(params)}"
            try:
                html = await self._get_html(url)
            except httpx.HTTPError as e:
                logger.error(f"saramin search failed at page={page}: {e}")
                break
            items = self._parse_list(html)
            if not items:
                break
            summaries.extend(items)
            if len(items) < self.PAGE_SIZE:
                break
            page += 1

        return summaries[: criteria.max_results]

    def _parse_list(self, html: str) -> list[JobSummary]:
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(_SELECTORS["item"])
        summaries: list[JobSummary] = []
        for it in items:
            a = it.select_one(_SELECTORS["title_link"])
            company_el = it.select_one(_SELECTORS["company"])
            if not a or not company_el:
                continue
            href = a.get("href") or ""
            title = a.get("title") or a.get_text(strip=True)
            m = re.search(r"rec_idx=(\d+)", href)
            external_id = m.group(1) if m else (it.get("value") or href)
            full_url = (
                href if href.startswith("http") else f"https://www.saramin.co.kr{href}"
            )
            conditions = [c.get_text(" ", strip=True) for c in it.select(_SELECTORS["conditions"])]
            location = conditions[0] if conditions else None
            experience = next((c for c in conditions if "경력" in c or "신입" in c), None)
            employment = next(
                (c for c in conditions if c in {"정규직", "계약직", "인턴", "파견직", "프리랜서"}),
                None,
            )
            self._meta[str(external_id)] = {
                "experience": experience,
                "employment_type": employment,
            }
            summaries.append(
                JobSummary(
                    site=self.site_name,
                    external_id=str(external_id),
                    url=full_url,
                    title=title,
                    company=company_el.get_text(strip=True),
                    location=location,
                )
            )
        return summaries

    async def fetch_detail(self, summary: JobSummary) -> JobDetail:
        view_url = re.sub(
            r"/zf_user/jobs/relay/view", "/zf_user/jobs/view", summary.url
        )
        try:
            html = await self._get_html(view_url)
        except httpx.HTTPError as e:
            logger.error(f"saramin detail failed {summary.external_id}: {e}")
            return JobDetail(summary=summary, body_text="")

        body_text = self._extract_body(html)
        meta = self._meta.get(summary.external_id, {})
        return JobDetail(
            summary=summary,
            body_text=body_text[:20000],
            body_raw=html[:50000],
            experience=meta.get("experience"),
            employment_type=meta.get("employment_type"),
        )

    def _extract_body(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        content_keywords = ("주요업무", "자격요건", "모집분야", "담당업무", "지원자격", "우대사항")
        for jv in soup.select(".jv_cont"):
            text = jv.get_text(" ", strip=True)
            if any(k in text for k in content_keywords):
                return jv.get_text("\n", strip=True)
        wrap = soup.select_one(".wrap_jv_cont")
        if wrap:
            for tag in wrap.select("script, style, .jv_header, .jv_util, .btn_wrap"):
                tag.decompose()
            return wrap.get_text("\n", strip=True)
        return soup.get_text("\n", strip=True)

"""잡코리아 크롤러. 2026 개편 후 Tailwind 기반 SSR. httpx로 직접 조회.

카드 셀렉터: `div.shadow-list` 중 GI_Read 링크를 포함하는 요소.
카드 내부 GI_Read 앵커는 보통 3개(스크랩/제목/회사) 순서로 렌더링.
"""
from __future__ import annotations

import re
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseCrawler, JobDetail, JobSummary, SearchCriteria

SEARCH_BASE = "https://www.jobkorea.co.kr/Search/"

REGION_CODES = {
    "서울": "I000",
    "경기": "I100",
    "판교": "I100",
    "부산": "I200",
}


class JobkoreaCrawler(BaseCrawler):
    site_name = "jobkorea"

    _REGION_WORDS = (
        "서울", "경기", "인천", "부산", "대구", "대전", "광주", "울산",
        "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
        "해외", "전국",
    )

    def __init__(self, user_agent: str, request_delay_sec: float = 2.0):
        super().__init__(request_delay_sec=request_delay_sec)
        self._meta: dict[str, dict[str, str | None]] = {}
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "Referer": "https://www.jobkorea.co.kr/",
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

    async def search(self, criteria: SearchCriteria) -> list[JobSummary]:
        params = {
            "stext": " ".join(criteria.keywords) if criteria.keywords else "백엔드",
            "tabType": "recruit",
        }
        local = ",".join(
            {REGION_CODES[r] for r in criteria.regions if r in REGION_CODES}
        )
        if local:
            params["local"] = local
        if criteria.years_min is not None and criteria.years_max is not None:
            params["careerMin"] = str(criteria.years_min)
            params["careerMax"] = str(criteria.years_max)
            params["careerType"] = "1"
        url = f"{SEARCH_BASE}?{urlencode(params)}"

        try:
            html = await self._get_html(url)
        except httpx.HTTPError as e:
            logger.error(f"jobkorea search failed: {e}")
            return []

        return self._parse_list(html)[: criteria.limit]

    def _parse_list(self, html: str) -> list[JobSummary]:
        soup = BeautifulSoup(html, "html.parser")
        cards = [c for c in soup.select("div.shadow-list") if c.select_one("a[href*=GI_Read]")]
        summaries: list[JobSummary] = []
        for c in cards:
            anchors = c.select("a[href*=GI_Read]")
            title_a = next(
                (a for a in anchors if a.get_text(strip=True)), None
            )
            company_a = next(
                (a for a in anchors if a is not title_a and a.get_text(strip=True)),
                None,
            )
            if not title_a:
                continue
            href = title_a.get("href") or ""
            title = title_a.get_text(" ", strip=True)
            if not title:
                continue
            m = re.search(r"/GI_Read/(\d+)", href)
            external_id = m.group(1) if m else href
            full_url = href if href.startswith("http") else f"https://www.jobkorea.co.kr{href}"
            company = company_a.get_text(strip=True) if company_a else "알수없음"
            card_text = c.get_text(" ", strip=True)
            location = self._extract_location(card_text)
            experience = self._extract_experience(card_text)
            self._meta[str(external_id)] = {"experience": experience}
            summaries.append(
                JobSummary(
                    site=self.site_name,
                    external_id=str(external_id),
                    url=full_url,
                    title=title,
                    company=company,
                    location=location,
                )
            )
        return summaries

    def _extract_location(self, text: str) -> str | None:
        for w in self._REGION_WORDS:
            idx = text.find(w)
            if idx == -1:
                continue
            tail = text[idx : idx + 20].split()
            return " ".join(tail[:2]) if len(tail) >= 2 else tail[0] if tail else w
        return None

    def _extract_experience(self, text: str) -> str | None:
        m = re.search(r"(신입[·~\-]?경력|경력무관|경력\s*\d+[~\-]?\d*년?|신입|경력)", text)
        return m.group(1) if m else None

    async def fetch_detail(self, summary: JobSummary) -> JobDetail:
        try:
            html = await self._get_html(summary.url)
        except httpx.HTTPError as e:
            logger.error(f"jobkorea detail failed {summary.external_id}: {e}")
            return JobDetail(summary=summary, body_text="")
        body_text = self._extract_body(html)
        description_text = await self._fetch_description(html, summary.external_id)
        if description_text:
            body_text = f"{body_text}\n\n{description_text}" if body_text else description_text
        meta = self._meta.get(summary.external_id, {})
        return JobDetail(
            summary=summary,
            body_text=body_text[:20000],
            body_raw=html[:50000],
            experience=meta.get("experience"),
        )

    async def _fetch_description(self, html: str, external_id: str) -> str:
        """GI_Read SSR HTML의 Next.js 데이터에서 S3 pre-signed 상세 URL을 찾아 내용 조회."""
        m = re.search(
            r'__next_f\.push\(\[1,"(https://job-hub-files[^"]+_DESCRIPTION\.html[^"]+)"\]\)',
            html,
        )
        if not m:
            return ""
        url = re.sub(r"\\u([0-9a-fA-F]{4})", lambda x: chr(int(x.group(1), 16)), m.group(1))
        try:
            await self._throttle()
            r = await self._client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"jobkorea description fetch failed {external_id}: {e}")
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup.select("script, style"):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return "\n".join(lines)

    def _extract_body(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        content = None
        for d in soup.find_all("div"):
            cls = " ".join(d.get("class", []))
            if "grid-area:content" in cls:
                content = d
                break
        if not content:
            content = soup
        for tag in content.select("aside, nav, footer, script, style, header"):
            tag.decompose()
        text = content.get_text("\n", strip=True)
        lines = text.split("\n")
        start = 0
        for i, line in enumerate(lines):
            if "모집요강" in line or "모집분야" in line:
                start = i
                break
        end = len(lines)
        stop_markers = ("접수기간", "궁금해요", "남은기간", "이 공고를", "관련 채용", "추천공고", "기업 정보", "기업정보 더보기")
        for i, line in enumerate(lines):
            if i > start + 2 and any(m in line for m in stop_markers):
                end = i
                break
        clean_lines: list[str] = []
        skip_phrases = (
            "로그인", "적합도 체크", "핵심 역량", "회사에서 중요하게", "AI추천공고",
            "지도보기", "인근지하철", "TOP", "궁금해요",
            "나와 맞는지 알아보기", "적합도를 비교",
            "이 기업과 나의", "핵심역량",
        )
        for line in lines[start:end]:
            if any(p in line for p in skip_phrases):
                continue
            clean_lines.append(line)
        return "\n".join(clean_lines)

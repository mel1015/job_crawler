"""사람인 크롤러. Playwright는 핑거프린팅으로 차단되어 httpx로 HTML 직접 조회.

상세 페이지도 server-rendered 되므로 httpx로 조회. 실패 시 빈 본문.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import IMAGE_ONLY_PLACEHOLDER, BaseCrawler, JobDetail, JobSummary, SearchCriteria

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


# 상세 JD 텍스트가 이보다 짧으면("상세요강" 제목만 있는 경우) 이미지 공고로 본다
DETAIL_MIN_CHARS = 50
# 공고 본문 이미지는 pds.saramin.co.kr이나 외부 이미지 프록시
# (www.saraminimage.co.kr?url=...)에 있고,
# 템플릿 장식은 static.saraminimage.co.kr, 워터마크는 파일명에 watermark가 들어간다 (2026-11 확인)
_DECORATIVE_IMG = re.compile(r"static\.saraminimage\.co\.kr|watermark", re.I)


def _detail_image_urls(detail) -> list[str]:
    urls: list[str] = []
    for img in detail.select("img[src]"):
        src = img["src"].strip()
        if not src or src.startswith("data:") or _DECORATIVE_IMG.search(src):
            continue
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = "https://www.saramin.co.kr" + src
        if src not in urls:
            urls.append(src)
    return urls


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

        soup = BeautifulSoup(html, "html.parser")
        meta = self._meta.get(summary.external_id, {})
        body_text, image_urls = self._extract_body(soup)
        return JobDetail(
            summary=summary,
            body_text=body_text[:20000],
            image_urls=image_urls,
            body_raw=html[:50000],
            experience=meta.get("experience"),
            employment_type=meta.get("employment_type"),
            deadline_at=self._extract_deadline(soup),
            company_type_signals=self._extract_company_type_signals(soup),
            is_closed_hint=soup.select_one(".sri_btn_expired_apply") is not None,
        )

    def _extract_company_type_signals(self, soup: BeautifulSoup) -> dict:
        """'기업형태' dt/dd 블록에서 태그 목록 추출 (예: 코스닥, 중견기업, 외부감사법인)."""
        for dt in soup.find_all("dt"):
            if dt.get_text(strip=True) != "기업형태":
                continue
            dd = dt.find_next_sibling("dd")
            if not dd:
                continue
            raw = dd.get("title") or dd.get_text(strip=True)
            tags = [t.strip() for t in raw.split(",") if t.strip()]
            return {"company_type_tags": tags}
        return {}

    _DEADLINE_FORMATS = ("%Y.%m.%d %H:%M", "%Y.%m.%d")
    _DEADLINE_RE = re.compile(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})")

    def _extract_deadline(self, soup: BeautifulSoup) -> datetime | None:
        # 1) dt.end → dd 구조 (기존)
        dt_end = soup.select_one("dt.end")
        if dt_end:
            dd = dt_end.find_next_sibling("dd")
            if dd:
                text = dd.get_text(strip=True)
                for fmt in self._DEADLINE_FORMATS:
                    try:
                        return datetime.strptime(text, fmt)
                    except ValueError:
                        pass

        # 2) 접수기간 텍스트 블록에서 마감 날짜 추출
        for el in soup.select("dt, th, strong, span.tit"):
            if "마감" in el.get_text() or "접수기간" in el.get_text():
                sibling = el.find_next_sibling() or el.parent
                if sibling:
                    text = sibling.get_text(" ", strip=True)
                    m = self._DEADLINE_RE.search(text)
                    if m:
                        try:
                            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                        except ValueError:
                            pass
        return None

    def _extract_body(self, soup: BeautifulSoup) -> tuple[str, list[str]]:
        """(본문, 이미지 URL)을 돌려준다.

        상세 JD는 `.jv_cont.jv_detail`에 있다. 그 앞의 "핵심 정보" 요약(`.jv_summary`)에도
        "자격요건 상세보기", "우대사항 상세보기" 버튼 문구가 있어서,
        키워드가 든 첫 `.jv_cont`를 고르던 예전 방식은 요약만 저장하고 JD를 버렸다
        (2026-11 열린 사람인 공고 1,172건 중 598건).
        요약(경력/학력/근무형태)은 채점에 쓰이므로 JD 앞에 함께 저장한다.
        """
        summary = soup.select_one(".jv_cont.jv_summary")
        # 마감 공고는 "마감 안내" 블록(.jv_detail.expired)이 JD 블록 앞에 온다
        detail = soup.select_one(".jv_cont.jv_detail:not(.expired)")
        if detail:
            for tag in detail.select("script, style"):
                tag.decompose()
            parts = [summary.get_text("\n", strip=True)] if summary else []
            detail_text = detail.get_text("\n", strip=True)
            if len(detail_text.replace("상세요강", "").strip()) >= DETAIL_MIN_CHARS:
                parts.append(detail_text)
                return "\n".join(parts), []
            # 본문이 이미지로만 된 공고: catch와 같은 자리표시 문구를 넣어
            # 이미지 공고로 채점되게 한다
            images = _detail_image_urls(detail)
            if images:
                parts.append(IMAGE_ONLY_PLACEHOLDER)
                return "\n".join(parts), images
        content_keywords = ("주요업무", "자격요건", "모집분야", "담당업무", "지원자격", "우대사항")
        for jv in soup.select(".jv_cont"):
            text = jv.get_text(" ", strip=True)
            if any(k in text for k in content_keywords):
                return jv.get_text("\n", strip=True), []
        wrap = soup.select_one(".wrap_jv_cont")
        if wrap:
            for tag in wrap.select("script, style, .jv_header, .jv_util, .btn_wrap"):
                tag.decompose()
            return wrap.get_text("\n", strip=True), []
        return soup.get_text("\n", strip=True), []

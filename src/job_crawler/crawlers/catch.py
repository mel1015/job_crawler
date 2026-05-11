"""캐치(catch.co.kr) 크롤러. 대기업/공기업 채용 특화 플랫폼.

Nuxt.js SPA라 httpx 직접 파싱 불가. Playwright로 렌더링 후 추출.
키워드 필터링이 완벽하지 않으므로 pass_filters에서 2차 필터링.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from loguru import logger

from .base import JobDetail, JobSummary, SearchCriteria
from .playwright_base import PlaywrightCrawler

SEARCH_URL = "https://www.catch.co.kr/NCS/RecruitSearch"
DETAIL_BASE = "https://www.catch.co.kr/NCS/RecruitInfoDetails"


class CatchCrawler(PlaywrightCrawler):
    site_name = "catch"

    async def search(self, criteria: SearchCriteria) -> list[JobSummary]:
        keyword = " ".join(criteria.keywords) if criteria.keywords else "개발자"
        summaries: list[JobSummary] = []
        seen: set[str] = set()

        # 단일 페이지 렌더링 (키워드 필터 불완전하여 페이지네이션 실익 낮음)
        url = f"{SEARCH_URL}?keyword={keyword}"
        try:
            page = await self._new_page()
            await page.goto(url, wait_until="networkidle", timeout=40000)
            links = await page.query_selector_all("a[href*='RecruitInfoDetails']")

            for lnk in links:
                try:
                    href = await lnk.get_attribute("href") or ""
                    job_id = self._extract_id(href)
                    if not job_id or job_id in seen:
                        continue
                    seen.add(job_id)

                    name_el = await lnk.query_selector("p.name")
                    subj_el = await lnk.query_selector("p.subj")
                    company = (await name_el.inner_text()).strip() if name_el else "알수없음"
                    title = (await subj_el.inner_text()).strip() if subj_el else "제목없음"
                    if not title or not company:
                        continue

                    summaries.append(
                        JobSummary(
                            site=self.site_name,
                            external_id=job_id,
                            url=f"{DETAIL_BASE}/{job_id}",
                            title=title,
                            company=company,
                        )
                    )
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"catch card parse skipped: {e}")

            await page.close()
        except Exception as e:  # noqa: BLE001
            logger.error(f"catch search failed: {e}")

        logger.info(f"[catch] keyword='{keyword}' collected {len(summaries)} summaries")
        return summaries[: criteria.max_results]

    def _extract_id(self, href: str) -> str | None:
        # returnUrl=/NCS/RecruitInfoDetails/{id} 패턴
        m = re.search(r"RecruitInfoDetails/(\d+)", href)
        if m:
            return m.group(1)
        # 직접 /NCS/RecruitInfoDetails/{id} 패턴
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        return_url = qs.get("returnUrl", [""])[0]
        m2 = re.search(r"RecruitInfoDetails/(\d+)", return_url)
        return m2.group(1) if m2 else None

    async def fetch_detail(self, summary: JobSummary) -> JobDetail:
        try:
            page = await self._new_page()
            await page.goto(summary.url, wait_until="networkidle", timeout=40000)
            body_text = await self._extract_body(page)
            await page.close()
        except Exception as e:  # noqa: BLE001
            logger.error(f"catch detail failed {summary.external_id}: {e}")
            return JobDetail(summary=summary, body_text="")

        return JobDetail(
            summary=summary,
            body_text=body_text[:20000],
        )

    async def _extract_body(self, page) -> str:
        # 공고 상세 내용 영역
        for sel in [".wrap_jv_cont", ".jv_cont", ".info_tab_area", ".recruit_info"]:
            el = await page.query_selector(sel)
            if el:
                return (await el.inner_text()).strip()
        # fallback: 전체 텍스트에서 불필요한 nav/header 제외
        text = await page.inner_text("body")
        return text[:5000]

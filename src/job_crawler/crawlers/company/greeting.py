"""그리팅(greetinghr) 채용 페이지 범용 크롤러.

토스·당근·배민 등 상당수 스타트업이 greetinghr.com 도메인에 채용 공고를 호스팅한다.
슬러그와 회사명을 주입해 재사용.
"""
from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from ..base import BaseCrawler, JobDetail, JobSummary, SearchCriteria

API_LIST = "https://api.greetinghr.com/v1/recruitments/public/companies/{slug}/jobs"
API_DETAIL = "https://api.greetinghr.com/v1/recruitments/public/jobs/{job_id}"
WEB_DETAIL = "https://{slug}.career.greetinghr.com/o/{job_id}"


class GreetingCrawler(BaseCrawler):
    def __init__(
        self,
        slug: str,
        company: str,
        user_agent: str,
        request_delay_sec: float = 1.0,
    ):
        super().__init__(request_delay_sec=request_delay_sec)
        self.slug = slug
        self.company = company
        self.site_name = f"greeting:{slug}"
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=20.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, criteria: SearchCriteria) -> list[JobSummary]:
        await self._throttle()
        try:
            r = await self._client.get(API_LIST.format(slug=self.slug))
            r.raise_for_status()
            data: dict[str, Any] = r.json()
        except httpx.HTTPError as e:
            logger.error(f"greeting {self.slug} search failed: {e}")
            return []

        items = data.get("data") or data.get("jobs") or []
        summaries: list[JobSummary] = []
        for it in items[: criteria.max_results]:
            job_id = str(it.get("id") or it.get("jobId"))
            title = it.get("name") or it.get("title") or "제목없음"
            location = (it.get("workplace") or {}).get("name") if isinstance(
                it.get("workplace"), dict
            ) else it.get("location")
            summaries.append(
                JobSummary(
                    site=self.site_name,
                    external_id=job_id,
                    url=WEB_DETAIL.format(slug=self.slug, job_id=job_id),
                    title=title,
                    company=self.company,
                    location=location,
                )
            )
        return summaries

    async def fetch_detail(self, summary: JobSummary) -> JobDetail:
        await self._throttle()
        try:
            r = await self._client.get(API_DETAIL.format(job_id=summary.external_id))
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as e:
            logger.error(f"greeting detail failed {summary.external_id}: {e}")
            return JobDetail(summary=summary, body_text="")

        job = data.get("data") or data
        body_parts = [
            job.get("description"),
            job.get("qualifications"),
            job.get("preferred"),
            job.get("benefits"),
        ]
        body_text = "\n\n".join(p for p in body_parts if p)
        return JobDetail(
            summary=summary,
            body_text=body_text[:20000],
            experience=job.get("experience"),
            employment_type=job.get("employmentType"),
        )

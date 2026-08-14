from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger

IMAGE_ONLY_PLACEHOLDER = "(이미지 공고 — 원문 링크에서 확인)"


@dataclass
class SearchCriteria:
    keywords: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    years_min: int | None = None
    years_max: int | None = None
    max_results: int = 300


@dataclass
class JobSummary:
    site: str
    external_id: str
    url: str
    title: str
    company: str
    location: str | None = None
    posted_at: datetime | None = None
    # 기업유형 판정 원본 신호 (사이트별 상이). 검색 목록 응답에만 있는 필드
    # (catch의 GroupName/PopularCategory 등)를 상세조회 단계까지 들고가기 위함.
    company_type_signals: dict = field(default_factory=dict)


@dataclass
class JobDetail:
    summary: JobSummary
    body_text: str
    body_raw: str | None = None
    experience: str | None = None
    employment_type: str | None = None
    salary: str | None = None
    tech_stack: list[str] = field(default_factory=list)
    deadline_at: datetime | None = None
    image_urls: list[str] = field(default_factory=list)
    # summary.company_type_signals + 상세 페이지에서 추가로 얻은 신호 병합
    company_type_signals: dict = field(default_factory=dict)
    # 사이트가 명시적으로 마감 상태를 알려줄 때만 True (wanted/remember의 status 필드,
    # saramin의 접수마감 배지 등). None이면 기존 deadline_at/last_seen_at 기반 로직을 그대로 따름.
    is_closed_hint: bool | None = None


class BaseCrawler(ABC):
    site_name: str = "base"
    robots_respected: bool = True

    def __init__(self, request_delay_sec: float = 2.0):
        self.request_delay_sec = request_delay_sec
        self._last_request_ts = 0.0

    async def _throttle(self) -> None:
        now = asyncio.get_event_loop().time()
        wait = self.request_delay_sec - (now - self._last_request_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request_ts = asyncio.get_event_loop().time()

    @abstractmethod
    async def search(self, criteria: SearchCriteria) -> list[JobSummary]:
        ...

    @abstractmethod
    async def fetch_detail(self, summary: JobSummary) -> JobDetail:
        ...

    async def aclose(self) -> None:
        """Override if resources need cleanup."""
        return None

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} site={self.site_name}>"


def log_error(site: str, stage: str, err: Exception) -> None:
    logger.opt(exception=err).error(f"[{site}] {stage} failed: {err}")

"""Playwright 기반 크롤러 공통 베이스."""
from __future__ import annotations

from abc import abstractmethod

from loguru import logger

from .base import BaseCrawler, JobDetail, JobSummary, SearchCriteria


class PlaywrightCrawler(BaseCrawler):
    """브라우저 컨텍스트를 lazy 생성하고 aclose 시 정리."""

    def __init__(self, user_agent: str, request_delay_sec: float = 2.0, headless: bool = True):
        super().__init__(request_delay_sec=request_delay_sec)
        self.user_agent = user_agent
        self.headless = headless
        self._pw = None
        self._browser = None
        self._context = None

    async def _ensure_context(self):
        if self._context is not None:
            return self._context
        from playwright.async_api import async_playwright  # lazy import

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
        )
        # 가벼운 stealth
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return self._context

    async def _new_page(self):
        ctx = await self._ensure_context()
        return await ctx.new_page()

    async def aclose(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
            if self._browser is not None:
                await self._browser.close()
            if self._pw is not None:
                await self._pw.stop()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"playwright cleanup: {e}")

    @abstractmethod
    async def search(self, criteria: SearchCriteria) -> list[JobSummary]:
        ...

    @abstractmethod
    async def fetch_detail(self, summary: JobSummary) -> JobDetail:
        ...

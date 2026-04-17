from __future__ import annotations

from ..config import get_settings
from .base import BaseCrawler
from .company.toss import TossCrawler
from .jobkorea import JobkoreaCrawler
from .saramin import SaraminCrawler
from .wanted import WantedCrawler


def build_crawler(site: str) -> BaseCrawler:
    settings = get_settings()
    if site == "wanted":
        return WantedCrawler(
            user_agent=settings.user_agent,
            request_delay_sec=settings.request_delay_sec,
        )
    if site == "saramin":
        return SaraminCrawler(
            user_agent=settings.user_agent,
            request_delay_sec=settings.request_delay_sec,
        )
    if site == "jobkorea":
        return JobkoreaCrawler(
            user_agent=settings.user_agent,
            request_delay_sec=settings.request_delay_sec,
        )
    if site == "toss":
        return TossCrawler(
            user_agent=settings.user_agent,
            request_delay_sec=settings.request_delay_sec,
        )
    raise ValueError(f"unknown site: {site}")


ACTIVE_SITES: list[str] = ["wanted", "saramin", "jobkorea"]

"""토스 채용 - greeting 기반."""
from __future__ import annotations

from .greeting import GreetingCrawler


class TossCrawler(GreetingCrawler):
    def __init__(self, user_agent: str, request_delay_sec: float = 1.0):
        super().__init__(
            slug="toss",
            company="토스",
            user_agent=user_agent,
            request_delay_sec=request_delay_sec,
        )

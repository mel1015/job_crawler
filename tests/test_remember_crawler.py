import httpx
import pytest

from job_crawler.crawlers import remember as remember_mod
from job_crawler.crawlers.base import SearchCriteria
from job_crawler.crawlers.remember import RememberCrawler


def _item(i: int) -> dict:
    return {"id": i, "title": f"백엔드 {i}", "organization": {"name": "회사"}}


@pytest.fixture
def sleeps(monkeypatch):
    # 실제로 기다리지 않고 sleep 호출 시간만 기록
    calls: list[float] = []

    async def fake_sleep(sec: float) -> None:
        calls.append(sec)

    monkeypatch.setattr(remember_mod.asyncio, "sleep", fake_sleep)
    return calls


def _crawler(handler) -> RememberCrawler:
    c = RememberCrawler(user_agent="test", request_delay_sec=0)
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


async def test_search_waits_retry_after_on_429(sleeps):
    # Cloudflare rate limit(429 + Retry-After: 60) 뒤에 같은 요청이 성공하면
    # 결과를 그대로 받아야 한다
    responses = [
        httpx.Response(429, headers={"Retry-After": "60"}),
        httpx.Response(200, json={"data": [_item(1)], "meta": {"total_pages": 1}}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    c = _crawler(handler)
    result = await c.search(SearchCriteria(keywords=["SI"], max_results=10))
    await c.aclose()

    assert [s.external_id for s in result] == ["1"]
    assert 60 in sleeps


async def test_persistent_429_is_not_retried_by_backoff(sleeps):
    # 계속 429면 Retry-After 대기를 정해진 횟수만 하고 실패해야 한다
    # (지수 백오프 재시도로 대기가 곱절이 되면 안 됨)
    hits = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal hits
        hits += 1
        return httpx.Response(429, headers={"Retry-After": "60"})

    c = _crawler(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await c._post_json(remember_mod.SEARCH_URL, {})
    await c.aclose()

    assert hits == remember_mod.RATE_LIMIT_MAX_WAITS + 1


async def test_retry_after_is_capped(sleeps):
    responses = [
        httpx.Response(429, headers={"Retry-After": "3600"}),
        httpx.Response(200, json={"data": []}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    c = _crawler(handler)
    await c._post_json(remember_mod.SEARCH_URL, {})
    await c.aclose()

    assert max(sleeps) == remember_mod.RATE_LIMIT_MAX_WAIT_SEC

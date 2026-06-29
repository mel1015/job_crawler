from __future__ import annotations

from types import SimpleNamespace

import pytest

from job_crawler.crawlers.base import JobSummary
from job_crawler.filters import criteria
from job_crawler.filters.criteria import extract_position, pass_filters


@pytest.mark.parametrize(
    "title,expected",
    [
        ("백엔드 개발자", "백엔드"),
        ("Backend Engineer", "백엔드"),
        ("서버 개발자 채용", "백엔드"),
        ("프론트엔드 개발자", "프론트엔드"),
        ("Full-Stack Developer", "풀스택"),
        ("iOS 개발자", "모바일"),
        ("Android Engineer", "모바일"),
        ("DevOps Engineer", "DevOps"),
        ("데이터 엔지니어", "데이터"),
        ("ML Engineer", "ML/AI"),
        ("QA 엔지니어", "QA"),
        ("정보보안 담당자", "보안"),
        ("Python 개발자", "개발"),  # 특정 직군 미매치 → generic
        ("마케팅 매니저", ""),  # 개발 직군 아님
    ],
)
def test_extract_position(title, expected):
    assert extract_position(title) == expected


@pytest.fixture
def empty_settings(monkeypatch):
    """positions/blacklist/required 모두 비운 기본 설정으로 고정."""
    fake = SimpleNamespace(
        positions_list=[],
        blacklist_companies_list=[],
        required_keywords_list=[],
        it_company_whitelist_list=[],
    )
    monkeypatch.setattr(criteria, "get_settings", lambda: fake)
    return fake


def _summary(title: str, company: str = "테스트회사", site: str = "wanted") -> JobSummary:
    return JobSummary(
        site=site,
        external_id="1",
        url="http://example.com",
        title=title,
        company=company,
    )


def test_pass_filters_dev_title(empty_settings):
    assert pass_filters(_summary("백엔드 개발자")) is True


def test_pass_filters_non_dev_title(empty_settings):
    # DEV_KEYWORDS 미포함 → 탈락
    assert pass_filters(_summary("마케팅 매니저")) is False


def test_pass_filters_blacklist_keyword(empty_settings):
    assert pass_filters(_summary("보험설계사 모집")) is False


def test_pass_filters_blacklist_company(empty_settings, monkeypatch):
    empty_settings.blacklist_companies_list = ["나쁜회사"]
    assert pass_filters(_summary("백엔드 개발자", company="나쁜회사 주식회사")) is False


def test_pass_filters_catch_whitelist_skips_keyword(empty_settings):
    # catch 화이트리스트 IT 기업은 키워드 없는 제목도 통과 (다부문 공채 대응)
    empty_settings.it_company_whitelist_list = ["넥슨"]
    assert pass_filters(_summary("서비스 운영", company="넥슨", site="catch")) is True
    # 화이트리스트 밖 기업은 일반 필터 적용 → 키워드 없으면 탈락
    assert pass_filters(_summary("서비스 운영", company="무명회사", site="catch")) is False


def test_pass_filters_position_whitelist(empty_settings):
    empty_settings.positions_list = ["백엔드"]
    assert pass_filters(_summary("백엔드 개발자")) is True
    # 프론트엔드는 화이트리스트 밖 → 탈락
    assert pass_filters(_summary("프론트엔드 개발자")) is False
    # generic "개발"은 항상 통과 (광범위 제목 누락 방지)
    assert pass_filters(_summary("Python 개발자")) is True

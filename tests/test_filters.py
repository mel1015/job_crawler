from __future__ import annotations

from types import SimpleNamespace

import pytest

from job_crawler.crawlers.base import JobSummary
from job_crawler.filters import criteria
from job_crawler.filters.criteria import (
    employment_kind,
    extract_min_years,
    extract_position,
    pass_filters,
    target_tier,
)


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


@pytest.mark.parametrize(
    "company,title,expected",
    [
        # 1순위: 금융사 IT 직고용
        ("현대캐피탈", "백엔드 개발자", "1"),
        ("JB우리캐피탈", "IT기획 개발", "1"),
        ("SBI저축은행", "자바 개발자", "1"),
        ("삼성화재해상보험", "IT 개발", "1"),
        ("신한카드", "백엔드 개발자", "1"),
        # 1순위: 증권사 IT 직고용
        ("OO증권", "IT 개발", "1"),
        ("OO투자증권(주)", "백엔드 개발자", "1"),
        # 연계/중계: 펌뱅킹/PG/VAN/연계솔루션 (통신 계층 경험을 요구하는 경우가 많음)
        ("웹케시", "백엔드 개발자", "relay"),
        ("쿠콘", "API 개발", "relay"),
        ("KG이니시스", "PG 개발", "relay"),
        # 2순위: 금융지주 IT 자회사와 대기업 IT
        ("하나금융티아이", "채널계 개발", "2"),
        ("우리에프아이에스", "백엔드 개발자", "2"),
        ("LG CNS", "금융 SI 개발", "2"),
        ("현대오토에버", "백엔드 개발자", "2"),
        # 3순위: 인터넷은행 도메인 명시 포지션만
        ("카카오뱅크", "여신 서버 개발자", "3"),
        ("토스뱅크", "수신 백엔드 개발자", "3"),
        # 인터넷은행이라도 플랫폼/공통 포지션은 보류
        ("카카오뱅크", "플랫폼 서버 개발자", "hold"),
        ("케이뱅크", "공통 개발", "hold"),
        # 보류: 대규모 트래픽/MSA 중심 회사 유형
        ("카카오페이", "서버 개발자", "hold"),
        ("트래블월렛", "백엔드 개발자", "hold"),
        # 보류: 경쟁이 몰리는 1군 프로덕트사 (서류 결과에서 확인된 유형)
        ("네이버", "백엔드 개발자", "hold"),
        ("쿠팡", "백엔드 개발자", "hold"),
        ("LINE Plus", "Server Engineer", "hold"),
        ("토스플레이스", "Server Developer", "hold"),
        # 타겟 외
        ("무명스타트업", "백엔드 개발자", ""),
    ],
)
def test_target_tier(company, title, expected):
    assert target_tier(company, title) == expected


def test_pass_filters_position_whitelist(empty_settings):
    empty_settings.positions_list = ["백엔드"]
    assert pass_filters(_summary("백엔드 개발자")) is True
    # 프론트엔드는 화이트리스트 밖 → 탈락
    assert pass_filters(_summary("프론트엔드 개발자")) is False
    # generic "개발"은 항상 통과 (광범위 제목 누락 방지)
    assert pass_filters(_summary("Python 개발자")) is True


@pytest.mark.parametrize(
    "text, expected",
    [
        ("[자격 요건]\n- 관련 경력 1년 이상\n- Java 기본", 1),
        ("백엔드 개발 경력 3년 이상\n- 운영 경험 5년 이상 우대", 3),
        ("경력 2~5년", 2),
        ("경력 무관, 신입 가능", None),
        ("설립 30년 이상의 회사입니다", None),
        ("", None),
    ],
)
def test_extract_min_years(text, expected):
    assert extract_min_years(text) == expected


@pytest.mark.parametrize(
    "employment_type, title, body, expected",
    [
        ("계약직", "IT 개발자", "", "contract"),
        (None, "IT 개발 경력직 채용 (계약직)", "", "contract"),
        (None, "IT 경력직(연봉계약직)", "", "contract"),
        ("프리랜서", "금융권 SM 개발", "", "freelance"),
        (None, "Java 개발자", "고용형태: 파견직\n근무지: 여의도", "contract"),
        ("정규직", "백엔드 개발자", "", "regular"),
        (None, "백엔드 개발자", "고용형태 정규직 (수습 3개월)", "regular"),
        (None, "백엔드 개발자", "주요 업무", ""),
        # 본문은 근무형태/고용형태 표기 뒤의 값만 본다 (업무 설명 속 단어 오탐 방지)
        (None, "풀스택 개발자", "외주 관리 경험이 있으신 분", ""),
        (None, "백엔드 개발자", "근로자, 프리랜서를 위한 세금 신고 서비스", ""),
        (None, "SM 개발", "근무형태 계약직, 프리랜서 급여 면접 후 결정", "freelance"),
    ],
)
def test_employment_kind(employment_type, title, body, expected):
    assert employment_kind(employment_type, title, body) == expected

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from job_crawler.filters import apply_history as ah

COMPANY_INTRO = "\n".join(
    [
        "우리 회사는 국내 최고의 핀테크 기업으로 금융의 모든 경험을 새롭게 만듭니다",
        "누적 사용자 천만 명을 넘어 글로벌 시장으로 서비스를 빠르게 확장하고 있습니다",
        "자율과 책임을 바탕으로 수평적인 문화에서 함께 성장할 동료를 찾고 있습니다",
        "복지 제도로 자기계발비 지원과 최신 장비 지급, 유연 근무제를 운영합니다",
    ]
)
CORE_JD = "\n".join(
    [
        "- 계정계 여신 원장 시스템을 설계하고 개발하며 운영합니다",
        "- 대출 실행과 상환 배치 프로세스를 안정적으로 처리합니다",
        "- Java Spring 기반 금융 거래 API를 설계하고 구현합니다",
        "- Oracle 대용량 원장 데이터 조회 성능을 개선합니다",
    ]
)
DATA_JD = "\n".join(
    [
        "- Kafka 기반 실시간 데이터 수집 파이프라인을 구축합니다",
        "- Spark 배치로 사용자 행동 로그를 집계하고 적재합니다",
        "- 데이터 웨어하우스 모델링과 품질 모니터링을 담당합니다",
        "- Airflow 워크플로우를 설계하고 운영 자동화를 진행합니다",
    ]
)
SARAMIN_META = "\n".join(
    [
        "최저임금계산에 대한 알림",
        "하단에 명시된 급여, 근무 내용 등이 최저임금에 미달하는 경우 위 내용이 우선합니다.",
        "경력 3~10년",
        "조회수 97 홈페이지접속 21",
    ]
)


def _job(id, title, body, company="테스트핀테크(주)", site="wanted", **kw):
    return SimpleNamespace(id=id, site=site, company=company, title=title, body_text=body, **kw)


def _others():
    # 회사 공통 문구를 판별하려면 같은 회사의 다른 포지션 공고가 있어야 한다.
    # 실제 DB에서 공통 문구 가중치가 충분히 낮아지는 회사는 포지션명이 3개 이상이었다
    return [
        _job(
            9,
            "프론트엔드 개발자",
            COMPANY_INTRO + "\n- React 기반 웹 프론트엔드 화면을 개발하고 운영합니다",
        ),
        _job(
            10,
            "iOS 개발자",
            COMPANY_INTRO + "\n- Swift 기반 모바일 앱 신규 기능을 개발하고 운영합니다",
        ),
        _job(
            11,
            "QA 엔지니어",
            COMPANY_INTRO + "\n- 금융 서비스 테스트 자동화 체계를 구축하고 운영합니다",
        ),
    ]


def _index(jobs, boilerplate=frozenset()):
    return ah.JobIndex(jobs, set(boilerplate))


@pytest.mark.parametrize(
    "a,b,expected",
    [
        # 괄호 안 팀명이 다르면 다른 포지션 (문자열 유사도로는 0.86이 나와 같다고 오판하던 쌍)
        ("Backend Engineer(Trading Core)", "Backend Engineer(Data)", ah.TITLE_DIFFERENT),
        (
            "[토스뱅크] Server Developer (계정계)",
            "[토스뱅크] Server Developer (수신)",
            ah.TITLE_DIFFERENT,
        ),
        # 띄어쓰기/어순만 다르면 같은 포지션
        (
            "[대형저축은행] 여신 JAVA 개발 (계장~대리급)",
            "[대형저축은행] java  여신개발(계장~대리급)",
            ah.TITLE_SAME,
        ),
        # 상투어(채용, 경력, 마감일)는 무시
        ("IT 개발팀 경력직 채용 (~6/28)", "IT 개발팀", ah.TITLE_SAME),
        # 한쪽이 더 구체적이면 포함 관계
        ("백엔드 개발자", "시니어 백엔드 개발자", ah.TITLE_SUBSET),
    ],
)
def test_title_relation(a, b, expected):
    assert ah.title_relation(ah.title_tokens(a), ah.title_tokens(b)) == expected


def test_company_tag_in_title_is_ignored():
    a = ah.title_tokens("[빗썸] Backend 개발자 (3년 이상)", "(주)빗썸")
    b = ah.title_tokens("Backend 개발자 (3년 이상)", "(주)빗썸")
    assert ah.title_relation(a, b) == ah.TITLE_SAME


def test_repost_on_other_site_is_same_job():
    # 같은 JD를 사람인에 다시 올리면서 사이트 안내 문구가 붙은 경우
    applied = _job(1, "여신 서버 개발자", COMPANY_INTRO + "\n" + CORE_JD)
    repost = _job(
        2, "여신 서버 개발자", SARAMIN_META + "\n" + COMPANY_INTRO + "\n" + CORE_JD, site="saramin"
    )
    other = _job(3, "데이터 엔지니어", COMPANY_INTRO + "\n" + DATA_JD)
    idx = _index([applied, repost, other], boilerplate={"최저임금계산에대한알림"})
    assert idx.match(applied, repost) == ah.SAME


def test_same_jd_with_different_title_is_same_job():
    # 사이트마다 포지션명을 다르게 올렸지만 JD가 같은 경우
    applied = _job(1, "Loan Core Backend Engineer", COMPANY_INTRO + "\n" + CORE_JD)
    renamed = _job(2, "여신 원장 서버 개발", COMPANY_INTRO + "\n" + CORE_JD, site="jobkorea")
    assert _index([applied, renamed]).match(applied, renamed) == ah.SAME


def test_shared_company_intro_does_not_make_jobs_same():
    # 회사 소개가 같아도 업무가 다르면 다른 업무 (회사 공통 문구 가중치가 낮아야 함)
    applied = _job(1, "여신 서버 개발자", COMPANY_INTRO + "\n" + CORE_JD)
    data = _job(2, "데이터 엔지니어", COMPANY_INTRO + "\n" + DATA_JD)
    assert _index([applied, data, *_others()]).match(applied, data) is None


def test_same_title_different_jd_is_title_only():
    # 포지션명은 같지만 다른 팀 JD (엑셈: 맥스게이지 서버 vs Kafka 파이프라인)
    applied = _job(1, "Java 개발자", COMPANY_INTRO + "\n" + CORE_JD)
    other_team = _job(2, "Java 개발자", COMPANY_INTRO + "\n" + DATA_JD, site="jobkorea")
    assert _index([applied, other_team, *_others()]).match(applied, other_team) == ah.TITLE_ONLY


def test_manual_summary_is_not_called_different_job():
    # 수동 등록 공고는 원문 요약본이라 JD가 달라 보여도 다른 업무로 단정하지 않는다
    applied = _job(1, "Java 개발자", COMPANY_INTRO + "\n" + CORE_JD, site="manual")
    crawled = _job(2, "Java 개발자", COMPANY_INTRO + "\n" + DATA_JD, site="remember")
    assert _index([applied, crawled, *_others()]).match(applied, crawled) == ah.SAME_UNVERIFIED


def test_missing_body_falls_back_to_title():
    applied = _job(1, "여신 서버 개발자", COMPANY_INTRO + "\n" + CORE_JD)
    meta_only = _job(2, "여신 서버 개발자", "경력 3~10년", site="saramin")
    assert _index([applied, meta_only]).match(applied, meta_only) == ah.SAME_UNVERIFIED


def test_different_company_never_matches():
    a = _job(1, "여신 서버 개발자", CORE_JD, company="A캐피탈")
    b = _job(2, "여신 서버 개발자", CORE_JD, company="B캐피탈")
    assert _index([a, b]).match(a, b) is None


def _applied(id, status, events, site="saramin", first_seen=None):
    return _job(
        id,
        "여신 서버 개발자",
        COMPANY_INTRO + "\n" + CORE_JD,
        site=site,
        application_status=status,
        first_seen_at=first_seen,
        events=[SimpleNamespace(label=label, event_date=d) for label, d in events],
    )


def test_application_dates_from_events():
    a = _applied(1, "doc_rejected", [("서류결과", date(2026, 10, 10)), ("지원", date(2026, 10, 1))])
    assert ah.application_dates(a) == (date(2026, 10, 1), date(2026, 10, 10), "서류결과")


def test_application_dates_manual_falls_back_to_registered_date():
    a = _applied(1, None, [], site="manual", first_seen=datetime(2026, 9, 23, 5, 0))
    assert ah.application_dates(a) == (date(2026, 9, 23), None, None)


def _advice(status, events, today=date(2026, 11, 25)):
    applied = _applied(1, status, events)
    target = _job(2, "여신 서버 개발자", COMPANY_INTRO + "\n" + CORE_JD, site="jobkorea")
    priors = ah.find_prior_applications(target, [applied], _index([applied, target]))
    return priors, ah.reapply_advice(priors, today)


def test_recent_rejection_of_same_job_is_not_recommended():
    priors, advice = _advice(
        "doc_rejected", [("지원", date(2026, 10, 1)), ("서류결과", date(2026, 10, 10))]
    )
    assert priors[0].match == ah.SAME
    assert priors[0].status_label == "서류탈락"
    assert advice.level == "bad"
    assert "재지원 비권장" in advice.text


def test_old_rejection_allows_reapply():
    _, advice = _advice(
        "final_rejected", [("지원", date(2025, 12, 1)), ("최종결과", date(2026, 1, 5))]
    )
    assert advice.level == "ok"
    assert "재지원 검토 가능" in advice.text


def test_in_progress_application_blocks_duplicate():
    _, advice = _advice("job_interview", [("지원", date(2026, 11, 1))])
    assert advice.level == "bad"
    assert "중복 지원 불필요" in advice.text


def test_long_no_response_suggests_reapply_check():
    _, advice = _advice(None, [("지원", date(2026, 9, 1))])
    assert advice.level == "warn"
    assert "무응답" in advice.text


@pytest.mark.parametrize(
    "a,b",
    [
        # 잡코리아는 회사명 뒤에 그룹명을 붙인다
        ("신세계I&C신세계그룹", "신세계I&C"),
        ("현대자동차그룹 (HYUNDAI)", "현대자동차"),
        ("(주)비바리퍼블리카", "㈜비바리퍼블리카"),
    ],
)
def test_normalize_company_joins_site_variants(a, b):
    assert ah.normalize_company(a) == ah.normalize_company(b)


@pytest.mark.parametrize(
    "a,b", [("카카오", "카카오페이"), ("NHN", "NHN페이코"), ("링크(주)", "링크앤스카우트")]
)
def test_normalize_company_keeps_different_companies_apart(a, b):
    assert ah.normalize_company(a) != ah.normalize_company(b)


def test_final_rejection_shows_stage():
    a = _applied(
        1, "final_rejected", [("지원", date(2026, 4, 3)), ("1차면접결과", date(2026, 8, 31))]
    )
    target = _job(2, "여신 서버 개발자", COMPANY_INTRO + "\n" + CORE_JD, site="jobkorea")
    priors = ah.find_prior_applications(target, [a], _index([a, target]))
    assert priors[0].result_label == "1차면접결과"


def test_title_only_asks_to_check_instead_of_allowing():
    prior = ah.PriorApplication(
        1, "saramin", "Java 개발자", ah.TITLE_ONLY, "doc_rejected", None, None
    )
    assert ah.reapply_advice([prior], date(2026, 11, 25)).level == "warn"

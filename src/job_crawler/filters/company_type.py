"""사이트별 원본 신호(company_type_signals)를 단일 기업유형 라벨로 정규화.

라벨: 대기업 | 중견기업 | 중소기업 | 공기업 | 외국계 | 스타트업 | 금융업 | None(미분류)

각 사이트 크롤러가 검색/상세 응답에서 원본 신호를 추출해
JobSummary/JobDetail.company_type_signals에 담아두면, pipeline._upsert_job이
이 모듈로 정규화해 Job.company_type에 저장한다. 라벨 규칙이 바뀌어도
원본 신호(Job.company_type_signals)가 남아있으면 재크롤 없이 재정규화 가능.
"""
from __future__ import annotations

import re

# 우선순위: 공기업 > 외국계 > 금융업 > 대기업 > 스타트업 > 중소(기본값)
# 회사명이 여러 범주에 걸칠 수 있어(신한카드=대기업+금융업) 순서를 고정한다.

_PUBLIC_PAT = re.compile(
    r"공사$|공단$|진흥원$|평가원$|관리공단|산업은행|기업은행|수출입은행"
    r"|신용보증기금|주택도시보증공사|한국은행|한국전력|코레일",
    re.I,
)
_FOREIGN_PAT = re.compile(
    r"코리아|구글|Google|마이크로소프트|Microsoft|오라클|Oracle"
    r"|아마존|Amazon|\bIBM\b|메타(?:\s|$)|Meta(?:\s|$)|애플|Apple|세일즈포스|Salesforce|\bSAP\b",
    re.I,
)
_FINANCE_PAT = re.compile(
    r"은행|카드|캐피탈|캐피털|증권|보험|저축은행|여신금융|신탁|자산운용"
    r"|생명(?:\s|$)|화재(?:\s|$)|손해보험",
    re.I,
)


def _is_public(company: str) -> bool:
    return bool(_PUBLIC_PAT.search(company))


def _is_foreign(company: str) -> bool:
    return bool(_FOREIGN_PAT.search(company))


def _is_finance(company: str) -> bool:
    return bool(_FINANCE_PAT.search(company))


def _from_catch(company: str, signals: dict) -> str | None:
    if _is_public(company):
        return "공기업"
    if _is_foreign(company):
        return "외국계"
    if _is_finance(company):
        return "금융업"
    # PopularCategory는 "중견기업"/"TOP중견"/"상위 10% 중소" 등 접두/접미가 붙어
    # 나오므로 부분 문자열로 매칭한다.
    popular = signals.get("popular_category") or ""
    if "중견" in popular:
        return "중견기업"
    if "스타트업" in popular:
        return "스타트업"
    if "중소" in popular:
        return "중소기업"
    if signals.get("group_name") or "코스피" in popular or "매출액" in popular:
        return "대기업"
    return None


def _from_saramin(company: str, signals: dict) -> str | None:
    tags = signals.get("company_type_tags") or []
    joined = " ".join(tags)
    if _is_public(company) or "공기업" in joined or "공사" in joined or "공단" in joined:
        return "공기업"
    if _is_foreign(company) or "외국계" in joined or "외국인" in joined:
        return "외국계"
    if _is_finance(company):
        return "금융업"
    if "대기업" in joined:
        return "대기업"
    if "중견기업" in joined:
        return "중견기업"
    if "중소기업" in joined:
        return "중소기업"
    if "벤처기업" in joined or "이노비즈" in joined:
        return "스타트업"
    return None


def _from_jobkorea(company: str, signals: dict) -> str | None:
    if _is_public(company):
        return "공기업"
    if signals.get("foreign") or _is_foreign(company):
        return "외국계"
    if _is_finance(company):
        return "금융업"
    name = signals.get("company_type_name") or ""
    if "대기업" in name:
        return "대기업"
    if "중견기업" in name:
        return "중견기업"
    if "중소기업" in name:
        return "중소기업"
    return None


def _from_remember(company: str, signals: dict) -> str | None:
    # 헤드헌팅/서치펌 대행 공고는 organization이 실제 고용주가 아니라
    # 서치펌 정보라 이 신호로 분류하면 오분류. 미분류로 남긴다.
    if signals.get("is_headhunter"):
        return None
    if _is_public(company):
        return "공기업"
    if _is_foreign(company):
        return "외국계"
    if "금융" in (signals.get("industries_level1") or []) or _is_finance(company):
        return "금융업"
    if signals.get("investment_value"):
        return "스타트업"
    return None


def _from_wanted(company: str, signals: dict) -> str | None:
    if _is_public(company):
        return "공기업"
    if _is_foreign(company):
        return "외국계"
    if _is_finance(company):
        return "금융업"
    tag = signals.get("employee_count_tag") or ""
    nums = [int(n.replace(",", "")) for n in re.findall(r"[\d,]+(?=명)", tag)]
    if not nums:
        return None
    size = max(nums)
    if "이상" in tag and size >= 1000:
        return "대기업"
    if size >= 1000:
        return "대기업"
    if size >= 300:
        return "중견기업"
    return "중소기업"


_SITE_HANDLERS = {
    "catch": _from_catch,
    "saramin": _from_saramin,
    "jobkorea": _from_jobkorea,
    "remember": _from_remember,
    "wanted": _from_wanted,
}


def normalize_company_type(site: str, company: str, signals: dict | None) -> str | None:
    """사이트별 원본 신호를 단일 기업유형 라벨로 정규화. 판정 불가 시 None(미분류)."""
    handler = _SITE_HANDLERS.get(site)
    if not handler or not company:
        return None
    return handler(company, signals or {})

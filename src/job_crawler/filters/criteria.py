from __future__ import annotations

import re

from ..config import get_settings
from ..crawlers.base import JobSummary

BLACKLIST_KEYWORDS = [
    "인턴십", "파트타임", "알바", "시니어 10년", "신입전용",
    # 비개발 직군
    "보험설계사", "보험설계", "보험모집", "보험영업", "보험상담",
    "지사장", "지점장", "영업관리", "영업직",
    "채권추심", "채권관리", "채권상담",
    "경영컨설팅", "경영컨설턴트", "경영본부", "경영지원", "경영관리",
    "재무", "회계", "세무", "인사", "총무", "법무",
    "텔레마케팅", "콜센터", "상담사", "상담원",
    "배달", "배송", "택배", "운전", "기사",
    "간호", "요양", "돌봄",
    "설계사 모집", "GA ", "GFC",
    "무료DB", "DB제공",
    # SW 개발이지만 직무 불일치 (임베디드/하드웨어)
    "임베디드", "펌웨어", "firmware", "embedded",
    "f/w 개발", "h/w 개발", "hw 개발", "fw 개발",
]

DEV_KEYWORDS = [
    "개발", "developer", "engineer", "backend", "frontend",
    "풀스택", "서버", "웹개발", "앱개발", "소프트웨어",
    "devops", "sre", "데이터", "머신러닝", "ml ", "ai ",
    "java", "python", "spring", "react", "node",
    "dba", "인프라", "클라우드", "cloud", "qa", "테스트",
    "아키텍트", "cto", "기술개발", "기술연구", "기술팀",
]


POSITION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("백엔드", re.compile(r"백엔드|back.?end|서버\s*개발|server\s*dev", re.I)),
    ("프론트엔드", re.compile(r"프론트엔드|front.?end|퍼블리셔", re.I)),
    ("풀스택", re.compile(r"풀스택|full.?stack", re.I)),
    ("모바일", re.compile(r"android|ios|모바일|앱\s*개발|flutter|react\s*native|kotlin|swift", re.I)),
    ("DevOps", re.compile(r"devops|sre|인프라|infrastructure|cloud|클라우드|플랫폼\s*엔지니어", re.I)),
    ("데이터", re.compile(r"데이터\s*엔지니어|data\s*engineer|etl|빅데이터|big\s*data|데이터\s*개발", re.I)),
    ("ML/AI", re.compile(r"머신러닝|machine\s*learning|ml\b|ai\s*엔지니어|딥러닝|deep\s*learning|mlops", re.I)),
    ("DBA", re.compile(r"\bdba\b|데이터베이스\s*관리", re.I)),
    ("QA", re.compile(r"\bqa\b|테스트\s*엔지니어|품질\s*보증|sdet", re.I)),
    ("보안", re.compile(r"보안|security|시큐리티", re.I)),
    ("웹개발", re.compile(r"웹\s*개발|web\s*dev", re.I)),
]


# 지원 타겟 우선순위 (claude_resume/공통/기술보강_실행계획_2026-07.md 1장 기준)
# 1순위: 금융사 IT 직군 직고용 (캐피탈, 카드, 저축은행, 보험, 증권)
_TIER1_PAT = re.compile(
    r"캐피탈|캐피털|저축은행|여신금융|증권"
    r"|신한카드|삼성카드|현대카드|롯데카드|국민카드|KB카드|우리카드|하나카드|BC카드|비씨카드"
    r"|생명보험|손해보험|화재해상|해상화재|생명(?:\s|$)|화재(?:\s|$)|보험",
    re.I,
)
# 2순위: 금융지주 IT 자회사와 대기업 IT
_TIER2_PAT = re.compile(
    r"우리에프아이에스|우리FIS|하나금융티아이|하나금융TI|신한DS|신한디에스"
    r"|KB데이타시스템|KB데이터시스템|농협정보시스템|NH농협|금융지주"
    r"|LG\s*CNS|삼성SDS|삼성에스디에스|SK\s*C&C|SK\s*AX|포스코DX|현대오토에버"
    r"|롯데이노베이트|롯데정보통신|CJ올리브네트웍스|kt\s*ds|신세계아이앤씨|코오롱베니트",
    re.I,
)
# 3순위: 인터넷은행 - 도메인(여신/수신/외환) 명시 포지션만, 그 외는 보강 전까지 보류
_TIER3_COMPANY_PAT = re.compile(r"카카오뱅크|토스뱅크|케이뱅크", re.I)
_TIER3_DOMAIN_PAT = re.compile(
    r"여신|수신|외환|대출|심사|채권|원장|코어뱅킹|core\s*banking|뱅킹\s*코어|도메인|퇴직연금",
    re.I,
)
# 보류: 대규모 트래픽/MSA/Kafka 중심 JD 유형 (테스트 코드, Redis 보강 반영 후 재도전)
_HOLD_COMPANY_PAT = re.compile(
    r"카카오페이|토스페이먼츠|토스증권|비바리퍼블리카|트래블월렛|트레블월렛", re.I
)
# 보류: 지원자가 몰리는 1군 프로덕트사. 2군 금융사 공고보다 우선순위를 낮추기 위한 분류이며,
# 인터넷은행 도메인 포지션(3순위) 판정 뒤에 적용한다 (카카오뱅크가 "카카오"에 먼저 걸리지 않게)
_TOP_PRODUCT_PAT = re.compile(
    r"네이버|NAVER|카카오|쿠팡|당근|^LINE|라인플러스|우아한형제들|배달의민족|빗썸|두나무|토스",
    re.I,
)
# 연계/중계: 펌뱅킹, PG, VAN, 연계솔루션 회사. 업무 계층 경험은 맞지만 통신 계층(소켓, 전문 조립,
# 재전송) 구현 경험을 깊게 묻는 경우가 많아 별도 등급으로 분리한다
_RELAY_PAT = re.compile(
    r"더즌|dozn|인젠트|쿠콘|웹케시|핑거|KICC|한국정보통신|나이스정보통신|NICE정보통신"
    r"|이니시스|세틀뱅크|헥토파이낸셜|KCP|다날",
    re.I,
)

TARGET_TIER_LABELS = {
    "1": "1순위 금융사",
    "2": "2순위 금융IT",
    "3": "3순위 도메인",
    "relay": "연계/중계",
    "hold": "지원 보류",
}


def target_tier(company: str, title: str = "") -> str:
    """회사명과 공고 제목으로 지원 우선순위를 분류한다.

    반환: "1" | "2" | "3" | "relay" | "hold" | ""(타겟 외)
    """
    company = company or ""
    title = title or ""
    if _HOLD_COMPANY_PAT.search(company):
        return "hold"
    if _TIER3_COMPANY_PAT.search(company):
        # 인터넷은행은 도메인 명시 포지션만 3순위, 플랫폼/공통 개발은 보류
        return "3" if _TIER3_DOMAIN_PAT.search(title) else "hold"
    if _TOP_PRODUCT_PAT.search(company):
        return "hold"
    if _RELAY_PAT.search(company):
        return "relay"
    if _TIER1_PAT.search(company):
        return "1"
    if _TIER2_PAT.search(company):
        return "2"
    return ""


# 경력 하한: "N년 이상", "N년↑", "N~M년". 회사 연혁("설립 30년 이상") 같은 큰 수는 제외
_MIN_YEARS_PAT = re.compile(r"(\d{1,2})\s*년\s*(?:이상|↑)|(\d{1,2})\s*[~\-]\s*\d{1,2}\s*년")
_MAX_REASONABLE_YEARS = 20


def extract_min_years(text: str) -> int | None:
    """공고 본문에서 요구 경력 하한(년)을 뽑는다. 여러 개면 가장 작은 값, 없으면 None."""
    years = [
        int(a or b)
        for a, b in _MIN_YEARS_PAT.findall(text or "")
        if int(a or b) <= _MAX_REASONABLE_YEARS
    ]
    return min(years) if years else None


_FREELANCE_PAT = re.compile(r"프리랜서|도급|외주", re.I)
_CONTRACT_PAT = re.compile(r"계약직|파견|연봉계약|촉탁", re.I)
_EMPLOYMENT_FIELD_PAT = re.compile(r"(?:근무|고용)\s*형태\s*[:：]?\s*([^\n]{0,40})")


def employment_kind(employment_type: str | None, title: str, body: str = "") -> str:
    """고용형태를 "regular" | "contract" | "freelance" | ""(미상)로 정규화한다.

    사이트가 준 employment_type이 비어 있는 공고가 많아(열린 공고의 약 60%) 제목, 본문 순으로 보정한다.
    """
    for text in (employment_type or "", title or ""):
        if _FREELANCE_PAT.search(text):
            return "freelance"
        if _CONTRACT_PAT.search(text):
            return "contract"
    if employment_type and "정규" in employment_type:
        return "regular"
    if not employment_type:
        # 본문은 "근무형태/고용형태" 표기 뒤의 값만 본다. 업무 설명 속 "외주 관리" 같은 오탐 방지
        m = _EMPLOYMENT_FIELD_PAT.search(body or "")
        field = m.group(1) if m else ""
        if _FREELANCE_PAT.search(field):
            return "freelance"
        if _CONTRACT_PAT.search(field):
            return "contract"
        if "정규" in field:
            return "regular"
    return ""


def extract_position(title: str) -> str:
    for label, pat in POSITION_PATTERNS:
        if pat.search(title):
            return label
    if re.search(r"개발|developer|engineer|소프트웨어", title, re.I):
        return "개발"
    return ""


def pass_filters(summary: JobSummary) -> bool:
    settings = get_settings()
    title = (summary.title or "").lower()
    company = (summary.company or "").lower()

    for bad in BLACKLIST_KEYWORDS:
        if bad.lower() in title:
            return False

    for bad_co in settings.blacklist_companies_list:
        if bad_co.lower() in company:
            return False

    # catch: 화이트리스트 IT 기업은 제목 키워드 없이도 통과 (다부문 공채 대응)
    if summary.site == "catch":
        company = (summary.company or "").lower()
        whitelist = [w.lower() for w in settings.it_company_whitelist_list]
        if whitelist and any(w in company for w in whitelist):
            return _check_position(title, settings)

    required = settings.required_keywords_list or DEV_KEYWORDS
    if not any(kw.lower() in title for kw in required):
        return False

    return _check_position(title, settings)


def _check_position(title: str, settings) -> bool:
    if not settings.positions_list:
        return True
    pos = extract_position(title)
    # 분류 불가("") 또는 generic("개발")은 통과 — 광범위 제목의 백엔드 공고 누락 방지
    if pos in {"", "개발"}:
        return True
    allowed = {p.lower() for p in settings.positions_list}
    return pos.lower() in allowed

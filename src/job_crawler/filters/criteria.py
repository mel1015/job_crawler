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


def extract_position(title: str) -> str:
    for label, pat in POSITION_PATTERNS:
        if pat.search(title):
            return label
    if re.search(r"개발|developer|engineer|소프트웨어", title, re.I):
        return "개발"
    return ""


def pass_filters(summary: JobSummary) -> bool:
    _ = get_settings()
    title = (summary.title or "").lower()
    for bad in BLACKLIST_KEYWORDS:
        if bad.lower() in title:
            return False
    for dev in DEV_KEYWORDS:
        if dev.lower() in title:
            return True
    return False

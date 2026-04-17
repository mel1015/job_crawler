"""Plain-text job body -> styled HTML."""
from __future__ import annotations

import re
from markupsafe import Markup

JUNK_PATTERNS = [
    re.compile(r"^.*?본문 바로가기", re.S),
    re.compile(r"커리어의 시작.*?사람인!", re.S),
    re.compile(r"AI 검색.*?인적성검사", re.S),
    re.compile(r"로그인\n회원가입", re.S),
    re.compile(r"기업서비스.*?채용상품", re.S),
    re.compile(r"사람인 비즈니스.*?사람인스토어", re.S),
    re.compile(r"전체메뉴.*?취업축하금", re.S),
    re.compile(r"신입·인턴.*?홈\n", re.S),
    re.compile(r"스크랩\s*공유\s*프린트", re.S),
    re.compile(r"접수기간.*?접수방법", re.S),
    re.compile(r"지원자 현황.*$", re.S),
    re.compile(r"이 공고를 스크랩한.*$", re.S),
    re.compile(r"기업정보\s*대표자명.*$", re.S),
    re.compile(r"관련 채용정보.*$", re.S),
    re.compile(r"Copyright.*$", re.S),
    re.compile(r"채용정보\n지역별\n.*?홈\n", re.S),
]

JUNK_LINES = {
    "지도보기", "인근지하철", "TOP", "궁금해요", "로그인", "회원가입",
    "기업 서비스", "JOB 찾기", "합격축하금", "공채정보", "신입·인턴",
    "기업·연봉", "콘텐츠", "취업톡톡", "상세요강", "추천공고",
    "IT 개발자 전문 채용관", "해주세요.", "문의",
    "채용정보에 잘못된 내용이 있을 경우",
    "접수기간∙방법", "기업정보", "기업정보 더보기",
    "조회수", "공유하기", "페이스북", "트위터", "URL복사", "SMS발송", "신고하기",
    "최저임금계산에 대한 알림",
    "하단에 명시된 급여, 근무 내용 등이 최저임금에 미달하는 경우 위 내용이 우선합니다.",
    "스크랩", "홈페이지 지원", "채용시 마감",
    "○", "명",
    "나와 맞는지 알아보기", "회사", "나", "지금",
    "하면 나와 회사의 적합도를 비교해볼 수 있어요.",
}

JUNK_SUBSTRINGS = [
    "적합도 체크", "핵심 역량", "회사에서 중요하게", "AI추천공고",
    "로그인하고", "로그인하면", "비슷한 조건의",
    "이 기업과 나의 적합도",
]

METADATA_KEYS = {
    "모집분야", "모집인원", "고용형태", "급여", "근무시간", "근무지주소",
    "경력", "학력", "스킬", "우대조건", "기본우대", "자격증", "우대전공",
    "직급/직책",
}

SECTION_RE = re.compile(
    r"^\[([^\]]+)\]$|"
    r"^#+\s+(.+)$|"
    r"^[📋✅🏠🎯💡⭐🔥🚀📌🎁🏢💰📄🍽️🍱]*\s*(주요\s*업무|자격\s*요건|우대\s*사항|우대\s*요건|혜택|복지|근무\s*조건|근무조건|채용\s*절차|지원\s*자격|담당\s*업무|필수\s*조건|기술\s*스택|모집\s*부문|모집\s*분야|모집\s*요강|사용\s*기술|주요\s*사용\s*기술|핵심\s*역량|전형\s*절차|접수\s*방법|회사\s*소개|팀\s*소개).*$",
    re.M,
)

BULLET_RE = re.compile(r"^\s*[•·\-\*▪▸►◦‧]\s*", re.M)
NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s*", re.M)


def clean_body(text: str) -> str:
    if not text:
        return ""
    for pat in JUNK_PATTERNS:
        text = pat.sub("", text)
    lines = text.split("\n")
    cleaned: list[str] = []
    blank_count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_count += 1
            if blank_count <= 2:
                cleaned.append("")
            continue
        if stripped in JUNK_LINES:
            continue
        if any(js in stripped for js in JUNK_SUBSTRINGS):
            continue
        blank_count = 0
        cleaned.append(stripped)
    return "\n".join(cleaned).strip()


def format_body_html(text: str) -> str:
    text = clean_body(text)
    if not text:
        return '<p class="body-empty">본문 없음</p>'

    lines = text.split("\n")
    html_parts: list[str] = []
    in_list = False
    in_meta = False
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            if in_meta:
                html_parts.append("</div>")
                in_meta = False
            html_parts.append('<div class="body-spacer"></div>')
            i += 1
            continue

        section_match = SECTION_RE.match(stripped)
        if section_match:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            if in_meta:
                html_parts.append("</div>")
                in_meta = False
            title = section_match.group(1) or section_match.group(2) or section_match.group(3)
            icon = _section_icon(title)
            html_parts.append(f'<h3 class="body-section">{icon} {_esc(title)}</h3>')
            i += 1
            continue

        if stripped in METADATA_KEYS:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            vals: list[str] = []
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if not nxt or nxt in METADATA_KEYS or SECTION_RE.match(nxt):
                    break
                if nxt in JUNK_LINES or nxt == ",":
                    i += 1
                    continue
                vals.append(nxt)
                i += 1
            if vals:
                val_str = _esc(", ".join(v for v in vals if v != ","))
                if not in_meta:
                    html_parts.append('<div class="body-meta-block">')
                    in_meta = True
                html_parts.append(
                    f'<div class="body-meta-row">'
                    f'<span class="body-meta-key">{_esc(stripped)}</span>'
                    f'<span class="body-meta-val">{val_str}</span>'
                    f'</div>'
                )
            continue

        if BULLET_RE.match(line) or NUMBERED_RE.match(line):
            if in_meta:
                html_parts.append("</div>")
                in_meta = False
            content = BULLET_RE.sub("", NUMBERED_RE.sub("", line)).strip()
            if not in_list:
                html_parts.append('<ul class="body-list">')
                in_list = True
            html_parts.append(f"<li>{_esc(content)}</li>")
            i += 1
            continue

        if in_list:
            html_parts.append("</ul>")
            in_list = False
        if in_meta:
            html_parts.append("</div>")
            in_meta = False

        html_parts.append(f"<p>{_esc(stripped)}</p>")
        i += 1

    if in_list:
        html_parts.append("</ul>")
    if in_meta:
        html_parts.append("</div>")

    return "\n".join(html_parts)


def _section_icon(title: str) -> str:
    t = title.strip().lower()
    if any(k in t for k in ("업무", "담당", "역할")):
        return '<span class="sec-icon">&#128188;</span>'
    if any(k in t for k in ("자격", "필수", "요건")):
        return '<span class="sec-icon">&#9989;</span>'
    if any(k in t for k in ("우대", "선호")):
        return '<span class="sec-icon">&#11088;</span>'
    if any(k in t for k in ("혜택", "복지", "보상")):
        return '<span class="sec-icon">&#127873;</span>'
    if any(k in t for k in ("기술", "스택", "사용")):
        return '<span class="sec-icon">&#128736;</span>'
    if any(k in t for k in ("절차", "전형", "채용")):
        return '<span class="sec-icon">&#128203;</span>'
    if any(k in t for k in ("근무", "조건", "위치")):
        return '<span class="sec-icon">&#128205;</span>'
    if any(k in t for k in ("소개", "회사", "팀")):
        return '<span class="sec-icon">&#127970;</span>'
    return '<span class="sec-icon">&#128196;</span>'


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

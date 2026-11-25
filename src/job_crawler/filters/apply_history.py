"""지원 이력 매칭: 새로 수집된 공고가 예전에 지원한 공고와 같은 업무인지 판정한다.

사람인/잡코리아 등은 같은 공고를 다시 올리거나 사이트마다 포지션명을 다르게 올려서
회사명만으로는 "같은 업무"인지 알 수 없다. 같은 회사(정규화한 회사명) 안에서
JD 본문과 제목을 각각 비교한 뒤 함께 판정한다.

JD 비교 (2026-11 DB 측정 근거: 지원 공고 70건과 같은 회사 공고 736쌍)
- 사이트 템플릿 줄(사람인 "최저임금계산에 대한 알림", "면접 후 결정" 등)은 DB 전체에서
  SITE_BOILERPLATE_MIN_COMPANIES개 이상 회사에 나오는 줄로 판정해 지운다. 공고 수로 세면 한 회사가
  여러 번 재게시한 짧은 업무 항목("여신개발 및 여신 사후 개발")까지 템플릿으로 지워진다
- 숫자가 든 짧은 줄도 뺀다. 사람인 메타("경력3~10년", "조회수97홈페이지접속21")는 숫자가 공고마다
  달라 템플릿 판정에 안 걸리고, 짧은 쪽 공고의 분모만 키워 같은 공고(NICE정보통신 catch vs 사람인)를
  다르게 만든다. 사람인 공고의 절반 이상(4,911건 중 2,509건)은 "상세요강" 없이 메타 블록 안에 JD가
  들어 있어 "상세요강" 뒤만 쓰는 방식은 쓸 수 없다
- 사이트마다 줄바꿈이 달라(점핏/수동 등록은 여러 항목을 한 줄로 합침) 줄 단위가 아니라
  문자 조각(SHINGLE 글자) 단위로 비교한다
- 회사 소개/복지/공통 자격요건은 같은 회사의 다른 포지션에도 반복돼(트래블월렛 3년차 vs 리드
  공고가 66줄 중 45줄 공유) 그대로 세면 다른 업무도 같다고 나온다. 조각마다 그 회사 안에서
  "서로 다른 포지션명 몇 개에 나오는지"의 역수로 가중치를 준다. 공고 수로 세면 같은 JD를 여러
  사이트에 재게시한 회사(핀다: 4개 사이트)는 JD 본문 가중치가 낮아지고, 수동 등록 요약본에만
  있는 바뀐 표현이 가중치를 독차지해 같은 업무가 다르게 나온다
- 한쪽이 여러 포지션을 묶은 공고일 수 있어(티빙 집중채용 공고 안에 지원한 팀이 포함) 작은 쪽 기준
  포함도(contained)를 기본으로 쓰고, 포지션명이 다를 때만 양쪽 기준(mutual)을 함께 본다
  한계: DB에 있는 그 회사 포지션명이 2개 이하면 공통 문구 가중치가 충분히 낮아지지 않아, 회사 소개가
  긴 공고는 다른 팀 공고도 같은 업무로 나올 수 있다
- 수동 등록 공고는 사용자가 원문을 요약해 옮겨 적어(리딩투자증권, RDPLINE: 같은 공고인데 0.1 ~ 0.2)
  JD가 달라 보여도 다른 업무로 단정하지 않는다

제목 비교
- 대괄호/괄호 안 팀명과 계열사명은 업무 구분 정보라 남긴다 ("Backend Engineer(Trading Core)" vs
  "(Data)", "[쿠팡페이]" vs "[쿠팡이츠]"). 문자열 유사도는 공통 접두어 때문에 이런 쌍도 0.85 이상이
  나와서 쓰지 않고 단어 집합으로 비교한다
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

SITE_BOILERPLATE_MIN_COMPANIES = 15
MIN_LINE_CHARS = 8
SHORT_LINE_CHARS = 15
SHINGLE = 6
# 비교 가능한 JD로 보는 최소 글자 수(템플릿 제거 후). 사람인 메타만 수집된 공고, catch 이미지 공고,
# 한 줄짜리 수동 등록 공고는 이보다 짧아 제목으로만 판정한다
MIN_JD_CHARS = 150
MANUAL_SITE = "manual"

_CORP_PAT = re.compile(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(재\)|\(사\)|\([^)]*\)|\s")
# 업무를 구분하지 않는 상투어
_TITLE_NOISE_PAT = re.compile(
    r"채용공고|채용|모집|공고|경력직|경력사원|경력|신입|정규직|계약직|인재|집중|수시|상시|연장|담당자?"
    r"|\d{4}\s*년도?|상반기|하반기|~?\s*\d{1,2}\s*/\s*\d{1,2}"
)
_NON_WORD = re.compile(r"[^0-9a-z가-힣]+")
_DIGIT = re.compile(r"\d")


class JobLike(Protocol):
    id: int
    site: str
    company: str
    title: str
    body_text: str | None


def normalize_company(name: str | None) -> str:
    co = _CORP_PAT.sub("", name or "").lower()
    if co.endswith("그룹") and len(co) > 4:
        # 잡코리아는 회사명 뒤에 그룹명을 붙인다("신세계I&C신세계그룹" = 신세계I&C).
        # 회사명이 그룹명으로 시작하는 경우만 그룹명을 떼고, 그 외에는 "그룹"만 뗀다
        # ("현대자동차그룹").
        # 부분 문자열 매칭은 하지 않는다: 카카오 vs 카카오페이, NHN vs NHN페이코는 다른 회사다
        stem = co[:-2]
        for i in range(2, len(stem)):
            head, group = stem[:i], stem[i:]
            if len(group) >= 2 and head.startswith(group) and len(head) > len(group):
                return head
        return stem
    return co


def title_tokens(title: str | None, company: str | None = None) -> frozenset[str]:
    t = _TITLE_NOISE_PAT.sub(" ", (title or "").lower())
    co = normalize_company(company)
    tokens = {w for w in _NON_WORD.split(t) if w}
    # 제목 앞에 붙는 회사명 태그("[빗썸]", "[어니스트AI]")는 업무 구분 정보가 아니다
    return frozenset(w for w in tokens if not (co and (w in co or co in w)))


# 제목 관계
TITLE_SAME = "same"
TITLE_SUBSET = "subset"  # 한쪽이 더 구체적 ("백엔드 개발자" vs "시니어 백엔드 개발자")
TITLE_DIFFERENT = "different"


def title_relation(a: frozenset[str], b: frozenset[str]) -> str:
    if not a or not b:
        return TITLE_DIFFERENT
    if a == b or Counter("".join(a)) == Counter("".join(b)):
        # 글자 구성이 같으면 띄어쓰기/어순만 다른 것 ("여신 JAVA 개발" vs "java 여신개발")
        return TITLE_SAME
    if a <= b or b <= a:
        return TITLE_SUBSET
    return TITLE_DIFFERENT


def _lines(body: str | None) -> set[str]:
    out = set()
    for line in (body or "").splitlines():
        n = _NON_WORD.sub("", line.lower())
        if len(n) >= MIN_LINE_CHARS:
            out.add(n)
    return out


def site_boilerplate(jobs: Iterable[tuple[str | None, str | None]]) -> set[str]:
    """(회사명, 본문) 목록에서 여러 회사에 공통으로 나오는 템플릿 줄을 찾는다."""
    companies: dict[str, set[str]] = {}
    for company, body in jobs:
        co = normalize_company(company)
        for line in _lines(body):
            companies.setdefault(line, set()).add(co)
    return {line for line, cos in companies.items() if len(cos) >= SITE_BOILERPLATE_MIN_COMPANIES}


def jd_shingles(body: str | None, boilerplate: set[str]) -> frozenset[str]:
    parts = []
    for line in (body or "").splitlines():
        n = _NON_WORD.sub("", line.lower())
        if not n or n in boilerplate:
            continue
        if len(n) < SHORT_LINE_CHARS and _DIGIT.search(n):
            continue
        parts.append(n)
    text = "".join(parts)
    if len(text) < MIN_JD_CHARS:
        return frozenset()
    return frozenset(text[i : i + SHINGLE] for i in range(len(text) - SHINGLE + 1))


@dataclass(frozen=True)
class JdSimilarity:
    """가중 포함도. contained: 작은 쪽 기준(한쪽이 다른 쪽에 들어가는 정도),
    mutual: 큰 쪽 기준(양쪽이 서로를 얼마나 덮는지)."""

    contained: float
    mutual: float


def jd_similarity(
    a: frozenset[str], b: frozenset[str], company_df: Counter[str]
) -> JdSimilarity | None:
    """비교할 본문이 없으면 None."""
    if not a or not b:
        return None

    def w(shingles: Iterable[str]) -> float:
        return sum(1.0 / company_df.get(s, 1) for s in shingles)

    wa, wb = w(a), w(b)
    if not wa or not wb:
        return None
    shared = w(a & b)
    return JdSimilarity(contained=shared / min(wa, wb), mutual=shared / max(wa, wb))


# 판정 결과
SAME = "same"  # 같은 업무 (재게시, 사이트별 중복, 포지션명만 다르게 올린 경우 포함)
SAME_UNVERIFIED = "same_unverified"  # 포지션명 동일, JD 비교 불가(한쪽 본문 없음/수동 요약본)
SIMILAR = "similar"  # 포지션명이 포함 관계이거나 JD가 대부분 겹침. 확인 필요
TITLE_ONLY = "title_only"  # 포지션명은 같지만 JD가 다름 (같은 회사의 다른 팀일 가능성 큼)

MATCH_LABELS = {
    SAME: "같은 업무",
    SAME_UNVERIFIED: "같은 업무 추정",
    SIMILAR: "비슷한 업무",
    TITLE_ONLY: "포지션명만 같음",
}

# 임계값 (모듈 docstring의 측정 기준)
# - 포지션명이 같은 쌍: 실제 같은 업무는 0.4 이상(핀다 수동 요약본 0.41), 다른 팀은 엑셈 0.05
# - 포지션명이 다른 쌍은 짧은 공고가 긴 공고에 공통 자격요건만으로 대부분 들어가는 경우(쿠팡페이
#   Payment vs New Product: contained 0.96, mutual 0.27)와, 같은 업무를 영문/한글 제목으로 올린 경우
#   (현대오토에버: contained 1.0, mutual 0.26)를 수치로 가를 수 없어 "비슷한 업무"로 둔다.
#   헤드헌터 공통 양식(커리어커넥트 0.64 ~ 0.71)은 여기서 빠진다
SAME_TITLE_JD_MIN = 0.3
SUBSET_TITLE_JD_SAME = 0.6
SUBSET_TITLE_JD_SIMILAR = 0.25
DIFFERENT_TITLE_JD_MUTUAL = 0.8
DIFFERENT_TITLE_JD_CONTAINED = 0.9


def classify(title_rel: str, jd: JdSimilarity | None, has_manual: bool = False) -> str | None:
    """같은 회사 공고 쌍의 업무 동일성 판정. 다른 업무면 None."""
    if title_rel == TITLE_SAME:
        if jd is None:
            return SAME_UNVERIFIED
        if jd.contained >= SAME_TITLE_JD_MIN:
            return SAME
        return SAME_UNVERIFIED if has_manual else TITLE_ONLY
    if title_rel == TITLE_SUBSET:
        if jd is None:
            return SIMILAR
        if jd.contained >= SUBSET_TITLE_JD_SAME:
            return SAME
        return SIMILAR if jd.contained >= SUBSET_TITLE_JD_SIMILAR or has_manual else None
    if jd is not None:
        if jd.mutual >= DIFFERENT_TITLE_JD_MUTUAL:
            return SAME
        if jd.contained >= DIFFERENT_TITLE_JD_CONTAINED:
            return SIMILAR
    return None


class JobIndex:
    """같은 회사 공고 비교에 필요한 전처리 결과(템플릿 줄, 회사별 조각 빈도)를 묶는다.

    jobs에는 비교 대상 회사의 공고를 모두 넣어야 한다. 회사 공통 문구 가중치가 이 집합에서 나온다.
    """

    def __init__(self, jobs: Iterable[JobLike], boilerplate: set[str]):
        self.boilerplate = boilerplate
        self._shingles: dict[int, frozenset[str]] = {}
        self._titles: dict[int, frozenset[str]] = {}
        self.company_df: dict[str, Counter[str]] = {}
        # 회사별 {포지션명 단어 집합: 그 포지션명 공고들의 조각 합집합}
        groups: dict[str, dict[frozenset[str], set[str]]] = {}
        for j in jobs:
            sh = jd_shingles(j.body_text, boilerplate)
            tt = title_tokens(j.title, j.company)
            self._shingles[j.id] = sh
            self._titles[j.id] = tt
            groups.setdefault(normalize_company(j.company), {}).setdefault(tt, set()).update(sh)
        for co, by_title in groups.items():
            df: Counter[str] = Counter()
            for sh in by_title.values():
                df.update(sh)
            self.company_df[co] = df

    def _sh(self, j: JobLike) -> frozenset[str]:
        if j.id not in self._shingles:
            self._shingles[j.id] = jd_shingles(j.body_text, self.boilerplate)
        return self._shingles[j.id]

    def _tt(self, j: JobLike) -> frozenset[str]:
        if j.id not in self._titles:
            self._titles[j.id] = title_tokens(j.title, j.company)
        return self._titles[j.id]

    def compare(self, a: JobLike, b: JobLike) -> tuple[str, JdSimilarity | None]:
        df = self.company_df.get(normalize_company(a.company), Counter())
        return title_relation(self._tt(a), self._tt(b)), jd_similarity(self._sh(a), self._sh(b), df)

    def match(self, a: JobLike, b: JobLike) -> str | None:
        if a.id == b.id or normalize_company(a.company) != normalize_company(b.company):
            return None
        has_manual = MANUAL_SITE in (a.site, b.site)
        return classify(*self.compare(a, b), has_manual=has_manual)


# ---- 지원 이력과 재지원 판단 ----

STATUS_LABELS = {
    None: "결과대기",
    "doc_passed": "서류합격",
    "doc_rejected": "서류탈락",
    "coding_test": "코딩테스트",
    "job_interview": "직무면접",
    "exec_interview": "임원면접",
    "final_passed": "최종합격",
    "final_rejected": "최종탈락",
}
IN_PROGRESS_STATUSES = {None, "doc_passed", "coding_test", "job_interview", "exec_interview"}
REJECTED_STATUSES = {"doc_rejected", "final_rejected"}

# 같은 업무 탈락 후 재지원을 권하지 않는 기간. 회사마다 재지원 제한 규정이 달라(대개 6개월 ~ 1년)
# 확인된 규정이 아니라 일반적인 하한으로 둔 값이다
REAPPLY_COOLDOWN_DAYS = 180
# 결과대기 상태로 이 기간이 지나면 사실상 불합격(미통보)으로 본다
NO_RESPONSE_DAYS = 45


class EventLike(Protocol):
    label: str
    event_date: date


class AppliedJobLike(JobLike, Protocol):
    application_status: str | None
    first_seen_at: datetime | None
    events: Sequence[EventLike]


@dataclass(frozen=True)
class PriorApplication:
    job_id: int
    site: str
    title: str
    match: str
    status: str | None
    applied_on: date | None
    result_on: date | None
    result_label: str | None = None

    @property
    def match_label(self) -> str:
        return MATCH_LABELS[self.match]

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status or "")


@dataclass(frozen=True)
class Advice:
    level: str  # ok | warn | bad
    text: str


def application_dates(job: AppliedJobLike) -> tuple[date | None, date | None, str | None]:
    """전형 타임라인에서 (지원일, 마지막 결과일, 마지막 결과 이벤트 이름)을 뽑는다.

    지원일은 "지원"이 들어간 가장 이른 이벤트. 없으면 수동 등록 공고의 등록일
    (지원하면서 등록하므로).
    결과일은 지원일보다 늦은 마지막 이벤트. 이벤트 이름("1차면접결과", "코딩테스트결과")으로
    최종탈락이 어느 전형에서 났는지 보여준다.
    """
    events = sorted(job.events, key=lambda e: e.event_date)
    applied = next((e.event_date for e in events if "지원" in e.label), None)
    if applied is None and job.site == MANUAL_SITE and job.first_seen_at:
        applied = job.first_seen_at.date()
    later = [e for e in events if applied is None or e.event_date > applied]
    if not later:
        return applied, None, None
    return applied, later[-1].event_date, later[-1].label


# 이력 표시 우선순위: 같은 업무 판정이 확실한 순
_MATCH_ORDER = {SAME: 0, SAME_UNVERIFIED: 1, SIMILAR: 2, TITLE_ONLY: 3}


def find_prior_applications(
    target: JobLike, applied: Iterable[AppliedJobLike], index: JobIndex
) -> list[PriorApplication]:
    out = []
    for a in applied:
        m = index.match(a, target)
        if m is None:
            continue
        applied_on, result_on, result_label = application_dates(a)
        out.append(
            PriorApplication(
                job_id=a.id,
                site=a.site,
                title=a.title,
                match=m,
                status=a.application_status,
                applied_on=applied_on,
                result_on=result_on,
                result_label=result_label,
            )
        )
    out.sort(key=lambda p: (_MATCH_ORDER[p.match], -(p.applied_on or date.min).toordinal()))
    return out


def _months(days: int) -> str:
    return f"{days // 30}개월" if days >= 60 else f"{days}일"


def reapply_advice(priors: Sequence[PriorApplication], today: date) -> Advice | None:
    """가장 확실한 매칭 이력 기준으로 이번 공고에 지원해도 되는지 한 줄 판단."""
    if not priors:
        return None
    p = priors[0]
    if p.match == TITLE_ONLY:
        # 실제로 같은 업무인데 "지원 가능"으로 안내하면 재지원 제한 기간에 지원하게 되므로
        # 확인을 요구한다
        return Advice("warn", "포지션명은 같고 JD가 다름, 다른 팀 공고인지 확인 후 지원")
    same = p.match in (SAME, SAME_UNVERIFIED)
    what = "같은 업무" if same else "비슷한 업무"

    if p.status in IN_PROGRESS_STATUSES:
        since = (today - p.applied_on).days if p.applied_on else None
        if p.status is None and since is not None and since >= NO_RESPONSE_DAYS:
            return Advice(
                "warn" if same else "ok",
                f"{what} 지원 후 {_months(since)} 무응답, 재게시라면 재지원 검토",
            )
        return Advice(
            "bad" if same else "warn", f"{what} 전형 진행 중({p.status_label}), 중복 지원 불필요"
        )
    if p.status == "final_passed":
        return Advice("warn", f"{what} 최종합격 이력")
    if p.status in REJECTED_STATUSES:
        base = p.result_on or p.applied_on
        if base is None:
            return Advice(
                "warn", f"{what} {p.status_label} 이력, 날짜 미기록이라 재지원 제한 기간 확인 필요"
            )
        days = (today - base).days
        if days < REAPPLY_COOLDOWN_DAYS:
            if same:
                return Advice("bad", f"{_months(days)} 전 {p.status_label}, 재지원 비권장")
            return Advice(
                "warn", f"비슷한 업무 {_months(days)} 전 {p.status_label}, JD 차이 확인 후 지원"
            )
        return Advice("ok", f"{p.status_label} 후 {_months(days)} 경과, 재지원 검토 가능")
    return None

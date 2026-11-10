from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import defer, joinedload, selectinload

from ...db.models import ApplicationEvent, Job, ScoreResult
from ...db.session import session_scope
from ...filters.criteria import employment_kind, extract_min_years, target_tier
from ...resume.export import export_job
from ..templating import templates

router = APIRouter()

VALID_TIERS = {"1", "2", "3", "relay", "hold", "none", "target"}
# "target": 지원 우선순위 등급 전체(1/2/3/연계). "맞춤" 프리셋이 쓴다
TARGET_TIERS = {"1", "2", "3", "relay"}
VALID_EMPLOYMENTS = {"regular", "contract", "freelance"}

COMPANY_TYPES = ["대기업", "중견기업", "중소기업", "공기업", "외국계", "스타트업", "금융업"]
VALID_COMPANY_TYPES = set(COMPANY_TYPES) | {"none"}

PAGE_SIZE = 50

# 지원예정: 아직 지원하지 않은 상태라 is_applied=False로 두고 application_status에만 기록한다.
# VALID_APP_STATUSES(=is_applied=True 전제)와 섞으면 "지원완료" 조회에 딸려 들어와 별도 취급.
PLANNED_STATUS = "planned"

VALID_APP_STATUSES = {
    "doc_passed",
    "doc_rejected",
    "coding_test",
    "job_interview",
    "exec_interview",
    "final_passed",
    "final_rejected",
}

REJECTED_STATUSES = {"doc_rejected", "final_rejected"}

# "지원완료" 필터 전용 정렬 우선순위 (낮을수록 먼저 표시). 결과대기(None)는 서류합격 바로 앞에 배치
APP_STATUS_ORDER = {
    "final_passed": 0,
    "exec_interview": 1,
    "job_interview": 2,
    "coding_test": 3,
    None: 4,
    "doc_passed": 5,
    "final_rejected": 6,
    "doc_rejected": 7,
}


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    site: str | None = Query(None),
    min_rate: str | None = Query(None),
    status: str | None = Query(
        None, description="scored | unscored | planned | applied | ignored | closed"
    ),
    tier: str | None = Query(None, description="1 | 2 | 3 | relay | hold | none | target"),
    max_years: str | None = Query(
        None, description="요구 경력 하한이 N년 이하인 공고만 (미표기 포함)"
    ),
    employment: str | None = Query(None, description="regular | contract | freelance"),
    company_type: str | None = Query(None, description="대기업 | 중견기업 | ... | none(미분류)"),
    q: str | None = Query(None),
    sort: str = Query("rate", description="latest | rate"),
    page: int = Query(1, ge=1),
):
    site = site or None
    status = status or None
    tier = tier if tier in VALID_TIERS else None
    company_type = company_type if company_type in VALID_COMPANY_TYPES else None
    employment = employment if employment in VALID_EMPLOYMENTS else None
    try:
        max_years_val: int | None = int(max_years) if max_years else None
    except ValueError:
        max_years_val = None
    q = q or None
    min_rate_val: int | None
    try:
        min_rate_val = int(min_rate) if min_rate else None
    except ValueError:
        min_rate_val = None
    with session_scope() as session:
        # 목록·검색 어디서도 body_raw(원본 HTML, 활성 row당 평균 ~25KB)를 쓰지
        # 않으므로 defer해 매 요청 직렬화 비용 제거. body_text는 q 검색에 필요해 유지.
        open_jobs = list(
            session.execute(
                select(Job)
                .options(joinedload(Job.score), selectinload(Job.events), defer(Job.body_raw))
                .where(Job.is_closed == False)  # noqa: E712
            ).unique().scalars()
        )
        # first_seen_at/last_seen_at은 SQLite func.now()로 naive UTC 저장 →
        # 비교 기준 now도 naive UTC로 맞춰 9시간 오차 제거 ("신규" 배지·통계 정확)
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        week_ago = now - timedelta(days=7)
        day_ago = now - timedelta(days=1)
        stats = {
            "total": len(open_jobs),
            "scored": sum(1 for j in open_jobs if j.score and j.score.status == "done"),
            "high": sum(
                1
                for j in open_jobs
                if j.score and j.score.status == "done" and (j.score.match_rate or 0) >= 75
            ),
            "recent_week": sum(1 for j in open_jobs if j.first_seen_at and j.first_seen_at >= week_ago),
            "recent_day": sum(1 for j in open_jobs if j.first_seen_at and j.first_seen_at >= day_ago),
        }
        by_site: dict[str, int] = {}
        for j in open_jobs:
            by_site[j.site] = by_site.get(j.site, 0) + 1
        stats["by_site"] = by_site

        # 마감 보기: is_closed=True 공고만 별도 조회 (open_jobs는 is_closed=False라 미포함)
        if status == "closed":
            all_jobs = list(
                session.execute(
                    select(Job)
                    .options(joinedload(Job.score), selectinload(Job.events), defer(Job.body_raw))
                    .where(Job.is_closed == True)  # noqa: E712
                ).unique().scalars()
            )
        # 전형 상태 필터(applied/doc_rejected 등)는 마감된 공고도 포함해야 함
        elif status in VALID_APP_STATUSES or status == "applied":
            all_jobs = list(
                session.execute(
                    select(Job)
                    .options(joinedload(Job.score), selectinload(Job.events), defer(Job.body_raw))
                    .where(Job.is_applied == True)  # noqa: E712
                ).unique().scalars()
            )
        else:
            all_jobs = open_jobs

        if status == "ignored":
            jobs = [j for j in all_jobs if j.is_ignored]
        elif status == "closed":
            jobs = [j for j in all_jobs if not j.is_ignored]
        else:
            jobs = [j for j in all_jobs if not j.is_ignored]
            if status == "scored":
                jobs = [j for j in jobs if j.score and j.score.status == "done"]
            elif status == "unscored":
                jobs = [j for j in jobs if not (j.score and j.score.status == "done")]
            elif status == "applied":
                jobs = [j for j in jobs if j.is_applied]
            elif status == PLANNED_STATUS:
                jobs = [j for j in jobs if j.application_status == PLANNED_STATUS]
            elif status in VALID_APP_STATUSES:
                jobs = [j for j in jobs if j.application_status == status]

        if site:
            jobs = [j for j in jobs if j.site == site]
        if tier:
            # "none": 타겟 외 공고만 (1장 우선순위에 해당하지 않는 공고)
            if tier == "target":
                jobs = [j for j in jobs if target_tier(j.company, j.title) in TARGET_TIERS]
            else:
                want = "" if tier == "none" else tier
                jobs = [j for j in jobs if target_tier(j.company, j.title) == want]
        if max_years_val is not None:
            # 하한 미표기(None) 공고는 남긴다. 경력 무관/협의 공고를 잃지 않기 위함
            jobs = [
                j
                for j in jobs
                if (y := extract_min_years(f"{j.experience or ''}\n{j.body_text or ''}")) is None
                or y <= max_years_val
            ]
        if employment:
            jobs = [
                j
                for j in jobs
                if employment_kind(j.employment_type, j.title, j.body_text or "") == employment
            ]
        if company_type:
            want_type = None if company_type == "none" else company_type
            jobs = [j for j in jobs if j.company_type == want_type]
        if q:
            ql = q.lower()
            jobs = [
                j
                for j in jobs
                if ql in (j.title or "").lower()
                or ql in (j.company or "").lower()
                or ql in (j.body_text or "").lower()
            ]
        if min_rate_val is not None:
            jobs = [j for j in jobs if j.score and (j.score.match_rate or 0) >= min_rate_val]

        if status == "applied":
            # 전형 단계 우선순위로 1차 정렬 후, 같은 단계 내에서는 기존 정렬 기준을 유지
            if sort == "rate":
                jobs.sort(
                    key=lambda j: (
                        j.score.match_rate
                        if j.score and j.score.match_rate is not None
                        else -1
                    ),
                    reverse=True,
                )
            else:
                jobs.sort(key=lambda j: j.first_seen_at, reverse=True)
            jobs.sort(key=lambda j: APP_STATUS_ORDER.get(j.application_status, 99))
        elif sort == "rate":
            jobs.sort(
                key=lambda j: (
                    j.score.match_rate
                    if j.score and j.score.match_rate is not None
                    else -1
                ),
                reverse=True,
            )
        else:
            jobs.sort(key=lambda j: j.first_seen_at, reverse=True)
        if status != "applied" and status not in VALID_APP_STATUSES:
            # 이미 탈락한 공고는 다시 볼 일이 없어 합격률이 높아도 맨 뒤로 보낸다 (안정 정렬이라 기존 순서 유지)
            jobs.sort(key=lambda j: j.application_status in REJECTED_STATUSES)

        # 필터 적용된 전체 매치 수(페이지 슬라이싱 전) — 카운트 표시·페이지 계산용
        filtered_count = len(jobs)
        total_pages = max(1, (filtered_count + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, total_pages)
        start = (page - 1) * PAGE_SIZE
        jobs = jobs[start : start + PAGE_SIZE]

        sites = sorted(by_site.keys())

        # 페이지 링크가 현재 필터를 유지하도록 page를 뺀 쿼리스트링 구성
        base_params = {
            k: v
            for k, v in (
                ("site", site or ""),
                ("min_rate", min_rate_val if min_rate_val is not None else ""),
                ("status", status or ""),
                ("tier", tier or ""),
                ("max_years", max_years_val if max_years_val is not None else ""),
                ("employment", employment or ""),
                ("company_type", company_type or ""),
                ("q", q or ""),
                ("sort", sort),
            )
            if v != ""
        }
        base_qs = urlencode(base_params)

        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "jobs": jobs,
                "sites": sites,
                "company_types": COMPANY_TYPES,
                "stats": stats,
                "now": now,
                "filtered_count": filtered_count,
                "pagination": {
                    "page": page,
                    "total_pages": total_pages,
                    "base_qs": base_qs,
                },
                "filters": {
                    "site": site or "",
                    "min_rate": min_rate_val if min_rate_val is not None else "",
                    "status": status or "",
                    "tier": tier or "",
                    "max_years": max_years_val if max_years_val is not None else "",
                    "employment": employment or "",
                    "company_type": company_type or "",
                    "q": q or "",
                    "sort": sort,
                },
            },
        )


# /jobs/{job_id}는 {job_id:int} 컨버터로 못박아 "new" 같은 비-숫자 경로가
# 절대 매칭되지 않게 한다 (등록 순서와 무관하게 /jobs/new 보호).
@router.get("/jobs/new", response_class=HTMLResponse)
def new_job_form(request: Request):
    """오프플랫폼(기업 채용홈 등) 공고 수동 등록 폼."""
    return templates.TemplateResponse(request, "new_job.html", {})


@router.post("/jobs/new")
def create_manual_job(
    title: str = Form(""),
    company: str = Form(""),
    url: str = Form(""),
    location: str = Form(""),
    body_text: str = Form(""),
    application_status: str = Form("applied"),
):
    """수동 공고를 site='manual'로 생성해 지원 추적에 합류시킨다.

    크롤되지 않는 공고(기업 채용 홈페이지 전용 등)도 대시보드에서
    전형 단계를 추적할 수 있게 한다. is_applied=True로 생성.
    """
    title, company = title.strip(), company.strip()
    if not title or not company:
        raise HTTPException(400, "제목과 회사명은 필수입니다.")

    status = application_status if application_status in VALID_APP_STATUSES else None
    with session_scope() as session:
        job = Job(
            site="manual",
            external_id=f"manual-{uuid4().hex}",
            url=url.strip() or "",
            title=title,
            company=company,
            location=location.strip() or None,
            body_text=body_text.strip() or None,
            is_applied=True,
            application_status=status,
        )
        session.add(job)
    return RedirectResponse("/?status=applied", status_code=303)


@router.get("/jobs/{job_id:int}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: int):
    with session_scope() as session:
        job = session.execute(
            select(Job)
            .options(joinedload(Job.score), selectinload(Job.events))
            .where(Job.id == job_id)
        ).unique().scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "job not found")
        return templates.TemplateResponse(request, "detail.html", {"job": job})


@router.post("/jobs/{job_id:int}/events", response_class=HTMLResponse)
def create_application_event(
    request: Request,
    job_id: int,
    label: str = Form(""),
    event_date: str = Form(""),
    note: str = Form(""),
):
    label = label.strip()
    if not label:
        raise HTTPException(400, "전형 단계명을 입력하세요.")
    try:
        parsed_date = datetime.strptime(event_date.strip().replace(".", "-"), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "날짜 형식이 올바르지 않습니다 (YYYY.MM.DD).") from None
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404)
        session.add(
            ApplicationEvent(
                job_id=job_id, label=label, event_date=parsed_date, note=note.strip() or None
            )
        )
        session.flush()  # autoflush=False → job.events 지연로드가 새 row를 보려면 flush 필요
        return templates.TemplateResponse(request, "_events.html", {"job": job})


@router.post("/jobs/{job_id:int}/events/{event_id:int}/delete", response_class=HTMLResponse)
def delete_application_event(request: Request, job_id: int, event_id: int):
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404)
        event = session.get(ApplicationEvent, event_id)
        if event is None or event.job_id != job_id:
            raise HTTPException(404)
        session.delete(event)
        session.flush()
        return templates.TemplateResponse(request, "_events.html", {"job": job})


@router.get("/jobs/{job_id:int}/analysis", response_class=HTMLResponse)
def get_analysis(request: Request, job_id: int):
    with session_scope() as session:
        job = session.execute(
            select(Job).options(joinedload(Job.score)).where(Job.id == job_id)
        ).unique().scalar_one_or_none()
        if job is None:
            raise HTTPException(404)
        return templates.TemplateResponse(
            request, "_analysis.html", {"job": job}
        )


@router.post("/jobs/{job_id:int}/application-status", response_class=HTMLResponse)
def set_application_status(request: Request, job_id: int, status: str = Form("")):
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404)
        # 드롭다운이 is_applied / application_status / is_ignored를 함께 제어 (정합성 보장)
        if status == "ignored":
            # 관심없음: is_applied/application_status는 건드리지 않음.
            # 해제 시엔 드롭다운에서 고른 값으로 갱신됨 (이전 단계 자동 복원은 아님)
            job.is_ignored = True
        else:
            job.is_ignored = False
            if status == "not_applied":
                job.is_applied = False
                job.application_status = None
            elif status == PLANNED_STATUS:
                # 지원예정은 아직 지원 전이라 is_applied를 올리지 않는다
                job.is_applied = False
                job.application_status = PLANNED_STATUS
            elif status == "applied":
                job.is_applied = True
                job.application_status = None
            elif status in VALID_APP_STATUSES:
                job.is_applied = True
                job.application_status = status
        return templates.TemplateResponse(
            request, "_application_status.html", {"job": job}
        )


@router.post("/jobs/{job_id:int}/plan-apply", response_class=HTMLResponse)
def plan_apply(request: Request, job_id: int):
    """지원예정으로 표시하고 claude_resume에 회사 폴더/공고 md를 만든다.

    파일 생성이 실패해도 상태 변경은 유지하고 버튼에 실패 사유만 표시한다
    (이력서 저장소 경로 문제로 대시보드 조작 자체가 막히지 않게 함).
    """
    with session_scope() as session:
        job = session.execute(
            select(Job).options(joinedload(Job.score)).where(Job.id == job_id)
        ).unique().scalar_one_or_none()
        if job is None:
            raise HTTPException(404)
        # 지원완료 공고를 지원예정으로 되돌리면 전형 단계가 사라진다. 되돌리려면
        # 드롭다운으로 명시적으로 미지원부터 거치게 한다.
        if job.is_applied:
            raise HTTPException(400, "이미 지원한 공고입니다.")
        job.is_ignored = False
        job.application_status = PLANNED_STATUS

        error: str | None = None
        result = None
        try:
            result = export_job(job)
        except Exception as exc:  # 경로 부재·권한 등
            logger.exception("공고 내보내기 실패 job_id={}", job_id)
            error = str(exc)

        return templates.TemplateResponse(
            request,
            "_plan_btn.html",
            {"job": job, "result": result, "error": error},
        )


@router.post("/jobs/{job_id:int}/toggle-closed", response_class=HTMLResponse)
def toggle_closed(request: Request, job_id: int):
    """마감 여부 수동 토글. 크롤로 마감일이 안 잡히는 공고를 수기로 마감/해제."""
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404)
        job.is_closed = not job.is_closed
        return templates.TemplateResponse(request, "_closed_btn.html", {"job": job})

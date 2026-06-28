from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import defer, joinedload

from ...db.models import Job, ScoreResult
from ...db.session import session_scope
from ..templating import templates

router = APIRouter()

PAGE_SIZE = 50

VALID_APP_STATUSES = {
    "doc_passed",
    "doc_rejected",
    "interview",
    "final_passed",
    "final_rejected",
}


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    site: str | None = Query(None),
    min_rate: str | None = Query(None),
    status: str | None = Query(None, description="scored | unscored | applied | ignored"),
    q: str | None = Query(None),
    sort: str = Query("latest", description="latest | rate"),
    page: int = Query(1, ge=1),
):
    site = site or None
    status = status or None
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
                .options(joinedload(Job.score), defer(Job.body_raw))
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

        # 전형 상태 필터(applied/doc_rejected 등)는 마감된 공고도 포함해야 함
        if status in VALID_APP_STATUSES or status == "applied":
            all_jobs = list(
                session.execute(
                    select(Job)
                    .options(joinedload(Job.score), defer(Job.body_raw))
                    .where(Job.is_applied == True)  # noqa: E712
                ).unique().scalars()
            )
        else:
            all_jobs = open_jobs

        if status == "ignored":
            jobs = [j for j in all_jobs if j.is_ignored]
        else:
            jobs = [j for j in all_jobs if not j.is_ignored]
            if status == "scored":
                jobs = [j for j in jobs if j.score and j.score.status == "done"]
            elif status == "unscored":
                jobs = [j for j in jobs if not (j.score and j.score.status == "done")]
            elif status == "applied":
                jobs = [j for j in jobs if j.is_applied]
            elif status in VALID_APP_STATUSES:
                jobs = [j for j in jobs if j.application_status == status]

        if site:
            jobs = [j for j in jobs if j.site == site]
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

        if sort == "rate":
            jobs.sort(key=lambda j: (j.score.match_rate if j.score and j.score.match_rate else -1), reverse=True)
        else:
            jobs.sort(key=lambda j: j.first_seen_at, reverse=True)

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
            select(Job).options(joinedload(Job.score)).where(Job.id == job_id)
        ).unique().scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "job not found")
        return templates.TemplateResponse(request, "detail.html", {"job": job})


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
            elif status == "applied":
                job.is_applied = True
                job.application_status = None
            elif status in VALID_APP_STATUSES:
                job.is_applied = True
                job.application_status = status
        return templates.TemplateResponse(
            request, "_application_status.html", {"job": job}
        )

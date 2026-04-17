from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from ...db.models import Job, ScoreResult
from ...db.session import session_scope
from ...scoring.matcher import score_job
from ..templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    site: str | None = Query(None),
    min_rate: str | None = Query(None),
    status: str | None = Query(None, description="scored | unscored"),
    q: str | None = Query(None),
    sort: str = Query("latest", description="latest | rate"),
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
        all_jobs = list(
            session.execute(select(Job).options(joinedload(Job.score))).unique().scalars()
        )
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        day_ago = now - timedelta(days=1)
        stats = {
            "total": len(all_jobs),
            "scored": sum(1 for j in all_jobs if j.score and j.score.status == "done"),
            "high": sum(
                1
                for j in all_jobs
                if j.score and j.score.status == "done" and (j.score.match_rate or 0) >= 75
            ),
            "recent_week": sum(1 for j in all_jobs if j.first_seen_at and j.first_seen_at >= week_ago),
            "recent_day": sum(1 for j in all_jobs if j.first_seen_at and j.first_seen_at >= day_ago),
        }
        by_site: dict[str, int] = {}
        for j in all_jobs:
            by_site[j.site] = by_site.get(j.site, 0) + 1
        stats["by_site"] = by_site

        jobs = all_jobs
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
        if status == "scored":
            jobs = [j for j in jobs if j.score and j.score.status == "done"]
        elif status == "unscored":
            jobs = [j for j in jobs if not (j.score and j.score.status == "done")]
        if min_rate_val is not None:
            jobs = [j for j in jobs if j.score and (j.score.match_rate or 0) >= min_rate_val]

        if sort == "rate":
            jobs.sort(key=lambda j: (j.score.match_rate if j.score and j.score.match_rate else -1), reverse=True)
        else:
            jobs.sort(key=lambda j: j.first_seen_at, reverse=True)

        sites = sorted(by_site.keys())

        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "jobs": jobs,
                "sites": sites,
                "stats": stats,
                "now": now,
                "filters": {
                    "site": site or "",
                    "min_rate": min_rate_val if min_rate_val is not None else "",
                    "status": status or "",
                    "q": q or "",
                    "sort": sort,
                },
            },
        )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: int):
    with session_scope() as session:
        job = session.execute(
            select(Job).options(joinedload(Job.score)).where(Job.id == job_id)
        ).unique().scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "job not found")
        return templates.TemplateResponse(request, "detail.html", {"job": job})


@router.post("/jobs/{job_id}/score", response_class=HTMLResponse)
def post_score(request: Request, job_id: int):
    try:
        score_job(job_id, force=False)
    except RuntimeError as e:
        logger.warning(f"score conflict: {e}")
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=e).error(f"score failed job={job_id}")
    return _render_score_fragment(request, job_id)


@router.get("/jobs/{job_id}/analysis", response_class=HTMLResponse)
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


@router.post("/jobs/{job_id}/rescore", response_class=HTMLResponse)
def post_rescore(request: Request, job_id: int):
    try:
        score_job(job_id, force=True)
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=e).error(f"rescore failed job={job_id}")
    return _render_score_fragment(request, job_id)


def _render_score_fragment(request: Request, job_id: int) -> HTMLResponse:
    with session_scope() as session:
        job = session.execute(
            select(Job).options(joinedload(Job.score)).where(Job.id == job_id)
        ).unique().scalar_one_or_none()
        if job is None:
            raise HTTPException(404)
        return templates.TemplateResponse(request, "_score.html", {"job": job})

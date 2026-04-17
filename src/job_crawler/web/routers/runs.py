from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse
from loguru import logger
from sqlalchemy import select

from ...crawlers.registry import ACTIVE_SITES
from ...db.models import CrawlRun
from ...db.session import session_scope
from ...pipeline import run as pipeline_run
from ..templating import templates

router = APIRouter()


async def _run_pipeline_safe(sites: list[str], limit: int) -> None:
    try:
        await pipeline_run(sites, limit)
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=e).error(f"manual crawl failed sites={sites} limit={limit}")


@router.get("/runs", response_class=HTMLResponse)
def runs(request: Request):
    with session_scope() as session:
        rows = list(
            session.execute(
                select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(100)
            ).scalars()
        )

        total = len(rows)
        ok = sum(1 for r in rows if r.status == "ok")
        errors = sum(1 for r in rows if r.status == "error")
        total_fetched = sum(r.fetched or 0 for r in rows)
        total_new = sum(r.new_jobs or 0 for r in rows)
        success_rate = int(ok * 100 / total) if total else 0

        by_site: dict[str, dict] = {}
        for r in rows:
            s = by_site.setdefault(
                r.site, {"runs": 0, "ok": 0, "fetched": 0, "new_jobs": 0}
            )
            s["runs"] += 1
            if r.status == "ok":
                s["ok"] += 1
            s["fetched"] += r.fetched or 0
            s["new_jobs"] += r.new_jobs or 0

        summary = {
            "total": total,
            "ok": ok,
            "errors": errors,
            "total_fetched": total_fetched,
            "total_new": total_new,
            "success_rate": success_rate,
            "by_site": sorted(by_site.items()),
        }
        running = [r for r in rows if r.status == "running"]
        return templates.TemplateResponse(
            request,
            "runs.html",
            {
                "runs": rows,
                "summary": summary,
                "active_sites": ACTIVE_SITES,
                "running": running,
            },
        )


@router.post("/crawl", response_class=HTMLResponse)
async def start_crawl(
    request: Request,
    background_tasks: BackgroundTasks,
    site: str = Form(""),
    limit: int = Form(20),
):
    with session_scope() as session:
        in_flight = list(
            session.execute(
                select(CrawlRun).where(CrawlRun.status == "running")
            ).scalars()
        )
    if in_flight:
        sites = ", ".join(r.site for r in in_flight)
        return HTMLResponse(
            f'<span class="chip warn">이미 진행 중인 크롤링이 있습니다 · {sites}</span>'
        )

    limit = max(1, min(limit, 100))
    sites = [site] if site else list(ACTIVE_SITES)
    for s in sites:
        if s not in {"wanted", "saramin", "jobkorea", "toss"}:
            return HTMLResponse(
                f'<span class="chip bad">알 수 없는 사이트: {s}</span>', status_code=400
            )

    background_tasks.add_task(_run_pipeline_safe, sites, limit)
    logger.info(f"manual crawl triggered sites={sites} limit={limit}")
    return HTMLResponse(
        f'<span class="chip ok">크롤링 시작됨 · {", ".join(sites)}</span>'
        f'<span class="muted" style="margin-left:6px; font-size:12px;">곧 진행 상황이 표시됩니다…</span>'
    )


@router.get("/crawl/status", response_class=HTMLResponse)
def crawl_status(request: Request):
    now = datetime.utcnow()
    with session_scope() as session:
        running = list(
            session.execute(
                select(CrawlRun)
                .where(CrawlRun.status == "running")
                .order_by(CrawlRun.started_at)
            ).scalars()
        )
        recent = session.execute(
            select(CrawlRun)
            .where(CrawlRun.status != "running")
            .order_by(CrawlRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    recent_fresh = (
        recent is not None
        and recent.finished_at is not None
        and (now - recent.finished_at) < timedelta(minutes=3)
    )
    return templates.TemplateResponse(
        request,
        "_crawl_status.html",
        {"running": running, "recent": recent, "recent_fresh": recent_fresh, "now": now},
    )

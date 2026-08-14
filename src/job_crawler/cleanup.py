"""마감+미지원 상태로 오래 방치된 공고의 본문(body_text/body_raw/image_urls)을 비우는 아카이브.

스코어링/통계/대시보드 어디에서도 마감된 과거 공고의 본문을 참조하지 않는다(2026-08 조사 확인).
title/company/tech_stack/salary/ScoreResult 등 메타데이터는 그대로 남기고 용량을 많이 차지하는
본문만 비워, 향후 회사 재공고 패턴 추적 같은 활용 가능성은 열어두면서 DB 용량은 줄인다.

되돌릴 수 없는 작업이라(특히 catch는 마감 공고를 재크롤로 복구 불가) 스케줄러에 자동 통합하지 않고
`/cleanup` 스킬을 통해 사용자가 직접 실행한다.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from sqlalchemy import select, text, update

from .config import get_settings
from .db.models import Job
from .db.session import engine, session_scope


def get_archive_candidates(days: int | None = None) -> list[dict]:
    """아카이브 대상(마감+미지원+미아카이브, last_seen_at이 days일 이상 지남) 미리보기."""
    days = days if days is not None else get_settings().job_retention_days
    threshold = datetime.now() - timedelta(days=days)
    with session_scope() as session:
        rows = session.execute(
            select(Job.id, Job.site, Job.company, Job.title, Job.last_seen_at)
            .where(
                Job.is_closed == True,  # noqa: E712
                Job.is_applied == False,  # noqa: E712
                Job.is_archived == False,  # noqa: E712
                Job.last_seen_at < threshold,
            )
            .order_by(Job.last_seen_at.asc())
        ).all()
        return [
            {
                "id": r.id,
                "site": r.site,
                "company": r.company,
                "title": r.title,
                "last_seen_at": r.last_seen_at,
            }
            for r in rows
        ]


def archive_stale_jobs(days: int | None = None) -> int:
    """아카이브 대상의 body_text/body_raw/image_urls를 비우고 is_archived=True로 마킹.

    VACUUM으로 디스크 회수까지 수행.
    """
    days = days if days is not None else get_settings().job_retention_days
    threshold = datetime.now() - timedelta(days=days)
    with session_scope() as session:
        result = session.execute(
            update(Job)
            .where(
                Job.is_closed == True,  # noqa: E712
                Job.is_applied == False,  # noqa: E712
                Job.is_archived == False,  # noqa: E712
                Job.last_seen_at < threshold,
            )
            .values(body_text=None, body_raw=None, image_urls=None, is_archived=True)
        )
        count = result.rowcount

    if count:
        # VACUUM은 트랜잭션 안에서 실행 불가 → session 커밋/종료 후 별도 AUTOCOMMIT 연결로 실행
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("VACUUM"))

    return count


def main() -> None:
    from .logging_setup import setup_logging

    setup_logging()

    parser = argparse.ArgumentParser(description="마감+미지원 오래된 공고 본문 아카이브")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="last_seen_at 기준 N일 이상 지난 공고 대상 (기본 settings.job_retention_days)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="실제 변경 없이 대상 건수/목록만 출력"
    )
    args = parser.parse_args()

    days = args.days if args.days is not None else get_settings().job_retention_days

    if args.dry_run:
        candidates = get_archive_candidates(days=days)
        print(
            f"\n아카이브 대상: {len(candidates)}건 "
            f"(last_seen_at {days}일 이상 경과, 마감+미지원)"
        )
        for c in candidates[:10]:
            print(
                f"  #{c['id']} [{c['site']}] {c['company']} - {c['title']} "
                f"(last_seen: {c['last_seen_at']})"
            )
        if len(candidates) > 10:
            print(f"  ... 외 {len(candidates) - 10}건")
        return

    count = archive_stale_jobs(days=days)
    print(f"아카이브 완료: {count}건")


if __name__ == "__main__":
    main()

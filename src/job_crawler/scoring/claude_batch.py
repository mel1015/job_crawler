"""Claude Code 세션에서 직접 배치 스코링을 수행할 때 사용하는 헬퍼.

사용 흐름:
  1. (사용자) jc-crawl 로 신규 공고 수집
  2. (사용자) Claude Code에서 '새 공고 분석해줘' 요청
  3. (Claude) get_unscored_jobs()로 미평가 공고 조회
  4. (Claude) 이력서와 비교해 점수 산출
  5. (Claude) save_claude_scores()로 결과를 DB에 저장
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select

from ..crawlers.base import IMAGE_ONLY_PLACEHOLDER
from ..db.models import Job, ScoreResult
from ..db.session import session_scope

def _is_image_only(body_text: str | None) -> bool:
    return (body_text or "").strip() == IMAGE_ONLY_PLACEHOLDER


def get_unscored_jobs(limit: int = 50, days: int = 3) -> list[dict]:
    """Claude Code로 미평가된 공고를 dict 리스트로 반환.

    Args:
        limit: 최대 반환 건수
        days: 최근 N일 이내 수집된 공고만 반환 (기본 3일)
    """
    with session_scope() as session:
        cutoff = datetime.now(tz=timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        q = (
            select(Job)
            .outerjoin(Job.score)
            .where(
                Job.is_closed == False,  # noqa: E712
                Job.first_seen_at >= cutoff,
                or_(
                    ScoreResult.id == None,  # noqa: E711
                    and_(
                        ScoreResult.model != "claude-code",
                        ScoreResult.status != "scoring",
                    ),
                ),
            )
            .order_by(Job.first_seen_at.desc())
        )
        q = q.limit(limit)
        jobs = session.execute(q).scalars().all()
        return [
            {
                "id": j.id,
                "site": j.site,
                "company": j.company,
                "title": j.title,
                "location": j.location or "",
                "experience": j.experience or "",
                "tech_stack": j.tech_stack or [],
                "salary": j.salary or "",
                "body_text": (j.body_text or "")[:1500],
                "is_image_only": _is_image_only(j.body_text),
                "image_urls": j.image_urls or [],
            }
            for j in jobs
        ]


def save_claude_scores(scores: list[dict]) -> int:
    """Claude Code가 분석한 점수를 DB에 저장.

    Args:
        scores: [
            {
                "job_id": int,
                "match_rate": int,   # 0-100
                "verdict": str,      # 강한매치 | 적합 | 애매 | 부적합
                "strengths": list[str],
                "gaps": list[str],
                "red_flags": list[str],
                "action_tip": str,
            }
        ]

    Returns:
        저장된 건수
    """
    count = 0
    for s in scores:
        job_id = s["job_id"]
        with session_scope() as session:
            existing = session.execute(
                select(ScoreResult).where(ScoreResult.job_id == job_id)
            ).scalar_one_or_none()
            now = datetime.utcnow()
            if existing is None:
                session.add(
                    ScoreResult(
                        job_id=job_id,
                        status="done",
                        match_rate=int(s.get("match_rate", 0)),
                        verdict=s.get("verdict"),
                        strengths=s.get("strengths") or [],
                        gaps=s.get("gaps") or [],
                        red_flags=s.get("red_flags") or [],
                        action_tip=s.get("action_tip"),
                        model="claude-code",
                        scored_at=now,
                    )
                )
            else:
                existing.status = "done"
                existing.match_rate = int(s.get("match_rate", 0))
                existing.verdict = s.get("verdict")
                existing.strengths = s.get("strengths") or []
                existing.gaps = s.get("gaps") or []
                existing.red_flags = s.get("red_flags") or []
                existing.action_tip = s.get("action_tip")
                existing.model = "claude-code"
                existing.error = None
                existing.scored_at = now
            count += 1
    return count


def main() -> None:
    """미평가 공고 현황 출력."""
    from ..logging_setup import setup_logging

    setup_logging()

    parser = argparse.ArgumentParser(description="미평가 공고 현황 확인")
    parser.add_argument("--days", type=int, default=3, help="최근 N일 이내 공고만 확인 (기본 3)")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    jobs = get_unscored_jobs(limit=args.limit, days=args.days)

    print(f"\n미평가 공고: {len(jobs)}건")
    if not jobs:
        print("분석할 신규 공고가 없습니다.")
        return

    by_site: dict[str, int] = {}
    for j in jobs:
        by_site[j["site"]] = by_site.get(j["site"], 0) + 1
    print("사이트별:", "  ".join(f"{s}:{c}" for s, c in sorted(by_site.items())))
    print("\nClaude Code에서 '새 공고 분석해줘' 라고 요청하세요.")

"""온디맨드 합격률 평가.

호출 경로: 대시보드의 POST /jobs/{id}/score.
자동 파이프라인에서는 호출되지 않는다.
"""
from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy import select

from ..db.models import Job, ScoreResult
from ..db.session import session_scope
from ..resume.loader import load_resume
from ..resume.models import ResumeProfile
from .gemini_client import GeminiClient, GeminiError

SYSTEM_PROMPT = """너는 한국 IT 채용 서류 전형 경험이 많은 테크 리크루터다.
주어진 지원자 이력서와 채용 공고를 비교해 "예상 합격률(서류+1차 면접 통과)"을 산출한다.
점수는 냉정하게 매긴다. 이력서에 증거가 있는 항목만 강점으로 인정한다.
JSON 스키마를 엄격히 준수해 응답한다. 다른 텍스트를 덧붙이지 않는다."""


def _build_prompt(resume: ResumeProfile, job: Job) -> str:
    tech = ", ".join(resume.tech_stack_flat)
    exp_summary = "\n".join(
        f"- {e.company} ({e.start}~{e.end}, {e.months or 0}개월) {e.role or ''}"
        for e in resume.experiences
    )
    projects = "\n".join(
        f"- {p.title} [{', '.join(p.tech_tags)}]" for p in resume.projects
    )

    return f"""[지원자 요약]
이름: {resume.name}
총 경력: {resume.total_experience_years}년 ({resume.total_experience_months}개월)
기술스택: {tech}
경력:
{exp_summary}
개인 프로젝트:
{projects}
자격증: {', '.join(resume.certs)}

[지원자 이력서 원문]
{resume.raw_text}

[채용 공고]
사이트: {job.site}
회사: {job.company}
직무: {job.title}
지역: {job.location or '미표기'}
경력 요건: {job.experience or '미표기'}
기술 태그: {', '.join(job.tech_stack or [])}
연봉: {job.salary or '미표기'}
원문:
{job.body_text or '(본문 없음)'}

[과업]
1. 이 공고에 지원했을 때의 **예상 합격률(0~100 정수)**을 산출해라.
2. 이력서에 증거가 있는 **강점(strengths)** 3~6개를 구체 문장으로 나열.
3. 공고 요건 대비 **부족한 점(gaps)** 2~5개.
4. 명확한 **결격 요소(red_flags)** — 없으면 빈 배열.
5. 지원 전 강조/보강할 **행동 팁(action_tip)** 한 문장.

평가 가이드: 경력 연차 · 필수 기술 일치 · 도메인 경험(금융/ERP 등) · 우대 사항 일치 · 문화/기술 태그 종합."""


def score_job(job_id: int, force: bool = False) -> ScoreResult:
    """단건 평가. 중복 호출 방지 위해 status='scoring' 선점."""
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"job {job_id} not found")
        existing = session.execute(
            select(ScoreResult).where(ScoreResult.job_id == job_id)
        ).scalar_one_or_none()

        if existing and existing.status == "scoring":
            raise RuntimeError(f"job {job_id} is already being scored")
        if existing and existing.status == "done" and not force:
            return existing

        if existing is None:
            existing = ScoreResult(job_id=job_id, status="scoring")
            session.add(existing)
        else:
            existing.status = "scoring"
            existing.error = None
        session.flush()
        score_pk = existing.id
        # snapshot job fields we need outside session
        job_snapshot = {
            "site": job.site,
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "experience": job.experience,
            "tech_stack": job.tech_stack,
            "salary": job.salary,
            "body_text": job.body_text,
        }

    resume = load_resume()

    class _JobShim:  # prompt 빌더가 속성 접근하므로 가벼운 셰이프
        pass

    shim = _JobShim()
    for k, v in job_snapshot.items():
        setattr(shim, k, v)

    prompt = _build_prompt(resume, shim)  # type: ignore[arg-type]

    try:
        client = GeminiClient()
        result = client.generate_json(prompt, system=SYSTEM_PROMPT)
        data = result.data
        logger.info(
            f"scored job {job_id} match_rate={data.get('match_rate')} verdict={data.get('verdict')}"
        )
        with session_scope() as session:
            row = session.get(ScoreResult, score_pk)
            row.status = "done"
            row.match_rate = int(data.get("match_rate", 0))
            row.verdict = data.get("verdict")
            row.strengths = data.get("strengths") or []
            row.gaps = data.get("gaps") or []
            row.red_flags = data.get("red_flags") or []
            row.action_tip = data.get("action_tip")
            row.model = result.model
            row.tokens_in = result.tokens_in
            row.tokens_out = result.tokens_out
            row.error = None
            row.scored_at = datetime.utcnow()
            session.flush()
            session.refresh(row)
            return row
    except GeminiError as e:
        with session_scope() as session:
            row = session.get(ScoreResult, score_pk)
            row.status = "failed"
            row.error = str(e)[:2000]
            session.flush()
        raise

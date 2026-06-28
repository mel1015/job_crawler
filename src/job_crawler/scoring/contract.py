"""스코어링 계약 — verdict 기준·출력 스키마·분석 프롬프트의 단일 출처.

claude_batch.py와 scheduler.py가 이 모듈을 import한다.
CLAUDE.md의 스코어링 섹션은 이 파일을 참조한다.
"""
from __future__ import annotations


# ── verdict 경계 ──────────────────────────────────────────────────────────────

def verdict_for_rate(rate: int) -> str:
    """match_rate → verdict 변환 (강한매치 80+ / 적합 60-79 / 애매 45-59 / 부적합 ~44)."""
    if rate >= 80:
        return "강한매치"
    if rate >= 60:
        return "적합"
    if rate >= 45:
        return "애매"
    return "부적합"


# ── 출력 스키마 ───────────────────────────────────────────────────────────────

SCORE_FIELDS = ("strengths", "gaps", "red_flags")

SCORE_SCHEMA = """\
{
  "job_id": int,
  "match_rate": int,       # 0-100 정수
  "verdict": str,          # 강한매치(80+) | 적합(60-79) | 애매(45-59) | 부적합(~44) | 평가불가
  "strengths": list[str],  # 이력서에 근거한 강점 (최대 5개)
  "gaps": list[str],       # 부족한 부분 (최대 3개)
  "red_flags": list[str],  # 지원 자체를 막는 결격 사유 (없으면 [])
  "action_tip": str        # 지원 시 어필 포인트 또는 보완 방향 한 줄
}"""


def validate_score(s: dict) -> dict:
    """스코어 dict의 list 필드 타입을 보정한 새 dict 반환 (str → [str], None → [])."""
    out = dict(s)
    for field in SCORE_FIELDS:
        val = out.get(field)
        if not isinstance(val, list):
            out[field] = [val] if isinstance(val, str) and val else []
    return out


# ── 분석 프롬프트 ─────────────────────────────────────────────────────────────

def build_analysis_prompt(days: int, limit: int) -> str:
    return f"""\
새 공고 분석 (--days {days} --limit {limit})

## 절차
1. `get_unscored_jobs(days={days}, limit={limit})` 로 미평가 공고 조회
2. 이력서 역량 프로파일 확보 (세션 1회):
   - `from job_crawler.resume.loader import load_resume, load_profile_cache, save_profile_cache`
   - `cached = load_profile_cache()` → 있으면 그대로 역량 기준으로 사용 (재도출 금지)
   - 없으면 `load_resume()` 로 이력서를 읽어 핵심 역량·강점·도메인·연차 요약 dict를 만들고
     `save_profile_cache(profile)` 로 저장한 뒤 그 프로파일을 기준으로 사용
3. 각 공고를 역량 프로파일과 비교해 아래 스키마로 평가
4. `save_claude_scores(scores)` 로 저장 (또는 점수 리스트를 stdin JSON으로 `jc-score`에 전달)

## 출력 스키마
{SCORE_SCHEMA}

## 주의사항
- strengths 는 이력서에 실제 근거가 있는 항목만 기재
- 자기검증: 각 strength를 적기 전 "이력서의 어느 경력/프로젝트/기술이 근거인가"를 확인하고,
  근거를 댈 수 없는 항목은 strengths에서 제외 (근거 환각 방지)
- 이미지 공고(is_image_only=True): image_urls 이미지를 /tmp/ 에 다운로드 후 시각 분석, 동일 스키마로 평가
- 평가 불가(본문 없음·이미지 다운로드 실패 등): verdict="평가불가", match_rate=null
"""

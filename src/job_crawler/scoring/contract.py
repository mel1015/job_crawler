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

## 채점 규칙 (match_rate 산정 — 골든셋 eval로 검증됨, MAE 14→9)
1. hard-reject — 명백한 필수요건 미달일 때만 과감히 낮춘다 (남용 금지).
   공고에 "자격요건/지원자격/필수요건"으로 **명시된** 항목을 프로파일이 충족 못 할 때만 적용:
   - 학력: "석사 이상 필수"인데 프로파일 학력이 미달이면 부적합(0~20). "석사 우대"는 감점 금지.
   - 필수 스택/언어: 특정 언어/솔루션을 필수로 명시했고 프로파일에 없으면 크게 낮춘다.
   - 필수 도메인 경험: "특정 시스템 경험 N년 이상 필수"인데 프로파일에 없으면 낮춘다.
   - 연차 하한: 요구 연차가 프로파일보다 1년 많으면 소폭 감점, 격차 크거나(3년+)
     시니어/리드/팀장급이면 크게 낮춘다.
2. 일반 백엔드 과민 금지: 공고가 일반 Java/Spring 백엔드이고 요구 기술이 프로파일 보유
   스택과 겹치면 hard-reject 대상이 아니다(정상 60~90). 우대/보조 스택(Kotlin/AWS/Kafka 등)
   미보유는 소폭만 반영. 필수요건이 애매하면 깎지 말고 역량 일치도를 그대로 반영하라.
3. 특정 도메인/시스템 경험이 필수면 hard-reject가 언어 일치보다 우선한다 (룰2의 예외):
   "PLM·ERP·SAP 특정 모듈·특정 패키지 솔루션 경험 N년 필수"인데 프로파일에 없으면,
   JAVA/JSP/ORACLE 등 언어가 겹쳐도 부적합(10~30). 언어는 구현 도구일 뿐이고 진짜 필수는
   특정 시스템 경험이다. 특정 시스템 경험을 필수로 요구하는 공고는 일반 백엔드가 아니다.
4. full-range — 점수 0~100을 끝까지 쓴다. 강하게 맞으면 80~95, 명시된 핵심 필수요건이
   안 맞으면 10~30. 모든 공고를 40~70 중간대에 몰지 마라.

## 주의사항
- strengths 는 이력서에 실제 근거가 있는 항목만 기재
- 자기검증: 각 strength를 적기 전 "이력서의 어느 경력/프로젝트/기술이 근거인가"를 확인하고,
  근거를 댈 수 없는 항목은 strengths에서 제외 (근거 환각 방지)
- 이미지 공고(is_image_only=True): image_urls 이미지를 /tmp/ 에 다운로드 후 시각 분석, 동일 스키마로 평가
- 평가 불가(본문 없음·이미지 다운로드 실패 등): verdict="평가불가", match_rate=null
"""

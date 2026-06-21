# ROADMAP — 크롤러 + 스코어링 파이프라인 개선 (에이전트 하네스 관점)

> 모델 자체가 아니라 **모델을 둘러싼 실행 환경**(도구·컨텍스트·루프·메모리·검증·평가)을 개선하는 작업 목록.
> 현재 시스템은 이미 "Claude Code 세션을 스코어링 엔진으로 쓰는" 반(半)에이전트 구조라 하네스 관점이 직접 적용됨.

## 현재 구조의 핵심 약점

두 개의 스코어링 경로가 **평가 계약(프롬프트·기준·스키마)** 이 갈라져 있음.

| | Gemini 온디맨드 (`scoring/matcher.py`) | Claude Code 배치 (`scoring/claude_batch.py`) |
|---|---|---|
| 트리거 | 대시보드 버튼 `POST /jobs/{id}/score` | "새 공고 분석해줘" 수동 |
| 프롬프트 | `SYSTEM_PROMPT` + `_build_prompt` 코드화 | **코드에 없음** — `CLAUDE.md` 문서로만 존재 |
| 스키마 강제 | `response_schema` | 없음 (모델이 알아서) |
| verdict 기준 | Gemini가 산출 | `_verdict_for_rate()` 사후 보정 |

→ 같은 "합격률 평가"인데 한쪽은 코드에, 한쪽은 문서에 규칙이 있어 일관성·재현성이 깨짐.

## 개선 항목 (우선순위 순)

### 1. 스코어링 계약(contract) 통합 — 최우선 / 리스크 낮음
- `matcher.py:20`의 `SYSTEM_PROMPT`/`_build_prompt`와 verdict 기준을 **모델 무관 단일 모듈**(`scoring/contract.py`)로 추출.
- Gemini·Claude 두 경로가 동일 프롬프트·스키마·기준을 import.
- verdict는 두 경로 모두 `_verdict_for_rate()`(`claude_batch.py:25`) 단일 함수로 통일.
- 효과: Claude 배치가 "기준이 CLAUDE.md에만 있어 세션마다 흔들리는" 문제 해소.

### 2. 피드백 루프 — 이 프로젝트만의 최대 기회
- DB의 `application_status`(서류통과/면접/최종)가 **스코어링에 전혀 안 쓰임** — 하네스 메모리의 핵심 누락.
- 과거 "서류 통과 N건 / 탈락 N건"을 few-shot 앵커로 프롬프트에 주입 → 점수 캘리브레이션.
- 효과: 추상적 합격률이 **실제 내 합격 이력에 정렬된 합격률**로 전환.

### 3. 컨텍스트 압축 — 배치 효율
- `_build_prompt`가 이력서 원문 전체(`resume.raw_text`)를 공고마다 반복 주입(50건이면 50회).
- 이력서를 1회 구조화 요약 후 캐싱(Gemini context caching / Claude prompt caching).
- 공고도 본문 전체 대신 "자격요건/우대" 섹션만 추출 후 비교.

### 4. 자기검증(self-critique) 단계
- 현재 `claude_batch.py:137` 보정은 숫자 경계만 검사. 정작 위험한 건 **근거 환각**(이력서에 없는 강점을 strengths에 기입).
- 스코어 산출 후 "각 strength가 이력서 어느 줄에 근거하는가" 검증 패스 추가.
- `matcher.py:22`의 "증거 있는 항목만 인정" 규칙을 사후 검증으로 강제.

### 5. 크롤러 self-healing — 후순위 (ROI 낮음)
- `crawlers/*.py`의 CSS 셀렉터는 DOM 변경 시 조용히 0건 반환(jobkorea 0건 트러블슈팅 항목 존재).
- 0건/파싱실패를 신호로 LLM이 페이지 구조 보고 셀렉터 재발견하는 복구 루프.

### 6. 평가(eval) 골든셋 — 측정 없이는 개선 없음
- 수동 라벨링 골든셋 20~30건 고정 → 프롬프트/모델 변경 시 점수 드리프트 회귀 테스트.
- `tests/test_scoring_regression.py` 형태.

## 추천 착수 순서

1. **스코어링 계약 통합**(#1) — 나머지 개선의 토대
2. **피드백 루프**(#2) — 가장 큰 차별적 가치
3. **자기검증**(#4) + **eval 골든셋**(#6) — 품질 안전망

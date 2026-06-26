# ROADMAP — 크롤러 + 스코어링 파이프라인 개선

> **최종 점검: 2026-06-26.** Gemini 제거 이후 현재 구조를 기준으로 재작성.

## 현재 구조 (실제)

스코어링 경로는 **Claude Code 배치 단일 경로**만 존재 (`scoring/claude_batch.py`).

| 항목 | 현재 상태 |
|---|---|
| 트리거 | `jc-scheduler` → 크롤 완료 후 `claude -p <build_analysis_prompt()>` |
| 프롬프트 | `scoring/contract.py:build_analysis_prompt()` 로 조립. 스키마·기준 명시적 주입 |
| 스키마 강제 | `validate_score()` 가 저장 전 타입 보정 |

## 핵심 약점

**eval 없음**: 프롬프트·기준 변경 시 점수 드리프트를 측정할 수단이 없음.

---

## 개선 항목

### 1. 스코어링 계약 코드화 ✅ 완료

verdict 기준·출력 스키마·분석 프롬프트를 `scoring/contract.py` 단일 출처로 추출.
`validate_score()`가 저장 전 타입 오염 차단. CLAUDE.md는 contract.py를 참조.

### 2. 자기검증(self-critique) 단계

`strengths` 항목이 이력서에 근거 없이 생성될 수 있음 (근거 환각 위험).
스코어 산출 후 "각 strength가 이력서 어느 부분에 근거하는가" 검증 패스 추가.

- **대상 파일**: `scoring/contract.py` — `build_analysis_prompt()`에 검증 지시 추가
- **효과**: "증거 있는 항목만 strength로 인정" 규칙을 프롬프트 레벨에서 강제
- **현황**: 실제 오염 케이스 미관측. 우선순위 낮음

### 3. eval 골든셋 — 측정 없이는 개선 없음

수동 라벨링 공고 20~30건 고정 → 프롬프트/기준 변경 시 점수 드리프트 회귀 테스트.

- **대상 파일**: `tests/test_scoring_regression.py` (신규)
- **현재 테스트**: `test_filters.py`, `test_resume_loader.py` — 스코어링 테스트 없음

### 4. 크롤러 self-healing — 후순위 (ROI 낮음)

0건/파싱실패를 신호로 LLM이 페이지 구조를 보고 CSS 셀렉터를 재발견하는 복구 루프.
jobkorea 0건 트러블슈팅이 반복될 때 착수.

---

## 착수 순서 (권장)

```
계약 코드화 ✅  →  eval 골든셋  →  자기검증  →  크롤러 self-healing
```

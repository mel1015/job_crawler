# ROADMAP — 크롤러 + 스코어링 파이프라인 개선

> **최종 점검: 2026-06-26.** Gemini 제거 이후 현재 구조를 기준으로 재작성.

## 현재 구조 (실제)

스코어링 경로는 **Claude Code 배치 단일 경로**만 존재 (`scoring/claude_batch.py`).

| 항목 | 현재 상태 |
|---|---|
| 트리거 | `jc-scheduler` → 크롤 완료 후 `claude -p "새 공고 분석해줘"` |
| 프롬프트 | CLI에 한 줄 문자열만 전달. 기준·스키마는 세션이 CLAUDE.md를 읽어서 해석 |
| 스키마 강제 | 없음 — 모델이 CLAUDE.md 산문을 따라 자유 형식 출력 |
| 피드백 | `application_status` DB에 있지만 스코어링에 미사용 |

## 핵심 약점

**계약이 산문에만 있음**: 스코어 기준(80+ 강한매치 등)이 코드가 아닌 CLAUDE.md에만 존재. 세션마다 해석이 흔들릴 수 있고, 기준 변경 시 버전 추적이 불가.

---

## 개선 항목

### 1. 스코어링 계약 코드화 — 최우선

현재 CLAUDE.md 산문에만 있는 verdict 기준·출력 스키마를 `scoring/contract.py`로 추출.
`claude -p` 호출 시 계약 파일을 프롬프트에 명시적으로 포함.

```python
# scheduler.py _run_analysis 변경 예시
prompt = CONTRACT_PROMPT + f"\n\n새 공고 {unscored}건 분석해줘 --days 1 --limit {min(unscored, 50)}"
```

- **효과**: 기준 변경이 git diff로 추적 가능, 세션 간 일관성 확보
- **주의**: `_verdict_for_rate()` (`claude_batch.py:25`)는 이미 코드에 있어 그대로 재사용

### 2. 컨텍스트 압축 — 배치 효율

분석 세션이 이력서 원문 전체를 공고마다 반복 비교하고 있음.

- 이력서 1회 구조화 요약 후 세션 내 재사용 (공고 N건이면 N회 반복 주입 → 1회로 단축)
- **대상 파일**: `scoring/claude_batch.py:90` 반환 dict 또는 분석 세션 프롬프트 조립부
- 공고 본문 섹션 추출(자격요건/우대 등)은 사이트마다 헤더 표현이 달라 규칙 기반 불가, LLM 추출은 호출당 비용이 추가되어 ROI 없음 → 미적용

### 3. 자기검증(self-critique) 단계

`strengths` 항목이 이력서에 근거 없이 생성될 수 있음 (근거 환각 위험).
스코어 산출 후 "각 strength가 이력서 어느 부분에 근거하는가" 검증 패스 추가.

- **대상 파일**: `scoring/claude_batch.py:108` (`save_claude_scores` 저장 전 검증)
- **효과**: "증거 있는 항목만 strength로 인정" 규칙을 사후 강제

### 4. eval 골든셋 — 측정 없이는 개선 없음

수동 라벨링 공고 20~30건 고정 → 프롬프트/기준 변경 시 점수 드리프트 회귀 테스트.

- **대상 파일**: `tests/test_scoring_regression.py` (신규)
- **현재 테스트**: `test_filters.py`, `test_resume_loader.py` — 스코어링 테스트 없음

### 5. 크롤러 self-healing — 후순위 (ROI 낮음)

0건/파싱실패를 신호로 LLM이 페이지 구조를 보고 CSS 셀렉터를 재발견하는 복구 루프.
jobkorea 0건 트러블슈팅이 반복될 때 착수.

---

## 착수 순서 (권장)

```
#1 계약 코드화  →  #3 자기검증 + #4 골든셋  →  #2 압축  →  #5 self-healing
```

**#1이 선행되어야 하는 이유**: 기준이 코드로 고정되어야 #3(자기검증)·#4(골든셋)가 일관된 대상을 측정할 수 있음.

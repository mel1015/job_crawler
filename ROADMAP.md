# ROADMAP — 크롤러 + 스코어링 파이프라인

> **최종 점검: 2026-06-28.** 프로젝트 전체 재점검 후 개선(현재 결함)·발전(신규 역량)으로 분리 정리.

## 현재 구조 (실제)

스코어링 경로는 **Claude Code 배치 단일 경로**만 존재 (`scoring/claude_batch.py`).

| 항목 | 현재 상태 |
|---|---|
| 트리거 | `jc-scheduler` (09:00/19:00 KST) → 크롤 완료 후 `claude -p <build_analysis_prompt()>` 자동 실행 |
| 프롬프트 | `scoring/contract.py:build_analysis_prompt()` 로 조립. 스키마·기준 명시적 주입 |
| 스키마 강제 | `validate_score()` 가 저장 전 list 필드 타입 보정 |
| verdict 단일 출처 | `contract.py:verdict_for_rate()` — match_rate→verdict 경계 강제, 불일치 시 보정 |
| 활성 사이트 | wanted · saramin · jobkorea · jumpit · remember · catch (6개, 전부 httpx) |

## 핵심 약점 (불변)

**eval 없음**: 프롬프트·기준 변경 시 점수 드리프트를 측정할 수단이 없음. 여전히 #1 약점.
이 약점이 안 풀리는 근본 원인은 **스코어링 입력 경로가 매 세션 수작업**이라는 점(아래 발전 1 참조).

---

## 개선 (현재 결함 — fix/cleanup)

### A. 임시파일 정리 규약 불일치 ✅ 해소

- **증상(과거)**: `*_tmp.py` 컨벤션과 달리 `.gitignore`·`scheduler.py` cleanup이 `_*` 접두만 대상으로 해 `*_tmp.py` 가 ignore도 cleanup도 안 됨.
- **조치**: `.gitignore`·`_run_analysis` cleanup glob에 `*_tmp.py` 추가, 잔존 tmp 3종 삭제 완료.

### B. 자동 분석 결과 가시성 부족

- `scheduler.py:_run_analysis` 가 `claude -p` 결과를 rc/stderr 일부만 로깅. 실제 몇 건 저장됐는지(`save_claude_scores` 반환) 미기록.
- **해결**: 분석 전/후 `count_unscored_jobs()` 차이를 로그로 남겨 무진행(0건 저장) 조기 감지.

---

## 발전 (신규 역량 — growth)

### 1. 스코어링 입출력 형식화 — eval의 전제조건 🎯

현재 Claude가 매 세션 점수 dict를 하드코딩한 `save_scores_tmp.py` 를 작성→실행한다.
재현 불가·자동화 불가의 근원. 이걸 풀어야 골든셋 회귀도 가능.

- **방향**: `jc-score` CLI 신설 — stdin JSON(list[score dict]) → `validate_score` → `save_claude_scores`.
- **대상 파일**: `scoring/claude_batch.py:main()` 확장 또는 신규 엔트리포인트, `pyproject.toml` scripts 등록.
- **효과**: 수작업 tmp 스크립트 제거(개선 A 동시 해소), 점수 입력을 파이프 가능한 표준 인터페이스로 고정.

### 2. 이력서 역량 프로파일 캐싱 — 반복 분석 비용 제거 🎯

> 사용자 관찰: "이력서는 거의 안 바뀌는데 매 공고 분석마다 역량·강점을 다시 도출해 비교한다."

현황: `load_resume()` 는 이미 MD를 구조화 파싱(`ResumeProfile`: tech_stack·experiences·projects·`total_experience_months`)한다 — 파싱은 결정적·저비용.
**반복되는 진짜 비용은 LLM이 매 세션 "이 지원자의 역량·강점이 무엇인가"를 재해석하는 단계**다. 이 도출이 세션마다 미세하게 달라져 점수 드리프트도 유발한다.

- **방향**: 이력서 내용 해시를 키로 LLM 역량 스냅샷(핵심 역량·강점·도메인·연차 요약)을 1회 도출해 캐싱(`data/resume_profile.json` 등). 해시 변동 시에만 재도출. 분석은 공고 ↔ 캐시된 프로파일을 비교.
- **대상 파일**: `resume/loader.py`(해시·캐시 IO), `scoring/contract.py:build_analysis_prompt()`(프로파일 주입)
- **효과**: 토큰 절감 + **프로파일 일관성 확보 → 드리프트 감소(발전 3 eval과 직결)**

### 3. eval 골든셋 — 측정 없이는 개선 없음

수동 라벨링 공고 20~30건 고정 → 프롬프트/기준 변경 시 점수 드리프트 회귀 테스트.
**발전 1(표준 입력 경로) 위에 얹는다** — 골든 입력 JSON을 `jc-score`로 흘려 결과 비교.

- **대상 파일**: `tests/test_scoring_regression.py` (신규)
- **현재 테스트**: `test_filters.py`(7), `test_resume_loader.py`(8) — 스코어링·파이프라인 테스트 0건
- **지표**: verdict 일치율 + match_rate 평균절대오차(MAE) 임계.

### 4. 오프플랫폼 공고 수동 등록 — 지원 추적 사각지대 해소

> 사용자 관찰: "기업 채용 홈페이지에만 있는 공고에 지원하면 현재 프로젝트로는 지원 상태 추적이 안 된다."

현황: `crawlers/company/`(toss·greeting) 는 존재하나 `ACTIVE_SITES` 외이고 기업별이라 확장성이 없다. 크롤되지 않은 공고는 DB에 없어 `application_status` 트래킹에 합류 불가.

- **방향**: 수동 공고 등록 경로 신설 — `site="manual"` 로 URL·제목·기업·(선택)본문 입력 → 기존 전형 상태 드롭다운·스코어링 흐름에 그대로 합류.
- **대상 파일**: `web/routers/jobs.py`(등록 라우트+폼), `db/models.py`(`external_id` 수동 채번 규칙)
- **효과**: 플랫폼 외 지원도 단일 대시보드에서 전형 단계 추적.

### 5. 지원 결과 기반 약점 역추론 — 사유는 못 받아도 신호는 모은다

> 사용자 관찰(정정): "탈락 사유는 기업이 안 알려줘 지원자가 알 수 없다 — 어떤 약점으로 떨어졌는지 모른다."

전제: 명시적 탈락 사유는 **구조적으로 획득 불가**. 사유 입력 필드를 만드는 건 무의미(지원자도 추측만 가능). 대신 **이미 보유한 결과 레이블**(`application_status`: doc_passed/doc_rejected/final_passed/final_rejected)을 스코어 예측과 대조한다.

- **방향**: "강한매치/적합인데 서류 탈락" 군집에서 반복 출현하는 `gaps`·`red_flags` 패턴을 집계 → 통계적으로 반복 상관되는 잠재 약점 추출. (예: 탈락 공고가 불균형하게 요구한 키워드)
- **대상 파일**: `scoring/` 신규 분석 모듈, 대시보드 리포트
- **전제·한계**: 표본 누적 필요(장기) + 탈락≠부적합(노이즈). **발전 3 eval과 결합** — 지원 결과는 준-정답 레이블로 골든셋을 보강.

### 6. 자기검증(self-critique) 단계

`strengths` 항목이 이력서 근거 없이 생성될 환각 위험.

- **대상 파일**: `scoring/contract.py:build_analysis_prompt()` 에 "각 strength의 이력서 근거 명시" 검증 지시 추가
- **현황**: 실제 오염 케이스 미관측. 우선순위 낮음 (골든셋 구축 후 효과 측정 가능해지면 착수)

### 7. 크롤러 self-healing — 후순위 (ROI 낮음)

0건/파싱실패를 신호로 LLM이 페이지 구조를 보고 CSS 셀렉터를 재발견하는 복구 루프.
6개 사이트 전부 httpx 기반(Playwright는 봇 차단으로 제거)이라 셀렉터 깨짐이 상시 리스크.
jobkorea 0건 트러블슈팅이 반복될 때 착수.

---

## 완료 항목

### 스코어링 계약 코드화 ✅
verdict 기준·출력 스키마·분석 프롬프트를 `scoring/contract.py` 단일 출처로 추출.
`validate_score()`가 저장 전 타입 오염 차단. CLAUDE.md는 contract.py를 참조.

### 자동 분석 연결 ✅
`jc-scheduler` 크롤 완료 후 `claude -p` 자동 트리거 (`scheduler.py:_run_analysis`).

### 마감/중복 처리 견고화 ✅
- saramin 재등록 시 `(site, company, title)` 기준 열린 공고 재사용 (중복 생성 방지)
- `is_applied=True` 공고는 자동 마감 제외 (지원 이력 보호)
- deadline 없는 공고는 7일 미갱신 기준으로만 마감

---

## 착수 순서 (권장)

```
계약 코드화 ✅ · tmp 정리 규약 ✅
  → [개선 B]  자동 분석 로그
  → [발전 1] 스코어링 입력 형식화 (jc-score)
  → [발전 2] 이력서 역량 프로파일 캐싱   ← 저비용·고레버리지(드리프트 감소)
  → [발전 3] eval 골든셋
  → [발전 4] 오프플랫폼 공고 수동 등록   ← 독립 트랙, 사용자 가치 즉시
  → [발전 5] 지원 결과 기반 약점 역추론  ← 표본 누적 후 (장기)
  → [발전 6] 자기검증
  → [발전 7] 크롤러 self-healing
```

> 의존: 발전 5는 발전 4(추적 데이터 확보)·발전 3(레이블 결합)에 선행 의존. 발전 2는 발전 3의 드리프트 안정화 전제.

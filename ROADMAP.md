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

### B. 자동 분석 결과 가시성 부족 ✅ 해소

- **증상(과거)**: `scheduler.py:_run_analysis` 가 `claude -p` 결과를 rc/stderr 일부만 로깅. 실제 저장 건수 미기록.
- **조치**: 분석 전후 `count_unscored_jobs()` 차이로 평가 건수·잔량을 로그에 남기고, rc=0이나 0건 저장 시 "무진행 의심" 경고.

---

## 발전 (신규 역량 — growth)

### 1. 스코어링 입출력 형식화 — eval의 전제조건 ✅ 완료

수작업 `save_scores_tmp.py`(점수 dict 하드코딩→실행)가 재현·자동화 불가의 근원이었음.

- **구현**: `jc-score` CLI 신설(`claude_batch.py:score_main`, pyproject scripts) — stdin JSON(list 또는 `{"scores": [...]}`) → `validate_score` → `save_claude_scores`. 빈 입력·파싱 실패·비-list는 종료코드 1.
- **테스트**: `tests/test_score_cli.py`(stdin 파싱 5케이스, save 모킹)
- **효과**: 수작업 tmp 제거, 점수 입력을 파이프 가능한 표준 인터페이스로 고정.

### 2. 이력서 역량 프로파일 캐싱 — 반복 분석 비용 제거 ✅ 완료

> 사용자 관찰: "이력서는 거의 안 바뀌는데 매 공고 분석마다 역량·강점을 다시 도출해 비교한다."

`load_resume()` 의 MD 파싱(`ResumeProfile`)은 이미 결정적·저비용. 진짜 비용은 **LLM이 매 세션 역량·강점을 재해석하는 단계**(드리프트 유발)였음.

- **구현**: `resume/loader.py` 에 `resume_content_hash()`·`load_profile_cache()`·`save_profile_cache()` 추가 — 이력서 본문 sha256 키로 `data/resume_profile.json` 캐시, 내용 변동 시 자동 무효화. `contract.build_analysis_prompt()` 가 캐시 적중 시 재도출 금지하도록 절차 갱신.
- **테스트**: `tests/test_resume_cache.py`(해시 변동·라운드트립·무효화)
- **효과**: 토큰 절감 + **프로파일 일관성 확보 → 드리프트 감소(발전 3 eval과 직결)**

### 3. eval 골든셋 — 측정 없이는 개선 없음

수동 라벨링 공고 20~30건 고정 → 프롬프트/기준 변경 시 점수 드리프트 회귀 테스트.
**발전 1(표준 입력 경로) 위에 얹는다** — 골든 입력 JSON을 `jc-score`로 흘려 결과 비교.

- **대상 파일**: `tests/test_scoring_regression.py` (신규)
- **현재 테스트**: `test_filters.py`(7), `test_resume_loader.py`(8) — 스코어링·파이프라인 테스트 0건
- **지표**: verdict 일치율 + match_rate 평균절대오차(MAE) 임계.

### 4. 오프플랫폼 공고 수동 등록 — 지원 추적 사각지대 해소 ✅ 완료

> 사용자 관찰: "기업 채용 홈페이지에만 있는 공고에 지원하면 현재 프로젝트로는 지원 상태 추적이 안 된다."

`crawlers/company/`(toss·greeting)는 기업별이라 확장성이 없음. 크롤되지 않은 공고는 DB에 없어 `application_status` 트래킹 불가였음.

- **구현**: `GET/POST /jobs/new`(`web/routers/jobs.py`) + `new_job.html` 폼. `site="manual"`, `external_id="manual-<uuid>"`, `is_applied=True` 로 생성 → 기존 전형 드롭다운·스코어링에 합류. 네비 "공고 추가" 링크·manual 배지 추가.
- **주의**: 두 라우트는 `/jobs/{job_id}`(int)보다 **먼저** 등록(아니면 `/jobs/new` 가 422). DB 마이그레이션 불필요(기존 컬럼 재사용).
- **효과**: 플랫폼 외 지원도 단일 대시보드에서 전형 단계 추적.

### 5. 지원 결과 기반 약점 역추론 — 사유는 못 받아도 신호는 모은다

> 사용자 관찰(정정): "탈락 사유는 기업이 안 알려줘 지원자가 알 수 없다 — 어떤 약점으로 떨어졌는지 모른다."

전제: 명시적 탈락 사유는 **구조적으로 획득 불가**. 사유 입력 필드를 만드는 건 무의미(지원자도 추측만 가능). 대신 **이미 보유한 결과 레이블**(`application_status`: doc_passed/doc_rejected/final_passed/final_rejected)을 스코어 예측과 대조한다.

- **방향**: "강한매치/적합인데 서류 탈락" 군집에서 반복 출현하는 `gaps`·`red_flags` 패턴을 집계 → 통계적으로 반복 상관되는 잠재 약점 추출. (예: 탈락 공고가 불균형하게 요구한 키워드)
- **대상 파일**: `scoring/` 신규 분석 모듈, 대시보드 리포트
- **전제·한계**: 표본 누적 필요(장기) + 탈락≠부적합(노이즈). **발전 3 eval과 결합** — 지원 결과는 준-정답 레이블로 골든셋을 보강.

### 6. 자기검증(self-critique) 단계 ✅ 완료

`strengths` 항목이 이력서 근거 없이 생성될 환각 위험.

- **구현**: `contract.build_analysis_prompt()` 주의사항에 "각 strength의 이력서 근거를 확인하고 근거 없는 항목은 제외" 규칙 추가.
- **남은 검증**: 실제 환각 감소 효과는 발전 3(eval 골든셋) 구축 후 측정 가능.

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
완료 ✅  계약 코드화 · tmp 정리 규약 · 개선 B · 발전 1 · 발전 2 · 발전 4 · 발전 6
남음
  → [발전 3] eval 골든셋               ← 다음 차례 (발전 1·2 위에 얹음). 수동 골든 라벨 필요
  → [발전 5] 지원 결과 기반 약점 역추론  ← 표본 누적 후 (현재 탈락 2건, 장기)
  → [발전 7] 크롤러 self-healing         ← 후순위
```

> 의존: 발전 5는 발전 4(추적 데이터 확보, 완료)·발전 3(레이블 결합)에 선행 의존.
> 발전 3은 발전 1(`jc-score` 입력 경로)·발전 2(프로파일 일관성)가 갖춰져 이제 착수 가능.

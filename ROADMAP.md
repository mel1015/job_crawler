# ROADMAP — 크롤러 + 스코어링 파이프라인

> **최종 점검: 2026-07-11.** 프로젝트 전체 재점검 후 개선(현재 결함)·발전(신규 역량)으로 분리 정리.
> 이번 점검에서 wanted·saramin 크롤이 수일째 전체 실패 중인 활성 결함(개선 C) 발견 → **당일 수리 완료**.

## 현재 구조 (실제)

스코어링 경로는 **Claude Code 배치 단일 경로**만 존재 (`scoring/claude_batch.py`).

| 항목 | 현재 상태 |
|---|---|
| 트리거 | `jc-scheduler` (09:00/19:00 KST) → 크롤 완료 후 `claude -p <build_analysis_prompt()>` 자동 실행 |
| 프롬프트 | `scoring/contract.py:build_analysis_prompt()` 로 조립. 스키마·기준 명시적 주입 |
| 스키마 강제 | `validate_score()` 가 저장 전 list 필드 타입 보정 |
| verdict 단일 출처 | `contract.py:verdict_for_rate()` — match_rate→verdict 경계 강제, 불일치 시 보정 |
| 활성 사이트 | wanted · saramin · jobkorea · jumpit · remember · catch (6개, 전부 httpx) |

## 핵심 약점

**~~eval 없음~~ → 해소됨** (발전 1·3으로 골든셋 회귀 가드 정착, MAE 9.0 baseline).
현재 #1 약점은 **크롤 실패의 침묵**: 사이트 단위 전체 실패(개선 C)가 수일간 지속돼도
CrawlRun.errors 에만 남고 아무도 못 봄. `/check-daemon` 은 수동 호출 전제. → 개선 D(실패 알림) 필요.

---

## 개선 (현재 결함 — fix/cleanup)

### A. 임시파일 정리 규약 불일치 ✅ 해소

- **증상(과거)**: `*_tmp.py` 컨벤션과 달리 `.gitignore`·`scheduler.py` cleanup이 `_*` 접두만 대상으로 해 `*_tmp.py` 가 ignore도 cleanup도 안 됨.
- **조치**: `.gitignore`·`_run_analysis` cleanup glob에 `*_tmp.py` 추가, 잔존 tmp 3종 삭제 완료.

### B. 자동 분석 결과 가시성 부족 ✅ 해소

- **증상(과거)**: `scheduler.py:_run_analysis` 가 `claude -p` 결과를 rc/stderr 일부만 로깅. 실제 저장 건수 미기록.
- **조치**: 분석 전후 `count_unscored_jobs()` 차이로 평가 건수·잔량을 로그에 남기고, rc=0이나 0건 저장 시 "무진행 의심" 경고.

### C. wanted·saramin 크롤 전체 실패 — upsert 중복행 예외 ✅ 해소 (2026-07-11)

- **증상(과거)**: wanted 는 7/2 이후, saramin 은 대부분 `MultipleResultsFound` 로 크롤 run 전체가 error·fetched 0. 두 사이트 신규 공고가 열흘 가까이 수집 안 됨.
- **원인**: `pipeline.py:_upsert_job` 의 saramin 재등록 대응 조회(`(site, company, title, is_closed=0)` → `scalar_one_or_none()`)가 단일행을 전제하는데, DB에 이미 열린 중복 공고 22그룹(saramin 18·wanted 4) 존재 → 예외가 사이트 크롤 전체를 중단시킴.
- **조치**: ① 조회를 `order_by(last_seen_at desc, id desc)` + `scalars().first()` 로 완화(중복 시 최신 재사용) ② 기존 중복 31행 close 처리(그룹당 최신 1건 유지, `?status=closed` 로 복구 가능). 실크롤로 두 사이트 정상 수집 재확인.
- **교훈**: 마감/중복 처리 견고화(완료 항목)가 만든 로직이 자기 자신이 허용한 중복 데이터와 충돌 — 단일행 전제 조회는 항상 다중행 존재를 가정할 것.

### D. 크롤 실패 알림 부재 (개선 C 의 2차 원인)

- **증상**: 사이트 전체 실패가 수일 지속돼도 신호 없음. `/check-daemon` 은 프로세스 생존·최근 수집만 보고 **사이트별 연속 error 를 안 봄**.
- **방향**: `scheduler.py` 크롤 완료 후 CrawlRun status=error 사이트를 로그 WARNING + macOS 알림(`osascript`) 등 저비용 채널로 표면화. `/check-daemon` 판정에 "동일 사이트 연속 N회 error" 추가.

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

### 3. eval 골든셋 — 측정 없이는 개선 없음 ✅ 1차 완료

수동 라벨링 공고 20건 고정 → 프롬프트/기준 변경 시 점수 드리프트 회귀 테스트.

- **구현**: `tests/golden/golden_set.json`(사람 정답 라벨, 익명화) +
  `tests/golden/baseline_scores.json`(현재 프롬프트 평가 기준선) +
  `scoring/eval.py`(`match_rate_mae`/`verdict_agreement`) + `tests/test_scoring_regression.py`(8케이스).
  LLM은 비결정·토큰 문제로 테스트에서 직접 호출하지 않음 — 프롬프트 변경 시 골든셋을 재평가해
  baseline을 갱신하고, 테스트가 사람 라벨 대비 MAE 임계(≤11.0)·verdict 일치(≥60%)를 가드.
- **검증된 효과**: 채점 룰 4개 추가로 MAE 14.0→8.9, verdict 일치 50%→70~75% (발전 6 self-critique 위에 얹음).
- **표본 확대**: 골든셋 20→30건 (2차 10건 추가, MAE 임계 11→12로 재설정). baseline MAE 10.5.
- **라벨 정책 정리**: 5차 룰 개선을 시도하다 "주력 언어 미스매치"를 골든셋에서 0/40/75로 달리 매긴
  비일관(라벨 천장)을 발견. 룰이 아니라 라벨 문제 → **부분 적합(35~50) 정책으로 통일**(해당 3건→40).
  MAE 10.5→9.0, verdict 80%. 교훈: 잔여 오차가 within-band/라벨 노이즈면 룰을 더 얹지 말 것(과적합).
- **남은 것**: 진짜 Java 백엔드 케이스로 표본 추가 확대, 지원 결과(발전 5) 레이블 결합.
- **지표**: verdict 일치율 + match_rate 평균절대오차(MAE) 임계.

### 4. 오프플랫폼 공고 수동 등록 — 지원 추적 사각지대 해소 ✅ 완료

> 사용자 관찰: "기업 채용 홈페이지에만 있는 공고에 지원하면 현재 프로젝트로는 지원 상태 추적이 안 된다."

`crawlers/company/`(toss·greeting)는 기업별이라 확장성이 없음. 크롤되지 않은 공고는 DB에 없어 `application_status` 트래킹 불가였음.

- **구현**: `GET/POST /jobs/new`(`web/routers/jobs.py`) + `new_job.html` 폼. `site="manual"`, `external_id="manual-<uuid>"`, `is_applied=True` 로 생성 → 기존 전형 드롭다운·스코어링에 합류. 네비 "공고 추가" 링크·manual 배지 추가.
- **주의**: 두 라우트는 `/jobs/{job_id}`(int)보다 **먼저** 등록(아니면 `/jobs/new` 가 422). DB 마이그레이션 불필요(기존 컬럼 재사용).
- **효과**: 플랫폼 외 지원도 단일 대시보드에서 전형 단계 추적.

### 5. 지원 결과 기반 약점 역추론 — 사유는 못 받아도 신호는 모은다

> 전제: 기업은 탈락 사유를 알려주지 않으므로 어떤 약점이 원인인지 직접 알 수 없다.

전제: 명시적 탈락 사유는 **구조적으로 획득 불가**. 사유 입력 필드를 만드는 건 무의미(지원자도 추측만 가능). 대신 **이미 보유한 결과 레이블**(`application_status`: doc_passed/doc_rejected/final_passed/final_rejected)을 스코어 예측과 대조한다.

- **방향**: "강한매치/적합인데 서류 탈락" 군집에서 반복 출현하는 `gaps`·`red_flags` 패턴을 집계 → 통계적으로 반복 상관되는 잠재 약점 추출. (예: 탈락 공고가 불균형하게 요구한 키워드)
- **대상 파일**: `scoring/` 신규 분석 모듈, 대시보드 리포트
- **전제·한계**: 표본 누적 필요(장기) + 탈락≠부적합(노이즈). **발전 3 eval과 결합** — 지원 결과는 준-정답 레이블로 골든셋을 보강.
- **착수 조건**: 서류 단계 결과 레이블이 20건 전후 누적되면 1차 집계 시도.

### 6. 자기검증(self-critique) 단계 ✅ 완료

`strengths` 항목이 이력서 근거 없이 생성될 환각 위험.

- **구현**: `contract.build_analysis_prompt()` 주의사항에 "각 strength의 이력서 근거를 확인하고 근거 없는 항목은 제외" 규칙 추가.
- **남은 검증**: 실제 환각 감소 효과는 발전 3(eval 골든셋) 구축 후 측정 가능.

### 7. 크롤러 self-healing — 후순위 (ROI 낮음)

0건/파싱실패를 신호로 LLM이 페이지 구조를 보고 CSS 셀렉터를 재발견하는 복구 루프.
6개 사이트 전부 httpx 기반(Playwright는 봇 차단으로 제거)이라 셀렉터 깨짐이 상시 리스크.
jobkorea 0건 트러블슈팅이 반복될 때 착수.
> 참고: 이번 wanted·saramin 실패(개선 C)는 셀렉터가 아니라 내부 DB 로직 문제 — self-healing 대상 아님. 우선순위 변동 없음.

### 8. 스코어링 병렬 배치 처리 ✅ 완료 (스킬 레벨)

미평가 20건 초과 시 `/analyze` 가 `num_batches = min(4, ceil(N/15))` 로 분할해 general-purpose 에이전트를 병렬 호출,
결과를 메인이 취합해 `save_claude_scores()` 1회 저장(SQLite 락 방지). `.claude/skills/analyze` 에 문서화.

---

## 완료 항목

### 스코어링 계약 코드화 ✅
verdict 기준·출력 스키마·분석 프롬프트를 `scoring/contract.py` 단일 출처로 추출.
`validate_score()`가 저장 전 타입 오염 차단. CLAUDE.md는 contract.py를 참조.

### 자동 분석 연결 ✅
`jc-scheduler` 크롤 완료 후 `claude -p` 자동 트리거 (`scheduler.py:_run_analysis`).

### 마감/중복 처리 견고화 ✅
- saramin 재등록 시 `(site, company, title)` 기준 열린 공고 재사용 (중복 생성 방지)
  — 단, 이 조회의 단일행 전제가 개선 C 의 원인이 됨 (2026-07-11 최신 1건 재사용으로 수리)
- `is_applied=True` 공고는 자동 마감 제외 (지원 이력 보호)
- deadline 없는 공고는 7일 미갱신 기준으로만 마감

### 대시보드·크롤러 유지보수 (2026-07 전반) ✅
- 0점(match_rate=0) 공고가 미평가로 표시되던 버그 수정 / match_rate 없는 평가완료 공고 구분 표시
- 대시보드 기본 정렬을 합격률순으로 변경
- remember 크롤러가 경력 필터로 경력 미설정 공고를 통째로 누락하던 문제 수정
- 스케줄러 임시파일 cleanup 디렉토리 미삭제 버그 수정, `/check-daemon` 스킬 정착

---

## 착수 순서 (권장)

```
완료 ✅  계약 코드화 · tmp 정리 규약 · 개선 A·B·C · 발전 1 · 2 · 3(1차, 30건·MAE 9.0) · 4 · 6 · 8
남음
  → [개선 D] 크롤 실패 알림 (scheduler 경고 + /check-daemon 연속 error 판정)  ← C 재발 시 조기 발견용
  → [발전 5] 지원 결과 기반 약점 역추론  ← 결과 레이블 20건 전후 누적 시 착수
  → [발전 3+] 골든셋 표본 추가 확대 · 발전 5 레이블 결합
  → [발전 7] 크롤러 self-healing         ← 후순위
```

> 의존: 발전 5는 발전 4(추적 데이터 확보, 완료)·발전 3(레이블 결합, 1차 완료)에 선행 의존.
> 개선 C 가 지속되면 미평가 파이프라인 자체에 새 공고가 안 들어오므로 다른 모든 항목보다 앞선다.

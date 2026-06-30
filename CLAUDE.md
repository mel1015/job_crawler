# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 브랜치 전략 (필수)

`feature/<name>` → `develop` (머지) → `main` (PR)

- main, develop에 **직접 커밋/push 금지**
- "git 최신화", "커밋해줘", "올려줘" 등 어떤 표현이든 git 작업 전 **현재 브랜치 확인 필수**
- main 또는 develop이면 **반드시 `git checkout -b feature/<name>` 먼저** 실행

## 문서 동기화 (필수)

기능 추가·버그 픽스 등 코드 수정을 완료하면, 영향받는 md 문서(`CLAUDE.md`의 모델/라우터/마이그레이션/트러블슈팅 등)도 **같은 커밋에 함께 갱신**한다. 사용자가 별도로 "문서 최신화"를 요청하지 않아도 자동으로 수행한다.

## Commands

```bash
# 의존성 설치
pip install -e ".[dev]"

# DB 마이그레이션
mkdir -p data && alembic upgrade head

# 크롤링 실행
jc-crawl --limit 300                          # 전체 ACTIVE_SITES
jc-crawl --site wanted --limit 100            # 단일 사이트
jc-crawl --site wanted --site saramin --limit 100  # 복수 사이트

# 대시보드 (http://127.0.0.1:8000)
jc-web

# 미평가 공고 현황 확인 (Claude Code 세션 스코어링용)
jc-analyze --days 7          # 최근 7일 미평가 공고 건수 출력
jc-analyze --limit 100       # 최대 100건 조회

# 점수 저장 (stdin JSON → DB). 수작업 tmp 스크립트 대체
echo '[{"job_id":1,"match_rate":70,"verdict":"적합",...}]' | jc-score
jc-score < scores.json       # {"scores": [...]} 형식도 허용

# 스케줄러 (09:00 / 19:00 KST 자동 크롤링)
jc-scheduler

# 린트
ruff check src/
ruff format src/

# 타입 체크
mypy src/

# 테스트
pytest
pytest tests/test_resume_loader.py  # 단일 파일
```

## Architecture

### 핵심 파이프라인 (`pipeline.py`)

`run()` → `crawl_site()` 순서:
1. `DESIRED_ROLES` 키워드마다 `crawler.search()` 호출 → `external_id` 기준 dedupe
2. `pass_filters()` 로 블랙리스트/직군/필수키워드 필터링
3. `asyncio.gather` + `Semaphore(CRAWL_CONCURRENCY)` 로 병렬 `crawler.fetch_detail()`
4. SQLite upsert (`_upsert_job`) + `CrawlRun` 이력 기록
5. `_mark_closed_jobs`: deadline_at 경과 또는 7일 미갱신 공고 → `is_closed=True` (`is_applied=True` 공고는 제외)

### 크롤러 (`crawlers/`)

- `BaseCrawler` (ABC): `search()`, `fetch_detail()`, `_throttle()`, `aclose()` 인터페이스
- `registry.py`: `build_crawler(site)` 팩토리 + `ACTIVE_SITES` 목록
- 모든 크롤러는 httpx 기반 (Playwright 미사용). 봇 차단으로 전환됨
- `company/`: 개별 기업 채용페이지 크롤러 (toss 등). ACTIVE_SITES에 포함되지 않음

**새 크롤러 추가 시**: `BaseCrawler` 상속 → `registry.py`에 등록 → 필요 시 `ACTIVE_SITES`에 추가

### 필터링 (`filters/criteria.py`)

`pass_filters()` 체인 (사이트 무관):
1. 제목에 `BLACKLIST_KEYWORDS` 포함 → 탈락
2. 기업명이 `.env BLACKLIST_COMPANIES` 에 포함 → 탈락
3. catch 제외: 제목에 `REQUIRED_KEYWORDS`(없으면 `DEV_KEYWORDS`) 미포함 → 탈락
4. `DESIRED_POSITIONS` 설정 시: `extract_position(title)` 로 직군 분류 → 불일치 탈락
   - 직군 분류 불가(`""`) 또는 generic(`"개발"`)은 항상 통과 (광범위 제목 누락 방지)

### DB (`db/`)

SQLAlchemy 2.0 + Alembic, SQLite (`data/jobs.db`)

모델:
- `Job`: 공고 본문 (`body_text`, `body_raw`), `is_closed`, `is_applied`, `application_status`, `is_ignored`, `last_seen_at`, `score_result` 관계
  - `is_applied`: 지원완료 표시 (기본 목록에 포함)
  - `application_status`: 지원 후 전형 단계. `None`=결과대기, `doc_passed`/`doc_rejected`/`interview`/`final_passed`/`final_rejected`. `is_applied=True`일 때만 의미
  - `is_ignored`: 관심없음 표시 (기본 목록에서 숨김 — `status=ignored` 필터로만 열람)
  - 위 세 필드는 카드의 전형 상태 드롭다운(`_application_status.html`) 하나로 통합 제어 (컨트롤 분산 시 모순 상태 방지)
- `ScoreResult`: 합격률 평가 결과 (`match_rate`, `verdict`, `strengths`, `gaps`, `red_flags`, `action_tip`, `model`). `model='claude-code'` 고정
- `CrawlRun`: 실행 이력 (`site`, `fetched`, `new_jobs`, `status`, `errors`)

마이그레이션 이력:
- `866a1946d299_init.py`: 초기 스키마
- `a1b2c3d4e5f6_add_image_urls_to_jobs.py`: `image_urls` JSON 컬럼 추가
- `b2c3d4e5f6a7_add_is_applied_to_jobs.py`: `is_applied` Boolean 컬럼 추가
- `c3d4e5f6a7b8_add_is_ignored_to_jobs.py`: `is_ignored` Boolean 컬럼 추가
- `d4e5f6a7b8c9_add_application_status_to_jobs.py`: `application_status` String 컬럼 추가 (전형 단계)

### 합격률 평가 (`scoring/`)

**Claude Code 배치 스코어링만 사용** (`scoring/claude_batch.py`). Gemini는 제거됨.
- `get_unscored_jobs(limit, days)`: `ScoreResult IS NULL` 또는 `model != 'claude-code'`인 공고 조회
- `save_claude_scores(scores)`: `model='claude-code'`로 upsert. 저장 전 `validate_score()`로 타입 보정
- `score_main()` (`jc-score`): stdin JSON(list 또는 `{"scores":[...]}`)을 받아 `save_claude_scores` 호출. 수작업 tmp 스크립트 대체
- 대시보드 평가 버튼 없음 — 모든 스코어링은 Claude Code 세션에서 수행

> **이력서 역량 프로파일 캐싱**: `resume/loader.py`의 `load_profile_cache()`/`save_profile_cache()`가
> 이력서 본문 sha256 해시를 키로 `data/resume_profile.json`에 LLM 역량 스냅샷을 캐싱.
> 분석 시 캐시 적중이면 역량 재도출 금지(드리프트 감소·토큰 절감), 이력서 변경 시 해시 불일치로 자동 무효화.

> **스코어 포맷·verdict 기준·분석 프롬프트의 단일 출처: `scoring/contract.py`**
> `verdict_for_rate()`, `SCORE_SCHEMA`, `build_analysis_prompt()` 참조.

> **채점 룰** (`build_analysis_prompt()` 내 "## 채점 규칙"): 골든셋 eval로 검증된 4개 룰.
> ① hard-reject(명시 필수요건 미달만 과감히 ↓: 학력·필수스택·도메인경험·연차), ② 일반 백엔드
> 과민 금지(보유 스택 겹치면 60~90 정상), ③ **특정 시스템 경험(PLM·ERP·SAP모듈 등) 필수면
> 언어 일치보다 hard-reject 우선**(Java 겹쳐도 부적합), ④ full-range(0~100 끝까지, 중간대 회피).
> 사람 라벨 대비 MAE 14→9로 개선 검증(룰 정제 과정에서 ②가 ③ 없이는 PLM류를 과보호하는 부작용 확인).

**Claude 분석 흐름**:
1. `jc-analyze --days 7` → 미평가 건수 확인
2. `jc-scheduler` 또는 직접 `claude -p "$(python -c 'from job_crawler.scoring.contract import build_analysis_prompt; print(build_analysis_prompt(7,50))')"` 실행
3. `get_unscored_jobs()` 조회 → 역량 프로파일(캐시 우선) 비교 → `save_claude_scores()` 또는 `jc-score` 저장
4. 대시보드 `?sort=rate` 로 합격률 순 정렬 확인

> **골든셋 회귀 테스트** (`tests/test_scoring_regression.py`, `tests/golden/`): 채점 룰/프롬프트 변경 시
> 점수 드리프트 가드. `golden_set.json`(사람 정답 라벨 30건+본문) + `baseline_scores.json`(현재 프롬프트
> 평가 기준선) + `scoring/eval.py`(`match_rate_mae`/`verdict_agreement`). LLM은 테스트에서 호출 안 함 —
> **프롬프트 바꾸면 골든셋을 현재 프롬프트로 재평가 → `baseline_scores.json` 갱신** → 테스트가 사람 라벨
> 대비 MAE≤12.0·verdict 일치≥60% 가드. 현재 baseline MAE 9.0(verdict 80%). 사람 정답 라벨 원본은
> `tests/golden/골든셋_라벨링.md`·`tests/golden/골든셋_라벨링_2차.md`. 표본 추출은 `extract_golden*.sql`로 재현.

> **라벨링 정책**: 주력 언어(Java)와 다른 필수 언어를 요구하는 공고는 **부분 적합(35~50)** 으로 일관
> 채점(백엔드 설계·DB·API 역량 전이 인정). 골든셋 내 동일 상황을 0/40/75로 달리 매겼던 비일관(NHN·리디·모카)을
> 40으로 통일 → MAE 10.5→9.0. 골든셋은 회귀 baseline이므로 **케이스 패치 금지, 일반 정책만 추가**(과적합 방지).

**이미지 공고 처리** (`is_image_only=True`인 공고):
- `image_urls` 필드에 이미지 URL 목록 포함. 이미지 공고 스코어링 절차:
  1. `job["is_image_only"] == True` 확인
  2. `job["image_urls"]` 의 각 URL을 Bash로 `/tmp/` 에 다운로드: `curl -sL <url> -o /tmp/img_<job_id>_N.jpg`
  3. `Read` 툴로 이미지 파일 시각적 분석
  4. 분석 결과로 `contract.py`의 스키마와 동일하게 `save_claude_scores()` 저장

### 웹 (`web/`)

FastAPI + Jinja2 + HTMX. 라우터:
- `routers/jobs.py`: 목록/상세/분석 조회/전형 상태 변경(`POST /jobs/{id}/application-status`)/수동 공고 등록(`GET·POST /jobs/new`)/수동 마감 토글(`POST /jobs/{id}/toggle-closed`)
- `routers/runs.py`: 크롤링 이력

> **수동 공고 등록** (`GET·POST /jobs/new`, `new_job.html`): 크롤되지 않는 오프플랫폼 공고(기업 채용홈 등)를
> `site="manual"`·`external_id="manual-<uuid>"`·`is_applied=True`로 생성해 전형 추적에 합류. 두 라우트는
> `/jobs/{job_id}`(int)보다 **먼저** 등록해야 함 (아니면 `/jobs/new`가 `{job_id}="new"`로 매칭돼 422).

> 지원완료·관심없음 토글 버튼(`toggle-applied`/`toggle-ignored` 라우트, `_applied_btn.html`/`_ignored_btn.html`)은 전형 상태 드롭다운으로 통합되며 제거됨. 드롭다운 변경 시 `applyCardStatus()` JS가 카드 색(`st-*` 클래스)을 즉시 갱신하고, hx-post가 DB 저장을 병행.

> **수동 마감 버튼** (`_closed_btn.html`, `POST /jobs/{id}/toggle-closed`): `is_closed`는 `application_status`와 **독립 축**이라 드롭다운에 섞지 않고 별도 버튼으로 둠 (지원완료한 공고도 마감 가능). 크롤로 마감일이 안 잡혀 자동 마감 안 되는 공고를 수기로 마감/해제하는 용도. 클릭 시 `hideCardOnClose()` JS가 현재 뷰와 안 맞으면 카드를 즉시 숨김(단 applied/전형 상태 필터는 `is_closed` 무시하므로 유지), hx-post가 DB 저장 병행. 마감 공고는 `?status=closed`로 열람·복구.

대시보드 필터 (`status` 파라미터):
- `scored` / `unscored`: 평가 완료/미평가
- `applied`: `is_applied=True` 공고 (마감 여부 무관 — `is_closed` 무시)
- `doc_passed`/`doc_rejected`/`interview`/`final_passed`/`final_rejected`: 전형 단계별 공고 (`application_status` 일치, 마감 여부 무관)
- `ignored`: `is_ignored=True` 공고만 표시 (이 외 모든 상태에서는 `is_ignored=False` 공고만 표시)
- `closed`: `is_closed=True` 공고만 별도 조회 (기본 목록은 `is_closed=False`라 미포함). 수동 마감/해제 공고 열람·복구용

> **주의**: `applied`/전형 상태 필터에서는 `is_applied=True` 공고를 별도 쿼리로 조회 (`is_closed` 무시). stats 카운터는 항상 `is_closed=False` 기준으로 산출.

> **주의**: `is_ignored` 필터링은 DB 쿼리가 아닌 Python 리스트 단계에서 처리. `status=ignored`일 때 ignored=True, 그 외엔 ignored=False 공고만 노출. DB 쿼리에서 `is_ignored==False` 조건을 넣으면 "관심없음 보기"가 영원히 빈 리스트가 됨.

### 설정 (`config.py`)

`pydantic-settings` 기반, `.env` 파일 로드. `get_settings()` 로 싱글톤 접근.
주요 설정: `DESIRED_ROLES`, `DESIRED_REGIONS`, `DESIRED_POSITIONS`, `BLACKLIST_COMPANIES`, `REQUIRED_KEYWORDS`, `CRAWL_CONCURRENCY`, `RESUME_PATH`

## 새 사이트 추가 패턴

```python
# crawlers/mysite.py
class MySiteCrawler(BaseCrawler):
    site_name = "mysite"

    async def search(self, criteria: SearchCriteria) -> list[JobSummary]: ...
    async def fetch_detail(self, summary: JobSummary) -> JobDetail: ...
```

`registry.py`의 `build_crawler()`에 분기 추가, `ACTIVE_SITES`에 추가.

## 트러블슈팅

| 증상 | 해결 |
|------|------|
| saramin 타임아웃 | `.env`의 `REQUEST_DELAY_SEC` 증가 (예: 5) |
| jobkorea 결과 0건 | `crawlers/jobkorea.py:_parse_list` CSS 셀렉터 확인 |
| catch body_text 이미지 공고 placeholder | 이미지 공고 — Claude Code 세션에서 이미지 다운로드 후 시각 분석 |
| `jc-crawl` 명령 없음 | `pip install -e .`가 아닌 `source .venv/bin/activate` 먼저 확인 |
| `save_claude_scores` ModuleNotFoundError | 스크립트에 `sys.path.insert(0, "<repo root>/src")` 추가 |
| `alembic upgrade head` 실패 | `mkdir -p data` 먼저 실행 |
| 대시보드 포트 충돌 (Errno 48) | `lsof -i :8000 -n -P` 로 PID 확인 후 `kill <PID>` |
| `load_resume()` TypeError | `ResumeProfile` 객체 반환 — 텍스트는 `.raw_text`, 임포트는 `job_crawler.resume.loader` |
| 카드 클릭 시 드롭다운 대신 상세로 이동 | select에 `event.stopPropagation()` 필요. 카드 `onclick`의 `closest()` 제외 대상에 `select` 포함 |
| 드롭다운 바꿔도 카드 색 즉시 안 변함 | fragment 스왑은 드롭다운만 갱신 → `applyCardStatus()` JS로 `.job-card` 클래스 즉시 변경 |
| 관심없음 선택해도 기본 목록에서 안 사라짐 | `applyCardStatus()`가 `status≠ignored`일 때 `style.display='none'` 처리 (DB 저장은 hx-post 병행) |
| 상세에서 마감/상태 변경 후 뒤로가기 시 목록 반영 안 됨 | 브라우저 bfcache가 옛 목록 복원 → `base.html` `pageshow` 핸들러가 `e.persisted`/nav type=`back_forward`면 `location.reload()` |

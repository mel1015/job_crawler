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
5. `_mark_closed_jobs`: deadline_at 경과 또는 7일 미갱신 공고 → `is_closed=True`

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
- 대시보드 평가 버튼 없음 — 모든 스코어링은 Claude Code 세션에서 수행

> **스코어 포맷·verdict 기준·분석 프롬프트의 단일 출처: `scoring/contract.py`**
> `verdict_for_rate()`, `SCORE_SCHEMA`, `build_analysis_prompt()` 참조.

**Claude 분석 흐름**:
1. `jc-analyze --days 7` → 미평가 건수 확인
2. `jc-scheduler` 또는 직접 `claude -p "$(python -c 'from job_crawler.scoring.contract import build_analysis_prompt; print(build_analysis_prompt(7,50))')"` 실행
3. `get_unscored_jobs()` 조회 → 이력서 비교 → `save_claude_scores()` 저장
4. 대시보드 `?sort=rate` 로 합격률 순 정렬 확인

**이미지 공고 처리** (`is_image_only=True`인 공고):
- `image_urls` 필드에 이미지 URL 목록 포함. 이미지 공고 스코어링 절차:
  1. `job["is_image_only"] == True` 확인
  2. `job["image_urls"]` 의 각 URL을 Bash로 `/tmp/` 에 다운로드: `curl -sL <url> -o /tmp/img_<job_id>_N.jpg`
  3. `Read` 툴로 이미지 파일 시각적 분석
  4. 분석 결과로 `contract.py`의 스키마와 동일하게 `save_claude_scores()` 저장

### 웹 (`web/`)

FastAPI + Jinja2 + HTMX. 라우터:
- `routers/jobs.py`: 목록/상세/분석 조회/전형 상태 변경(`POST /jobs/{id}/application-status`)
- `routers/runs.py`: 크롤링 이력

> 지원완료·관심없음 토글 버튼(`toggle-applied`/`toggle-ignored` 라우트, `_applied_btn.html`/`_ignored_btn.html`)은 전형 상태 드롭다운으로 통합되며 제거됨. 드롭다운 변경 시 `applyCardStatus()` JS가 카드 색(`st-*` 클래스)을 즉시 갱신하고, hx-post가 DB 저장을 병행.

대시보드 필터 (`status` 파라미터):
- `scored` / `unscored`: 평가 완료/미평가
- `applied`: `is_applied=True` 공고
- `doc_passed`/`doc_rejected`/`interview`/`final_passed`/`final_rejected`: 전형 단계별 공고 (`application_status` 일치)
- `ignored`: `is_ignored=True` 공고만 표시 (이 외 모든 상태에서는 `is_ignored=False` 공고만 표시)

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

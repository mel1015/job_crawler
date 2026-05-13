# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 브랜치 전략 (필수)

`feature/<name>` → `develop` (머지) → `main` (PR)

- main, develop에 **직접 커밋/push 금지**
- "git 최신화", "커밋해줘", "올려줘" 등 어떤 표현이든 git 작업 전 **현재 브랜치 확인 필수**
- main 또는 develop이면 **반드시 `git checkout -b feature/<name>` 먼저** 실행

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
5. `_mark_closed_jobs`: deadline_at 경과 또는 14일 미갱신 공고 → `is_closed=True`

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
- `Job`: 공고 본문 (`body_text`, `body_raw`), `is_closed`, `last_seen_at`, `score_result` 관계
- `ScoreResult`: 합격률 평가 결과 (`match_rate`, `verdict`, `strengths`, `gaps`, `red_flags`, `action_tip`, `model`). `model` 필드로 Gemini/claude-code 구분
- `CrawlRun`: 실행 이력 (`site`, `fetched`, `new_jobs`, `status`, `errors`)

### 합격률 평가 (`scoring/`)

**Gemini 온디맨드**: 자동 호출 금지. 대시보드 버튼(`POST /jobs/{id}/score`)으로만 트리거.
- `matcher.py`: `status=scoring` 락으로 중복 호출 방지
- `gemini_client.py`: `response_schema` 기반 JSON 강제 출력

**Claude Code 배치 스코어링** (`scoring/claude_batch.py`): Gemini API 비용 없이 Claude Code 세션 자체를 분석 엔진으로 활용.
- `get_unscored_jobs(limit, days)`: `ScoreResult IS NULL` 또는 `model != 'claude-code'`인 공고 조회
- `save_claude_scores(scores)`: `model='claude-code'`로 upsert, Gemini 점수도 덮어씀
- 스코어 포맷: `{"job_id", "match_rate", "verdict", "strengths", "gaps", "red_flags", "action_tip"}`
- verdict 기준: 강한매치(80+) / 적합(60-79) / 애매(45-59) / 부적합(~44)

**Claude 분석 흐름**:
1. `jc-analyze --days 7` → 미평가 건수 확인
2. Claude Code에서 "새 공고 분석해줘" 요청
3. `get_unscored_jobs()` 조회 → 이력서 비교 → `save_claude_scores()` 저장
4. 대시보드 `?sort=rate` 로 합격률 순 정렬 확인

### 웹 (`web/`)

FastAPI + Jinja2 + HTMX. 라우터:
- `routers/jobs.py`: 목록/상세/합격률 평가/재평가
- `routers/runs.py`: 크롤링 이력

### 설정 (`config.py`)

`pydantic-settings` 기반, `.env` 파일 로드. `get_settings()` 로 싱글톤 접근.
주요 설정: `DESIRED_ROLES`, `DESIRED_REGIONS`, `DESIRED_POSITIONS`, `BLACKLIST_COMPANIES`, `REQUIRED_KEYWORDS`, `CRAWL_CONCURRENCY`, `GEMINI_API_KEY`, `RESUME_PATH`

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
| catch body_text 비어있음 | 이미지 공고 — 정상 동작 |
| 합격률 평가 500 에러 | `.env`의 `GEMINI_API_KEY` 확인 |
| `jc-analyze` 명령 없음 | `pip install -e .` 재실행 |
| `save_claude_scores` ModuleNotFoundError | 스크립트에 `sys.path.insert(0, "<repo root>")` 추가 |
| `alembic upgrade head` 실패 | `mkdir -p data` 먼저 실행 |

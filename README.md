# job_crawler

내 조건(직무/스택/연차/지역)에 맞는 채용 공고를 여러 사이트에서 수집하고,
Claude Code로 이력서 기반 **예상 합격률**을 평가해주는 로컬 도구.

## 특징

- **다중 사이트**: 원티드·사람인·잡코리아·점핏·리멤버·캐치 6개 사이트 지원
- **조건 기반 수집**: `.env`의 키워드별로 반복 검색 → `external_id` 기준 병합(dedupe)
- **병렬 fetch**: `asyncio.gather` + `Semaphore(CRAWL_CONCURRENCY)` — 동시 N개 상세 조회
- **세분화 필터**: 블랙리스트 키워드/기업명, 직군 화이트리스트, 제목 필수 키워드
- **Claude Code 배치 스코어링**: API 비용 없이 Claude Code 세션에서 직접 이력서 매칭 분석 (`scoring/claude_batch.py`)
- **저장**: SQLite (`data/jobs.db`), SQLAlchemy 2.0 + Alembic
- **UI**: FastAPI + HTMX 대시보드 (필터/정렬/상세/합격률 분석/전형 상태 관리)
- **스케줄**: APScheduler (09:00 / 19:00 KST) + 크롤 완료 후 자동 분석

## 지원 사이트

| 사이트 | 방식 | 비고 |
|--------|------|------|
| 원티드 | `/api/v4/jobs` (httpx JSON) | offset 페이지네이션 |
| 사람인 | httpx + BeautifulSoup | SSR HTML, recruitPage 페이지네이션 |
| 잡코리아 | httpx + BeautifulSoup | page 파라미터 페이지네이션 |
| 점핏 | `jumpit.saramin.co.kr/api/positions` (httpx JSON) | page 페이지네이션 |
| 리멤버 | httpx JSON | 경력직 특화 |
| 캐치 | httpx + BeautifulSoup | SSR 상세 페이지 (`controls/recruitDetail/{id}`) |

> Playwright는 봇 차단으로 httpx로 통일. 토스 등 client-side 렌더링 사이트는 `crawlers/company/` 에 개별 구현.

## 디렉토리

```
src/job_crawler/
├── config.py              # pydantic-settings (.env 연동)
├── pipeline.py            # crawl → dedupe → filter → parallel fetch → upsert
├── scheduler.py           # APScheduler 엔트리 + 크롤 후 자동 분석
├── crawlers/
│   ├── base.py            # BaseCrawler / SearchCriteria / JobSummary / JobDetail
│   ├── wanted.py
│   ├── saramin.py
│   ├── jobkorea.py
│   ├── jumpit.py
│   ├── remember.py
│   ├── catch.py
│   ├── registry.py        # ACTIVE_SITES, build_crawler()
│   └── company/           # 개별 기업 채용 페이지 (toss 등, ACTIVE_SITES 미포함)
├── db/models.py           # Job / ScoreResult / CrawlRun
├── resume/loader.py       # MD → dict + 역량 프로파일 캐시
├── scoring/
│   ├── contract.py        # 스키마·verdict 기준·분석 프롬프트 단일 출처
│   ├── claude_batch.py    # get_unscored_jobs / save_claude_scores / jc-score CLI
│   └── eval.py            # 골든셋 회귀 평가 (match_rate_mae / verdict_agreement)
├── filters/criteria.py    # BLACKLIST_KEYWORDS, DEV_KEYWORDS, extract_position, pass_filters
└── web/                   # FastAPI + Jinja2 (HTMX)
```

## 셋업

### 1. Python 3.11+ 가상환경 생성

```bash
cd /path/to/job_crawler
python3.11 -m venv .venv
source .venv/bin/activate
```

### 2. 의존성 설치

```bash
pip install -e ".[dev]"
```

### 3. `.env` 작성

```bash
cp .env.example .env
```

필수 편집 항목:

| 변수 | 설명 | 예시 |
|------|------|------|
| `RESUME_PATH` | 이력서 MD 파일 절대 경로 | `/Users/.../메인_이력서.md` |
| `DESIRED_ROLES` | 검색 키워드 (쉼표 구분) | `백엔드,Backend,서버,Java,Spring,금융,핀테크,SAP` |
| `DESIRED_REGIONS` | 지역 (쉼표 구분) | `서울,경기,판교` |
| `DESIRED_EXPERIENCE_MIN` / `MAX` | 연차 범위 | `2` / `5` |
| `DESIRED_POSITIONS` | 직군 화이트리스트, 빈값=전체 허용 | `백엔드,풀스택,ML/AI,웹개발` |
| `BLACKLIST_COMPANIES` | 제외 기업명 (쉼표 구분) | `회사A,회사B` |
| `REQUIRED_KEYWORDS` | 제목 필수 키워드, 빈값=내장 DEV_KEYWORDS 사용 | `개발,engineer,백엔드` |
| `CRAWL_CONCURRENCY` | 동시 fetch_detail 수 | `5` |
| `REQUEST_DELAY_SEC` | 요청 간 딜레이(초) | `1.0` |

`DESIRED_POSITIONS` 허용 값: `백엔드`, `프론트엔드`, `풀스택`, `모바일`, `DevOps`, `데이터`, `ML/AI`, `DBA`, `QA`, `보안`, `웹개발`

### 4. DB 마이그레이션

```bash
mkdir -p data
alembic upgrade head
```

## 실행

### 크롤링 (수동)

```bash
# 전체 활성 사이트 (ACTIVE_SITES)
jc-crawl --limit 300

# 단일 사이트
jc-crawl --site wanted --limit 100
jc-crawl --site saramin --limit 100

# 여러 사이트
jc-crawl --site wanted --site saramin --limit 100
```

동작:
1. `DESIRED_ROLES`의 키워드마다 각각 검색
2. `external_id`로 병합하여 중복 제거
3. 필터링 (`BLACKLIST_KEYWORDS`, `REQUIRED_KEYWORDS`, `DESIRED_POSITIONS`)
4. `asyncio.gather`로 병렬 상세 조회 (동시 `CRAWL_CONCURRENCY`개)
5. SQLite에 upsert, `crawl_runs`에 실행 이력 기록

### 합격률 평가 (Claude Code)

모든 스코어링은 Claude Code 세션에서 수행한다. 대시보드에 평가 버튼 없음.

```bash
# 미평가 건수 확인
jc-analyze --days 7

# Claude Code 세션에서 분석 실행 (/analyze 스킬 또는 직접)
claude -p "$(python -c 'from job_crawler.scoring.contract import build_analysis_prompt; print(build_analysis_prompt(7,50))')"

# 점수 저장 (stdin JSON)
echo '[{"job_id":1,"match_rate":70,"verdict":"적합",...}]' | jc-score
jc-score < scores.json
```

### 대시보드

```bash
jc-web
# → http://127.0.0.1:8000
```

- 목록: 사이트/회사/제목/합격률/버딕트/등록일 + 필터/정렬
- 상세: `/jobs/{id}` — 원문 링크, 기술스택, 본문, 평가 결과
- **전형 상태 드롭다운**: 결과대기 → 서류통과 / 서류탈락 / 면접 / 최종합격 / 최종탈락
- **수동 마감 버튼**: `POST /jobs/{id}/toggle-closed` — 자동 마감 안 잡히는 공고 수동 처리
- **공고 직접 등록**: `GET/POST /jobs/new` — 크롤 안 되는 오프플랫폼 공고 수동 추가

### 스케줄러

```bash
nohup .venv/bin/jc-scheduler > logs/scheduler.log &
```

매일 09:00 / 19:00 KST에 `ACTIVE_SITES` 전부 크롤링 → 완료 후 미평가 공고 자동 분석.

## 대시보드 필터

| 필터 | 설명 |
|------|------|
| 검색 | 제목·회사·본문 텍스트 검색 |
| 사이트 | 특정 사이트만 표시 |
| 평가완료 | ScoreResult가 있는 공고만 |
| 미평가 | ScoreResult가 없는 공고만 |
| 지원완료 | `is_applied=True` 공고만 |
| 관심없음 | `is_ignored=True` 공고만 (기본 목록에서는 숨김) |
| 합격률 최소값 | match_rate ≥ N% 필터 |
| 정렬 | 최신순 / 합격률순 |

## 필터링 동작

```
제목 BLACKLIST_KEYWORDS 체크
    → 기업명 BLACKLIST_COMPANIES 체크
    → (catch 제외) REQUIRED_KEYWORDS 제목 포함 여부 체크
    → DESIRED_POSITIONS 직군 화이트리스트 체크
        (직군 분류 불가 "" 또는 generic "개발"은 통과)
```

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| saramin 타임아웃 | IP 차단 | `REQUEST_DELAY_SEC` 증가 (예: 5) |
| jobkorea 결과 0건 | Tailwind 셀렉터 개편 | `crawlers/jobkorea.py:_parse_list` 셀렉터 확인 |
| catch body_text 비어있음 | 이미지 공고 | Claude Code 세션에서 `image_urls` 이미지 다운로드 후 시각 분석 |
| `alembic upgrade head` 실패 | `data/` 디렉토리 없음 | `mkdir -p data` |
| `jc-crawl` 명령 없음 | venv 미활성화 | `pip install -e .` 아닌 `source .venv/bin/activate` |
| 대시보드 포트 충돌 (Errno 48) | 기존 프로세스 살아있음 | `lsof -i :8000 -n -P` → `kill <PID>` |
| `save_claude_scores` ModuleNotFoundError | sys.path 누락 | 스크립트에 `sys.path.insert(0, "<repo root>/src")` 추가 |
| `load_resume()` TypeError | ResumeProfile 객체 반환 | 텍스트는 `.raw_text`, 임포트는 `job_crawler.resume.loader` |

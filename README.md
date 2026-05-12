# job_crawler

내 조건(직무/스택/연차/지역)에 맞는 채용 공고를 여러 사이트에서 수집하고,
필요할 때만 Gemini API로 이력서 기반 **예상 합격률**을 평가해주는 로컬 도구.

## 특징

- **다중 사이트**: 원티드·사람인·잡코리아·점핏·리멤버·캐치 6개 사이트 지원
- **조건 기반 수집**: `.env`의 키워드별로 반복 검색 → `external_id` 기준 병합(dedupe)
- **병렬 fetch**: `asyncio.gather` + `Semaphore(CRAWL_CONCURRENCY)` — 동시 N개 상세 조회
- **세분화 필터**: 블랙리스트 키워드/기업명, 직군 화이트리스트, 제목 필수 키워드
- **합격률 평가는 온디맨드**: 자동 호출 금지, 대시보드에서 건별 버튼으로만 Gemini 호출
- **저장**: SQLite (`data/jobs.db`), SQLAlchemy 2.0 + Alembic
- **UI**: FastAPI + HTMX 대시보드 (필터/정렬/상세/합격률 분석)
- **스케줄**: APScheduler (09:00 / 19:00 KST)

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
├── scheduler.py           # APScheduler 엔트리
├── crawlers/
│   ├── base.py            # BaseCrawler / SearchCriteria / JobSummary / JobDetail
│   ├── wanted.py
│   ├── saramin.py
│   ├── jobkorea.py
│   ├── jumpit.py
│   ├── remember.py
│   ├── catch.py
│   ├── registry.py        # ACTIVE_SITES, build_crawler()
│   └── company/           # 개별 기업 채용 페이지 (toss 등)
├── db/models.py           # Job / ScoreResult / CrawlRun
├── resume/loader.py       # MD → dict
├── scoring/
│   ├── gemini_client.py   # response_schema 기반 JSON 강제
│   └── matcher.py         # 단건 평가 (status=scoring 락)
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
| `GEMINI_API_KEY` | Gemini API 키 | `AIza...` |
| `GEMINI_MODEL` | 모델 | `gemini-2.5-flash` |
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
.venv/bin/python -m job_crawler.pipeline --limit 300

# 단일 사이트
.venv/bin/python -m job_crawler.pipeline --site wanted --limit 100
.venv/bin/python -m job_crawler.pipeline --site saramin --limit 100

# 여러 사이트
.venv/bin/python -m job_crawler.pipeline --site wanted --site saramin --limit 100
```

또는 가상환경 활성화 후:

```bash
source .venv/bin/activate
jc-crawl --limit 300
jc-crawl --site wanted --limit 100
```

동작:
1. `DESIRED_ROLES`의 키워드마다 각각 검색
2. `external_id`로 병합하여 중복 제거
3. 필터링 (`BLACKLIST_KEYWORDS`, `REQUIRED_KEYWORDS`, `DESIRED_POSITIONS`)
4. `asyncio.gather`로 병렬 상세 조회 (동시 `CRAWL_CONCURRENCY`개)
5. SQLite에 upsert, `crawl_runs`에 실행 이력 기록

### 대시보드

```bash
jc-web
# → http://127.0.0.1:8000
```

- 목록: 사이트/회사/제목/합격률/버딕트/등록일 + 필터/정렬
- 상세: `/jobs/{id}` — 원문 링크, 기술스택, 본문
- **합격률 평가 버튼**: 클릭 시 `POST /jobs/{id}/score` → Gemini 1회 호출
- **재평가**: `/jobs/{id}/rescore`
- **분석 펼치기**: strengths/gaps/red_flags/action_tip 인라인 표시

### 스케줄러

```bash
nohup .venv/bin/jc-scheduler > logs/scheduler.log &
```

매일 09:00 / 19:00 KST에 `ACTIVE_SITES` 전부 크롤링.

## 필터링 동작

```
제목 BLACKLIST_KEYWORDS 체크
    → 기업명 BLACKLIST_COMPANIES 체크
    → (catch 제외) REQUIRED_KEYWORDS 체목 포함 여부 체크
    → DESIRED_POSITIONS 직군 화이트리스트 체크
        (직군 분류 불가 "" 또는 generic "개발"은 통과)
```

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| saramin 타임아웃 | IP 차단 | `REQUEST_DELAY_SEC` 증가 (예: 5) |
| jobkorea 결과 0건 | Tailwind 셀렉터 개편 | `crawlers/jobkorea.py:_parse_list` 셀렉터 확인 |
| catch body_text 비어있음 | 이미지 공고 | 정상 — `(이미지 공고 — 원문 링크에서 확인)` 표시됨 |
| `합격률 평가` 500 에러 | Gemini API 키 누락/만료 | `.env`의 `GEMINI_API_KEY` 확인 |
| `alembic upgrade head` 실패 | `data/` 디렉토리 없음 | `mkdir -p data` |

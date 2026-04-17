# job_crawler

원티드·사람인·잡코리아에서 내 조건(직무/스택/연차/지역)에 맞는 공고를 수집하고,
필요할 때만 Gemini API로 이력서 기반 **예상 합격률**을 평가해주는 로컬 도구.

## 특징

- **조건 기반 수집**: `.env`에 설정한 키워드별로 반복 검색 → `external_id` 기준 병합(dedupe)
- **합격률 평가는 온디맨드**: 자동 호출 금지, 대시보드에서 건별 버튼으로만 Gemini 호출 → API 비용 최소화
- **저장**: SQLite (`data/jobs.db`), SQLAlchemy 2.0 + Alembic
- **UI**: FastAPI + HTMX 대시보드 (필터/정렬/상세/합격률 분석)
- **스케줄**: APScheduler (09:00 / 19:00 KST)

## 지원 사이트

| 사이트 | 방식 | 비고 |
|--------|------|------|
| 원티드 | `/api/v4/jobs` (httpx) | JSON API |
| 사람인 | httpx + BeautifulSoup | SSR HTML |
| 잡코리아 | httpx + BeautifulSoup | 2026 Tailwind 개편 대응 |

Playwright는 사람인·잡코리아에서 봇 차단(ERR_CONNECTION_RESET/timeout)이 발생해 httpx로 통일.
토스 등 자체 채용 페이지는 client-side 렌더링으로 현재 미지원.

리멤버·캐치는 ToS 리스크로 제외.

## 디렉토리

```
src/job_crawler/
├── config.py              # pydantic-settings
├── pipeline.py            # crawl → dedupe → upsert (LLM 평가 X)
├── scheduler.py           # APScheduler 엔트리
├── crawlers/
│   ├── base.py            # BaseCrawler / SearchCriteria / JobSummary / JobDetail
│   ├── wanted.py
│   ├── saramin.py
│   ├── jobkorea.py
│   └── registry.py        # ACTIVE_SITES
├── db/models.py           # Job / ScoreResult / CrawlRun
├── resume/loader.py       # MD → dict
├── scoring/
│   ├── gemini_client.py   # response_schema 기반 JSON 강제
│   └── matcher.py         # 단건 평가 (status=scoring 락)
├── filters/criteria.py    # 블랙리스트만 차단 (느슨)
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

(Playwright는 아직 사용 중이므로 browser binary가 필요한 경우에만)

```bash
playwright install chromium
```

### 3. `.env` 작성

```bash
cp .env.example .env
```

필수 편집 항목:

| 변수 | 설명 | 예시 |
|------|------|------|
| `GEMINI_API_KEY` | Gemini API 키 ([AI Studio](https://aistudio.google.com/app/apikey)에서 발급) | `AIza...` |
| `GEMINI_MODEL` | 모델 | `gemini-2.5-flash` |
| `RESUME_PATH` | 이력서 MD 파일 절대 경로 | `/Users/.../메인_이력서.md` |
| `DESIRED_ROLES` | 검색 키워드(쉼표 구분) | `백엔드,Java,Spring,금융,은행,SAP` |
| `DESIRED_REGIONS` | 지역(쉼표 구분) | `서울,경기,판교` |
| `DESIRED_EXPERIENCE_MIN` / `MAX` | 연차 범위 | `2` / `8` |
| `DESIRED_SALARY_MIN` | 최소 연봉(만원, 표기 참고용) | `5000` |
| `DATABASE_URL` | SQLite 경로 | `sqlite:///./data/jobs.db` |

### 4. DB 마이그레이션

```bash
mkdir -p data
alembic upgrade head
```

## 실행

### 가상환경 활성화 (매 터미널 세션마다)

```bash
cd /path/to/job_crawler
source .venv/bin/activate   # 프롬프트에 (.venv) 표시 확인
```

활성화 없이 쓰려면 모든 명령 앞에 `./.venv/bin/` 경로를 붙이면 됩니다 (예: `./.venv/bin/jc-web`).

### 크롤링 (수동)

```bash
# 전체 활성 사이트 (ACTIVE_SITES)
jc-crawl --limit 20

# 단일 사이트
jc-crawl --site wanted   --limit 20
jc-crawl --site saramin  --limit 10
jc-crawl --site jobkorea --limit 10

# 여러 사이트
jc-crawl --site wanted --site saramin --limit 10
```

동작:
1. `DESIRED_ROLES`의 키워드마다 각각 검색 (6개 키워드면 6번 요청)
2. `external_id`로 병합하여 중복 제거
3. 블랙리스트(`인턴십`, `파트타임`, ...) 필터링
4. 상세 조회 후 SQLite에 upsert
5. `crawl_runs`에 실행 이력 기록 (`fetched`, `new_jobs`, `errors`)

### 대시보드

```bash
jc-web
# → http://127.0.0.1:8000
```

- 목록: 사이트/회사/제목/합격률/버딕트/등록일 + 필터(사이트/평가상태/최소 합격률/검색어) + 정렬(등록일/합격률)
- 상세: `/jobs/{id}` — 원문 링크, 기술스택, 본문
- **합격률 평가 버튼**: 클릭 시 `POST /jobs/{id}/score` → Gemini 1회 호출 (5~10초 소요, 스피너 표시)
- **재평가**: `/jobs/{id}/rescore` — 기존 결과 덮어쓰기
- **분석 펼치기**: 목록의 합격률 셀에서 strengths/gaps/red_flags/action_tip 인라인 표시

### 스케줄러

```bash
jc-scheduler
```

매일 09:00 / 19:00 KST에 `ACTIVE_SITES` 전부 크롤링 (LLM 평가는 수행하지 않음).
백그라운드에서 계속 돌아야 하므로 `nohup` 또는 `tmux` 권장:

```bash
nohup .venv/bin/jc-scheduler > logs/scheduler.log &
```

### DB 조회 (선택)

```bash
sqlite3 data/jobs.db "
SELECT j.site, j.company, j.title, s.match_rate, s.verdict
FROM jobs j LEFT JOIN score_results s ON s.job_id = j.id
ORDER BY s.match_rate DESC NULLS LAST LIMIT 20;
"
```

## 검증

```bash
# 이력서 로더
pytest tests/test_resume_loader.py

# 크롤러 파싱 (픽스처 기반, 네트워크 불필요)
pytest tests/test_crawlers.py

# E2E smoke
jc-crawl --site wanted --limit 5
sqlite3 data/jobs.db "SELECT COUNT(*) FROM jobs WHERE site='wanted';"
```

## 설정 커스터마이즈

### 크롤링 키워드/지역/연차 변경

`.env`에서 `DESIRED_*` 수정 후 `jc-crawl` 재실행. 코드 변경 불필요.

### 지역 코드 매핑 추가

각 크롤러 상단 `REGION_CODES` / `LOCATION_MAP` 딕셔너리에 추가:
- `crawlers/wanted.py` — 원티드 지역 코드 (예: `"대전": "daejeon.all"`)
- `crawlers/saramin.py` — 사람인 `loc_mcd` 코드
- `crawlers/jobkorea.py` — 잡코리아 `local` 코드

### 블랙리스트 키워드

`src/job_crawler/filters/criteria.py`의 `BLACKLIST_KEYWORDS` 리스트 수정.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `jc-crawl --site saramin` 타임아웃 | IP 차단 (드문 경우) | `REQUEST_DELAY_SEC` 증가 (예: 5) |
| 잡코리아 결과 0건 | Tailwind 셀렉터 또 개편 | `div.shadow-list` 구조 확인 후 `crawlers/jobkorea.py:_parse_list` 수정 |
| `합격률 평가` 500 에러 | Gemini API 키 누락/만료 | `.env`의 `GEMINI_API_KEY` 확인 |
| 대시보드 필터 `int_parsing` 에러 | 빈 쿼리 파라미터 | 해결됨 — 재시작만 필요 |
| `alembic upgrade head` 실패 | `data/` 디렉토리 없음 | `mkdir -p data` |

## 범위 및 한계

**포함**:
- 원티드/사람인/잡코리아 3사 조건 기반 수집
- 이력서 기반 합격률 온디맨드 평가
- 로컬 대시보드 + SQLite 영속화

**제외**:
- 리멤버, 캐치 (ToS)
- 토스·카카오 등 회사 채용 페이지 (client-side 렌더링, 개별 구현 필요 시 `crawlers/company/` 추가)
- 자동 합격률 평가 (비용 제어 목적)

"""이력서 역량 프로파일 캐시 (resume/loader.py) 라운드트립 테스트."""
from job_crawler.resume import loader


def _reload_with_cache(tmp_path, monkeypatch):
    """캐시 경로를 tmp로 격리한 loader 모듈 반환."""
    monkeypatch.setattr(loader, "_PROFILE_CACHE_PATH", tmp_path / "resume_profile.json")
    return loader


def test_hash_changes_with_content(tmp_path, monkeypatch):
    r1 = tmp_path / "resume.md"
    r1.write_text("# 홍길동\nJava 백엔드", encoding="utf-8")
    h1 = loader.resume_content_hash(r1)

    r1.write_text("# 홍길동\nPython 백엔드", encoding="utf-8")
    h2 = loader.resume_content_hash(r1)

    assert h1 != h2


def test_cache_roundtrip_and_invalidation(tmp_path, monkeypatch):
    mod = _reload_with_cache(tmp_path, monkeypatch)
    resume = tmp_path / "resume.md"
    resume.write_text("# 홍길동\nJava 백엔드 4년", encoding="utf-8")

    # 캐시 없음 → None
    assert mod.load_profile_cache(resume) is None

    profile = {"core_skills": ["Java", "Spring"], "years": 4}
    mod.save_profile_cache(profile, resume)

    # 동일 내용 → 캐시 적중
    assert mod.load_profile_cache(resume) == profile

    # 이력서 내용 변경 → 해시 불일치로 캐시 무효화
    resume.write_text("# 홍길동\nGo 백엔드 6년", encoding="utf-8")
    assert mod.load_profile_cache(resume) is None


def _write(d, name, text):
    (d / name).write_text(text, encoding="utf-8")


def test_resolve_picks_latest_version_per_doc_type(tmp_path):
    _write(tmp_path, "메인_이력서_홍길동_v4.md", "old")
    _write(tmp_path, "메인_이력서_홍길동_v5.md", "## 경력\n이력서")
    _write(tmp_path, "메인_경력기술서_홍길동_v10.md", "경력기술서")
    _write(tmp_path, "메인_경력기술서_홍길동_v9.md", "old")
    _write(tmp_path, "메인_이력서_경력기술서_통합_홍길동_v2.md", "통합")
    _write(tmp_path, "메인_이력서_홍길동.md", "버전 없음은 무시")
    _write(tmp_path, "사람인_자기소개.md", "메인 아님은 무시")

    names = [f.name for f in loader.resolve_resume_files(tmp_path)]

    # v10 > v9 는 문자열이 아닌 숫자 비교, 이력서가 맨 앞, 통합본 제외
    assert names == [
        "메인_이력서_홍길동_v5.md",
        "메인_경력기술서_홍길동_v10.md",
    ]


def test_resolve_file_path_returned_as_is(tmp_path):
    f = tmp_path / "resume.md"
    f.write_text("x", encoding="utf-8")
    assert loader.resolve_resume_files(f) == [f]


def test_load_resume_from_dir_joins_all_docs(tmp_path):
    _write(tmp_path, "메인_이력서_홍길동_v1.md", "# 홍길동\n\n## 경력\n이력서본문")
    _write(tmp_path, "메인_경력기술서_홍길동_v1.md", "경력기술서본문")

    profile = loader.load_resume(tmp_path)

    assert profile.name == "홍길동"
    assert "이력서본문" in profile.raw_text and "경력기술서본문" in profile.raw_text


def test_dir_hash_changes_when_any_doc_changes(tmp_path):
    _write(tmp_path, "메인_이력서_홍길동_v1.md", "이력서")
    _write(tmp_path, "메인_경력기술서_홍길동_v1.md", "경력기술서")
    h1 = loader.resume_content_hash(tmp_path)

    # 경력기술서만 새 버전이 생겨도 해시가 바뀌어야 함
    _write(tmp_path, "메인_경력기술서_홍길동_v2.md", "경력기술서 개정")
    assert loader.resume_content_hash(tmp_path) != h1

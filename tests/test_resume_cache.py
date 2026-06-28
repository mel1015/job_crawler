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

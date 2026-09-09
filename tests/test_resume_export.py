from __future__ import annotations

import pytest

from job_crawler.config import get_settings
from job_crawler.db.models import Job, ScoreResult
from job_crawler.resume import export as export_mod


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """claude_resume 저장소를 흉내낸 임시 디렉터리."""
    root = tmp_path / "claude_resume"
    (root / "공통").mkdir(parents=True)
    (root / "서류탈락").mkdir()
    settings = get_settings()
    monkeypatch.setattr(type(settings), "resume_repo_dir", property(lambda self: root))
    return root


def make_job(job_id: int = 1, title: str = "백엔드 개발자", company: str = "테스트사") -> Job:
    job = Job(
        site="manual",
        external_id=f"manual-{job_id}",
        url="https://example.com/1",
        title=title,
        company=company,
        body_text="[자격요건]\n- Java",
    )
    job.id = job_id
    return job


def test_새_회사면_루트에_폴더와_공고md를_만든다(repo):
    result = export_mod.export_job(make_job())

    assert result.created is True
    assert result.path == repo / "테스트사" / "공고_테스트사.md"
    text = result.path.read_text(encoding="utf-8")
    assert "job_crawler id: 1" in text
    assert "[자격요건]" in text


def test_기존_회사폴더가_하위에_있으면_재사용한다(repo):
    (repo / "서류탈락" / "테스트사").mkdir()

    result = export_mod.export_job(make_job())

    assert result.folder == repo / "서류탈락" / "테스트사"


def test_같은_공고를_다시_내보내면_덮어쓰지_않는다(repo):
    first = export_mod.export_job(make_job())
    first.path.write_text("수정한 내용\n- job_crawler id: 1\n", encoding="utf-8")

    second = export_mod.export_job(make_job())

    assert second.created is False
    assert second.path == first.path
    assert second.path.read_text(encoding="utf-8") == "수정한 내용\n- job_crawler id: 1\n"


def test_같은_회사_다른_공고는_직무_슬러그로_새_파일을_만든다(repo):
    export_mod.export_job(make_job(1, "백엔드 개발자"))

    result = export_mod.export_job(make_job(2, "테스트사 프론트엔드 개발자"))

    assert result.created is True
    assert result.path.name == "공고_테스트사_프론트엔드 개발자.md"


def test_점수가_있으면_합격률_분석_섹션을_붙인다(repo):
    job = make_job()
    job.score = ScoreResult(
        status="done",
        match_rate=85,
        verdict="강한매치",
        strengths=["Java 4년"],
        gaps=["Kafka 무경험"],
        red_flags=[],
        action_tip="결제 도메인 경험을 강조",
    )

    text = export_mod.export_job(job).path.read_text(encoding="utf-8")

    assert "- job_crawler 매치율/총평: 85% / 강한매치" in text
    assert "## 합격률 분석" in text
    assert "- Java 4년" in text
    assert "- Kafka 무경험" in text
    assert "결제 도메인 경험을 강조" in text
    assert "### 결격 요소" not in text  # 빈 항목은 섹션 자체를 만들지 않는다


def test_하위폴더와_루트에_같은_이름이_있으면_하위폴더를_쓴다(repo):
    """서류통과/서류탈락으로 이미 분류해 둔 폴더가 루트 폴더보다 우선한다."""
    (repo / "테스트사").mkdir()
    (repo / "서류탈락" / "테스트사").mkdir()

    result = export_mod.export_job(make_job())

    assert result.folder == repo / "서류탈락" / "테스트사"


def test_회사명의_경로문자는_치환한다(repo):
    result = export_mod.export_job(make_job(company="에이/비"))

    assert result.path.parent.name == "에이_비"


def test_저장소_경로가_없으면_에러(tmp_path, monkeypatch):
    settings = get_settings()
    missing = tmp_path / "없는경로"
    monkeypatch.setattr(type(settings), "resume_repo_dir", property(lambda self: missing))

    with pytest.raises(FileNotFoundError):
        export_mod.export_job(make_job())

import os
from pathlib import Path

import pytest

from job_crawler.resume.loader import load_resume

RESUME = Path(os.environ.get("RESUME_PATH", "resume.md"))


@pytest.fixture(scope="module")
def profile():
    if not RESUME.exists():
        pytest.skip(f"resume not found: {RESUME}")
    return load_resume(RESUME)


def test_header(profile):
    assert profile.name
    assert profile.contact and "@" in profile.contact


def test_tech_stack(profile):
    assert "Backend" in profile.tech_stack
    assert "Java" in profile.tech_stack["Backend"]
    assert "Spring Boot" in profile.tech_stack["Backend"]
    assert "Java" in profile.tech_stack_flat


def test_summary(profile):
    assert profile.summary and "백엔드" in profile.summary


def test_experiences(profile):
    assert len(profile.experiences) > 0
    exp = profile.experiences[0]
    assert exp.company
    assert exp.start
    assert exp.months > 0


def test_total_experience(profile):
    assert profile.total_experience_months > 0
    assert profile.total_experience_years > 0


def test_projects(profile):
    assert len(profile.projects) > 0
    assert profile.projects[0].title


def test_certs(profile):
    assert isinstance(profile.certs, list)


def test_raw_text_preserved(profile):
    assert "## 경력" in profile.raw_text

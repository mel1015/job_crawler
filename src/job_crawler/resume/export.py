"""지원예정 공고를 claude_resume 저장소에 공고 md로 내보낸다.

`/add-posting` 커맨드의 2~3단계(폴더 결정, 공고 파일 작성)를 서버에서 그대로 수행하고,
Claude가 필요한 자기소개서 초안(5단계)은 다루지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings
from ..db.models import Job

# 회사 폴더 탐색에서 제외할 디렉터리 (이력서 공용 자료·저장소 메타데이터)
_SKIP_DIRS = {".git", ".claude", ".agents", "공통", "notion_info_images", "node_modules"}

_ID_RE = re.compile(r"job_crawler id:\s*(\d+)")


@dataclass
class ExportResult:
    path: Path
    folder: Path
    created: bool  # False면 같은 공고 md가 이미 있어 새로 쓰지 않음


def _safe_name(name: str) -> str:
    """경로에 쓸 수 없는 문자를 _로 치환."""
    return re.sub(r'[/\\:*?"<>|]', "_", name).strip() or "unknown"


def _find_company_dir(root: Path, company: str) -> Path | None:
    """서류통과/서류탈락 등 하위에 이미 있는 회사 폴더를 찾는다 (없으면 None).

    후보가 여럿이면 깊은 쪽을 고른다. 전형 결과 폴더(`서류통과/`·`서류탈락/`) 밑으로
    이미 옮겨둔 폴더가 루트에 남은 동명 폴더보다 최신 분류이기 때문.
    """
    candidates = [
        path
        for path in root.rglob(company)
        if path.is_dir()
        and not any(part in _SKIP_DIRS for part in path.relative_to(root).parts)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: (-len(p.parts), p))[0]


def _role_slug(title: str, company: str) -> str:
    """같은 회사 다중 포지션을 구분할 파일명 조각."""
    slug = title.replace(company, " ")
    slug = re.sub(r"\s+", " ", _safe_name(slug)).strip(" _-")
    return slug[:40] or "position"


def _meta_line(label: str, value: object) -> str:
    return f"- {label}: {value if value not in (None, '') else '미표기'}"


def _build_markdown(job: Job) -> str:
    stack = ", ".join(job.tech_stack) if job.tech_stack else None
    deadline = job.deadline_at.strftime("%Y-%m-%d %H:%M") if job.deadline_at else None
    lines = [
        f"# {job.title}",
        "",
        _meta_line("회사", job.company),
        _meta_line("사이트", job.site),
        f"- job_crawler id: {job.id}",
        _meta_line("경력", job.experience),
        _meta_line("고용형태", job.employment_type),
        _meta_line("연봉", job.salary),
        _meta_line("기술스택", stack),
        _meta_line("마감일", deadline),
        _meta_line("원문 URL", job.url),
    ]

    score = job.score if job.score is not None and job.score.status == "done" else None
    if score is not None and score.match_rate is not None:
        lines.append(
            f"- job_crawler 매치율/총평: {score.match_rate}% / {score.verdict or '평가 완료'}"
        )

    lines += ["", "---", "", (job.body_text or "본문 없음").rstrip(), ""]

    if score is not None:
        lines.append("## 합격률 분석")
        for heading, items in (
            ("강점", score.strengths),
            ("부족한 점", score.gaps),
            ("결격 요소", score.red_flags),
        ):
            if items:
                lines += ["", f"### {heading}", ""]
                lines += [f"- {item}" for item in items]
        if score.action_tip:
            lines += ["", "### 지원 팁", "", score.action_tip]
        lines.append("")

    return "\n".join(lines)


def export_job(job: Job) -> ExportResult:
    """공고를 claude_resume 회사 폴더에 md로 쓴다. 같은 공고가 있으면 그대로 둔다."""
    root = get_settings().resume_repo_dir
    if not root.is_dir():
        raise FileNotFoundError(f"claude_resume 저장소를 찾을 수 없습니다: {root}")

    company = _safe_name(job.company)
    folder = _find_company_dir(root, company) or (root / company)
    folder.mkdir(parents=True, exist_ok=True)

    existing = sorted(folder.glob("공고_*.md"))
    for path in existing:
        found = _ID_RE.search(path.read_text(encoding="utf-8"))
        if found and int(found.group(1)) == job.id:
            return ExportResult(path=path, folder=folder, created=False)

    if not existing:
        target = folder / f"공고_{company}.md"
    else:
        # 이미 다른 포지션 공고가 있으면 절대 덮어쓰지 않고 직무 슬러그로 새 파일을 만든다
        target = folder / f"공고_{company}_{_role_slug(job.title, job.company)}.md"
        if target.exists():
            target = target.with_name(f"{target.stem}_{job.id}.md")

    target.write_text(_build_markdown(job), encoding="utf-8")
    return ExportResult(path=target, folder=folder, created=True)

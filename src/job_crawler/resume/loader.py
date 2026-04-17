from __future__ import annotations

import re
from pathlib import Path

from .models import Experience, Project, ResumeProfile

PERIOD_RE = re.compile(
    r"(\d{4})\.(\d{1,2})\s*~\s*(?:(\d{4})\.(\d{1,2})|현재|current)",
    re.IGNORECASE,
)
MONTHS_RE = re.compile(r"\((?:약\s*)?(\d+)년(?:\s*(\d+)개월)?\)|\((\d+)개월\)")


def _split_sections(md: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in md.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = m.group(1).strip()
            buf = []
        else:
            if current is None:
                sections.setdefault("_header", "")
                sections["_header"] += line + "\n"
            else:
                buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _parse_header(header: str) -> tuple[str | None, str | None]:
    name = None
    contact = None
    for line in header.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("# "):
            name = line[2:].strip()
        elif "@" in line or "github.com" in line or re.search(r"\d{3}-\d{3,4}-\d{4}", line):
            contact = line
    return name, contact


def _parse_tech_stack(block: str) -> tuple[dict[str, list[str]], list[str]]:
    grouped: dict[str, list[str]] = {}
    flat: list[str] = []
    for line in block.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        category, techs = cells[0], cells[1]
        if category in {"분야", "------"} or set(category) <= set("-: "):
            continue
        items = [t.strip() for t in techs.split(",") if t.strip()]
        if not items:
            continue
        grouped[category] = items
        flat.extend(items)
    # dedupe flat preserving order
    seen: set[str] = set()
    flat_unique = [t for t in flat if not (t in seen or seen.add(t))]
    return grouped, flat_unique


def _period_to_months(period: str) -> tuple[str | None, str | None, int | None]:
    m = PERIOD_RE.search(period)
    start = end = None
    months = None
    if m:
        sy, sm = int(m.group(1)), int(m.group(2))
        start = f"{sy:04d}.{sm:02d}"
        if m.group(3):
            ey, em = int(m.group(3)), int(m.group(4))
            end = f"{ey:04d}.{em:02d}"
            months = (ey - sy) * 12 + (em - sm) + 1
        else:
            end = "현재"
    mm = MONTHS_RE.search(period)
    if mm:
        if mm.group(1):
            yrs = int(mm.group(1))
            mos = int(mm.group(2) or 0)
            months = yrs * 12 + mos
        elif mm.group(3):
            months = int(mm.group(3))
    return start, end, months


def _parse_experiences(block: str) -> list[Experience]:
    # Split by '### ' company/role lines
    entries: list[Experience] = []
    chunks = re.split(r"^###\s+", block, flags=re.MULTILINE)
    for chunk in chunks[1:]:
        lines = chunk.splitlines()
        if not lines:
            continue
        header = lines[0].strip()
        # "애큐온캐피탈 | 디지털 개발팀 Backend Engineer"
        parts = [p.strip() for p in header.split("|")]
        company = parts[0]
        role = " | ".join(parts[1:]) if len(parts) > 1 else None

        body = "\n".join(lines[1:]).strip()
        period_raw = None
        start = end = None
        months = None
        bullets: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("**") and ("~" in stripped or "개월" in stripped or "년" in stripped):
                period_raw = period_raw or stripped.strip("* ")
                s, e, m = _period_to_months(stripped)
                if s and not start:
                    start, end = s, e
                if m and not months:
                    months = m
            elif stripped.startswith("- "):
                bullets.append(stripped[2:].strip())
        entries.append(
            Experience(
                company=company,
                role=role,
                period_raw=period_raw,
                start=start,
                end=end,
                months=months,
                bullets=bullets,
            )
        )
    return entries


def _parse_projects(block: str) -> list[Project]:
    projects: list[Project] = []
    chunks = re.split(r"^###\s+", block, flags=re.MULTILINE)
    for chunk in chunks[1:]:
        lines = chunk.splitlines()
        if not lines:
            continue
        title = lines[0].strip()
        # strip trailing " (Eng name)" keep as is
        body_lines = lines[1:]
        period_raw = None
        bullets: list[str] = []
        tech_tags: list[str] = []
        for line in body_lines:
            stripped = line.strip()
            if stripped.startswith("**") and "~" in stripped:
                period_raw = stripped.strip("* ")
            elif stripped.startswith("- "):
                bullets.append(stripped[2:].strip())
            elif stripped.startswith("`") and "`" in stripped[1:]:
                tech_tags.extend(re.findall(r"`([^`]+)`", stripped))
        projects.append(
            Project(title=title, period_raw=period_raw, bullets=bullets, tech_tags=tech_tags)
        )
    return projects


def _parse_bullet_list(block: str) -> list[str]:
    items = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def load_resume(path: str | Path | None = None) -> ResumeProfile:
    if path is None:
        from ..config import get_settings

        p = get_settings().resume_path
    else:
        p = Path(path)
    md = p.read_text(encoding="utf-8")
    sections = _split_sections(md)

    name, contact = _parse_header(sections.get("_header", ""))

    tech_grouped, tech_flat = ({}, [])
    for key in ("기술 스택", "기술스택"):
        if key in sections:
            tech_grouped, tech_flat = _parse_tech_stack(sections[key])
            break

    summary = sections.get("자기소개")

    experiences: list[Experience] = []
    for key in ("경력", "업무 경험", "경력사항"):
        if key in sections:
            experiences = _parse_experiences(sections[key])
            break
    total_months = sum(e.months or 0 for e in experiences)

    projects: list[Project] = []
    for key in ("개인 프로젝트", "프로젝트", "사이드 프로젝트"):
        if key in sections:
            projects = _parse_projects(sections[key])
            break

    education = _parse_bullet_list(sections.get("교육", ""))
    certs = _parse_bullet_list(sections.get("자격증", ""))
    schools = _parse_bullet_list(sections.get("학력", ""))

    return ResumeProfile(
        name=name,
        contact=contact,
        tech_stack=tech_grouped,
        tech_stack_flat=tech_flat,
        summary=summary,
        experiences=experiences,
        total_experience_months=total_months,
        projects=projects,
        education=education,
        schools=schools,
        certs=certs,
        raw_text=md,
    )

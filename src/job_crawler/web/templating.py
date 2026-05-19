from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from ..filters.criteria import extract_position
from .body_formatter import format_body_html

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["extract_position"] = extract_position
templates.env.filters["fmt_body"] = lambda text: Markup(format_body_html(text or ""))


_ALWAYS_HIRING = ("상시채용", "상시모집", "상시 모집")


def _deadline_badge(job: object, now: datetime) -> tuple[str, str]:
    deadline_at = getattr(job, "deadline_at", None)
    if deadline_at:
        days_left = (deadline_at - now).days
        if days_left < 0:
            return ("expired", "마감")
        if days_left <= 3:
            return ("urgent", f"D-{days_left}")
        if days_left <= 7:
            return ("soon", f"D-{days_left}")
        return ("normal", deadline_at.strftime("%m/%d") + " 마감")
    body = getattr(job, "body_text", None) or ""
    if any(kw in body for kw in _ALWAYS_HIRING):
        return ("always", "상시채용")
    return ("unknown", "마감일 미확인")


templates.env.globals["deadline_badge"] = _deadline_badge

from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from ..filters.criteria import extract_position
from .body_formatter import format_body_html

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["extract_position"] = extract_position
templates.env.filters["fmt_body"] = lambda text: Markup(format_body_html(text or ""))

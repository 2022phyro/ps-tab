"""Jinja2 template engine setup for Kwuo."""

from pathlib import Path
from fastapi.templating import Jinja2Templates

# Locate templates directory at project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

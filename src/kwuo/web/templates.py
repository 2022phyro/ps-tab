"""Jinja2 template engine setup for Kwuo."""

from pathlib import Path
from jinja2 import FileSystemBytecodeCache
from fastapi.templating import Jinja2Templates
from kwuo.core.config import settings
from kwuo.core.subdomain import get_tournament_url

# Locate templates directory at project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
CACHE_DIR = BASE_DIR / ".jinja_cache"
CACHE_DIR.mkdir(exist_ok=True)

# Configure Bytecode Cache for compiled template speed
bcc = FileSystemBytecodeCache(directory=str(CACHE_DIR), pattern="%s.cache")

templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
)
templates.env.auto_reload = settings.DEBUG
templates.env.bytecode_cache = bcc

# Register template globals
templates.env.globals["tournament_url"] = get_tournament_url

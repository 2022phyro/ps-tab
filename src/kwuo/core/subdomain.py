"""Multi-tenant subdomain resolution, slugification, and URL routing utilities."""

import re
import unicodedata
from typing import Optional
from starlette.requests import Request

from kwuo.core.config import settings


def slugify(text: str) -> str:
    """Normalize string, convert to lowercase, remove non-alphanumeric characters, and convert spaces/underscores to hyphens."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.replace("_", "-")
    text = re.sub(r"[^a-z0-9\s-]", "", text.lower()).strip()
    return re.sub(r"[-\s]+", "-", text).strip("-")


def is_valid_slug(slug: str) -> bool:
    """Validate that slug consists of lowercase alphanumeric characters and hyphens."""
    if not slug or len(slug) < 3 or len(slug) > 63:
        return False
    # Must start and end with alphanumeric, can contain single hyphens in between
    return bool(re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", slug))


def is_reserved_slug(slug: str) -> bool:
    """Check if the slug conflicts with system-reserved subdomains or platform routes."""
    return slug.lower() in settings.RESERVED_SLUGS


def extract_subdomain(host: str, base_domain: Optional[str] = None) -> Optional[str]:
    """Extract tenant slug from Host header.
    
    Handles:
    - 'yale-invitational.kwuo.com' -> 'yale-invitational'
    - 'yale-invitational.kwuo.com:8000' -> 'yale-invitational'
    - 'yale-invitational.localhost:8000' -> 'yale-invitational'
    - 'yale-invitational.localhost' -> 'yale-invitational'
    - 'kwuo.com', 'www.kwuo.com', 'localhost:8000', '127.0.0.1:8000' -> None (Apex)
    """
    if not host:
        return None

    # Strip port number if present
    hostname = host.split(":")[0].strip().lower()

    # Check .localhost development pattern (RFC 6761)
    if hostname.endswith(".localhost"):
        sub = hostname[:-len(".localhost")].strip()
        if sub and not is_reserved_slug(sub):
            return sub
        return None

    target_base = (base_domain or settings.BASE_DOMAIN).lower().strip()
    suffix = f".{target_base}"

    if hostname.endswith(suffix):
        sub = hostname[:-len(suffix)].strip()
        if sub and not is_reserved_slug(sub):
            return sub
        return None

    return None


def get_tournament_url(
    slug: str,
    request: Optional[Request] = None,
    *,
    is_local: Optional[bool] = None,
    port: Optional[int] = None,
) -> str:
    """Generate the absolute URL for a tournament subdomain.
    
    In local development: returns 'http://{slug}.localhost:{port}'.
    In production: returns 'https://{slug}.{settings.BASE_DOMAIN}'.
    """
    clean_slug = slug.strip().lower()

    if is_local is not None:
        local_mode = is_local
    elif request:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        local_mode = "localhost" in host or "127.0.0.1" in host
    else:
        local_mode = settings.ENVIRONMENT in ("development", "testing")

    if local_mode:
        p = port or (int(request.headers.get("host", "").split(":")[1]) if request and ":" in request.headers.get("host", "") else settings.PORT)
        port_str = f":{p}" if p and p not in (80, 443) else ""
        return f"http://{clean_slug}.localhost{port_str}"

    base = settings.BASE_DOMAIN.strip().lower()
    return f"https://{clean_slug}.{base}"

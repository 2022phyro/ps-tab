"""Multi-tenant subdomain resolution and facade isolation middleware."""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

import kwuo.core.database as db_core
from kwuo.core.subdomain import extract_subdomain
from kwuo.models.tournament import Tournament, Participant, Division, OfficialProfile, ParticipantInstitution
from kwuo.web.templates import templates


class TenantSubdomainMiddleware(BaseHTTPMiddleware):
    """Intercepts requests to resolve tenant tournament context from subdomain.
    
    If an incoming request arrives on [slug].kwuo.com or [slug].localhost:8000:
    1. Looks up the Tournament by slug.
    2. Attaches tournament to request.state.tenant_tournament.
    3. Enforces facade separation by blocking apex-only routes from executing.
    """

    # Paths that belong strictly to the apex platform and must not leak into tournament facade
    APEX_ONLY_PREFIXES = (
        "/auth/",
        "/dashboard",
        "/tournaments",
        "/profile",
        "/docs",
        "/design",
    )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        subdomain = extract_subdomain(host)

        # Bypass tournament lookup for static assets
        if request.url.path.startswith("/static"):
            return await call_next(request)

        if not subdomain:
            # Request is on the apex platform domain
            request.state.is_tenant_domain = False
            request.state.tenant_tournament = None
            request.state.subdomain = None
            return await call_next(request)

        # Tenant subdomain detected: lookup tournament
        async with db_core.async_session_factory() as session:
            stmt = (
                select(Tournament)
                .options(
                    selectinload(Tournament.divisions),
                    selectinload(Tournament.schedule_items),
                )
                .where(Tournament.slug == subdomain)
            )
            result = await session.execute(stmt)
            tournament = result.scalar_one_or_none()

        if not tournament:
            # Unknown tournament subdomain
            return templates.TemplateResponse(
                request=request,
                name="tenant/not_found.html",
                context={"subdomain": subdomain},
                status_code=404,
            )

        # Attach tournament state
        request.state.is_tenant_domain = True
        request.state.tenant_tournament = tournament
        request.state.subdomain = subdomain

        # Check if requested path is an apex-only route that shouldn't bleed into tenant facade
        path = request.url.path
        if any(path.startswith(prefix) for prefix in self.APEX_ONLY_PREFIXES):
            return templates.TemplateResponse(
                request=request,
                name="tenant/not_found.html",
                context={
                    "subdomain": subdomain,
                    "tournament": tournament,
                    "message": "This platform route is not available on tournament domains.",
                },
                status_code=404,
            )

        # On tenant domain, allow tab room admin routes while isolating platform admin
        TENANT_ADMIN_ALLOWED_PREFIXES = (
            "/admin/login",
            "/admin/logout",
            "/admin/reset-password",
            "/admin/settings",
            "/admin/documents",
            "/admin/rubric",
            "/admin/speakers",
            "/admin/judges",
            "/admin/officials",
            "/admin/institutions",
            "/admin/authorization",
            "/admin/rules",
        )
        if path.startswith("/admin"):
            is_valid_tenant_admin = path in ("/admin", "/admin/") or any(path.startswith(p) for p in TENANT_ADMIN_ALLOWED_PREFIXES)
            if not is_valid_tenant_admin:
                return templates.TemplateResponse(
                    request=request,
                    name="tenant/not_found.html",
                    context={
                        "subdomain": subdomain,
                        "tournament": tournament,
                        "message": "This administrative route is not available on tournament domains.",
                    },
                    status_code=404,
                )

        return await call_next(request)

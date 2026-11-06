"""Tests for multi-tenant subdomain resolution, slug utilities, and facade isolation."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from kwuo.core.subdomain import (
    slugify,
    is_valid_slug,
    is_reserved_slug,
    extract_subdomain,
    get_tournament_url,
)
from kwuo.models.tournament import Tournament, TournamentStatus, LocationType, Division, RubricCriterion
from kwuo.models.user import User, UserStatus
from kwuo.core.security import hash_password


# ============================================================================
# 1. Unit Tests for Subdomain and Slug Utilities
# ============================================================================

def test_slugify_utility():
    assert slugify("Havard Invitational 2026") == "havard-invitational-2026"
    assert slugify("National Oratory & Forensics!") == "national-oratory-forensics"
    assert slugify("   Leading and Trailing   ") == "leading-and-trailing"
    assert slugify("Multiple---Dashes___Underscores") == "multiple-dashes-underscores"
    assert slugify("Café & Débat") == "cafe-debat"


def test_is_valid_slug():
    assert is_valid_slug("valid-slug-123") is True
    assert is_valid_slug("abc") is True
    assert is_valid_slug("a" * 63) is True

    # Too short (< 3)
    assert is_valid_slug("ab") is False
    assert is_valid_slug("") is False

    # Too long (> 63)
    assert is_valid_slug("a" * 64) is False

    # Invalid characters or formats
    assert is_valid_slug("-starts-with-dash") is False
    assert is_valid_slug("ends-with-dash-") is False
    assert is_valid_slug("has_underscore") is False
    assert is_valid_slug("UPPERCASE") is False
    assert is_valid_slug("has space") is False
    assert is_valid_slug("has.dot") is False


def test_is_reserved_slug():
    assert is_reserved_slug("www") is True
    assert is_reserved_slug("api") is True
    assert is_reserved_slug("admin") is True
    assert is_reserved_slug("dashboard") is True
    assert is_reserved_slug("auth") is True
    assert is_reserved_slug("tournaments") is True
    assert is_reserved_slug("havard-open") is False


def test_extract_subdomain():
    # Production domain
    assert extract_subdomain("havard.kwuo.com") == "havard"
    assert extract_subdomain("kwuo.com") is None
    assert extract_subdomain("www.kwuo.com") is None
    assert extract_subdomain("api.kwuo.com") is None

    # Local development
    assert extract_subdomain("havard.localhost:8000") == "havard"
    assert extract_subdomain("havard.localhost") == "havard"
    assert extract_subdomain("localhost:8000") is None
    assert extract_subdomain("localhost") is None
    assert extract_subdomain("127.0.0.1:8000") is None

    # Edge cases
    assert extract_subdomain("") is None
    assert extract_subdomain("malformed..host") is None


def test_get_tournament_url():
    # Production
    prod_url = get_tournament_url("haven-open", is_local=False)
    assert prod_url == "https://haven-open.kwuo.com"

    # Local development
    dev_url = get_tournament_url("haven-open", is_local=True, port=8000)
    assert dev_url == "http://haven-open.localhost:8000"


# ============================================================================
# 2. Integration Tests for Tenant Subdomain Middleware & Facade Isolation
# ============================================================================

@pytest.mark.asyncio
async def test_tenant_subdomain_renders_tournament_home(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """When navigating to [slug].localhost:8000, renders the tenant landing page."""
    # Create test organizer
    user = User(
        email="org@speech.org",
        password_hash=hash_password("password123"),
        full_name="Tournament Director",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    # Create tournament with location info and rubric standard
    tournament = Tournament(
        name="Haven Championship 2026",
        slug="haven-open",
        location_type=LocationType.PHYSICAL,
        location="Boston, MA",
        description="The premier east coast forensic tournament.",
        organizer_id=user.id,
        status=TournamentStatus.ACTIVE,
        base_score=70.0,
        ceiling_score=100.0,
        max_time_penalty=10.0,
    )
    db_session.add(tournament)
    await db_session.flush()

    # Add a division and rubric criterion
    division = Division(
        tournament_id=tournament.id,
        name="Varsity Oratory",
        description="Open to all undergraduate and senior high speakers.",
    )
    criterion = RubricCriterion(
        tournament_id=tournament.id,
        name="Delivery & Vocal Variety",
        description="Modulation, pacing, pitch, and clarity.",
        max_points=30.0,
        display_order=1,
    )
    db_session.add_all([division, criterion])
    await db_session.commit()

    # Request tenant subdomain root
    response = await client.get(
        "/",
        headers={"Host": "haven-open.localhost:8000"},
    )
    assert response.status_code == 200
    assert "Haven Championship 2026" in response.text
    assert "Boston, MA" in response.text
    assert "The premier east coast forensic tournament." in response.text
    assert "Varsity Oratory" in response.text


@pytest.mark.asyncio
async def test_tenant_subdomain_facade_blocks_apex_routes(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Apex-only routes like /dashboard, /admin, /auth/login return 404 on tenant subdomain."""
    user = User(
        email="org2@speech.org",
        password_hash=hash_password("password123"),
        full_name="Director Two",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    tournament = Tournament(
        name="National Speech Fest",
        slug="nsf-2026",
        organizer_id=user.id,
    )
    db_session.add(tournament)
    await db_session.commit()

    # Request apex routes on tenant host
    for blocked_path in ["/dashboard", "/profile", "/auth/login", "/tournaments", "/admin/users"]:
        res = await client.get(
            blocked_path,
            headers={"Host": "nsf-2026.localhost:8000"},
        )
        assert res.status_code == 404
        assert "Tournament Not Found" in res.text or "not found" in res.text.lower()


@pytest.mark.asyncio
async def test_nonexistent_subdomain_returns_404(client: AsyncClient):
    """Subdomain with no registered tournament returns 404 tenant page."""
    response = await client.get(
        "/",
        headers={"Host": "non-existent-tourney.localhost:8000"},
    )
    assert response.status_code == 404
    assert "Tournament Not Found" in response.text
    assert "non-existent-tourney" in response.text


@pytest.mark.asyncio
async def test_apex_request_unaffected_by_middleware(client: AsyncClient):
    """Requests on the apex host are unaffected and render platform landing page."""
    response = await client.get(
        "/",
        headers={"Host": "localhost:8000"},
    )
    assert response.status_code == 200
    assert "Kwuo" in response.text
    assert "Tired of Terrifying Tabs" in response.text

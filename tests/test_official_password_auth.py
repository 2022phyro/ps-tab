"""Tests for tournament official password-based authentication and Tab Room administration."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from kwuo.core.security import hash_password
from kwuo.models.user import User, UserStatus
from kwuo.models.tournament import (
    Tournament,
    TournamentStatus,
    Participant,
    OfficialProfile,
    OfficialRole,
)


async def seed_tournament_with_official(db_session: AsyncSession) -> tuple[Tournament, User, Participant]:
    """Seed tournament with an organizer user and an official with password."""
    organizer = User(
        email="chief_director@tourn.org",
        password_hash=hash_password("DirectorSuperPass123!"),
        full_name="Director Sophia",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(organizer)
    await db_session.flush()

    tournament = Tournament(
        name="Metropolitan Debate Open",
        slug="metro-open-2026",
        organizer_id=organizer.id,
        status=TournamentStatus.ACTIVE,
    )
    db_session.add(tournament)
    await db_session.flush()

    # Dedicated official
    official_part = Participant(
        tournament_id=tournament.id,
        name="Tab Master Elena",
        email="elena@tabroom.org",
    )
    official_profile = OfficialProfile(role=OfficialRole.TAB)
    official_profile.set_password("TabOfficialPass456!")
    official_part.official_profile = official_profile

    db_session.add(official_part)
    await db_session.commit()
    await db_session.refresh(tournament)
    await db_session.refresh(organizer)
    await db_session.refresh(official_part)

    return tournament, organizer, official_part


@pytest.mark.asyncio
async def test_unauthenticated_admin_redirects_to_login(client: AsyncClient, db_session: AsyncSession):
    """Accessing /admin without credentials redirects to /admin/login."""
    tournament, _, _ = await seed_tournament_with_official(db_session)
    host = f"{tournament.slug}.kwuo.com"

    res = await client.get("/admin", headers={"Host": host}, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/admin/login"


@pytest.mark.asyncio
async def test_official_login_success(client: AsyncClient, db_session: AsyncSession):
    """Official can log in with their email and password."""
    tournament, _, official_part = await seed_tournament_with_official(db_session)
    host = f"{tournament.slug}.kwuo.com"

    res = await client.post(
        "/admin/login",
        headers={"Host": host},
        data={"email": "elena@tabroom.org", "password": "TabOfficialPass456!"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/admin"
    cookie_name = f"kwuo_off_{tournament.id}"
    assert cookie_name in res.cookies

    # Access /admin with official cookie
    client.cookies.set(cookie_name, res.cookies[cookie_name])
    admin_res = await client.get("/admin", headers={"Host": host})
    assert admin_res.status_code == 200
    assert "Tab Room Control Center" in admin_res.text
    assert "Tab Master Elena" in admin_res.text
    assert "TAB" in admin_res.text


@pytest.mark.asyncio
async def test_official_login_invalid_password_rejected(client: AsyncClient, db_session: AsyncSession):
    """Wrong password returns 401 with error notice."""
    tournament, _, _ = await seed_tournament_with_official(db_session)
    host = f"{tournament.slug}.kwuo.com"

    res = await client.post(
        "/admin/login",
        headers={"Host": host},
        data={"email": "elena@tabroom.org", "password": "WrongPassword999!"},
        follow_redirects=False,
    )
    assert res.status_code == 401
    assert "Invalid official credentials" in res.text


@pytest.mark.asyncio
async def test_organizer_user_login_to_tab_room(client: AsyncClient, db_session: AsyncSession):
    """Tournament organizer user can authenticate into /admin via their platform credentials."""
    tournament, organizer, _ = await seed_tournament_with_official(db_session)
    host = f"{tournament.slug}.kwuo.com"

    res = await client.post(
        "/admin/login",
        headers={"Host": host},
        data={"email": organizer.email, "password": "DirectorSuperPass123!"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/admin"

    cookie_name = f"kwuo_off_{tournament.id}"
    assert cookie_name in res.cookies

    client.cookies.set(cookie_name, res.cookies[cookie_name])
    admin_res = await client.get("/admin", headers={"Host": host})
    assert admin_res.status_code == 200
    assert "Director Sophia" in admin_res.text


@pytest.mark.asyncio
async def test_official_logout(client: AsyncClient, db_session: AsyncSession):
    """Logging out clears the official cookie and redirects to /admin/login."""
    tournament, _, _ = await seed_tournament_with_official(db_session)
    host = f"{tournament.slug}.kwuo.com"

    # Log in first
    login_res = await client.post(
        "/admin/login",
        headers={"Host": host},
        data={"email": "elena@tabroom.org", "password": "TabOfficialPass456!"},
        follow_redirects=False,
    )
    cookie_name = f"kwuo_off_{tournament.id}"
    client.cookies.set(cookie_name, login_res.cookies[cookie_name])

    # POST /admin/logout
    logout_res = await client.post("/admin/logout", headers={"Host": host}, follow_redirects=False)
    assert logout_res.status_code == 303
    assert logout_res.headers["location"] == "/admin/login"

    # Subsequent GET /admin redirects to login
    client.cookies.delete(cookie_name)
    subsequent_res = await client.get("/admin", headers={"Host": host}, follow_redirects=False)
    assert subsequent_res.status_code == 303
    assert subsequent_res.headers["location"] == "/admin/login"

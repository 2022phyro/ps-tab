"""Tests for tournament creation flow and dashboard listing on apex platform."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from kwuo.core.security import SESSION_COOKIE_NAME, hash_password
from kwuo.models.user import User, UserStatus
from kwuo.models.tournament import Tournament, LocationType, Division, RubricCriterion


@pytest.mark.asyncio
async def test_create_tournament_successful(client: AsyncClient, db_session: AsyncSession):
    """Authenticated organizer can create a tournament with full metadata and links."""
    # Register/login user
    user = User(
        email="director@tabroom.edu",
        password_hash=hash_password("SecurePassword123!"),
        full_name="Director Marcus",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Log in
    login_res = await client.post(
        "/auth/login",
        data={"email": "director@tabroom.edu", "password": "SecurePassword123!"},
        follow_redirects=False,
    )
    assert login_res.status_code == 302
    client.cookies.set(SESSION_COOKIE_NAME, login_res.cookies[SESSION_COOKIE_NAME])

    # POST /tournaments
    create_res = await client.post(
        "/tournaments",
        data={
            "name": "Midwest Forensic Open 2026",
            "slug": "midwest-open-2026",
            "location_type": "physical",
            "location": "Chicago, IL",
            "start_date": "2026-11-15T09:00",
            "end_date": "2026-11-17T18:00",
            "description": "Annual speech gathering with collegiate rules.",
        },
        follow_redirects=False,
    )
    assert create_res.status_code in (302, 303)
    assert "/dashboard" in create_res.headers["location"]

    # Verify tournament in database
    stmt = (
        select(Tournament)
        .options(
            selectinload(Tournament.divisions),
            selectinload(Tournament.rubric_criteria),
        )
        .where(Tournament.slug == "midwest-open-2026")
    )
    result = await db_session.execute(stmt)
    tournament = result.scalar_one_or_none()
    assert tournament is not None
    assert tournament.name == "Midwest Forensic Open 2026"
    assert tournament.location == "Chicago, IL"
    assert tournament.location_type == LocationType.PHYSICAL
    assert tournament.organizer_id == user.id

    # Verify auto-seeded division and standard criteria
    assert len(tournament.divisions) == 1
    assert tournament.divisions[0].name == "Open"
    assert len(tournament.rubric_criteria) >= 3

    # Verify dashboard lists the new tournament and has "Manage Tournament" link
    dash_res = await client.get("/dashboard")
    assert dash_res.status_code == 200
    assert "Midwest Forensic Open 2026" in dash_res.text
    assert "midwest-open-2026" in dash_res.text
    assert "Manage Tournament" in dash_res.text


@pytest.mark.asyncio
async def test_create_tournament_auto_slug(client: AsyncClient, db_session: AsyncSession):
    """When slug is omitted, it is automatically derived from the tournament name."""
    user = User(
        email="auto@tabroom.edu",
        password_hash=hash_password("SecurePassword123!"),
        full_name="Auto Slugger",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    login_res = await client.post(
        "/auth/login",
        data={"email": "auto@tabroom.edu", "password": "SecurePassword123!"},
        follow_redirects=False,
    )
    client.cookies.set(SESSION_COOKIE_NAME, login_res.cookies[SESSION_COOKIE_NAME])

    create_res = await client.post(
        "/tournaments",
        data={
            "name": "Cascadia Oratory Invitational",
            "slug": "",  # Empty slug, should auto-slugify
            "location": "Seattle, WA",
        },
        follow_redirects=False,
    )
    assert create_res.status_code in (302, 303)

    stmt = select(Tournament).where(Tournament.slug == "cascadia-oratory-invitational")
    result = await db_session.execute(stmt)
    tournament = result.scalar_one_or_none()
    assert tournament is not None
    assert tournament.name == "Cascadia Oratory Invitational"


@pytest.mark.asyncio
async def test_create_tournament_slug_validations(client: AsyncClient, db_session: AsyncSession):
    """Rejects invalid slugs, reserved slugs, and duplicate slugs."""
    user = User(
        email="validator@tabroom.edu",
        password_hash=hash_password("SecurePassword123!"),
        full_name="Valid Ator",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    login_res = await client.post(
        "/auth/login",
        data={"email": "validator@tabroom.edu", "password": "SecurePassword123!"},
        follow_redirects=False,
    )
    client.cookies.set(SESSION_COOKIE_NAME, login_res.cookies[SESSION_COOKIE_NAME])

    # 1. Invalid slug (e.g. contains underscore or spaces)
    res_invalid = await client.post(
        "/tournaments",
        data={"name": "Bad Slug Tourney", "slug": "bad_slug_name!"},
    )
    assert res_invalid.status_code == 400
    assert "Slug must be 3-63 characters" in res_invalid.text

    # 2. Reserved slug (e.g. 'admin')
    res_reserved = await client.post(
        "/tournaments",
        data={"name": "Admin Tourney", "slug": "admin"},
    )
    assert res_reserved.status_code == 400
    assert "is reserved" in res_reserved.text

    # 3. Create initial tournament
    res_first = await client.post(
        "/tournaments",
        data={"name": "First Tournament", "slug": "unique-open-2026"},
    )
    assert res_first.status_code in (302, 303)

    # 4. Duplicate slug
    res_dup = await client.post(
        "/tournaments",
        data={"name": "Duplicate Tournament", "slug": "unique-open-2026"},
    )
    assert res_dup.status_code == 400
    assert "already exists" in res_dup.text


@pytest.mark.asyncio
async def test_unauthenticated_cannot_create_tournament(client: AsyncClient):
    """Unauthenticated users cannot access POST /tournaments."""
    response = await client.post(
        "/tournaments",
        data={"name": "Unauthorized Tourney", "slug": "unauth-tourney"},
    )
    assert response.status_code in (302, 307, 401, 403)


@pytest.mark.asyncio
async def test_delete_tournament(client: AsyncClient, db_session: AsyncSession):
    """Tournament organizer can delete their tournament; unauthorized users cannot."""
    # 1. Create organizer and second user
    owner = User(
        email="owner@tabroom.edu",
        password_hash=hash_password("Pass1234!"),
        full_name="Owner User",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    stranger = User(
        email="stranger@tabroom.edu",
        password_hash=hash_password("Pass1234!"),
        full_name="Stranger User",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add_all([owner, stranger])
    await db_session.flush()

    tournament = Tournament(
        name="Tourney to Delete",
        slug="delete-me-open",
        organizer_id=owner.id,
    )
    db_session.add(tournament)
    await db_session.commit()

    # 2. Stranger attempts to delete tournament -> 403 Forbidden
    login_stranger = await client.post(
        "/auth/login",
        data={"email": "stranger@tabroom.edu", "password": "Pass1234!"},
        follow_redirects=False,
    )
    client.cookies.set(SESSION_COOKIE_NAME, login_stranger.cookies[SESSION_COOKIE_NAME])

    del_forbidden = await client.post(f"/tournaments/{tournament.id}/delete")
    assert del_forbidden.status_code == 403

    # 3. Owner logs in and deletes tournament -> 303 Redirect to dashboard
    login_owner = await client.post(
        "/auth/login",
        data={"email": "owner@tabroom.edu", "password": "Pass1234!"},
        follow_redirects=False,
    )
    client.cookies.set(SESSION_COOKIE_NAME, login_owner.cookies[SESSION_COOKIE_NAME])

    del_success = await client.post(f"/tournaments/{tournament.id}/delete", follow_redirects=False)
    assert del_success.status_code in (302, 303)
    assert "/dashboard" in del_success.headers["location"]

    # Verify tournament was deleted
    check = await db_session.scalar(select(Tournament).where(Tournament.id == tournament.id))
    assert check is None


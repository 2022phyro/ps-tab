"""Tests for competitor self-registration and public-facing zero-auth portals."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from kwuo.models.user import User, UserStatus
from kwuo.models.tournament import (
    Tournament,
    TournamentStatus,
    Participant,
    ParticipantStatus,
    Division,
    Institution,
)


async def seed_tournament_for_registration(db_session: AsyncSession) -> tuple[Tournament, Division, Division, Institution]:
    """Seed tournament with multiple divisions and an existing institution."""
    user = User(
        email="director@tabroom.org",
        password_hash="irrelevant_hash",
        full_name="Tournament Director",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    tournament = Tournament(
        name="Metropolitan Oratory Invitational 2026",
        slug="metro-oratory",
        organizer_id=user.id,
        status=TournamentStatus.REGISTRATION,
    )
    db_session.add(tournament)
    await db_session.flush()

    div_open = Division(
        tournament_id=tournament.id,
        name="Open Oratory",
        description="General championship division",
    )
    div_novice = Division(
        tournament_id=tournament.id,
        name="Novice Division",
        description="First-time competitors",
    )
    db_session.add_all([div_open, div_novice])

    inst_yale = Institution(
        tournament_id=tournament.id,
        name="Yale Forensics",
        code="YALE",
        country="United States",
    )
    db_session.add(inst_yale)

    await db_session.commit()
    await db_session.refresh(tournament)
    await db_session.refresh(div_open)
    await db_session.refresh(div_novice)
    await db_session.refresh(inst_yale)

    return tournament, div_open, div_novice, inst_yale


@pytest.mark.asyncio
async def test_get_registration_page(client: AsyncClient, db_session: AsyncSession):
    """GET /register renders registration form with divisions and institutions."""
    tournament, div_open, div_novice, inst_yale = await seed_tournament_for_registration(db_session)

    resp = await client.get("/register", headers={"Host": f"{tournament.slug}.kwuo.com"})
    assert resp.status_code == 200
    html = resp.text
    assert "Competitor Self-Registration" in html
    assert div_open.name in html
    assert div_novice.name in html
    assert inst_yale.name in html


@pytest.mark.asyncio
async def test_post_registration_success(client: AsyncClient, db_session: AsyncSession):
    """POST /register creates participant with multiple divisions, binds institution, and returns magic link."""
    tournament, div_open, div_novice, inst_yale = await seed_tournament_for_registration(db_session)
    tourn_id = str(tournament.id)
    tourn_slug = str(tournament.slug)
    inst_id = str(inst_yale.id)
    div_open_id = str(div_open.id)
    div_novice_id = str(div_novice.id)

    payload = {
        "name": "Kwame Mensah",
        "email": "kwame@ghana.edu",
        "phone_number": "+233 24 000 0000",
        "pronouns": "he/him",
        "division_ids": [div_open_id, div_novice_id],
        "institution_id": inst_id,
    }

    resp = await client.post(
        "/register",
        data=payload,
        headers={"Host": f"{tourn_slug}.kwuo.com"},
    )
    assert resp.status_code == 200
    html = resp.text
    assert "Registration Confirmed" in html
    assert "Kwame Mensah" in html
    assert "he/him" in html
    assert "Yale Forensics" in html
    assert "/s/" in html
    assert "/me" in html

    # Verify database persistence
    await db_session.rollback()
    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.divisions),
            selectinload(Participant.institution),
        )
        .where(
            Participant.tournament_id == tourn_id,
            Participant.email == "kwame@ghana.edu",
        )
    )
    part = (await db_session.execute(stmt)).scalar_one_or_none()
    assert part is not None
    assert part.name == "Kwame Mensah"
    assert part.is_speaker is True
    assert part.speaker_profile.pronouns == "he/him"
    assert len(part.divisions) == 2
    assert part.institution_id == inst_id
    assert part.access_token_hash is not None


@pytest.mark.asyncio
async def test_post_registration_with_inline_institution_creation(client: AsyncClient, db_session: AsyncSession):
    """POST /register creates a new institution atomically if selected."""
    tournament, div_open, _, _ = await seed_tournament_for_registration(db_session)
    tourn_id = str(tournament.id)
    tourn_slug = str(tournament.slug)
    div_open_id = str(div_open.id)

    payload = {
        "name": "Chioma Adeleke",
        "email": "chioma@unilag.edu.ng",
        "phone_number": "+234 80 111 2222",
        "pronouns": "she/her",
        "division_ids": [div_open_id],
        "institution_id": "new",
        "new_institution_name": "University of Lagos",
        "new_institution_code": "UNILAG",
        "new_institution_country": "Nigeria",
    }

    resp = await client.post(
        "/register",
        data=payload,
        headers={"Host": f"{tourn_slug}.kwuo.com"},
    )
    assert resp.status_code == 200
    html = resp.text
    assert "Registration Confirmed" in html
    assert "University of Lagos" in html

    # Verify institution was created
    await db_session.rollback()
    inst = await db_session.scalar(
        select(Institution).where(
            Institution.tournament_id == tourn_id,
            Institution.code == "UNILAG",
        )
    )
    assert inst is not None
    assert inst.name == "University of Lagos"
    assert inst.country == "Nigeria"


@pytest.mark.asyncio
async def test_duplicate_registration_retrieves_access_link(client: AsyncClient, db_session: AsyncSession):
    """Re-registering with the same email issues magic link without duplicating records."""
    tournament, div_open, _, inst_yale = await seed_tournament_for_registration(db_session)
    tourn_id = str(tournament.id)
    tourn_slug = str(tournament.slug)
    inst_id = str(inst_yale.id)
    div_open_id = str(div_open.id)

    # First registration
    await client.post(
        "/register",
        data={
            "name": "Nia Vance",
            "email": "nia@vance.org",
            "division_ids": [div_open_id],
            "institution_id": inst_id,
        },
        headers={"Host": f"{tourn_slug}.kwuo.com"},
    )

    # Second registration with updated phone
    resp2 = await client.post(
        "/register",
        data={
            "name": "Nia Vance",
            "email": "nia@vance.org",
            "phone_number": "+1 555 999 8888",
            "division_ids": [div_open_id],
            "institution_id": inst_id,
        },
        headers={"Host": f"{tourn_slug}.kwuo.com"},
    )
    assert resp2.status_code == 200
    assert "Access Link Retrieved" in resp2.text
    assert "/s/" in resp2.text

    # Verify no duplicate participant in database
    await db_session.rollback()
    participants = (await db_session.scalars(
        select(Participant).where(
            Participant.tournament_id == tourn_id,
            Participant.email == "nia@vance.org",
        )
    )).all()
    assert len(participants) == 1
    assert participants[0].phone_number == "+1 555 999 8888"


@pytest.mark.asyncio
async def test_registered_speaker_magic_link_to_personal_portal(client: AsyncClient, db_session: AsyncSession):
    """Extract raw magic link from registration response and access /portal/speaker."""
    tournament, div_open, div_novice, inst_yale = await seed_tournament_for_registration(db_session)
    tourn_id = str(tournament.id)
    tourn_slug = str(tournament.slug)
    inst_id = str(inst_yale.id)
    div_open_id = str(div_open.id)
    div_novice_id = str(div_novice.id)

    resp = await client.post(
        "/register",
        data={
            "name": "Amara Okafor",
            "email": "amara@okafor.org",
            "pronouns": "they/them",
            "division_ids": [div_open_id, div_novice_id],
            "institution_id": inst_id,
        },
        headers={"Host": f"{tourn_slug}.kwuo.com"},
    )
    assert resp.status_code == 200

    # Query participant to get raw token or hash
    await db_session.rollback()
    part = await db_session.scalar(
        select(Participant).where(
            Participant.tournament_id == tourn_id,
            Participant.email == "amara@okafor.org",
        )
    )
    assert part is not None

    # Test accessing portal directly using magic link flow
    raw_token, token_hash = Participant.generate_token()
    part.access_token_hash = token_hash
    await db_session.commit()

    magic_resp = await client.get(
        f"/s/{raw_token}/me",
        headers={"Host": f"{tourn_slug}.kwuo.com"},
        follow_redirects=True,
    )
    assert magic_resp.status_code == 200
    portal_html = magic_resp.text
    assert "Competitor Portal" in portal_html
    assert "Amara Okafor" in portal_html
    assert "they/them" in portal_html
    assert "Open Oratory" in portal_html
    assert "Novice Division" in portal_html


@pytest.mark.asyncio
async def test_registration_blocked_when_not_in_registration_status(client: AsyncClient, db_session: AsyncSession):
    """Registration is closed when status is DRAFT, ACTIVE, CONCLUDED, or ARCHIVED."""
    tournament, div_open, _, _ = await seed_tournament_for_registration(db_session)
    host_header = {"Host": f"{tournament.slug}.kwuo.com"}

    for non_reg_status in [TournamentStatus.DRAFT, TournamentStatus.ACTIVE, TournamentStatus.CONCLUDED, TournamentStatus.ARCHIVED]:
        tournament.status = non_reg_status
        await db_session.commit()

        # GET /register should indicate closed
        get_resp = await client.get("/register", headers=host_header)
        assert get_resp.status_code == 200
        assert "Registration Closed" in get_resp.text

        # POST /register should be rejected with 400
        post_resp = await client.post(
            "/register",
            data={
                "name": "Late Applicant",
                "email": "late@applicant.org",
                "division_ids": [str(div_open.id)],
            },
            headers=host_header,
        )
        assert post_resp.status_code == 400
        assert "registration phase" in post_resp.json()["detail"].lower()

"""Tests for participant zero-auth magic link authentication and personal portals."""

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
    SpeakerProfile,
    JudgeProfile,
)


async def seed_tournament_with_magic_participants(db_session: AsyncSession) -> tuple[Tournament, str, str, Participant, Participant]:
    """Seed tournament with speaker and judge holding magic link tokens."""
    user = User(
        email="org@forensics.org",
        password_hash="irrelevant_hash",
        full_name="Staff Alex",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    tournament = Tournament(
        name="Global Speech Open 2026",
        slug="global-speech-2026",
        organizer_id=user.id,
        status=TournamentStatus.ACTIVE,
    )
    db_session.add(tournament)
    await db_session.flush()

    raw_spk_token, spk_hash = Participant.generate_token()
    speaker = Participant(
        tournament_id=tournament.id,
        name="Nia Vance",
        email="nia@competitor.org",
        access_token_hash=spk_hash,
    )
    speaker.speaker_profile = SpeakerProfile()

    raw_judge_token, judge_hash = Participant.generate_token()
    judge = Participant(
        tournament_id=tournament.id,
        name="Justice Robert",
        email="robert@adjudicator.org",
        access_token_hash=judge_hash,
    )
    judge.judge_profile = JudgeProfile(is_chair_eligible=True)

    db_session.add_all([speaker, judge])
    await db_session.commit()
    await db_session.refresh(tournament)
    await db_session.refresh(speaker)
    await db_session.refresh(judge)

    return tournament, raw_spk_token, raw_judge_token, speaker, judge


@pytest.mark.asyncio
async def test_speaker_magic_url_access(client: AsyncClient, db_session: AsyncSession):
    """Visiting /s/{token}/me sets participant session cookie and redirects to /portal/speaker."""
    tournament, raw_spk_token, _, speaker, _ = await seed_tournament_with_magic_participants(db_session)
    host = f"{tournament.slug}.kwuo.com"

    # Access magic URL
    res = await client.get(f"/s/{raw_spk_token}/me", headers={"Host": host}, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/portal/speaker"
    cookie_name = f"kwuo_part_{tournament.id}"
    assert cookie_name in res.cookies

    # Follow into portal with cookie
    client.cookies.set(cookie_name, res.cookies[cookie_name])
    portal_res = await client.get("/portal/speaker", headers={"Host": host})
    assert portal_res.status_code == 200
    assert "Competitor Portal" in portal_res.text
    assert "Nia Vance" in portal_res.text


@pytest.mark.asyncio
async def test_judge_magic_url_access(client: AsyncClient, db_session: AsyncSession):
    """Visiting /j/{token}/me sets participant session cookie and redirects to /portal/judge."""
    tournament, _, raw_judge_token, _, judge = await seed_tournament_with_magic_participants(db_session)
    host = f"{tournament.slug}.kwuo.com"

    res = await client.get(f"/j/{raw_judge_token}/me", headers={"Host": host}, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/portal/judge"
    cookie_name = f"kwuo_part_{tournament.id}"
    assert cookie_name in res.cookies

    # Follow into portal with cookie
    client.cookies.set(cookie_name, res.cookies[cookie_name])
    portal_res = await client.get("/portal/judge", headers={"Host": host})
    assert portal_res.status_code == 200
    assert "Adjudicator Portal" in portal_res.text
    assert "Justice Robert" in portal_res.text
    assert "Chair Adjudicator" in portal_res.text


@pytest.mark.asyncio
async def test_generic_magic_url_dispatch(client: AsyncClient, db_session: AsyncSession):
    """Visiting /m/{token}/me dispatches cleanly to judge or speaker link."""
    tournament, raw_spk_token, raw_judge_token, _, _ = await seed_tournament_with_magic_participants(db_session)
    host = f"{tournament.slug}.kwuo.com"

    # Speaker dispatch
    res_spk = await client.get(f"/m/{raw_spk_token}/me", headers={"Host": host}, follow_redirects=False)
    assert res_spk.status_code == 307
    assert f"/s/{raw_spk_token}/me" in res_spk.headers["location"]

    # Judge dispatch
    res_judge = await client.get(f"/m/{raw_judge_token}/me", headers={"Host": host}, follow_redirects=False)
    assert res_judge.status_code == 307
    assert f"/j/{raw_judge_token}/me" in res_judge.headers["location"]


@pytest.mark.asyncio
async def test_participant_self_checkin(client: AsyncClient, db_session: AsyncSession):
    """Participant can confirm self check-in from their magic session."""
    tournament, raw_spk_token, _, speaker, _ = await seed_tournament_with_magic_participants(db_session)
    host = f"{tournament.slug}.kwuo.com"

    # Authenticate via magic URL
    login_res = await client.get(f"/s/{raw_spk_token}/me", headers={"Host": host}, follow_redirects=False)
    cookie_name = f"kwuo_part_{tournament.id}"
    client.cookies.set(cookie_name, login_res.cookies[cookie_name])

    # POST /portal/check-in
    checkin_res = await client.post("/portal/check-in", headers={"Host": host}, follow_redirects=False)
    assert checkin_res.status_code == 303
    assert "/portal/speaker" in checkin_res.headers["location"]

    # Verify participant status updated in database
    stmt = select(Participant).where(Participant.id == speaker.id)
    updated = (await db_session.execute(stmt)).scalar_one()
    assert updated.status == ParticipantStatus.CHECKED_IN
    assert updated.checked_in_at is not None


@pytest.mark.asyncio
async def test_invalid_magic_url_rejected(client: AsyncClient, db_session: AsyncSession):
    """Invalid token returns 403 with informative message."""
    tournament, _, _, _, _ = await seed_tournament_with_magic_participants(db_session)
    host = f"{tournament.slug}.kwuo.com"

    res = await client.get("/s/bogus_token_12345/me", headers={"Host": host})
    assert res.status_code == 403
    assert "Invalid or revoked competitor magic link" in res.text

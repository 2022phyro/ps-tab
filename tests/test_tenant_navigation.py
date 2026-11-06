"""Tests for multi-page tenant subdomain navigation and public tournament facade."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from kwuo.core.security import hash_password
from kwuo.models.user import User, UserStatus
from kwuo.models.tournament import (
    Tournament,
    TournamentStatus,
    LocationType,
    Division,
    RubricCriterion,
    Participant,
    SpeakerProfile,
    JudgeProfile,
    OfficialProfile,
    OfficialRole,
    Institution,
)
from kwuo.models.attachment import FileAttachment, AttachmentCategory


async def seed_tournament(db_session: AsyncSession) -> Tournament:
    """Seed a comprehensive tournament with divisions, participants, rubric, and attachments."""
    user = User(
        email="director@debatesociety.edu",
        password_hash=hash_password("DirectorPass123!"),
        full_name="Tournament Director Marcus",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    tournament = Tournament(
        name="Pan-African Forensic Championship",
        slug="pafc-2026",
        organizer_id=user.id,
        status=TournamentStatus.ACTIVE,
        location_type=LocationType.HYBRID,
        location="Accra International Conference Centre",
        description="The premier collegiate public speaking and forensic gathering.",
        base_score=70.0,
        ceiling_score=85.0,
        max_time_penalty=5.0,
    )
    db_session.add(tournament)
    await db_session.flush()

    # Divisions
    div_open = Division(tournament_id=tournament.id, name="Open", description="General collegiate division")
    div_novice = Division(tournament_id=tournament.id, name="Novice", description="First-year competitors")
    db_session.add_all([div_open, div_novice])

    # Rubric criteria
    c1 = RubricCriterion(tournament_id=tournament.id, name="Content & Argumentation", max_points=10.0, display_order=1)
    c2 = RubricCriterion(tournament_id=tournament.id, name="Delivery & Style", max_points=10.0, display_order=2)
    c3 = RubricCriterion(tournament_id=tournament.id, name="Structure & Flow", max_points=5.0, display_order=3)
    c4 = RubricCriterion(tournament_id=tournament.id, name="Language & Nuance", max_points=5.0, display_order=4)
    db_session.add_all([c1, c2, c3, c4])

    # Institution
    inst = Institution(name="University of Ghana", code="UG")
    db_session.add(inst)
    await db_session.flush()

    # Participants: Speaker, Judge, Official
    raw_spk_token, spk_hash = Participant.generate_token()
    speaker_part = Participant(
        tournament_id=tournament.id,
        institution_id=inst.id,
        name="Kofi Mensah",
        email="kofi@ug.edu.gh",
        access_token_hash=spk_hash,
    )
    speaker_part.speaker_profile = SpeakerProfile()
    speaker_part.divisions.append(div_open)

    raw_judge_token, judge_hash = Participant.generate_token()
    judge_part = Participant(
        tournament_id=tournament.id,
        institution_id=inst.id,
        name="Dr. Amina Bello",
        email="amina@ug.edu.gh",
        access_token_hash=judge_hash,
    )
    judge_part.judge_profile = JudgeProfile(is_chair_eligible=True)

    official_part = Participant(
        tournament_id=tournament.id,
        institution_id=inst.id,
        name="Chief Tabulator Kwame",
        email="kwame@ug.edu.gh",
    )
    official_profile = OfficialProfile(role=OfficialRole.TAB)
    official_profile.set_password("TabRoomPass123!")
    official_part.official_profile = official_profile

    db_session.add_all([speaker_part, judge_part, official_part])

    # Attachment
    doc = FileAttachment(
        tournament_id=tournament.id,
        title="Adjudicator Briefing Package",
        category=AttachmentCategory.BRIEFING,
        filename="Adjudicator_Briefing.pdf",
        file_path=f"{tournament.id}/att_briefing.pdf",
        file_size=1024,
        mime_type="application/pdf",
        is_public=True,
    )
    db_session.add(doc)

    await db_session.commit()
    await db_session.refresh(tournament)
    return tournament


@pytest.mark.asyncio
async def test_tenant_overview_home_page(client: AsyncClient, db_session: AsyncSession):
    """Overview page (GET /) displays numbers strip, divisions, and officials (rubric removed as tab info)."""
    tournament = await seed_tournament(db_session)
    res = await client.get("/", headers={"Host": f"{tournament.slug}.kwuo.com"})
    assert res.status_code == 200
    html = res.text

    # Tournament Identity
    assert tournament.name in html
    assert "Accra International Conference Centre" in html

    # Live Headcount Strip
    assert "Registered Speakers" in html
    assert "Accredited Judges" in html
    assert "Institutions" in html

    # Divisions & Officials
    assert "Open" in html
    assert "Novice" in html
    assert "Chief Tabulator Kwame" in html
    assert "TAB" in html

    # Rubrics section removed from overview (tab info)
    assert "Scoring Scale &amp; Rubric Standard" not in html and "Scoring Scale & Rubric Standard" not in html


@pytest.mark.asyncio
async def test_tenant_current_round_page(client: AsyncClient, db_session: AsyncSession):
    """GET /current-round renders active round room status."""
    tournament = await seed_tournament(db_session)
    res = await client.get("/current-round", headers={"Host": f"{tournament.slug}.kwuo.com"})
    assert res.status_code == 200
    html = res.text
    assert "Current Round" in html
    assert "Round Live in Progress" in html or "Round Standby" in html


@pytest.mark.asyncio
async def test_tenant_results_page(client: AsyncClient, db_session: AsyncSession):
    """GET /results renders released results and awards."""
    tournament = await seed_tournament(db_session)
    res = await client.get("/results", headers={"Host": f"{tournament.slug}.kwuo.com"})
    assert res.status_code == 200
    html = res.text
    assert "Results &amp; Awards" in html or "Results & Awards" in html


@pytest.mark.asyncio
async def test_tenant_documents_page(client: AsyncClient, db_session: AsyncSession):
    """GET /documents renders public briefing repository."""
    tournament = await seed_tournament(db_session)
    res = await client.get("/documents", headers={"Host": f"{tournament.slug}.kwuo.com"})
    assert res.status_code == 200
    html = res.text
    assert "Documents &amp; Briefing Repository" in html or "Documents & Briefing Repository" in html
    assert "Adjudicator Briefing Package" in html
    assert "/files/" in html


@pytest.mark.asyncio
async def test_tenant_tasks_page(client: AsyncClient, db_session: AsyncSession):
    """GET /tasks renders task and motion release page."""
    tournament = await seed_tournament(db_session)
    res = await client.get("/tasks", headers={"Host": f"{tournament.slug}.kwuo.com"})
    assert res.status_code == 200
    html = res.text
    assert "Tasks, Motions &amp; Speech Prompts" in html or "Tasks, Motions & Speech Prompts" in html


@pytest.mark.asyncio
async def test_tenant_schedule_page(client: AsyncClient, db_session: AsyncSession):
    """GET /schedule renders chronological timetable."""
    tournament = await seed_tournament(db_session)
    res = await client.get("/schedule", headers={"Host": f"{tournament.slug}.kwuo.com"})
    assert res.status_code == 200
    html = res.text
    assert "Master Schedule &amp; Timetable" in html or "Master Schedule & Timetable" in html


@pytest.mark.asyncio
async def test_tenant_participants_page(client: AsyncClient, db_session: AsyncSession):
    """GET /participants renders speaker and judge rosters with search and filter."""
    tournament = await seed_tournament(db_session)
    res = await client.get("/participants", headers={"Host": f"{tournament.slug}.kwuo.com"})
    assert res.status_code == 200
    html = res.text
    assert "Kofi Mensah" in html
    assert "Dr. Amina Bello" in html
    assert "University of Ghana" in html

    # Filter speakers only
    res_spk = await client.get("/participants?role=speakers", headers={"Host": f"{tournament.slug}.kwuo.com"})
    assert res_spk.status_code == 200
    assert "Kofi Mensah" in res_spk.text

    # Search filter
    res_search = await client.get("/participants?q=Amina", headers={"Host": f"{tournament.slug}.kwuo.com"})
    assert res_search.status_code == 200
    assert "Dr. Amina Bello" in res_search.text


@pytest.mark.asyncio
async def test_tenant_institutions_page(client: AsyncClient, db_session: AsyncSession):
    """GET /institutions lists attending contingents and participant sizes."""
    tournament = await seed_tournament(db_session)
    res = await client.get("/institutions", headers={"Host": f"{tournament.slug}.kwuo.com"})
    assert res.status_code == 200
    html = res.text
    assert "University of Ghana" in html
    assert "Entries" in html or "Entry" in html


@pytest.mark.asyncio
async def test_tenant_rankings_page(client: AsyncClient, db_session: AsyncSession):
    """GET /rankings renders standings / embargo notice."""
    tournament = await seed_tournament(db_session)
    res = await client.get("/rankings", headers={"Host": f"{tournament.slug}.kwuo.com"})
    assert res.status_code == 200
    html = res.text
    assert "Tournament Rankings &amp; Standings" in html or "Tournament Rankings & Standings" in html
    assert "Official Forensic Tie-Breaking Hierarchy" in html

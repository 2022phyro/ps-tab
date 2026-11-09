import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

from kwuo.main import app
from kwuo.core.security import hash_password
from kwuo.models.user import User, UserStatus
from kwuo.models.tournament import Tournament, TournamentStatus, LocationType, ScheduleItem
from kwuo.services.documentation import get_documentation_tree, get_document
from kwuo.web.routes.tenant import _parse_flexible_schedule_datetime


async def seed_tournament(db_session: AsyncSession) -> Tournament:
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
        timezone="UTC",
    )
    db_session.add(tournament)
    await db_session.commit()
    await db_session.refresh(tournament)
    return tournament


@pytest.mark.asyncio
async def test_tournament_timezone_default(db_session: AsyncSession):
    """Test that tournament timezone defaults to UTC and can be set."""
    sample_tournament = await seed_tournament(db_session)
    assert sample_tournament.timezone == "UTC"
    sample_tournament.timezone = "Africa/Harare"
    db_session.add(sample_tournament)
    await db_session.commit()
    await db_session.refresh(sample_tournament)
    assert sample_tournament.timezone == "Africa/Harare"


@pytest.mark.asyncio
async def test_schedule_item_timezone_aware(db_session: AsyncSession):
    """Test creating a schedule item with timezone-aware datetime."""
    sample_tournament = await seed_tournament(db_session)
    tz = ZoneInfo("Africa/Harare")
    st = datetime(2026, 11, 20, 9, 0, tzinfo=tz)
    item = ScheduleItem(
        tournament_id=sample_tournament.id,
        title="Round 1 Briefing",
        start_time=st,
        is_published=True,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    assert item.start_time is not None
    # In SQLite test runner, verify hour and minute are preserved
    assert item.start_time.hour == 9 or item.start_time.hour == 7  # 9 in Harare or 7 UTC
    assert item.start_time.minute == 0


@pytest.mark.asyncio
async def test_public_schedule_and_ics_download(db_session: AsyncSession):
    """Test public schedule endpoint and .ics download with timezone."""
    sample_tournament = await seed_tournament(db_session)
    sample_tournament.timezone = "Africa/Harare"
    item = ScheduleItem(
        tournament_id=sample_tournament.id,
        title="Opening Ceremony",
        start_time=datetime(2026, 11, 20, 8, 30, tzinfo=timezone.utc),
        is_published=True,
    )
    db_session.add(item)
    db_session.add(sample_tournament)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=f"http://{sample_tournament.slug}.localhost:8000") as client:
        # Public schedule page
        resp = await client.get("/schedule")
        assert resp.status_code == 200
        assert "Master Schedule" in resp.text
        assert "Africa/Harare" in resp.text
        assert "Official" in resp.text
        assert "Your Device Time" in resp.text
        assert "Other Timezone" in resp.text
        assert "AM" in resp.text

        # .ics download
        resp_ics = await client.get("/schedule/download.ics")
        assert resp_ics.status_code == 200
        assert "X-WR-TIMEZONE:Africa/Harare" in resp_ics.text
        assert "Opening Ceremony" in resp_ics.text


def test_parse_flexible_schedule_datetime_12hour():
    """Verify that both ISO and 12-hour AM/PM formats are parsed correctly."""
    tz = ZoneInfo("Africa/Harare")

    # 12-hour AM
    dt_am = _parse_flexible_schedule_datetime("2026-11-20 09:30 AM", tz)
    assert dt_am is not None
    assert dt_am.hour == 9
    assert dt_am.minute == 30

    # 12-hour PM
    dt_pm = _parse_flexible_schedule_datetime("2026-11-20 02:45 PM", tz)
    assert dt_pm is not None
    assert dt_pm.hour == 14
    assert dt_pm.minute == 45

    # Standard ISO
    dt_iso = _parse_flexible_schedule_datetime("2026-11-20T16:15", tz)
    assert dt_iso is not None
    assert dt_iso.hour == 16
    assert dt_iso.minute == 15


def test_documentation_system_tree_and_pages():
    """Verify that the documentation system reads the new 3-section hierarchy."""
    tree, flat_docs = get_documentation_tree()
    assert len(tree) == 3

    section_titles = [s.title for s in tree]
    assert "Getting Started" in section_titles
    assert "Setting Up Your Tournament" in section_titles
    assert "Deep Dives" in section_titles

    assert len(flat_docs) >= 10

    # Test loading individual documents
    for doc_item in flat_docs:
        doc = get_document(doc_item.slug)
        assert doc is not None
        assert doc.title != ""
        assert doc.html_content != ""
        assert len(doc.breadcrumbs) >= 1

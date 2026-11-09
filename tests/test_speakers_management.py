"""Tests for Tab Room admin speakers management, batch operations, and Excel import/export."""

import io
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import openpyxl

from kwuo.core.security import SESSION_COOKIE_NAME, hash_password, create_session_token
from kwuo.models.user import User, UserStatus
from kwuo.models.tournament import (
    Tournament,
    TournamentStatus,
    Participant,
    ParticipantStatus,
    Division,
    Institution,
    SpeakerProfile,
    OfficialProfile,
    OfficialRole,
)


async def seed_tournament_with_admin_user(db_session: AsyncSession) -> tuple[Tournament, User, str, Division, Division, Institution]:
    """Seed tournament, director user, session cookie, divisions, and institution."""
    user = User(
        email="director@tournament.org",
        password_hash=hash_password("password123"),
        full_name="Elena Rostova",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    tournament = Tournament(
        name="Apex Invitational 2026",
        slug="apex-invitational",
        organizer_id=user.id,
        status=TournamentStatus.ACTIVE,
    )
    db_session.add(tournament)
    await db_session.flush()

    div1 = Division(tournament_id=tournament.id, name="Varsity Oratory")
    div2 = Division(tournament_id=tournament.id, name="Junior Oratory")
    db_session.add_all([div1, div2])

    inst = Institution(tournament_id=tournament.id, name="Stanford University", code="STAN")
    db_session.add(inst)

    # Seed director official profile for tenant admin authorization
    director_part = Participant(
        tournament_id=tournament.id,
        user_id=user.id,
        name=user.full_name,
        email=user.email,
        status=ParticipantStatus.ACTIVE,
    )
    director_prof = OfficialProfile(role=OfficialRole.DIRECTOR)
    director_prof.set_password("password123")
    director_part.official_profile = director_prof
    db_session.add(director_part)

    await db_session.commit()
    await db_session.refresh(tournament)
    await db_session.refresh(user)
    await db_session.refresh(div1)
    await db_session.refresh(div2)
    await db_session.refresh(inst)

    session_token = create_session_token(user_id=user.id, auth_updated_at=user.auth_updated_at)
    return tournament, user, session_token, div1, div2, inst


async def login_test_official(client: AsyncClient, tournament: Tournament, email: str = "director@tournament.org", password: str = "password123") -> None:
    """Helper to authenticate official on tenant host and persist cookie."""
    host = f"{tournament.slug}.kwuo.com"
    res = await client.post(
        "/admin/login",
        headers={"Host": host},
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert res.status_code == 303
    cookie_name = f"kwuo_off_{tournament.id}"
    client.cookies.set(cookie_name, res.cookies[cookie_name])


@pytest.mark.asyncio
async def test_admin_speakers_page_access(client: AsyncClient, db_session: AsyncSession):
    """GET /admin/speakers renders speaker management interface for authorized organizer."""
    tournament, _, _, div1, _, inst = await seed_tournament_with_admin_user(db_session)
    tourn_slug = str(tournament.slug)
    await login_test_official(client, tournament)

    # Seed a speaker
    spk = Participant(
        tournament_id=tournament.id,
        name="Jordan Lee",
        email="jordan@stanford.edu",
        institution_id=inst.id,
        status=ParticipantStatus.REGISTERED,
    )
    spk.speaker_profile = SpeakerProfile(pronouns="they/them")
    spk.divisions = [div1]
    db_session.add(spk)
    await db_session.commit()

    resp = await client.get(
        "/admin/speakers",
        headers={"Host": f"{tourn_slug}.kwuo.com"},
    )
    assert resp.status_code == 200
    html = resp.text
    assert "Speakers Roster &amp; Desk" in html or "Speakers Roster" in html
    assert "Jordan Lee" in html
    assert "they/them" in html
    assert "Stanford University" in html


@pytest.mark.asyncio
async def test_admin_speakers_add_via_ajax_save_and_add_another(client: AsyncClient, db_session: AsyncSession):
    """POST /admin/speakers via AJAX supports 'Save & Add Another' returning JSON."""
    tournament, _, _, div1, div2, inst = await seed_tournament_with_admin_user(db_session)
    tourn_id = str(tournament.id)
    tourn_slug = str(tournament.slug)
    div1_id = str(div1.id)
    div2_id = str(div2.id)
    inst_id = str(inst.id)
    await login_test_official(client, tournament)

    payload = {
        "name": "Marcus Aurelius",
        "email": "marcus@rome.edu",
        "phone": "+1 555 432 1098",
        "pronouns": "he/him",
        "division_ids": [div1_id, div2_id],
        "institution_id": inst_id,
    }

    resp = await client.post(
        "/admin/speakers",
        json=payload,
        headers={
            "Host": f"{tourn_slug}.kwuo.com",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "registered successfully" in data["message"]
    assert data["speaker"]["name"] == "Marcus Aurelius"
    assert len(data["speaker"]["division_ids"]) == 2

    # Verify database persistence
    await db_session.rollback()
    part = await db_session.scalar(
        select(Participant)
        .options(selectinload(Participant.divisions))
        .where(
            Participant.tournament_id == tourn_id,
            Participant.email == "marcus@rome.edu",
        )
    )
    assert part is not None
    assert part.name == "Marcus Aurelius"
    assert len(part.divisions) == 2


@pytest.mark.asyncio
async def test_admin_speaker_inline_update_without_phone(client: AsyncClient, db_session: AsyncSession):
    """POST /admin/speakers/{id}/update successfully saves inline edit when phone is None or blank."""
    tournament, _, _, div1, _, inst = await seed_tournament_with_admin_user(db_session)
    tourn_slug = str(tournament.slug)
    await login_test_official(client, tournament)

    spk = Participant(
        tournament_id=tournament.id,
        name="Amartya Sen",
        email="amartya@cambridge.ac.uk",
        phone_number="+44 1223 333333",
        status=ParticipantStatus.REGISTERED,
    )
    spk.speaker_profile = SpeakerProfile(pronouns="he/him")
    db_session.add(spk)
    await db_session.commit()
    spk_id = str(spk.id)

    # 1. Update with phone=None and pronouns=None (simulating clearing or omitting phone)
    payload = {
        "name": "Amartya K. Sen",
        "email": "amartya.sen@cambridge.ac.uk",
        "phone": None,
        "pronouns": None,
        "institution_id": str(inst.id),
        "division_ids": [str(div1.id)],
    }
    resp = await client.post(
        f"/admin/speakers/{spk_id}/update",
        json=payload,
        headers={"Host": f"{tourn_slug}.kwuo.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["speaker"]["name"] == "Amartya K. Sen"
    assert data["speaker"]["phone"] == ""
    assert data["speaker"]["pronouns"] == ""
    assert data["speaker"]["institution_name"] == inst.name

    # 2. Verify in database
    await db_session.rollback()
    refreshed = await db_session.scalar(
        select(Participant)
        .options(selectinload(Participant.speaker_profile), selectinload(Participant.institution))
        .where(Participant.id == spk_id)
    )
    assert refreshed is not None
    assert refreshed.name == "Amartya K. Sen"
    assert refreshed.phone_number is None
    assert refreshed.speaker_profile.pronouns is None
    assert refreshed.institution_id == inst.id


@pytest.mark.asyncio
async def test_admin_speakers_toggle_checkin(client: AsyncClient, db_session: AsyncSession):
    """POST /admin/speakers/{id}/toggle-checkin toggles arrival check-in status."""
    tournament, _, _, div1, _, _ = await seed_tournament_with_admin_user(db_session)
    tourn_slug = str(tournament.slug)
    await login_test_official(client, tournament)

    spk = Participant(
        tournament_id=tournament.id,
        name="Tara Westover",
        email="tara@cambridge.edu",
        status=ParticipantStatus.REGISTERED,
    )
    spk.speaker_profile = SpeakerProfile()
    db_session.add(spk)
    await db_session.commit()
    spk_id = str(spk.id)

    # Toggle to CHECKED_IN
    resp = await client.post(
        f"/admin/speakers/{spk_id}/toggle-checkin",
        headers={
            "Host": f"{tourn_slug}.kwuo.com",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["checked_in"] is True

    # Toggle back to REGISTERED
    resp2 = await client.post(
        f"/admin/speakers/{spk_id}/toggle-checkin",
        headers={
            "Host": f"{tourn_slug}.kwuo.com",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["checked_in"] is False


@pytest.mark.asyncio
async def test_admin_speakers_bulk_actions(client: AsyncClient, db_session: AsyncSession):
    """POST /admin/speakers/bulk-action bulk checks-in and bulk deletes selected speakers."""
    tournament, _, _, div1, _, _ = await seed_tournament_with_admin_user(db_session)
    tourn_id = str(tournament.id)
    tourn_slug = str(tournament.slug)
    await login_test_official(client, tournament)

    s1 = Participant(tournament_id=tournament.id, name="Spk 1", email="s1@bulk.org", status=ParticipantStatus.REGISTERED)
    s1.speaker_profile = SpeakerProfile()
    s2 = Participant(tournament_id=tournament.id, name="Spk 2", email="s2@bulk.org", status=ParticipantStatus.REGISTERED)
    s2.speaker_profile = SpeakerProfile()
    db_session.add_all([s1, s2])
    await db_session.commit()
    s1_id = str(s1.id)
    s2_id = str(s2.id)

    # Bulk Check-In
    resp = await client.post(
        "/admin/speakers/bulk-action",
        data={"action": "checkin", "speaker_ids": [s1_id, s2_id]},
        headers={
            "Host": f"{tourn_slug}.kwuo.com",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Refresh and verify
    await db_session.rollback()
    refreshed_s1 = await db_session.scalar(select(Participant).where(Participant.id == s1_id))
    refreshed_s2 = await db_session.scalar(select(Participant).where(Participant.id == s2_id))
    assert refreshed_s1.status == ParticipantStatus.CHECKED_IN
    assert refreshed_s2.status == ParticipantStatus.CHECKED_IN

    # Bulk Delete
    resp_del = await client.post(
        "/admin/speakers/bulk-action",
        data={"action": "delete", "speaker_ids": [s1_id, s2_id]},
        headers={
            "Host": f"{tourn_slug}.kwuo.com",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    assert resp_del.status_code == 200

    await db_session.rollback()
    remaining = (await db_session.scalars(
        select(Participant).where(Participant.tournament_id == tourn_id)
    )).all()
    # Only director participant remains
    assert all(p.is_official for p in remaining)


@pytest.mark.asyncio
async def test_admin_speakers_excel_export_and_import(client: AsyncClient, db_session: AsyncSession):
    """Test Excel roster export and batch import from spreadsheet."""
    tournament, _, _, div1, _, inst = await seed_tournament_with_admin_user(db_session)
    tourn_id = str(tournament.id)
    tourn_slug = str(tournament.slug)
    div1_name = str(div1.name)
    await login_test_official(client, tournament)

    # 1. Test template download
    tmpl_resp = await client.get(
        "/admin/speakers/import-template.xlsx",
        headers={"Host": f"{tourn_slug}.kwuo.com"},
    )
    assert tmpl_resp.status_code == 200
    assert "spreadsheetml" in tmpl_resp.headers["content-type"]

    # 2. Build sample Excel file with 2 speakers
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Speakers"
    ws.append(["Name", "Email", "Phone", "Institution", "Division"])
    ws.append(["Chinua Achebe", "chinua@bard.edu", "+1 555 111 2222", "Bard College", div1_name])
    ws.append(["Zadie Smith", "zadie@nyu.edu", "", "New York University", div1_name])  # Blank phone cell
    file_bytes = io.BytesIO()
    wb.save(file_bytes)
    file_bytes.seek(0)

    # 3. Post import
    files = {"file": ("test_speakers.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    imp_resp = await client.post(
        "/admin/speakers/import",
        files=files,
        headers={"Host": f"{tourn_slug}.kwuo.com"},
        follow_redirects=True,
    )
    assert imp_resp.status_code == 200

    # 4. Verify imported participants
    await db_session.rollback()
    imported = (await db_session.scalars(
        select(Participant)
        .options(selectinload(Participant.institution))
        .where(Participant.tournament_id == tourn_id)
    )).all()
    names = [p.name for p in imported]
    assert "Chinua Achebe" in names
    assert "Zadie Smith" in names
    zadie = next(p for p in imported if p.name == "Zadie Smith")
    assert zadie.phone_number is None  # Blank phone cell stored as None

    # 5. Test export
    exp_resp = await client.get(
        "/admin/speakers/export.xlsx",
        headers={"Host": f"{tourn_slug}.kwuo.com"},
    )
    assert exp_resp.status_code == 200
    assert "spreadsheetml" in exp_resp.headers["content-type"]


@pytest.mark.asyncio
async def test_admin_speaker_individual_delete(client: AsyncClient, db_session: AsyncSession):
    """Test POST /admin/speakers/{participant_id}/delete."""
    tournament, _, _, div1, _, inst = await seed_tournament_with_admin_user(db_session)
    tourn_id = str(tournament.id)
    tourn_slug = str(tournament.slug)
    await login_test_official(client, tournament)

    # Seed a speaker to delete
    spk = Participant(
        tournament_id=tournament.id,
        name="Target Delete Speaker",
        email="target.delete@test.com",
        status=ParticipantStatus.REGISTERED,
    )
    spk.speaker_profile = SpeakerProfile()
    db_session.add(spk)
    await db_session.commit()
    spk_id = str(spk.id)

    # Delete via AJAX
    del_resp = await client.post(
        f"/admin/speakers/{spk_id}/delete",
        headers={
            "Host": f"{tourn_slug}.kwuo.com",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "ok"

    # Verify deleted
    await db_session.rollback()
    exists = await db_session.scalar(select(Participant).where(Participant.id == spk_id))
    assert exists is None


@pytest.mark.asyncio
async def test_admin_speakers_import_4_column_no_phone(client: AsyncClient, db_session: AsyncSession):
    """Test importing 4-column spreadsheet: Name, Email, Institution, Division (no Phone column)."""
    tournament, _, _, div1, _, inst = await seed_tournament_with_admin_user(db_session)
    tourn_id = str(tournament.id)
    tourn_slug = str(tournament.slug)
    await login_test_official(client, tournament)

    # Build Excel file matching user's exact sample
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Speakers"
    ws.append(["Name", "Email", "Institution", "Division"])
    ws.append(["Chukwudi Okafor", "chukwudi.okafor@st.ug.edu.gh", "University of Ghana", "Open"])
    ws.append(["Efua Sutherland", "efua.sutherland@st.knust.edu.gh", "Kwame Nkrumah University of Science and Technology", "Open, Novice"])
    file_bytes = io.BytesIO()
    wb.save(file_bytes)
    file_bytes.seek(0)

    files = {"file": ("african_speakers.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    imp_resp = await client.post(
        "/admin/speakers/import",
        files=files,
        headers={"Host": f"{tourn_slug}.kwuo.com"},
        follow_redirects=True,
    )
    assert imp_resp.status_code == 200

    await db_session.rollback()
    chukwudi = await db_session.scalar(
        select(Participant)
        .options(selectinload(Participant.institution), selectinload(Participant.divisions))
        .where(Participant.tournament_id == tourn_id, Participant.email == "chukwudi.okafor@st.ug.edu.gh")
    )
    assert chukwudi is not None
    assert chukwudi.name == "Chukwudi Okafor"
    assert chukwudi.phone_number is None  # Must NOT be "University of Ghana"!
    assert chukwudi.institution is not None
    assert chukwudi.institution.name == "University of Ghana"

    efua = await db_session.scalar(
        select(Participant)
        .options(selectinload(Participant.institution), selectinload(Participant.divisions))
        .where(Participant.tournament_id == tourn_id, Participant.email == "efua.sutherland@st.knust.edu.gh")
    )
    assert efua is not None
    assert efua.phone_number is None
    assert efua.institution.name == "Kwame Nkrumah University of Science and Technology"
    efua_div_names = [d.name.lower() for d in efua.divisions]
    assert "open" in efua_div_names or "novice" in efua_div_names

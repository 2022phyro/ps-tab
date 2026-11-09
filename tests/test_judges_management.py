"""Tests for Tab Room admin judges management, 3-factor composite scores, public registration switcher, and Excel import/export."""

import io
import json
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import openpyxl

from kwuo.core.security import hash_password, create_session_token
from kwuo.models.user import User, UserStatus
from kwuo.models.tournament import (
    Tournament,
    TournamentStatus,
    Participant,
    ParticipantStatus,
    Division,
    Institution,
    JudgeProfile,
    ParticipantInstitution,
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
        status=TournamentStatus.REGISTRATION,
        judge_weight_test=40.0,
        judge_weight_cv=20.0,
        judge_weight_feedback=40.0,
    )
    db_session.add(tournament)
    await db_session.flush()

    div1 = Division(tournament_id=tournament.id, name="Open Division")
    div2 = Division(tournament_id=tournament.id, name="Novice Tier")
    db_session.add_all([div1, div2])

    inst = Institution(tournament_id=tournament.id, name="Stanford University", code="STAN")
    db_session.add(inst)

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
async def test_tournament_judge_weights_configuration(client: AsyncClient, db_session: AsyncSession):
    """Tournament settings config tab saves judge weight ratios (e.g. 4:2:4, 0:5:5)."""
    tournament, _, _, _, _, _ = await seed_tournament_with_admin_user(db_session)
    tourn_slug = str(tournament.slug)
    await login_test_official(client, tournament)

    host = f"{tourn_slug}.kwuo.com"
    res = await client.post(
        "/admin/settings",
        headers={"Host": host},
        data={
            "name": tournament.name,
            "location_type": tournament.location_type.value,
            "status": tournament.status.value,
            "ghost_round_limit": 2,
            "active_tab": "config",
            "judge_weight_test": 50.0,
            "judge_weight_cv": 0.0,
            "judge_weight_feedback": 50.0,
        },
        follow_redirects=True,
    )
    assert res.status_code == 200

    await db_session.refresh(tournament)
    assert tournament.judge_weight_test == 50.0
    assert tournament.judge_weight_cv == 0.0
    assert tournament.judge_weight_feedback == 50.0
    assert tournament.judge_weight_ratio_str in ("1:0:1", "50:0:50")


@pytest.mark.asyncio
async def test_judge_composite_score_calculation(db_session: AsyncSession):
    """JudgeProfile correctly clamps scores to [0, 10] and computes weighted composite score."""
    tournament, _, _, _, _, _ = await seed_tournament_with_admin_user(db_session)

    adj = JudgeProfile(
        participant_id="part_sample",
        test_score=8.0,
        cv_score=6.0,
    )
    # Weights: test 40, cv 20, feedback 40. With no feedback, weights are 40:20 (total 60)
    # (40 * 8.0 + 20 * 6.0) / 60 = (320 + 120) / 60 = 440 / 60 = 7.33
    score_no_fb = adj.calculate_composite_score(weight_test=40.0, weight_cv=20.0, weight_feedback=40.0, feedback_avg=None)
    assert score_no_fb == 7.33

    # With feedback of 9.0: (320 + 120 + 40 * 9.0) / 100 = (440 + 360) / 100 = 8.0
    score_with_fb = adj.calculate_composite_score(weight_test=40.0, weight_cv=20.0, weight_feedback=40.0, feedback_avg=9.0)
    assert score_with_fb == 8.0

    # Over 10 clamp test
    adj_clamped = JudgeProfile(
        participant_id="part_sample2",
        test_score=15.0,  # should clamp to 10.0
        cv_score=-5.0,   # should clamp to 0.0
    )
    score_clamped = adj_clamped.calculate_composite_score(weight_test=50.0, weight_cv=50.0, weight_feedback=0.0)
    # (50 * 10 + 50 * 0) / 100 = 5.0
    assert score_clamped == 5.0


@pytest.mark.asyncio
async def test_public_registration_switcher_speaker_and_judge(client: AsyncClient, db_session: AsyncSession):
    """Public /register handles both speaker and judge self-registration."""
    tournament, _, _, div1, div2, inst = await seed_tournament_with_admin_user(db_session)
    tourn_slug = str(tournament.slug)
    host = f"{tourn_slug}.kwuo.com"

    # 1. Register as Speaker
    res_spk = await client.post(
        "/register",
        headers={"Host": host},
        data={
            "registration_role": "speaker",
            "name": "Kofi Mensah",
            "email": "kofi@mensah.edu",
            "phone_number": "+1234567890",
            "pronouns": "he/him",
            "institution_id": inst.id,
            "division_ids": [div1.id],
        },
    )
    assert res_spk.status_code == 200
    assert "Registration Confirmed" in res_spk.text
    assert "/s/" in res_spk.text

    # 2. Register as Judge (with IA flag and secondary clash affiliations)
    sec_inst = Institution(tournament_id=tournament.id, name="Oxford University", code="OXF")
    db_session.add(sec_inst)
    await db_session.commit()
    await db_session.refresh(sec_inst)

    clashes_json = json.dumps([
        {"institution_id": sec_inst.id, "tie_type": "alumnus"}
    ])

    res_adj = await client.post(
        "/register",
        headers={"Host": host},
        data={
            "registration_role": "judge",
            "name": "Prof. Maya Angelou",
            "email": "maya@adjudicator.org",
            "phone_number": "",  # Optional phone
            "is_independent": "true",
            "institution_id": "none",
            "division_ids": [div1.id, div2.id],
            "secondary_affiliations_json": clashes_json,
        },
    )
    assert res_adj.status_code == 200
    assert "Registration Confirmed" in res_adj.text
    assert "Adjudicator" in res_adj.text
    assert "/j/" in res_adj.text

    # Verify database state for judge
    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.judge_profile),
            selectinload(Participant.divisions),
            selectinload(Participant.affiliations),
        )
        .where(Participant.email == "maya@adjudicator.org")
    )
    part_judge = (await db_session.execute(stmt)).scalar_one()
    assert part_judge.is_judge is True
    assert part_judge.judge_profile.is_independent is True
    assert len(part_judge.divisions) == 2
    # Verify Oxford was added as secondary clash
    sec_clashes = [a for a in part_judge.affiliations if not a.is_primary]
    assert len(sec_clashes) == 1
    assert sec_clashes[0].institution_id == sec_inst.id
    assert sec_clashes[0].tie_type == "alumnus"


@pytest.mark.asyncio
async def test_judge_zero_auth_portal_access(client: AsyncClient, db_session: AsyncSession):
    """Judge magic URL /j/{token}/me logs in and redirects to /portal/judge."""
    tournament, _, _, _, _, _ = await seed_tournament_with_admin_user(db_session)
    tourn_slug = str(tournament.slug)
    host = f"{tourn_slug}.kwuo.com"

    raw_token, token_hash = Participant.generate_token()
    adj_part = Participant(
        tournament_id=tournament.id,
        name="Chinua Achebe",
        email="chinua@judge.org",
        access_token_hash=token_hash,
    )
    adj_part.judge_profile = JudgeProfile(is_chair_eligible=True)
    db_session.add(adj_part)
    await db_session.commit()

    # Access magic link
    res_magic = await client.get(
        f"/j/{raw_token}/me",
        headers={"Host": host},
        follow_redirects=False,
    )
    assert res_magic.status_code == 303
    assert res_magic.headers["location"] == "/portal/judge"
    cookie_name = f"kwuo_part_{tournament.id}"
    assert cookie_name in res_magic.cookies


@pytest.mark.asyncio
async def test_admin_judges_management_flow(client: AsyncClient, db_session: AsyncSession):
    """Admin page renders, adds, inline-updates, sends magic link, and deletes judges."""
    tournament, _, _, div1, _, inst = await seed_tournament_with_admin_user(db_session)
    tourn_slug = str(tournament.slug)
    await login_test_official(client, tournament)
    host = f"{tourn_slug}.kwuo.com"

    # 1. GET /admin/judges
    res_page = await client.get("/admin/judges", headers={"Host": host})
    assert res_page.status_code == 200
    assert "Adjudicators Roster" in res_page.text

    # 2. POST /admin/judges (Add Judge)
    res_add = await client.post(
        "/admin/judges",
        headers={"Host": host},
        data={
            "name": "Dr. Ngozi Okonjo",
            "email": "ngozi@global.org",
            "phone": "+2348012345678",
            "institution_id": inst.id,
            "is_chair_eligible": "true",
            "is_reserve": "false",
            "is_independent": "false",
            "test_score": "8.5",
            "cv_score": "9.0",
            "division_ids": [div1.id],
        },
        follow_redirects=False,
    )
    assert res_add.status_code == 303

    stmt = select(Participant).where(Participant.email == "ngozi@global.org")
    ngozi = (await db_session.execute(stmt)).scalar_one()
    assert ngozi.judge_profile.is_chair_eligible is True
    assert ngozi.judge_profile.test_score == 8.5
    assert ngozi.judge_profile.cv_score == 9.0

    # 3. POST /admin/judges/{id}/update (Inline update)
    res_update = await client.post(
        f"/admin/judges/{ngozi.id}/update",
        headers={"Host": host, "Content-Type": "application/json"},
        json={
            "name": "Dr. Ngozi Iweala",
            "email": "ngozi@global.org",
            "phone": "",  # Empty phone test
            "is_chair_eligible": False,
            "is_reserve": True,
            "is_independent": True,
            "test_score": 9.5,
            "cv_score": 8.0,
            "institution_id": None,
            "division_ids": [div1.id],
        },
    )
    assert res_update.status_code == 200
    update_data = res_update.json()
    assert update_data["status"] == "ok"
    assert update_data["judge"]["name"] == "Dr. Ngozi Iweala"
    assert update_data["judge"]["phone"] == ""
    assert update_data["judge"]["is_reserve"] is True

    # 4. POST /admin/judges/{id}/send-link
    res_link = await client.post(
        f"/admin/judges/{ngozi.id}/send-link",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
    )
    assert res_link.status_code == 200
    assert res_link.json()["status"] == "ok"

    # 5. POST /admin/judges/{id}/delete
    res_del = await client.post(
        f"/admin/judges/{ngozi.id}/delete",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "ok"

    stmt_check = select(Participant).where(Participant.id == ngozi.id)
    assert (await db_session.execute(stmt_check)).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_admin_judges_excel_export_and_import(client: AsyncClient, db_session: AsyncSession):
    """Exporting and importing judges via Excel (.xlsx) roundtrips successfully."""
    tournament, _, _, div1, _, inst = await seed_tournament_with_admin_user(db_session)
    tourn_slug = str(tournament.slug)
    await login_test_official(client, tournament)
    host = f"{tourn_slug}.kwuo.com"

    # Seed judge
    raw_token, token_hash = Participant.generate_token()
    part = Participant(
        tournament_id=tournament.id,
        name="Wole Soyinka",
        email="wole@soyinka.org",
        institution_id=inst.id,
        access_token_hash=token_hash,
        divisions=[div1],
    )
    part.judge_profile = JudgeProfile(
        is_chair_eligible=True,
        test_score=9.0,
        cv_score=8.5,
    )
    db_session.add(part)
    await db_session.commit()

    # 1. Export Excel
    res_export = await client.get("/admin/judges/export", headers={"Host": host})
    assert res_export.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res_export.headers["content-type"]

    wb = openpyxl.load_workbook(io.BytesIO(res_export.content))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0][0] == "Full Name"
    assert rows[1][0] == "Wole Soyinka"
    assert rows[1][1] == "wole@soyinka.org"

    # 2. Import Excel
    import_wb = openpyxl.Workbook()
    import_ws = import_wb.active
    import_ws.append([
        "Full Name", "Email Address", "Phone Number", "Primary Institution",
        "Divisions", "Chair Eligible", "Reserve", "Independent", "Test Score", "CV Score"
    ])
    import_ws.append([
        "Toni Morrison", "toni@morrison.edu", "", "Princeton University",
        "Open Division", "Yes", "No", "No", "9.2", "8.8"
    ])
    import_buf = io.BytesIO()
    import_wb.save(import_buf)
    import_buf.seek(0)

    res_import = await client.post(
        "/admin/judges/import",
        headers={"Host": host},
        files={"file": ("new_judges.xlsx", import_buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=True,
    )
    assert res_import.status_code == 200

    stmt_toni = select(Participant).where(Participant.email == "toni@morrison.edu")
    toni = (await db_session.execute(stmt_toni)).scalar_one_or_none()
    assert toni is not None
    assert toni.name == "Toni Morrison"
    assert toni.judge_profile.is_chair_eligible is True
    assert toni.judge_profile.test_score == 9.2
    assert toni.judge_profile.cv_score == 8.8
    assert toni.institution.name == "Princeton University"

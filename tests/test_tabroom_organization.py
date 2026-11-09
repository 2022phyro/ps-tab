"""Tests for Tab Room Side Drawer Navigation and Phase 1 ORGANIZATION modules."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kwuo.core.security import hash_password
from kwuo.models.user import User, UserStatus
from kwuo.models.tournament import (
    Tournament,
    TournamentStatus,
    LocationType,
    BallotMode,
    DrawMethod,
    RoomSizePreference,
    Division,
    RubricCriterion,
    Participant,
    ParticipantStatus,
    SpeakerProfile,
    JudgeProfile,
    OfficialProfile,
    OfficialRole,
    Institution,
)


async def seed_tabroom(db_session: AsyncSession) -> tuple[Tournament, Participant, str]:
    """Seed tournament with division, institution, and authenticated tab official."""
    organizer = User(
        email="director@tabroom.edu",
        password_hash=hash_password("DirectorPass123!"),
        full_name="Tournament Director Sophia",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(organizer)
    await db_session.flush()

    tournament = Tournament(
        name="World Parliamentary Masters",
        slug="wpm-2026",
        organizer_id=organizer.id,
        status=TournamentStatus.ACTIVE,
        location_type=LocationType.HYBRID,
        location="Great Hall, Cambridge University",
        base_score=70.0,
        ceiling_score=85.0,
        max_time_penalty=5.0,
    )
    db_session.add(tournament)
    await db_session.flush()

    div_open = Division(tournament_id=tournament.id, name="Open", description="All collegiate speakers")
    db_session.add(div_open)

    inst = Institution(tournament_id=tournament.id, name="Cambridge Union", code="CAM")
    db_session.add(inst)
    await db_session.flush()

    # Official with password
    official_part = Participant(
        tournament_id=tournament.id,
        name="Chief Tabulator Marcus",
        email="marcus@wpm.org",
    )
    official_profile = OfficialProfile(role=OfficialRole.TAB)
    official_profile.set_password("TabPass123!")
    official_part.official_profile = official_profile
    db_session.add(official_part)

    # Initial speaker
    spk_part = Participant(
        tournament_id=tournament.id,
        name="Alice Walker",
        email="alice@cam.ac.uk",
        institution_id=inst.id,
    )
    spk_part.speaker_profile = SpeakerProfile()
    spk_part.divisions.append(div_open)
    db_session.add(spk_part)

    # Initial judge
    judge_part = Participant(
        tournament_id=tournament.id,
        name="Lord Justice Higgins",
        email="higgins@cam.ac.uk",
        institution_id=inst.id,
    )
    judge_part.judge_profile = JudgeProfile(is_chair_eligible=True)
    db_session.add(judge_part)

    await db_session.commit()
    await db_session.refresh(tournament)
    await db_session.refresh(official_part)

    return tournament, official_part, "TabPass123!"


async def login_official(client: AsyncClient, tournament: Tournament, email: str, password: str) -> None:
    """Perform login and persist official cookie."""
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
async def test_tabroom_side_drawer_renders_all_sections(client: AsyncClient, db_session: AsyncSession):
    """Side drawer renders Organization 8 items, Rounds, and Asides badges."""
    tournament, official, password = await seed_tabroom(db_session)
    await login_official(client, tournament, official.email, password)
    host = f"{tournament.slug}.kwuo.com"

    res = await client.get("/admin", headers={"Host": host})
    assert res.status_code == 200
    html = res.text

    # Side Drawer Organization items
    assert "/admin/settings" in html
    assert "/admin/documents" in html
    assert "/admin/rubric" in html
    assert "/admin/speakers" in html
    assert "/admin/judges" in html
    assert "/admin/officials" in html
    assert "/admin/institutions" in html

    # Rounds & Asides
    assert "Rounds" in html
    assert "Clashes" in html
    assert "Equity Desk" in html


@pytest.mark.asyncio
async def test_tabroom_settings_get_and_post(client: AsyncClient, db_session: AsyncSession):
    """View and update tournament settings."""
    tournament, official, password = await seed_tabroom(db_session)
    await login_official(client, tournament, official.email, password)
    host = f"{tournament.slug}.kwuo.com"

    # GET
    res = await client.get("/admin/settings", headers={"Host": host})
    assert res.status_code == 200
    assert "Tournament Settings" in res.text
    assert tournament.name in res.text

    # POST update
    post_res = await client.post(
        "/admin/settings",
        headers={"Host": host},
        data={
            "name": "World Parliamentary Masters Updated",
            "location_type": "physical",
            "status": "active",
            "location": "Senate House, Oxford",
            "ghost_round_limit": "3",
            "start_date": "2026-11-10",
            "end_date": "2026-11-15",
            "description": "Updated championship description",
        },
        follow_redirects=True,
    )
    assert post_res.status_code == 200
    assert "Tournament settings saved successfully" in post_res.text
    assert "World Parliamentary Masters Updated" in post_res.text

    # Add Schedule milestone
    sch_res = await client.post(
        "/admin/settings/schedule",
        headers={"Host": host},
        data={
            "title": "Grand Final Presentation",
            "start_time": "2026-11-15T15:00",
            "end_time": "2026-11-15T17:30",
            "location": "Main Auditorium",
            "description": "Final championship speeches and award gala",
        },
        follow_redirects=True,
    )
    assert sch_res.status_code == 200
    assert "Schedule milestone added" in sch_res.text
    assert "Grand Final Presentation" in sch_res.text

    # Test .ics download
    ics_res = await client.get("/schedule/download.ics", headers={"Host": host})
    assert ics_res.status_code == 200
    assert ics_res.headers["content-type"].startswith("text/calendar")
    assert "attachment;" in ics_res.headers.get("content-disposition", "")
    assert "schedule.ics" in ics_res.headers.get("content-disposition", "")
    assert "BEGIN:VCALENDAR" in ics_res.text
    assert "Grand Final Presentation" in ics_res.text


@pytest.mark.asyncio
async def test_tournament_links_crud_and_public_display(client: AsyncClient, db_session: AsyncSession):
    """Organizers can configure external/communication links with presets and view them on public homepage."""
    tournament, official, password = await seed_tabroom(db_session)
    await login_official(client, tournament, official.email, password)
    host = f"{tournament.slug}.kwuo.com"

    # 1. View settings with tab=links
    get_res = await client.get("/admin/settings?tab=links", headers={"Host": host})
    assert get_res.status_code == 200
    assert "Links" in get_res.text

    # 2. Add WhatsApp link
    wa_res = await client.post(
        "/admin/settings/links",
        headers={"Host": host},
        data={
            "label": "Official WhatsApp Group",
            "url": "https://chat.whatsapp.com/invitation123",
            "preset": "whatsapp",
            "description": "Urgent announcements and flight calls",
            "is_public": "true",
        },
        follow_redirects=True,
    )
    assert wa_res.status_code == 200
    assert "Tournament link saved successfully" in wa_res.text
    assert "Official WhatsApp Group" in wa_res.text
    assert "ph-whatsapp-logo" in wa_res.text

    # 3. Add Discord server link
    dc_res = await client.post(
        "/admin/settings/links",
        headers={"Host": host},
        data={
            "label": "Judges & Debaters Discord",
            "url": "discord.gg/speechtab",
            "preset": "discord",
            "description": "Virtual debater lounge",
            "is_public": "true",
        },
        follow_redirects=True,
    )
    assert dc_res.status_code == 200
    assert "Judges &amp; Debaters Discord" in dc_res.text or "Judges & Debaters Discord" in dc_res.text
    assert "ph-discord-logo" in dc_res.text

    # Verify links on tournament model in db
    await db_session.refresh(tournament)
    assert len(tournament.links) == 2
    wa_link = next(l for l in tournament.links if l["preset"] == "whatsapp")
    dc_link = next(l for l in tournament.links if l["preset"] == "discord")
    assert wa_link["url"] == "https://chat.whatsapp.com/invitation123"
    assert dc_link["url"] == "https://discord.gg/speechtab"  # auto-prepended https://
    assert len(tournament.public_links) == 2

    # 4. Edit WhatsApp link
    edit_res = await client.post(
        "/admin/settings/links",
        headers={"Host": host},
        data={
            "link_id": wa_link["id"],
            "label": "Updated Official WhatsApp Announcements",
            "url": "https://chat.whatsapp.com/updated123",
            "preset": "whatsapp",
            "description": "All participants flight calls",
            "is_public": "true",
        },
        follow_redirects=True,
    )
    assert edit_res.status_code == 200
    assert "Updated Official WhatsApp Announcements" in edit_res.text

    # 5. Delete Discord link
    del_res = await client.post(
        f"/admin/settings/links/{dc_link['id']}/delete",
        headers={"Host": host},
        follow_redirects=True,
    )
    assert del_res.status_code == 200
    assert "Link deleted successfully" in del_res.text

    await db_session.refresh(tournament)
    assert len(tournament.links) == 1
    assert tournament.links[0]["id"] == wa_link["id"]

    # 6. Verify public homepage displays the WhatsApp link with icon and badge
    home_res = await client.get("/", headers={"Host": host})
    assert home_res.status_code == 200
    assert "Official Channels &amp; Links" in home_res.text or "Official Channels & Links" in home_res.text
    assert "Updated Official WhatsApp Announcements" in home_res.text
    assert "ph-whatsapp-logo" in home_res.text



@pytest.mark.asyncio
async def test_tabroom_rubric_boundaries_and_criteria(client: AsyncClient, db_session: AsyncSession):
    """Update scale boundaries and add/delete criteria dimensions."""
    tournament, official, password = await seed_tabroom(db_session)
    await login_official(client, tournament, official.email, password)
    host = f"{tournament.slug}.kwuo.com"

    # GET
    res = await client.get("/admin/rubric", headers={"Host": host})
    assert res.status_code == 200
    assert "Scoring Criteria &amp; Rubric Standard" in res.text or "Scoring Criteria & Rubric Standard" in res.text

    # Save boundaries
    res_bound = await client.post(
        "/admin/rubric",
        headers={"Host": host},
        data={"base_score": "68.0", "ceiling_score": "86.0", "max_time_penalty": "6.0"},
        follow_redirects=True,
    )
    assert res_bound.status_code == 200
    assert "Scoring scale boundaries saved successfully" in res_bound.text

    # Add criterion
    res_crit = await client.post(
        "/admin/rubric/criterion",
        headers={"Host": host},
        data={
            "name": "Elocution & Nuance",
            "max_points": "12.0",
            "display_order": "1",
            "description": "Clarity of voice and rhetoric",
        },
        follow_redirects=True,
    )
    assert res_crit.status_code == 200
    assert "Elocution &amp; Nuance" in res_crit.text or "Elocution & Nuance" in res_crit.text


@pytest.mark.asyncio
async def test_tabroom_documents_editable_table_and_crud(client: AsyncClient, db_session: AsyncSession):
    """Test full documents workflow: table rendering, upload via modal, inline update, and deletion."""
    import io
    tournament, official, password = await seed_tabroom(db_session)
    await login_official(client, tournament, official.email, password)
    host = f"{tournament.slug}.kwuo.com"

    # 1. GET /admin/documents renders table
    res_get = await client.get("/admin/documents", headers={"Host": host})
    assert res_get.status_code == 200
    assert "Documents &amp; Setup Repository" in res_get.text or "Documents & Setup Repository" in res_get.text
    assert "Add Document" in res_get.text
    assert "kwuoCustomSelect" in res_get.text
    assert "o.value ===" not in res_get.text
    assert "max 75MB" in res_get.text

    # 2. Upload new presentation / slide deck document (PPTX)
    from kwuo.core.typeid import generate_typeid
    sample_task_id = generate_typeid("task")
    pptx_bytes = b"PK\x03\x04 fake break slide deck binary content for test"
    files = {"file": ("breaks_round1.pptx", io.BytesIO(pptx_bytes), "application/vnd.openxmlformats-officedocument.presentationml.presentation")}
    data = {
        "title": "Adjudicator Official Briefing & Break Slides",
        "category": "briefing",
        "task_id": sample_task_id,
        "is_public": "true",
        "display_order": "1",
    }
    res_upload = await client.post(
        "/admin/documents/upload",
        headers={"Host": host},
        data=data,
        files=files,
        follow_redirects=True,
    )
    assert res_upload.status_code == 200
    assert "Document uploaded successfully" in res_upload.text
    assert "Adjudicator Official Briefing &amp; Break Slides" in res_upload.text or "Adjudicator Official Briefing & Break Slides" in res_upload.text
    assert "startEdit" in res_upload.text
    assert "openDelete" in res_upload.text

    # Find the newly created attachment
    from kwuo.models.attachment import FileAttachment
    att = (await db_session.execute(select(FileAttachment).where(FileAttachment.tournament_id == tournament.id))).scalar_one()
    assert att.title == "Adjudicator Official Briefing & Break Slides"
    assert att.task_id == sample_task_id
    assert att.extension == "pptx"

    # 3. Inline update document cells (AJAX mode with awards_breaks category)
    updated_task_id = generate_typeid("task")
    update_data = {
        "title": "Grand Final Break Slides",
        "category": "awards_breaks",
        "task_id": updated_task_id,
        "is_public": "true",
        "display_order": "2",
        "description": "Amended equity and judging protocol",
    }
    res_update_ajax = await client.post(
        f"/admin/documents/{att.id}/update",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
        data=update_data,
    )
    assert res_update_ajax.status_code == 200
    ajax_json = res_update_ajax.json()
    assert ajax_json["status"] == "ok"
    assert ajax_json["category"] == "awards_breaks"

    # Verify updated values in DB
    await db_session.refresh(att)
    assert att.title == "Grand Final Break Slides"
    assert att.category.value == "awards_breaks"
    assert att.task_id == updated_task_id

    # 4. Upload Staff-Only Document and Verify Admin vs Public Sync
    staff_doc_files = {"file": ("tab_room_deliberations.pdf", io.BytesIO(b"%PDF-1.4 confidential tab data"), "application/pdf")}
    res_staff_upload = await client.post(
        "/admin/documents/upload",
        headers={"Host": host},
        data={
            "title": "Internal Tab Room Deliberations",
            "category": "rules",
            "is_public": "false",  # Staff Only
            "display_order": "3",
        },
        files=staff_doc_files,
        follow_redirects=True,
    )
    assert res_staff_upload.status_code == 200
    assert "Internal Tab Room Deliberations" in res_staff_upload.text
    # In admin view, it must show Staff Only and not Public for this document
    assert "Staff Only" in res_staff_upload.text

    # On public /documents, the staff-only document must NOT appear
    pub_docs = await client.get("/documents", headers={"Host": host})
    assert pub_docs.status_code == 200
    assert "Internal Tab Room Deliberations" not in pub_docs.text
    # Public filters should only contain categories existing in public DB documents (e.g. Awards & Breaks)
    assert "Grand Final Break Slides" in pub_docs.text
    assert "Awards &amp; Breaks" in pub_docs.text or "Awards & Breaks" in pub_docs.text

    # 5. Delete document via AJAX
    res_delete_ajax = await client.post(
        f"/admin/documents/{att.id}/delete",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
    )
    assert res_delete_ajax.status_code == 200
    assert res_delete_ajax.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_tabroom_speakers_management(client: AsyncClient, db_session: AsyncSession):
    """Register single-name speaker and toggle check-in status."""
    tournament, official, password = await seed_tabroom(db_session)
    await login_official(client, tournament, official.email, password)
    host = f"{tournament.slug}.kwuo.com"

    # GET
    res = await client.get("/admin/speakers", headers={"Host": host})
    assert res.status_code == 200
    assert "Alice Walker" in res.text

    # Register new speaker with single nickname
    div_id = tournament.divisions[0].id
    res_add = await client.post(
        "/admin/speakers",
        headers={"Host": host},
        data={
            "name": "Kwame",
            "email": "kwame@student.org",
            "division_id": div_id,
            "institution_name": "Accra Debate Club",
        },
        follow_redirects=True,
    )
    assert res_add.status_code == 200
    assert "Kwame" in res_add.text
    assert "Speaker registered successfully" in res_add.text

    # Toggle check-in for Alice Walker
    alice = [s for s in tournament.speakers if s.name == "Alice Walker"][0]
    res_checkin = await client.post(
        f"/admin/speakers/{alice.id}/toggle-checkin",
        headers={"Host": host},
        follow_redirects=True,
    )
    assert res_checkin.status_code == 200
    assert "Present" in res_checkin.text or "Checked In" in res_checkin.text


@pytest.mark.asyncio
async def test_tabroom_judges_management(client: AsyncClient, db_session: AsyncSession):
    """Accredit new judge and toggle arrival check-in."""
    tournament, official, password = await seed_tabroom(db_session)
    await login_official(client, tournament, official.email, password)
    host = f"{tournament.slug}.kwuo.com"

    # GET
    res = await client.get("/admin/judges", headers={"Host": host})
    assert res.status_code == 200
    assert "Lord Justice Higgins" in res.text

    # Accredit judge
    res_add = await client.post(
        "/admin/judges",
        headers={"Host": host},
        data={
            "name": "Prof. Beatrice Vance",
            "email": "beatrice@law.ox.ac.uk",
            "institution_name": "Oxford Union",
            "is_chair_eligible": "true",
            "is_reserve": "false",
        },
        follow_redirects=True,
    )
    assert res_add.status_code == 200
    assert "Prof. Beatrice Vance" in res_add.text
    assert "Judge accredited successfully" in res_add.text


@pytest.mark.asyncio
async def test_tabroom_rules_configuration(client: AsyncClient, db_session: AsyncSession):
    """Configure balloting mode and room sizing bounds."""
    tournament, official, password = await seed_tabroom(db_session)
    await login_official(client, tournament, official.email, password)
    host = f"{tournament.slug}.kwuo.com"

    res = await client.post(
        "/admin/rules",
        headers={"Host": host},
        data={
            "ballot_mode": "strict",
            "draw_method": "power_matched",
            "min_room_size": "4",
            "max_room_size": "8",
            "room_size_preference": "smaller_rooms",
            "panel_size": "3",
            "minimum_panel_size": "1",
            "allow_prelim_ties": "true",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert "Rules and draw configuration saved successfully" in res.text


@pytest.mark.asyncio
async def test_tabroom_unauthenticated_subroutes_redirect(client: AsyncClient, db_session: AsyncSession):
    """Unauthenticated requests to any /admin/* sub-route redirect to /admin/login."""
    tournament, _, _ = await seed_tabroom(db_session)
    host = f"{tournament.slug}.kwuo.com"

    for subpath in ("/admin/settings", "/admin/documents", "/admin/rubric", "/admin/speakers", "/admin/judges", "/admin/officials", "/admin/institutions"):
        res = await client.get(subpath, headers={"Host": host}, follow_redirects=False)
        assert res.status_code == 307
        assert res.headers["location"] == "/admin/login"

    # /admin/rules is a consolidated route that redirects to /admin/settings?tab=config
    res_rules = await client.get("/admin/rules", headers={"Host": host}, follow_redirects=False)
    assert res_rules.status_code == 307
    assert res_rules.headers["location"] == "/admin/settings?tab=config"


@pytest.mark.asyncio
async def test_tabroom_institutions_full_workflow(client: AsyncClient, db_session: AsyncSession):
    """Test public table, admin management, autocomplete, in-place edit, merge, and Excel export/import."""
    import io
    import openpyxl
    tournament, official, password = await seed_tabroom(db_session)
    await login_official(client, tournament, official.email, password)
    host = f"{tournament.slug}.kwuo.com"

    # 1. Public Institutions Table
    pub_res = await client.get("/institutions", headers={"Host": host})
    assert pub_res.status_code == 200
    assert "Participating Delegations" in pub_res.text
    assert "<table" in pub_res.text
    assert "Speakers" in pub_res.text
    assert "Judges" in pub_res.text
    assert "viewMode" in pub_res.text
    assert "visibleCols" in pub_res.text
    assert "font-mono" not in pub_res.text

    # 2. Admin Institutions Table & Controls
    admin_res = await client.get("/admin/institutions", headers={"Host": host})
    assert admin_res.status_code == 200
    assert "Institutions &amp; Delegations" in admin_res.text or "Institutions & Delegations" in admin_res.text
    assert "institutionManager" in admin_res.text
    assert "Download Excel" in admin_res.text
    assert "Upload Excel" in admin_res.text
    assert "Merge" in admin_res.text
    assert "Add Institution" in admin_res.text
    assert "viewMode" in admin_res.text
    assert "visibleCols" in admin_res.text
    assert "region-catalog-datalist" in admin_res.text
    assert "country-catalog-datalist" in admin_res.text
    assert '<option value="us">' not in admin_res.text
    assert "font-mono" not in admin_res.text

    # 3. Add Institution via Form / AJAX
    add_res = await client.post(
        "/admin/institutions",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
        data={
            "name": "Harvard Forensic Society",
            "code": "HARV",
            "country": "United States",
            "region": "North America",
        },
    )
    assert add_res.status_code == 200
    add_json = add_res.json()
    assert add_json["status"] == "ok"
    assert add_json["institution"]["name"] == "Harvard Forensic Society"
    assert add_json["institution"]["code"] == "HARV"
    assert add_json["institution"]["country"] == "us"
    assert add_json["institution"]["region"] == "north america"
    inst_id1 = add_json["institution"]["id"]

    # 4. Combobox Live Search
    search_res = await client.get("/admin/institutions/search?q=harv", headers={"Host": host})
    assert search_res.status_code == 200
    results = search_res.json()
    assert len(results) >= 1
    assert any(r["name"] == "Harvard Forensic Society" for r in results)

    # 5. In-Place Update via AJAX
    update_res = await client.post(
        f"/admin/institutions/{inst_id1}/update",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
        data={
            "name": "Harvard Speech & Debate",
            "code": "HSD",
            "country": "US",
            "region": "East Coast",
        },
    )
    assert update_res.status_code == 200
    upd_json = update_res.json()
    assert upd_json["status"] == "ok"
    assert upd_json["institution"]["name"] == "Harvard Speech & Debate"
    assert upd_json["institution"]["code"] == "HSD"
    assert upd_json["institution"]["region"] == "east coast"

    # 6. Add second variation for Merge test
    add_res2 = await client.post(
        "/admin/institutions",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
        data={
            "name": "Harvard College Debate",
            "code": "HCD",
            "country": "us",
            "region": "east coast",
        },
    )
    assert add_res2.status_code == 200
    inst_id2 = add_res2.json()["institution"]["id"]

    # Assign participant to inst_id2
    part = Participant(
        tournament_id=tournament.id,
        institution_id=inst_id2,
        name="Elena Rostova",
        email="elena@harvard.edu",
    )
    part.speaker_profile = SpeakerProfile()
    db_session.add(part)
    await db_session.commit()

    # Perform Merge
    merge_res = await client.post(
        "/admin/institutions/merge",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
        json={
            "source_ids": [inst_id1, inst_id2],
            "target_name": "Harvard University Unified",
            "target_code": "HARV",
            "target_country": "United States",
            "target_region": "North America",
        },
    )
    assert merge_res.status_code == 200
    merge_json = merge_res.json()
    assert merge_json["status"] == "ok"
    assert "Successfully merged" in merge_json["message"]

    # Verify participant reassigned to merged institution
    await db_session.refresh(part)
    assert part.institution_id == merge_json["merged_id"]

    # 7. Excel Export
    export_res = await client.get("/admin/institutions/export.xlsx", headers={"Host": host})
    assert export_res.status_code == 200
    assert export_res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "attachment;" in export_res.headers["content-disposition"]
    assert "institutions.xlsx" in export_res.headers["content-disposition"]

    # Verify Excel contents via openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(export_res.content))
    ws = wb.active
    assert ws.title == "Institutions"
    headers = [cell.value for cell in ws[1]]
    assert headers == ["Name", "Code", "Country", "Region", "Speakers", "Adjudicators", "IAs", "Total Participants"]

    # 8. Excel Import
    import_wb = openpyxl.Workbook()
    import_ws = import_wb.active
    import_ws.append(["Name", "Code", "Country", "Region"])
    import_ws.append(["Stanford Forensic Union", "STAN", "United States", "West Coast"])
    import_ws.append(["Oxford Union Society", "OXF", "United Kingdom", "Europe"])
    import_buf = io.BytesIO()
    import_wb.save(import_buf)
    import_buf.seek(0)

    import_res = await client.post(
        "/admin/institutions/import",
        headers={"Host": host},
        files={"file": ("new_institutions.xlsx", import_buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=True,
    )
    assert import_res.status_code == 200
    assert "Successfully imported" in import_res.text
    assert "Stanford Forensic Union" in import_res.text
    assert "Oxford Union Society" in import_res.text

    # 9. Delete Institution via AJAX
    del_res = await client.post(
        f"/admin/institutions/{merge_json['merged_id']}/delete",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
    )
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "ok"

    # 10. Bulk Delete Institutions via AJAX
    # Find newly imported institutions
    stmt_imported = select(Institution).where(Institution.name.in_(["Stanford Forensic Union", "Oxford Union Society"]))
    imported_insts = (await db_session.execute(stmt_imported)).scalars().all()
    assert len(imported_insts) == 2
    bulk_del_res = await client.post(
        "/admin/institutions/bulk-delete",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
        json={"institution_ids": [i.id for i in imported_insts]},
    )
    assert bulk_del_res.status_code == 200
    bulk_json = bulk_del_res.json()
    assert bulk_json["status"] == "ok"
    assert bulk_json["deleted_count"] == 2


@pytest.mark.asyncio
async def test_tournament_divisions_management_and_speaker_creation(client: AsyncClient, db_session: AsyncSession):
    """Admin creates divisions in settings config, public view displays them, and speakers view allows selecting a division."""
    tournament, official, password = await seed_tabroom(db_session)
    await login_official(client, tournament, official.email, password)
    host = f"{tournament.slug}.kwuo.com"

    # 1. Config option in settings shows existing Open division
    res_settings = await client.get("/admin/settings?tab=config", headers={"Host": host})
    assert res_settings.status_code == 200
    assert "Competitive Divisions" in res_settings.text
    assert "Open" in res_settings.text

    # 2. Admin creates a new division (e.g. "Novice")
    create_res = await client.post(
        "/admin/settings/divisions",
        headers={"Host": host},
        data={
            "name": "Novice",
            "description": "First-year competitive debaters",
        },
        follow_redirects=True,
    )
    assert create_res.status_code == 200
    assert "Novice" in create_res.text

    # 3. Admin creates another division (e.g. "ESL")
    create_esl_res = await client.post(
        "/admin/settings/divisions",
        headers={"Host": host},
        data={
            "name": "ESL",
            "description": "English as a Second Language",
        },
        follow_redirects=True,
    )
    assert create_esl_res.status_code == 200
    assert "ESL" in create_esl_res.text

    # 4. Reject duplicate division creation
    dup_res = await client.post(
        "/admin/settings/divisions",
        headers={"Host": host},
        data={"name": "novice"},
        follow_redirects=True,
    )
    assert dup_res.status_code == 200
    assert "already exists" in dup_res.text

    # 5. Public view displays the created divisions
    # 5a. Public homepage (/) shows all active divisions
    home_res = await client.get("/", headers={"Host": host})
    assert home_res.status_code == 200
    assert "Competitor Divisions" in home_res.text
    assert "Open" in home_res.text
    assert "Novice" in home_res.text
    assert "ESL" in home_res.text
    assert "3 Active" in home_res.text

    # 5b. Public registration (/register) shows divisions to select when in REGISTRATION status
    tournament.status = TournamentStatus.REGISTRATION
    await db_session.commit()
    reg_res = await client.get("/register", headers={"Host": host})
    assert reg_res.status_code == 200
    assert "Novice" in reg_res.text
    assert "ESL" in reg_res.text

    # 5c. Public directory (/participants) shows division filter options
    parts_res = await client.get("/participants", headers={"Host": host})
    assert parts_res.status_code == 200
    assert "Novice" in parts_res.text
    assert "ESL" in parts_res.text

    # 6. Speaker creation view allows selecting a division
    # 6a. Load /admin/speakers and verify divisions are present in the form
    spk_page_res = await client.get("/admin/speakers", headers={"Host": host})
    assert spk_page_res.status_code == 200
    assert "Novice" in spk_page_res.text
    assert "ESL" in spk_page_res.text

    # Find the Novice division ID from DB
    stmt_novice = select(Division).where(Division.tournament_id == tournament.id, Division.name == "Novice")
    novice_div = (await db_session.execute(stmt_novice)).scalar_one()

    # 6b. Register a new speaker with Novice division selected
    spk_create_res = await client.post(
        "/admin/speakers",
        headers={"Host": host, "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
        json={
            "name": "Jane Rookie",
            "email": "jane.rookie@oxford.edu",
            "division_ids": [novice_div.id],
        },
    )
    assert spk_create_res.status_code == 200
    spk_json = spk_create_res.json()
    assert spk_json["status"] == "ok"
    assert "Novice" in spk_json["speaker"]["divisions"]
    assert novice_div.id in spk_json["speaker"]["division_ids"]

    # 7. Update division
    update_res = await client.post(
        f"/admin/settings/divisions/{novice_div.id}",
        headers={"Host": host},
        data={
            "name": "Novice & Junior",
            "description": "Updated eligibility criteria",
        },
        follow_redirects=True,
    )
    assert update_res.status_code == 200
    assert "Novice &amp; Junior" in update_res.text or "Novice & Junior" in update_res.text

    # 8. Delete ESL division
    stmt_esl = select(Division).where(Division.tournament_id == tournament.id, Division.name == "ESL")
    esl_div = (await db_session.execute(stmt_esl)).scalar_one()
    del_res = await client.post(
        f"/admin/settings/divisions/{esl_div.id}/delete",
        headers={"Host": host},
        follow_redirects=True,
    )
    assert del_res.status_code == 200
    assert "deleted successfully" in del_res.text

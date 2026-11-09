"""Tests for tournament-scoped institutions, participant multi-affiliations with clash policies,
password setup invitation tokens, and granular dynamic RBAC authorization gating.
"""

from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from kwuo.main import app
from kwuo.core.security import hash_password
from kwuo.models.user import User, UserStatus
from kwuo.models.tournament import (
    Tournament,
    TournamentStatus,
    LocationType,
    Participant,
    OfficialProfile,
    OfficialRole,
    Institution,
    ParticipantInstitution,
    Role,
    Permission,
    normalize_institution_name,
)
from kwuo.services.email import EmailProviderRegistry
from kwuo.web.routes.tenant import (
    ensure_tournament_roles_and_permissions,
    DEFAULT_TABROOM_PERMISSIONS,
)


@pytest.fixture(autouse=True)
def setup_mock_email():
    """Ensure email testing clears dispatched messages."""
    EmailProviderRegistry.clear_history()
    yield
    EmailProviderRegistry.clear_history()


async def create_rbac_test_environment(db_session: AsyncSession) -> dict:
    """Seed a tournament with roles, permissions, and test institutions."""
    organizer = User(
        email="admin@lagos-open.org",
        password_hash=hash_password("Pass123!"),
        full_name="Tournament Director",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(organizer)
    await db_session.flush()

    tourn = Tournament(
        name="Lagos Open Debate Championship",
        slug="lagos-open",
        organizer_id=organizer.id,
        status=TournamentStatus.ACTIVE,
        location_type=LocationType.PHYSICAL,
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc) + timedelta(days=3),
    )
    db_session.add(tourn)
    await db_session.flush()

    # Ensure system roles and permissions seeded
    await ensure_tournament_roles_and_permissions(db_session, tourn.id)

    # Seed institutions
    inst_lagos = Institution(
        tournament_id=tourn.id,
        name="University of Lagos",
        code="UNILAG",
    )
    inst_ibadan = Institution(
        tournament_id=tourn.id,
        name="University of Ibadan",
        code="UI",
    )
    db_session.add_all([inst_lagos, inst_ibadan])
    await db_session.commit()

    return {
        "tournament": tourn,
        "unilag": inst_lagos,
        "ui": inst_ibadan,
    }


@pytest.mark.asyncio
async def test_institution_name_normalization_and_uniqueness(db_session: AsyncSession):
    """Test institution name normalization strips punctuation, collapses whitespace, and enforces unique normalized name."""
    env = await create_rbac_test_environment(db_session)
    tourn = env["tournament"]

    norm1 = normalize_institution_name("University of Lagos")
    norm2 = normalize_institution_name("  university  of  lagos...  ")
    assert norm1 == "university of lagos"
    assert norm1 == norm2

    # Attempting to add an institution with duplicate normalized name in same tournament fails integrity
    inst_dup = Institution(
        tournament_id=tourn.id,
        name="UNIVERSITY OF LAGOS",
        code="UNILAG2",
    )
    db_session.add(inst_dup)
    with pytest.raises(Exception):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_participant_multi_affiliations_and_clash_policies(db_session: AsyncSession):
    """Test participant can represent one institution and have multiple ties with distinct clash policies."""
    env = await create_rbac_test_environment(db_session)
    tourn = env["tournament"]
    unilag = env["unilag"]
    ui = env["ui"]

    person = Participant(
        tournament_id=tourn.id,
        name="Judge Adewale",
        email="adewale@example.com",
    )
    db_session.add(person)
    await db_session.flush()

    # 1. Primary representation (UNILAG)
    aff_rep = ParticipantInstitution(
        participant_id=person.id,
        institution_id=unilag.id,
        is_primary=True,
        tie_type="represents",
        clash_policy="hard",
    )
    # 2. Secondary affiliation: Alumnus of UI
    aff_alum = ParticipantInstitution(
        participant_id=person.id,
        institution_id=ui.id,
        is_primary=False,
        tie_type="alumnus",
        clash_policy="hard",
    )
    # 3. Secondary affiliation: Coach at UNILAG (same institution as represents, different tie type)
    aff_coach = ParticipantInstitution(
        participant_id=person.id,
        institution_id=unilag.id,
        is_primary=False,
        tie_type="coach",
        clash_policy="soft",
    )
    db_session.add_all([aff_rep, aff_alum, aff_coach])
    await db_session.commit()

    # Query back affiliations
    stmt = (
        select(ParticipantInstitution)
        .where(ParticipantInstitution.participant_id == person.id)
        .order_by(ParticipantInstitution.tie_type)
    )
    affs = (await db_session.execute(stmt)).scalars().all()
    assert len(affs) == 3
    tie_types = {a.tie_type for a in affs}
    assert tie_types == {"represents", "alumnus", "coach"}
    assert any(a.is_primary for a in affs)


async def login_test_official(client: AsyncClient, tournament: Tournament, email: str, password: str) -> None:
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
async def test_official_registration_without_password_and_email_invitation(client: AsyncClient, db_session: AsyncSession):
    """Test registering an official without manual password generates reset token and sends invitation email."""
    env = await create_rbac_test_environment(db_session)
    tourn = env["tournament"]
    host = f"{tourn.slug}.kwuo.com"

    # Fetch Tab Director role
    tab_role = (
        await db_session.execute(select(Role).where(Role.tournament_id == tourn.id, Role.name == "Tab Director"))
    ).scalar_one()

    # Create superadmin official to perform registration
    super_part = Participant(
        tournament_id=tourn.id,
        name="Super Director",
        email="super@lagos-open.org",
    )
    super_prof = OfficialProfile(role=OfficialRole.DIRECTOR)
    super_prof.set_password("AdminPass123!")
    super_part.official_profile = super_prof
    db_session.add(super_part)
    await db_session.commit()

    # Login as super director
    await login_test_official(client, tourn, "super@lagos-open.org", "AdminPass123!")

    # Register new official (no password provided)
    reg_res = await client.post(
        "/admin/officials",
        headers={"Host": host},
        data={
            "name": "Deputy Tabulator Amina",
            "email": "amina@tabroom.org",
            "role_ids": [tab_role.id],
        },
        follow_redirects=True,
    )
    assert reg_res.status_code == 200

    # Verify participant and profile created
    stmt = (
        select(OfficialProfile)
        .join(Participant, OfficialProfile.participant_id == Participant.id)
        .where(Participant.email == "amina@tabroom.org")
    )
    created_profile = (await db_session.execute(stmt)).scalar_one()
    assert created_profile.password_hash is None
    assert created_profile.reset_token_hash is not None
    assert created_profile.reset_token_expires_at > datetime.now(timezone.utc)

    # Verify email was dispatched into registry
    latest = EmailProviderRegistry.get_latest_email_for("amina@tabroom.org")
    assert latest is not None
    assert "Accreditation & Password Setup" in latest["subject"]
    assert "/admin/reset-password?token=" in latest["body"]


@pytest.mark.asyncio
async def test_reset_password_page_and_token_redemption(client: AsyncClient, db_session: AsyncSession):
    """Test official redeeming setup token to activate account and set password."""
    env = await create_rbac_test_environment(db_session)
    tourn = env["tournament"]
    host = f"{tourn.slug}.kwuo.com"

    # Create official with reset token
    raw_token, token_hash = OfficialProfile.generate_reset_token()
    part = Participant(
        tournament_id=tourn.id,
        name="Equity Lead Chioma",
        email="chioma@equity.org",
    )
    prof = OfficialProfile(
        role=OfficialRole.EQUITY,
        reset_token_hash=token_hash,
        reset_token_expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    part.official_profile = prof
    db_session.add(part)
    await db_session.commit()

    # 1. View password setup view with valid token
    get_res = await client.get(f"/admin/reset-password?token={raw_token}", headers={"Host": host})
    assert get_res.status_code == 200
    assert "Set Password" in get_res.text
    assert "chioma@equity.org" in get_res.text

    # 2. View with invalid token
    invalid_res = await client.get("/admin/reset-password?token=invalid_dummy_token", headers={"Host": host})
    assert invalid_res.status_code == 200
    assert "Invalid or expired password setup link" in invalid_res.text

    # 3. Submit matching password >= 8 characters
    post_res = await client.post(
        "/admin/reset-password",
        headers={"Host": host},
        data={
            "token": raw_token,
            "password": "SecurePassword99!",
            "confirm_password": "SecurePassword99!",
        },
        follow_redirects=False,
    )
    assert post_res.status_code == 303
    assert "/admin/login" in post_res.headers["location"]

    # 4. Verify official can now sign in with newly set password
    await login_test_official(client, tourn, "chioma@equity.org", "SecurePassword99!")


@pytest.mark.asyncio
async def test_rbac_permission_gating_and_role_access(client: AsyncClient, db_session: AsyncSession):
    """Test RBAC permission enforcement: official with restricted role is blocked (403) from unauthorized sections."""
    env = await create_rbac_test_environment(db_session)
    tourn = env["tournament"]
    host = f"{tourn.slug}.kwuo.com"

    # Create official with ONLY 'equity:manage' role
    eq_role = (
        await db_session.execute(select(Role).where(Role.tournament_id == tourn.id, Role.name == "Equity Officer"))
    ).scalar_one()

    part = Participant(
        tournament_id=tourn.id,
        name="Equity Specialist Chidi",
        email="chidi@equityonly.org",
    )
    prof = OfficialProfile()
    prof.set_password("EquitySecret123!")
    prof.roles.append(eq_role)
    part.official_profile = prof
    db_session.add(part)
    await db_session.commit()

    # Login as Equity Specialist
    await login_test_official(client, tourn, "chidi@equityonly.org", "EquitySecret123!")

    # 1. Accessing Rubric configuration (requires rubric:manage) -> 403 Forbidden
    rubric_res = await client.get("/admin/rubric", headers={"Host": host})
    assert rubric_res.status_code == 403
    assert "Access denied" in rubric_res.text

    # 2. Accessing Institutions management (requires institutions:manage) -> 403 Forbidden
    inst_res = await client.get("/admin/institutions", headers={"Host": host})
    assert inst_res.status_code == 403

    # 3. Accessing Authorization management (requires authorization:manage) -> 403 Forbidden
    auth_res = await client.get("/admin/authorization", headers={"Host": host})
    assert auth_res.status_code == 403

    # 4. Accessing Documents repository (Equity role has documents:manage permission) -> 200 OK
    doc_res = await client.get("/admin/documents", headers={"Host": host})
    assert doc_res.status_code == 200


@pytest.mark.asyncio
async def test_custom_role_creation_and_permission_assignment(client: AsyncClient, db_session: AsyncSession):
    """Test creating a custom tournament role with selected permissions and assigning it to staff."""
    env = await create_rbac_test_environment(db_session)
    tourn = env["tournament"]
    host = f"{tourn.slug}.kwuo.com"

    # Super director login
    super_part = Participant(
        tournament_id=tourn.id,
        name="Convenor Fola",
        email="fola@lagos-open.org",
    )
    super_prof = OfficialProfile(role=OfficialRole.DIRECTOR)
    super_prof.set_password("ConvenorPass123!")
    super_part.official_profile = super_prof
    db_session.add(super_part)
    await db_session.commit()

    await login_test_official(client, tourn, "fola@lagos-open.org", "ConvenorPass123!")

    # 1. Create custom role: "Volunteer Coordinator" with documents:manage and speakers:manage
    create_role_res = await client.post(
        "/admin/authorization/roles",
        headers={"Host": host},
        data={
            "name": "Volunteer Coordinator",
            "description": "Manages briefing docs and attendee check-ins",
            "permission_codes": ["documents:manage", "speakers:manage"],
        },
        follow_redirects=False,
    )
    assert create_role_res.status_code == 303

    # Verify role exists in DB
    custom_role = (
        await db_session.execute(
            select(Role).where(Role.tournament_id == tourn.id, Role.name == "Volunteer Coordinator")
        )
    ).scalar_one()
    assert not custom_role.is_system
    perm_codes = {p.code for p in custom_role.permissions}
    assert perm_codes == {"documents:manage", "speakers:manage"}

    # 2. View authorization cockpit page (200 OK)
    auth_page_res = await client.get("/admin/authorization", headers={"Host": host})
    assert auth_page_res.status_code == 200
    assert "Volunteer Coordinator" in auth_page_res.text
    assert "Tournament Roles" in auth_page_res.text


@pytest.mark.asyncio
async def test_institution_merge_with_target_matching_existing_source_name(client: AsyncClient, db_session: AsyncSession):
    """Test merging when target_name matches one of the other source institutions' names.
    
    Verifies no unique constraint violation on name_normalized occurs when sources[0]
    is merged into the name of sources[1].
    """
    env = await create_rbac_test_environment(db_session)
    tourn = env["tournament"]
    host = f"{tourn.slug}.kwuo.com"

    # Create two institutions: "University of Nigeria" and "University of Nigeria, Nsukka"
    unn1 = Institution(
        tournament_id=tourn.id,
        name="University of Nigeria",
        code="UNN",
    )
    unn2 = Institution(
        tournament_id=tourn.id,
        name="University of Nigeria, Nsukka",
        code="UNN-N",
    )
    db_session.add_all([unn1, unn2])
    await db_session.flush()

    # Participant linked to unn1
    spk = Participant(
        tournament_id=tourn.id,
        institution_id=unn1.id,
        name="Speaker Okon",
        email="okon@unn.edu.ng",
    )
    db_session.add(spk)

    # Super director login
    director = Participant(
        tournament_id=tourn.id,
        name="Tab Director Joy",
        email="joy@lagos-open.org",
    )
    prof = OfficialProfile(role=OfficialRole.DIRECTOR)
    prof.set_password("JoyPass123!")
    director.official_profile = prof
    db_session.add(director)
    await db_session.commit()

    await login_test_official(client, tourn, "joy@lagos-open.org", "JoyPass123!")

    # Merge unn1 and unn2 with target_name equal to unn2's name: "University of Nigeria, Nsukka"
    # source_ids has unn1 first
    merge_res = await client.post(
        "/admin/institutions/merge",
        headers={"Host": host},
        json={
            "source_ids": [unn1.id, unn2.id],
            "target_name": "University of Nigeria, Nsukka",
            "target_code": "UNN",
            "target_country": "NG",
            "target_region": "West Africa",
        },
    )
    assert merge_res.status_code == 200
    data = merge_res.json()
    assert data["status"] == "ok"
    merged_id = data["merged_id"]
    assert merged_id == unn2.id

    # Verify unn1 was deleted
    unn1_check = (
        await db_session.execute(select(Institution).where(Institution.id == unn1.id))
    ).scalar_one_or_none()
    assert unn1_check is None

    # Verify unn2 survived with updated code
    unn2_check = (
        await db_session.execute(select(Institution).where(Institution.id == unn2.id))
    ).scalar_one()
    assert unn2_check.name == "University of Nigeria, Nsukka"
    assert unn2_check.code == "UNN"

    # Verify participant was repointed to unn2.id
    await db_session.refresh(spk)
    assert spk.institution_id == unn2.id


@pytest.mark.asyncio
async def test_authorization_role_permissions_and_official_roles_ajax(client: AsyncClient, db_session: AsyncSession):
    """Test updating role permissions and official roles via AJAX JSON payloads."""
    env = await create_rbac_test_environment(db_session)
    tourn = env["tournament"]
    host = f"{tourn.slug}.kwuo.com"

    # Super director login
    director = Participant(
        tournament_id=tourn.id,
        name="Tab Director Joy",
        email="joy@lagos-open.org",
    )
    prof = OfficialProfile(role=OfficialRole.DIRECTOR)
    prof.set_password("JoyPass123!")
    director.official_profile = prof
    db_session.add(director)

    # Official to assign
    sub_official = Participant(
        tournament_id=tourn.id,
        name="Staff Member Tunde",
        email="tunde@lagos-open.org",
    )
    sub_prof = OfficialProfile()
    sub_official.official_profile = sub_prof
    db_session.add(sub_official)
    await db_session.commit()

    await login_test_official(client, tourn, "joy@lagos-open.org", "JoyPass123!")

    # 1. Update role permissions via JSON
    tab_role = (
        await db_session.execute(select(Role).where(Role.tournament_id == tourn.id, Role.name == "Tab Director"))
    ).scalar_one()

    perm_res = await client.post(
        f"/admin/authorization/roles/{tab_role.id}/permissions",
        headers={"Host": host},
        json={"permission_codes": ["speakers:manage", "judges:manage", "rounds:manage"]},
    )
    assert perm_res.status_code == 200
    perm_data = perm_res.json()
    assert perm_data["status"] == "ok"

    # 2. Assign role to official via JSON
    assign_res = await client.post(
        f"/admin/authorization/officials/{sub_prof.id}/roles",
        headers={"Host": host},
        json={"role_ids": [tab_role.id]},
    )
    assert assign_res.status_code == 200
    assign_data = assign_res.json()
    assert assign_data["status"] == "ok"
    assert "Tab Director" in assign_data["role_names"]
    assert assign_data["permissions_count"] == 3


@pytest.mark.asyncio
async def test_officials_bulk_send_invite_and_excel_export_import(client: AsyncClient, db_session: AsyncSession):
    """Test bulk dispatching setup invitations, downloading excel, and importing officials."""
    env = await create_rbac_test_environment(db_session)
    tourn = env["tournament"]
    host = f"{tourn.slug}.kwuo.com"

    # Super director login
    director = Participant(
        tournament_id=tourn.id,
        name="Convenor Joy",
        email="joy@lagos-open.org",
    )
    prof = OfficialProfile(role=OfficialRole.DIRECTOR)
    prof.set_password("JoyPass123!")
    director.official_profile = prof
    db_session.add(director)

    # 2 pending officials
    off1 = Participant(tournament_id=tourn.id, name="Pending Off 1", email="off1@lagos.org")
    prof1 = OfficialProfile()
    off1.official_profile = prof1

    off2 = Participant(tournament_id=tourn.id, name="Pending Off 2", email="off2@lagos.org")
    prof2 = OfficialProfile()
    off2.official_profile = prof2

    db_session.add_all([off1, off2])
    await db_session.commit()

    await login_test_official(client, tourn, "joy@lagos-open.org", "JoyPass123!")

    # 1. Bulk send invitations
    bulk_res = await client.post(
        "/admin/officials/bulk-send-invite",
        headers={"Host": host},
        json={"official_ids": [prof1.id, prof2.id]},
    )
    assert bulk_res.status_code == 200
    bulk_data = bulk_res.json()
    assert bulk_data["status"] == "ok"
    assert bulk_data["count"] == 2

    # 2. Export excel
    export_res = await client.get("/admin/officials/export.xlsx", headers={"Host": host})
    assert export_res.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in export_res.headers["content-type"]
    assert len(export_res.content) > 100

    # 3. Import officials from CSV
    csv_content = (
        "Full Name,Email,Roles,Institution,Notes\n"
        "Chief Justice Wale,wale@supremecourt.org,\"Chief Adjudicator (CA), Tab Director\",University of Lagos,Key judge\n"
        "Equity Assistant Bimbo,bimbo@equitynet.org,Equity Officer,University of Ibadan,Lead investigator\n"
    ).encode("utf-8")

    import_res = await client.post(
        "/admin/officials/import",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
        files={"file": ("officials.csv", csv_content, "text/csv")},
    )
    assert import_res.status_code == 200
    import_data = import_res.json()
    assert import_data["status"] == "ok"
    assert import_data["imported"] == 2

    # Verify newly imported official exists in DB
    imported_part = (
        await db_session.execute(
            select(Participant)
            .options(selectinload(Participant.official_profile).selectinload(OfficialProfile.roles))
            .where(Participant.email == "wale@supremecourt.org")
        )
    ).scalar_one()
    assert imported_part.name == "Chief Justice Wale"
    assert imported_part.official_profile is not None
    assert len(imported_part.official_profile.roles) == 2


@pytest.mark.asyncio
async def test_official_title_phone_privacy_and_multi_affiliations(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Test official profile title, phone number privacy, and multi-school affiliations."""
    env = await create_rbac_test_environment(db_session)
    tourn = env["tournament"]
    unilag = env["unilag"]
    ui = env["ui"]
    host = f"{tourn.slug}.localhost:8000"

    # 1. Create an admin official to perform updates
    admin_part = Participant(
        tournament_id=tourn.id,
        name="Admin Supervisor",
        email="supervisor@lagos-open.org",
        institution_id=unilag.id,
    )
    admin_prof = OfficialProfile()
    admin_prof.set_password("Supervisor123!")
    admin_part.official_profile = admin_prof

    # Grant Tournament Director role
    td_role = (await db_session.execute(select(Role).where(Role.tournament_id == tourn.id, Role.name == "Tournament Director"))).scalar_one()
    admin_prof.roles.append(td_role)
    db_session.add(admin_part)

    # 2. Register a new official with Title, Phone, and Public Phone checked
    new_official_part = Participant(
        tournament_id=tourn.id,
        name="Dr. Kwame Mensah",
        email="kwame@ghana-open.org",
        institution_id=unilag.id,
    )
    new_official_prof = OfficialProfile(
        title="Co-Chief Adjudicator",
        phone="+233 24 123 4567",
        is_phone_public=True,
    )
    new_official_part.official_profile = new_official_prof
    db_session.add(new_official_part)
    await db_session.commit()

    await login_test_official(client, tourn, "supervisor@lagos-open.org", "Supervisor123!")

    # 3. Update official via AJAX endpoint: set secondary affiliations and toggle phone privacy to False
    update_res = await client.post(
        f"/admin/officials/{new_official_prof.id}/update",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
        json={
            "name": "Dr. Kwame Mensah",
            "email": "kwame@ghana-open.org",
            "title": "Chief Adjudication Panel Lead",
            "phone": "+233 24 999 8888",
            "is_phone_public": False,
            "primary_institution_id": unilag.id,
            "role_ids": [td_role.id],
            "secondary_affiliations": [
                {"institution_id": ui.id, "tie_type": "alumnus"}
            ],
        },
    )
    assert update_res.status_code == 200
    update_data = update_res.json()
    assert update_data["status"] == "ok"
    assert update_data["official"]["title"] == "Chief Adjudication Panel Lead"
    assert update_data["official"]["is_phone_public"] is False

    # 4. Verify in DB
    refreshed_prof = (
        await db_session.execute(
            select(OfficialProfile)
            .options(
                selectinload(OfficialProfile.participant).selectinload(Participant.affiliations),
                selectinload(OfficialProfile.roles),
            )
            .where(OfficialProfile.id == new_official_prof.id)
        )
    ).scalar_one()
    assert refreshed_prof.title == "Chief Adjudication Panel Lead"
    assert refreshed_prof.phone == "+233 24 999 8888"
    assert refreshed_prof.is_phone_public is False
    assert len(refreshed_prof.participant.affiliations) >= 2

    # 5. Verify public homepage: official title and name appear, but private phone number is HIDDEN
    home_res = await client.get("/", headers={"Host": host})
    assert home_res.status_code == 200
    home_html = home_res.text
    assert "Dr. Kwame Mensah" in home_html
    assert "Chief Adjudication Panel Lead" in home_html
    # Phone number MUST NOT leak because is_phone_public is False
    assert "+233 24 999 8888" not in home_html

    # 6. Now update is_phone_public back to True and verify phone appears on homepage
    await client.post(
        f"/admin/officials/{new_official_prof.id}/update",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
        json={
            "name": "Dr. Kwame Mensah",
            "email": "kwame@ghana-open.org",
            "title": "Chief Adjudication Panel Lead",
            "phone": "+233 24 999 8888",
            "is_phone_public": True,
            "primary_institution_id": unilag.id,
            "role_ids": [td_role.id],
            "secondary_affiliations": [
                {"institution_id": ui.id, "tie_type": "alumnus"}
            ],
        },
    )
    home_res2 = await client.get("/", headers={"Host": host})
    assert home_res2.status_code == 200
    # Public homepage strips personal phone contacts entirely to protect staff privacy
    assert "+233 24 999 8888" not in home_res2.text
    # But admin officials roster displays it
    admin_res = await client.get("/admin/officials", headers={"Host": host})
    assert admin_res.status_code == 200
    assert "+233 24 999 8888" in admin_res.text


@pytest.mark.asyncio
async def test_official_secondary_affiliations_attachment_and_retention(client: AsyncClient, db_session: AsyncSession):
    """Ensure attaching a new secondary affiliation does NOT remove or overwrite preexisting ones."""
    env = await create_rbac_test_environment(db_session)
    tournament = env["tournament"]
    unilag = env["unilag"]
    ui = env["ui"]
    oau = Institution(tournament_id=tournament.id, name="Obafemi Awolowo University", code="OAU")
    db_session.add(oau)
    await db_session.commit()
    host = f"{tournament.slug}.kwuo.com"

    # 1. Setup Director and log in
    admin_part = Participant(
        tournament_id=tournament.id,
        name="Tab Director Admin",
        email="tabdir@lagos-open.org",
    )
    admin_prof = OfficialProfile()
    admin_prof.set_password("Supervisor123!")
    admin_part.official_profile = admin_prof
    td_role = (await db_session.execute(select(Role).where(Role.tournament_id == tournament.id, Role.name == "Tournament Director"))).scalar_one()
    admin_prof.roles.append(td_role)
    db_session.add(admin_part)

    # 2. Setup target official
    target_part = Participant(
        tournament_id=tournament.id,
        name="Prof. Tunde Bakare",
        email="tunde.bakare@academic.org",
        institution_id=unilag.id,
    )
    target_prof = OfficialProfile(title="Adjudication Advisor")
    target_part.official_profile = target_prof
    db_session.add(target_part)
    await db_session.commit()

    await login_test_official(client, tournament, "tabdir@lagos-open.org", "Supervisor123!")
    official_prof = target_prof

    # 3. Add first secondary affiliation: UI as alumnus
    upd_res1 = await client.post(
        f"/admin/officials/{official_prof.id}/update",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
        json={
            "name": "Prof. Tunde Bakare",
            "email": "tunde.bakare@academic.org",
            "title": "Adjudication Advisor",
            "phone": "+234 801 111 2222",
            "is_phone_public": True,
            "primary_institution_id": unilag.id,
            "role_ids": [td_role.id],
            "secondary_affiliations": [
                {"institution_id": ui.id, "tie_type": "alumnus"}
            ],
        },
    )
    assert upd_res1.status_code == 200

    # Verify UI is present
    part1 = (
        await db_session.execute(
            select(Participant).options(selectinload(Participant.affiliations)).where(Participant.id == official_prof.participant_id)
        )
    ).scalar_one()
    sec_affs1 = [a for a in part1.affiliations if not a.is_primary]
    assert len(sec_affs1) == 1
    assert sec_affs1[0].institution_id == ui.id
    assert sec_affs1[0].tie_type == "alumnus"

    # 3. Attach a SECOND affiliation (OAU as coach) along with the existing UI affiliation
    upd_res2 = await client.post(
        f"/admin/officials/{official_prof.id}/update",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
        json={
            "name": "Prof. Tunde Bakare",
            "email": "tunde.bakare@academic.org",
            "title": "Adjudication Advisor",
            "phone": "+234 801 111 2222",
            "is_phone_public": True,
            "primary_institution_id": unilag.id,
            "role_ids": [td_role.id],
            "secondary_affiliations": [
                {"institution_id": ui.id, "tie_type": "alumnus"},
                {"institution_id": oau.id, "tie_type": "coach"},
            ],
        },
    )
    assert upd_res2.status_code == 200

    # Verify BOTH UI and OAU are attached and neither was deleted or overwritten
    part2 = (
        await db_session.execute(
            select(Participant).options(selectinload(Participant.affiliations)).where(Participant.id == target_part.id)
        )
    ).scalar_one()
    sec_affs2 = [a for a in part2.affiliations if not a.is_primary]
    assert len(sec_affs2) == 2
    sec_map2 = {a.institution_id: a.tie_type for a in sec_affs2}
    assert sec_map2[ui.id] == "alumnus"
    assert sec_map2[oau.id] == "coach"

    # 4. Now explicitly delete UI in the list, keeping only OAU
    upd_res3 = await client.post(
        f"/admin/officials/{official_prof.id}/update",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
        json={
            "name": "Prof. Tunde Bakare",
            "email": "tunde.bakare@academic.org",
            "title": "Adjudication Advisor",
            "phone": "+234 801 111 2222",
            "is_phone_public": True,
            "primary_institution_id": unilag.id,
            "role_ids": [td_role.id],
            "secondary_affiliations": [
                {"institution_id": oau.id, "tie_type": "coach"},
            ],
        },
    )
    assert upd_res3.status_code == 200

    part3 = (
        await db_session.execute(
            select(Participant).options(selectinload(Participant.affiliations)).where(Participant.id == target_part.id)
        )
    ).scalar_one()
    sec_affs3 = [a for a in part3.affiliations if not a.is_primary]
    assert len(sec_affs3) == 1
    assert sec_affs3[0].institution_id == oau.id
    assert sec_affs3[0].tie_type == "coach"


@pytest.mark.asyncio
async def test_delete_official_single_and_bulk(client: AsyncClient, db_session: AsyncSession):
    """Test single official delete and bulk delete with self-delete protection."""
    env = await create_rbac_test_environment(db_session)
    tourn = env["tournament"]
    host = f"{tourn.slug}.kwuo.com"

    # 1. Setup Director and log in
    admin_part = Participant(
        tournament_id=tourn.id,
        name="Tab Director Admin",
        email="tabdir@lagos-open.org",
    )
    admin_prof = OfficialProfile()
    admin_prof.set_password("Supervisor123!")
    admin_part.official_profile = admin_prof
    td_role = (
        await db_session.execute(
            select(Role).where(Role.tournament_id == tourn.id, Role.name == "Tournament Director")
        )
    ).scalar_one()
    admin_prof.roles.append(td_role)
    db_session.add(admin_part)

    # 2. Setup target official to delete
    del_part = Participant(
        tournament_id=tourn.id,
        name="Temporary Staff",
        email="temporary.staff@kwuo.com",
    )
    del_prof = OfficialProfile(title="Assistant Tab")
    del_part.official_profile = del_prof
    db_session.add(del_part)
    await db_session.commit()

    await login_test_official(client, tourn, "tabdir@lagos-open.org", "Supervisor123!")

    # Attempt to delete self -> should fail with 400
    self_del = await client.post(
        f"/admin/officials/{admin_prof.id}/delete",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
    )
    assert self_del.status_code == 400
    assert "cannot delete your own" in self_del.json()["message"]

    # Delete other official -> should succeed with 200
    del_res = await client.post(
        f"/admin/officials/{del_prof.id}/delete",
        headers={"Host": host, "X-Requested-With": "XMLHttpRequest"},
    )
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "ok"

    check = (
        await db_session.execute(
            select(OfficialProfile).where(OfficialProfile.id == del_prof.id)
        )
    ).scalar_one_or_none()
    assert check is None





"""Tests for tournament file handling, attachment models, and storage endpoints."""

import io
import os
import shutil
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kwuo.core.config import settings
from kwuo.core.security import SESSION_COOKIE_NAME, hash_password
from kwuo.models.user import User, UserStatus
from kwuo.models.tournament import Tournament, TournamentStatus, LocationType
from kwuo.models.attachment import FileAttachment, AttachmentCategory
from kwuo.services.storage import get_storage_base_dir


@pytest.fixture(autouse=True)
def isolate_test_uploads(tmp_path, monkeypatch):
    """Ensure tests use an isolated temporary directory for file uploads, preserving real uploads."""
    test_dir = tmp_path / "test_uploads"
    test_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(test_dir))
    yield test_dir
    # tmp_path is automatically cleaned up by pytest


async def create_test_organizer_and_tournament(db_session: AsyncSession) -> tuple[User, Tournament]:
    """Helper to seed an organizer and a draft tournament."""
    user = User(
        email="chief_tab@speech.org",
        password_hash=hash_password("TabDirectorPass123!"),
        full_name="Chief Director Sarah",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    tournament = Tournament(
        name="National Speech Showcase 2026",
        slug="national-speech-2026",
        organizer_id=user.id,
        status=TournamentStatus.DRAFT,
        location_type=LocationType.PHYSICAL,
        location="Chicago Convention Center",
        base_score=70.0,
        ceiling_score=100.0,
    )
    db_session.add(tournament)
    await db_session.commit()
    await db_session.refresh(tournament)
    return user, tournament


@pytest.mark.asyncio
async def test_upload_tournament_attachment_success(client: AsyncClient, db_session: AsyncSession):
    """Organizer can upload an adjudicator briefing document."""
    user, tournament = await create_test_organizer_and_tournament(db_session)

    # Log in
    login_res = await client.post(
        "/auth/login",
        data={"email": user.email, "password": "TabDirectorPass123!"},
        follow_redirects=False,
    )
    assert login_res.status_code == 302
    client.cookies.set(SESSION_COOKIE_NAME, login_res.cookies[SESSION_COOKIE_NAME])

    # Upload PDF file
    file_content = b"%PDF-1.4 Mock adjudicator briefing content for judges."
    files = {
        "file": ("Adjudicator_Briefing_2026.pdf", io.BytesIO(file_content), "application/pdf")
    }
    data = {
        "title": "Adjudicator Official Briefing",
        "category": "briefing",
        "description": "Comprehensive rubric guidelines and ballot submission instructions.",
        "is_public": "true",
        "display_order": "1",
    }

    res = await client.post(
        f"/tournaments/{tournament.id}/attachments",
        data=data,
        files=files,
        follow_redirects=False,
    )
    assert res.status_code in (302, 303)

    # Verify database record
    stmt = select(FileAttachment).where(FileAttachment.tournament_id == tournament.id)
    att = (await db_session.execute(stmt)).scalar_one_or_none()
    assert att is not None
    assert att.title == "Adjudicator Official Briefing"
    assert att.category == AttachmentCategory.BRIEFING
    assert att.filename.endswith("Adjudicator_Briefing_2026.pdf")
    assert att.file_size == len(file_content)
    assert att.mime_type == "application/pdf"
    assert att.sha256_hash is not None
    assert att.is_public is True
    assert att.task_id is None

    # Check physical file on disk
    base_dir = get_storage_base_dir()
    disk_path = base_dir / att.file_path
    assert disk_path.exists()
    assert disk_path.read_bytes() == file_content


@pytest.mark.asyncio
async def test_upload_task_material_attachment(client: AsyncClient, db_session: AsyncSession):
    """Files can be attached to specific round tasks or motions."""
    user, tournament = await create_test_organizer_and_tournament(db_session)

    login_res = await client.post(
        "/auth/login",
        data={"email": user.email, "password": "TabDirectorPass123!"},
        follow_redirects=False,
    )
    client.cookies.set(SESSION_COOKIE_NAME, login_res.cookies[SESSION_COOKIE_NAME])

    task_file_bytes = b"Motion: This House would abolish standardized speech quotas."
    files = {
        "file": ("round_1_motion.txt", io.BytesIO(task_file_bytes), "text/plain")
    }
    data = {
        "title": "Round 1 Motion Release Sheet",
        "category": "task_material",
        "task_id": "task_01h8x9p3z4w2y1q",
        "description": "Official motion prompt for Round 1 impromptu.",
        "is_public": "true",
    }

    res = await client.post(
        f"/tournaments/{tournament.id}/attachments",
        data=data,
        files=files,
        follow_redirects=False,
    )
    assert res.status_code in (302, 303)

    stmt = select(FileAttachment).where(FileAttachment.task_id == "task_01h8x9p3z4w2y1q")
    att = (await db_session.execute(stmt)).scalar_one_or_none()
    assert att is not None
    assert att.category == AttachmentCategory.TASK_MATERIAL
    assert att.task_id == "task_01h8x9p3z4w2y1q"


@pytest.mark.asyncio
async def test_disallowed_extension_rejected(client: AsyncClient, db_session: AsyncSession):
    """Uploading executables (.exe, .sh) is rejected."""
    user, tournament = await create_test_organizer_and_tournament(db_session)

    login_res = await client.post(
        "/auth/login",
        data={"email": user.email, "password": "TabDirectorPass123!"},
        follow_redirects=False,
    )
    client.cookies.set(SESSION_COOKIE_NAME, login_res.cookies[SESSION_COOKIE_NAME])

    files = {
        "file": ("malicious_script.exe", io.BytesIO(b"MZ executable header"), "application/x-msdownload")
    }
    data = {
        "title": "Malicious Payload",
        "category": "general",
    }

    res = await client.post(
        f"/tournaments/{tournament.id}/attachments",
        data=data,
        files=files,
        follow_redirects=False,
    )
    assert res.status_code == 400
    assert "not permitted" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_download_public_attachment_anonymous(client: AsyncClient, db_session: AsyncSession):
    """Any competitor or attendee can download public tournament files without logging in."""
    user, tournament = await create_test_organizer_and_tournament(db_session)

    login_res = await client.post(
        "/auth/login",
        data={"email": user.email, "password": "TabDirectorPass123!"},
        follow_redirects=False,
    )
    client.cookies.set(SESSION_COOKIE_NAME, login_res.cookies[SESSION_COOKIE_NAME])

    content = b"Official Equity Policy and Harassment Reporting Guide"
    files = {
        "file": ("Equity_Policy.pdf", io.BytesIO(content), "application/pdf")
    }
    await client.post(
        f"/tournaments/{tournament.id}/attachments",
        data={"title": "Equity Policy", "category": "equity", "is_public": "true"},
        files=files,
        follow_redirects=False,
    )

    stmt = select(FileAttachment).where(FileAttachment.tournament_id == tournament.id)
    att = (await db_session.execute(stmt)).scalar_one()

    # Clear cookies to simulate anonymous competitor / attendee
    client.cookies.clear()

    # Download via /files/{id}/download
    download_res = await client.get(f"/files/{att.id}/download")
    assert download_res.status_code == 200
    assert download_res.content == content
    assert "application/pdf" in download_res.headers["content-type"]


@pytest.mark.asyncio
async def test_download_private_attachment_access_control(client: AsyncClient, db_session: AsyncSession):
    """Private files require authentication and authorization."""
    user, tournament = await create_test_organizer_and_tournament(db_session)

    # Login as organizer to upload private file
    login_res = await client.post(
        "/auth/login",
        data={"email": user.email, "password": "TabDirectorPass123!"},
        follow_redirects=False,
    )
    client.cookies.set(SESSION_COOKIE_NAME, login_res.cookies[SESSION_COOKIE_NAME])

    confidential_data = b"Internal Tab Room Seed Keys & Private Notes"
    files = {
        "file": ("Tab_Secrets.txt", io.BytesIO(confidential_data), "text/plain")
    }
    await client.post(
        f"/tournaments/{tournament.id}/attachments",
        data={"title": "Internal Tab Notes", "category": "general", "is_public": "false"},
        files=files,
        follow_redirects=False,
    )

    stmt = select(FileAttachment).where(FileAttachment.tournament_id == tournament.id)
    att = (await db_session.execute(stmt)).scalar_one()

    # 1. Anonymous access is blocked (401)
    client.cookies.clear()
    res_anon = await client.get(f"/files/{att.id}/download")
    assert res_anon.status_code == 401

    # 2. Another non-organizer user is blocked (403)
    stranger = User(
        email="stranger@other.org",
        password_hash=hash_password("OtherPassword123!"),
        full_name="Random Attendee",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(stranger)
    await db_session.commit()

    login_stranger = await client.post(
        "/auth/login",
        data={"email": "stranger@other.org", "password": "OtherPassword123!"},
        follow_redirects=False,
    )
    client.cookies.set(SESSION_COOKIE_NAME, login_stranger.cookies[SESSION_COOKIE_NAME])
    res_forbidden = await client.get(f"/files/{att.id}/download")
    assert res_forbidden.status_code == 403

    # 3. Organizer can download
    client.cookies.set(SESSION_COOKIE_NAME, login_res.cookies[SESSION_COOKIE_NAME])
    res_org = await client.get(f"/files/{att.id}/download")
    assert res_org.status_code == 200
    assert res_org.content == confidential_data


@pytest.mark.asyncio
async def test_delete_attachment(client: AsyncClient, db_session: AsyncSession):
    """Deleting an attachment deletes both database record and disk file."""
    user, tournament = await create_test_organizer_and_tournament(db_session)

    login_res = await client.post(
        "/auth/login",
        data={"email": user.email, "password": "TabDirectorPass123!"},
        follow_redirects=False,
    )
    client.cookies.set(SESSION_COOKIE_NAME, login_res.cookies[SESSION_COOKIE_NAME])

    files = {
        "file": ("Draft_Schedule.pdf", io.BytesIO(b"Draft schedule content"), "application/pdf")
    }
    await client.post(
        f"/tournaments/{tournament.id}/attachments",
        data={"title": "Draft Schedule", "category": "schedule", "is_public": "true"},
        files=files,
        follow_redirects=False,
    )

    stmt = select(FileAttachment).where(FileAttachment.tournament_id == tournament.id)
    att = (await db_session.execute(stmt)).scalar_one()
    att_id = att.id
    file_path = att.file_path
    base_dir = get_storage_base_dir()
    disk_path = base_dir / file_path
    assert disk_path.exists()

    # Delete
    del_res = await client.post(
        f"/tournaments/{tournament.id}/attachments/{att_id}/delete",
        follow_redirects=False,
    )
    assert del_res.status_code in (302, 303)

    # Verify DB record gone
    stmt = select(FileAttachment).where(FileAttachment.id == att_id)
    assert (await db_session.execute(stmt)).scalar_one_or_none() is None

    # Verify physical file deleted from storage
    assert not disk_path.exists()


@pytest.mark.asyncio
async def test_tenant_subdomain_renders_documents(client: AsyncClient, db_session: AsyncSession):
    """Tenant subdomain portal lists public documents in the Documents & Briefings section."""
    user, tournament = await create_test_organizer_and_tournament(db_session)

    login_res = await client.post(
        "/auth/login",
        data={"email": user.email, "password": "TabDirectorPass123!"},
        follow_redirects=False,
    )
    client.cookies.set(SESSION_COOKIE_NAME, login_res.cookies[SESSION_COOKIE_NAME])

    # Upload public equity policy
    files = {
        "file": ("Equity_Guidelines.pdf", io.BytesIO(b"Respect each other in all rooms."), "application/pdf")
    }
    await client.post(
        f"/tournaments/{tournament.id}/attachments",
        data={"title": "Official Equity Guidelines", "category": "equity", "is_public": "true"},
        files=files,
        follow_redirects=False,
    )

    # Request tenant portal documents on subdomain
    tenant_res = await client.get(
        "/documents",
        headers={"Host": f"{tournament.slug}.kwuo.com"},
    )
    assert tenant_res.status_code == 200
    html = tenant_res.text
    assert "Documents &amp; Briefing" in html or "Documents & Briefing" in html
    assert "Official Equity Guidelines" in html
    assert "equity" in html.lower()
    assert "/download" in html

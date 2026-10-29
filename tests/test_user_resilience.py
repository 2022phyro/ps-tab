"""Comprehensive test suite for standardized user identity, resilience, OTP flows, Scoped RBAC, and audit logs."""

from datetime import datetime, timezone, timedelta
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from kwuo.core.security import SESSION_COOKIE_NAME, hash_password, create_session_token
from kwuo.core.rbac import seed_system_groups, SYSTEM_GROUPS_CATALOG
from kwuo.models.user import User, UserStatus, Group, GroupPermission
from kwuo.models.audit import AuditLog, AuditAction, AuditSeverity
from kwuo.services.otp import OtpService, OtpAction, OtpRateLimitExceeded, _fallback_cache, _fallback_rate_limits
from kwuo.services.email import EmailProviderRegistry, send_email
from kwuo.core.features import FeatureTracker


@pytest.fixture(autouse=True)
def clear_otp_caches():
    """Clear in-memory fallback caches before each test."""
    _fallback_cache.clear()
    _fallback_rate_limits.clear()
    yield
    _fallback_cache.clear()
    _fallback_rate_limits.clear()


# =========================================================================
# 1. Ephemeral Redis OTP Service Unit Tests
# =========================================================================

@pytest.mark.asyncio
async def test_otp_generation_verification_and_consumption():
    """Verify 6-digit OTP generation, SHA-256 validation, and consumption."""
    email = "orator@kwuo.org"
    action = OtpAction.ACCOUNT_VERIFY

    # Generate OTP
    code = await OtpService.create_otp(email, action=action)
    assert len(code) == 6
    assert code.isdigit()

    # Wrong code should fail
    assert await OtpService.verify_otp(email, "999999", action=action) is False

    # Correct code should succeed
    assert await OtpService.verify_otp(email, code, action=action) is True

    # Consuming the OTP should delete it
    assert await OtpService.consume_otp(email, action=action) is True

    # Second consumption or verification should fail
    assert await OtpService.verify_otp(email, code, action=action) is False


import secrets

@pytest.mark.asyncio
async def test_otp_rate_limiting():
    """Exceeding 5 OTP requests per minute triggers OtpRateLimitExceeded."""
    email = f"spammer_{secrets.token_hex(4)}@kwuo.org"
    action = OtpAction.PASSWORD_RESET

    # First 5 should succeed
    for _ in range(5):
        await OtpService.create_otp(email, action=action)

    # 6th should raise OtpRateLimitExceeded
    with pytest.raises(OtpRateLimitExceeded):
        await OtpService.create_otp(email, action=action)


# =========================================================================
# 2. Account Registration and OTP Verification Flow
# =========================================================================

@pytest.mark.asyncio
async def test_user_registration_and_otp_verification_flow(client: AsyncClient, db_session):
    """Subsequent user registers as unverified, submits OTP, and becomes active."""
    # Seed initial super admin first
    await client.post(
        "/auth/register",
        data={"full_name": "Chief Tab", "email": "admin@kwuo.org", "password": "AdminPassword123!"},
    )

    # Register competitor user (subsequent user)
    reg_resp = await client.post(
        "/auth/register",
        data={
            "first_name": "Ngozi",
            "last_name": "Adichie",
            "email": "ngozi@oratory.org",
            "password": "CompetitorPass123!",
            "phone_number": "+2348012345678",
            "timezone_name": "Africa/Lagos",
        },
        follow_redirects=False,
    )
    assert reg_resp.status_code == 302
    assert "/auth/verify" in reg_resp.headers["location"]
    assert SESSION_COOKIE_NAME in reg_resp.cookies

    # Verify user state in DB is UNVERIFIED
    user = (await db_session.execute(select(User).where(User.email == "ngozi@oratory.org"))).scalar_one()
    assert user.status == UserStatus.UNVERIFIED
    assert user.is_verified is False
    assert user.email_verified_at is None
    assert user.phone_number == "+2348012345678"
    assert user.timezone == "Africa/Lagos"

    # Set session cookie on client
    client.cookies.set(SESSION_COOKIE_NAME, reg_resp.cookies[SESSION_COOKIE_NAME])

    # Fetch verify page
    verify_page = await client.get("/auth/verify?email=ngozi@oratory.org")
    assert verify_page.status_code == 200
    assert "Verification code" in verify_page.text or "6-digit" in verify_page.text

    # Extract the generated OTP from EmailProviderRegistry
    latest_email = EmailProviderRegistry.get_latest_email_for("ngozi@oratory.org")
    assert latest_email is not None
    otp_code = latest_email["metadata"].get("otp_code")
    assert otp_code is not None

    # Test invalid code submission
    bad_resp = await client.post(
        "/auth/verify",
        data={"email": "ngozi@oratory.org", "otp": "000000"},
    )
    assert bad_resp.status_code == 400
    assert "Invalid or expired" in bad_resp.text

    # Submit valid OTP code
    good_resp = await client.post(
        "/auth/verify",
        data={"email": "ngozi@oratory.org", "otp": otp_code},
        follow_redirects=False,
    )
    assert good_resp.status_code == 302
    assert good_resp.headers["location"] == "/dashboard"

    # Refresh DB user and verify active status
    await db_session.refresh(user)
    assert user.status == UserStatus.ACTIVE
    assert user.is_verified is True
    assert user.email_verified_at is not None

    # Verify audit log was recorded
    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == AuditAction.USER_VERIFY_EMAIL,
                AuditLog.resource_id == user.id,
            )
        )
    ).scalar_one_or_none()
    assert audit is not None
    assert audit.severity == AuditSeverity.INFO.value


# =========================================================================
# 3. Brute Force Throttling and Account Lockout
# =========================================================================

@pytest.mark.asyncio
async def test_brute_force_login_lockout(client: AsyncClient, db_session):
    """5 failed password attempts locks the account for 15 minutes."""
    # Register and activate a test user
    now = datetime.now(timezone.utc)
    user = User(
        first_name="Target",
        last_name="Speaker",
        email="target@debate.org",
        password_hash=hash_password("CorrectSecret99!"),
        status=UserStatus.ACTIVE,
        is_verified=True,
        email_verified_at=now,
    )
    db_session.add(user)
    await db_session.commit()

    # Fail login 4 times
    for _ in range(4):
        resp = await client.post(
            "/auth/login",
            data={"email": "target@debate.org", "password": "WrongPassword!"},
        )
        assert resp.status_code == 400

    await db_session.refresh(user)
    assert user.login_failed_attempts == 4
    assert user.locked_until is None

    # 5th failed attempt should trigger lockout
    lock_resp = await client.post(
        "/auth/login",
        data={"email": "target@debate.org", "password": "WrongPassword!"},
    )
    assert lock_resp.status_code == 423
    assert "locked for 15 minutes" in lock_resp.text

    await db_session.refresh(user)
    assert user.login_failed_attempts == 5
    assert user.locked_until is not None
    locked_time = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
    assert locked_time > now + timedelta(minutes=14)

    # Next attempt with even the CORRECT password must be blocked while locked
    blocked_resp = await client.post(
        "/auth/login",
        data={"email": "target@debate.org", "password": "CorrectSecret99!"},
    )
    assert blocked_resp.status_code == 423
    assert "temporarily locked" in blocked_resp.text


# =========================================================================
# 4. Instant Session Invalidation via auth_updated_at
# =========================================================================

@pytest.mark.asyncio
async def test_session_invalidation_on_auth_updated_at(client: AsyncClient, db_session):
    """Changing user auth_updated_at instantly invalidates existing JWT sessions."""
    t0 = datetime.now(timezone.utc) - timedelta(minutes=10)
    user = User(
        first_name="Active",
        last_name="Tabber",
        email="tabber@kwuo.org",
        password_hash=hash_password("TabberPass123!"),
        status=UserStatus.ACTIVE,
        is_verified=True,
        auth_updated_at=t0,
    )
    db_session.add(user)
    await db_session.commit()

    # Issue session token with t0 timestamp
    token = create_session_token(user.id, auth_updated_at=t0)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    # Access /dashboard -> 200 OK
    dash_resp = await client.get("/dashboard")
    assert dash_resp.status_code == 200

    # Simulate password change or admin action updating auth_updated_at to t1 (NOW)
    t1 = datetime.now(timezone.utc)
    user.auth_updated_at = t1
    await db_session.commit()

    # Old session token should now be rejected and return 401 Unauthorized
    stale_resp = await client.get("/dashboard", follow_redirects=False)
    assert stale_resp.status_code == 401


# =========================================================================
# 5. Pre-Seeded System Security Groups
# =========================================================================

@pytest.mark.asyncio
async def test_seed_system_groups_idempotent(db_session):
    """seed_system_groups creates Tournament Manager, Auditor, Admin with permissions."""
    # First seed
    await seed_system_groups(db_session)

    for group_name, group_data in SYSTEM_GROUPS_CATALOG.items():
        stmt = select(Group).where(Group.name == group_name)
        group = (await db_session.execute(stmt)).scalar_one_or_none()
        assert group is not None, f"Group {group_name} should exist"
        assert group.tournament_id is None  # Global platform scope

        # Verify permissions
        perm_stmt = select(GroupPermission.permission).where(GroupPermission.group_id == group.id)
        existing_perms = set((await db_session.execute(perm_stmt)).scalars().all())
        for expected in group_data["permissions"]:
            assert expected in existing_perms

    # Second seed must be completely idempotent without creating duplicate groups or perms
    await seed_system_groups(db_session)
    count_stmt = select(Group).where(Group.name.in_(list(SYSTEM_GROUPS_CATALOG.keys())))
    groups = (await db_session.execute(count_stmt)).scalars().all()
    assert len(groups) == 3


# =========================================================================
# 6. Immutable DB AuditLog
# =========================================================================

@pytest.mark.asyncio
async def test_audit_log_immutability(db_session):
    """AuditLog rows cannot be updated or deleted."""
    log = AuditLog(
        action=AuditAction.USER_LOGIN,
        actor_id="usr_test123",
        actor_email="actor@kwuo.org",
        resource_type="tournament",
        resource_name="National Oratory 2026",
        severity=AuditSeverity.INFO.value,
        success=True,
    )
    db_session.add(log)
    await db_session.commit()
    log_id = log.id

    # Attempting to update an existing audit log must raise ValueError
    log.description = "Tampered description"
    with pytest.raises(ValueError, match="immutable and cannot be updated"):
        await db_session.commit()

    await db_session.rollback()

    # Attempting to delete an audit log must raise ValueError
    fresh_log = (await db_session.execute(select(AuditLog).where(AuditLog.id == log_id))).scalar_one()
    await db_session.delete(fresh_log)
    with pytest.raises(ValueError, match="cannot be deleted"):
        await db_session.commit()


# =========================================================================
# 7. User Self-Control (/profile)
# =========================================================================

@pytest.mark.asyncio
async def test_user_self_control_profile_and_password(client: AsyncClient, db_session):
    """User updates personal info and changes password with verification."""
    now = datetime.now(timezone.utc)
    user = User(
        first_name="Wole",
        last_name="Soyinka",
        email="wole@literature.org",
        password_hash=hash_password("OldPassword123!"),
        status=UserStatus.ACTIVE,
        is_verified=True,
        auth_updated_at=now,
    )
    db_session.add(user)
    await db_session.commit()

    token = create_session_token(user.id, auth_updated_at=now)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    # View profile
    profile_resp = await client.get("/profile")
    assert profile_resp.status_code == 200
    assert "Wole Soyinka" in profile_resp.text
    assert "wole@literature.org" in profile_resp.text

    # Verify Account Security card components
    assert "Account Security" in profile_resp.text
    assert "Two-Factor Authentication (2FA)" in profile_resp.text
    assert "DISABLED" in profile_resp.text
    assert "Enable 2FA" in profile_resp.text
    assert "Active Sessions" in profile_resp.text
    assert "Sign Out All Other Devices" in profile_resp.text
    assert "Last changed" in profile_resp.text

    # Verify complete IANA timezone registry and country codes in profile
    assert "Africa/Lagos" in profile_resp.text
    assert "America/New_York" in profile_resp.text
    assert "Europe/London" in profile_resp.text
    assert "Asia/Tokyo" in profile_resp.text or "Asia/Dubai" in profile_resp.text
    assert "+234" in profile_resp.text
    assert "+233" in profile_resp.text
    assert "+254" in profile_resp.text
    assert "phone_country_code" in profile_resp.text
    assert "phone_number_local" in profile_resp.text

    # Verify raw internal developer fields are REMOVED from the view
    assert "Primary Identifier:" not in profile_resp.text
    assert "Last Login IP:" not in profile_resp.text
    assert "Auth Invalidation Timestamp:" not in profile_resp.text

    # Update personal info using split country code + local number
    update_resp = await client.post(
        "/profile",
        data={
            "first_name": "Wole Akinwande",
            "last_name": "Soyinka",
            "phone_country_code": "+233",
            "phone_number_local": "0241234567",  # leading 0 should be stripped cleanly
            "timezone_name": "Africa/Accra",
        },
        follow_redirects=False,
    )
    assert update_resp.status_code == 302

    await db_session.refresh(user)
    assert user.first_name == "Wole Akinwande"
    assert user.phone_number == "+233241234567"
    assert user.timezone == "Africa/Accra"

    # Password change with wrong current password
    bad_pw_resp = await client.post(
        "/profile/change-password",
        data={
            "current_password": "WrongCurrentPassword!",
            "new_password": "NewSecretPass456!",
            "confirm_password": "NewSecretPass456!",
        },
    )
    assert bad_pw_resp.status_code == 400
    assert "incorrect" in bad_pw_resp.text.lower()

    # Password change with valid credentials
    good_pw_resp = await client.post(
        "/profile/change-password",
        data={
            "current_password": "OldPassword123!",
            "new_password": "NewSecretPass456!",
            "confirm_password": "NewSecretPass456!",
        },
        follow_redirects=False,
    )
    assert good_pw_resp.status_code == 302

    await db_session.refresh(user)
    auth_up = user.auth_updated_at if user.auth_updated_at.tzinfo else user.auth_updated_at.replace(tzinfo=timezone.utc)
    assert auth_up >= now


@pytest.mark.asyncio
async def test_comprehensive_timezones_and_phone_number_formatting(client: AsyncClient, db_session):
    """Verify complete IANA timezones registry and phone formatting with country codes."""
    from kwuo.core.localization import get_all_timezones_grouped, COUNTRY_CALLING_CODES, parse_phone_number

    # 1. Verify comprehensive IANA timezone registry contains extensive worldwide regions
    tzs_grouped = get_all_timezones_grouped()
    assert "Africa" in tzs_grouped
    assert "Americas" in tzs_grouped
    assert "Europe" in tzs_grouped
    assert "Asia & Middle East" in tzs_grouped
    assert "Australia & Pacific" in tzs_grouped
    assert "Universal (GMT)" in tzs_grouped

    # Verify total timezones count exceeds 200 (comprehensive catalog)
    total_tzs = sum(len(entries) for entries in tzs_grouped.values())
    assert total_tzs >= 200

    # Verify key zones exist
    africa_ids = [tz["id"] for tz in tzs_grouped["Africa"]]
    assert "Africa/Lagos" in africa_ids
    assert "Africa/Accra" in africa_ids
    assert "Africa/Nairobi" in africa_ids
    assert "Africa/Johannesburg" in africa_ids

    # 2. Verify country calling codes catalog covers 100+ countries
    assert len(COUNTRY_CALLING_CODES) >= 100
    assert any(c["code"] == "+234" and c["name"] == "Nigeria" for c in COUNTRY_CALLING_CODES)
    assert any(c["code"] == "+233" and c["name"] == "Ghana" for c in COUNTRY_CALLING_CODES)
    assert any(c["code"] == "+44" and c["name"] == "United Kingdom" for c in COUNTRY_CALLING_CODES)
    assert any(c["code"] == "+1" and "United States" in c["name"] for c in COUNTRY_CALLING_CODES)

    # 3. Verify parse_phone_number splits correctly
    cc, local = parse_phone_number("+2348012345678")
    assert cc == "+234"
    assert local == "8012345678"

    cc2, local2 = parse_phone_number("+18765551234")
    assert cc2 == "+1876"
    assert local2 == "5551234"

    # 4. User profile update strips spaces, dashes, and parentheses in local phone number
    now = datetime.now(timezone.utc)
    user = User(
        first_name="Wole",
        last_name="Soyinka",
        email="wole_formatting@literature.org",
        password_hash=hash_password("OldPassword123!"),
        status=UserStatus.ACTIVE,
        is_verified=True,
        auth_updated_at=now,
    )
    db_session.add(user)
    await db_session.commit()

    token = create_session_token(user.id, auth_updated_at=now)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    # Submit with formatting characters: (0803) 123-4567
    update_resp = await client.post(
        "/profile",
        data={
            "first_name": "Wole",
            "last_name": "Soyinka",
            "phone_country_code": "+234",
            "phone_number_local": "(0803) 123-4567",
            "timezone_name": "Africa/Lagos",
        },
        follow_redirects=False,
    )
    assert update_resp.status_code == 302
    await db_session.refresh(user)
    assert user.phone_number == "+2348031234567"
    assert user.timezone == "Africa/Lagos"

    # 5. Verify phone number length is bounded to max 15 digits (ITU E.164)
    bound_resp = await client.post(
        "/profile",
        data={
            "first_name": "Wole",
            "last_name": "Soyinka",
            "phone_country_code": "+234",
            "phone_number_local": "232343434343434343434434",  # 24 digits
            "timezone_name": "Africa/Lagos",
        },
        follow_redirects=False,
    )
    assert bound_resp.status_code == 302
    await db_session.refresh(user)
    # The 24 digits are bounded to max 15 digits (+234 + 15 digits = 19 chars)
    assert len(user.phone_number) <= 19
    assert user.phone_number == "+234232343434343434"

    # 6. Verify GMT is used rather than UTC for timezone display
    profile_page = await client.get("/profile")
    assert "GMT" in profile_page.text
    assert "window.showToast" in profile_page.text


@pytest.mark.asyncio
async def test_sign_out_all_other_devices(client: AsyncClient, db_session):
    """Sign out all other devices updates auth_updated_at and preserves current session."""
    t0 = datetime.now(timezone.utc) - timedelta(hours=2)
    user = User(
        first_name="Chimamanda",
        last_name="Adichie",
        email="author@story.org",
        password_hash=hash_password("StoryPass123!"),
        status=UserStatus.ACTIVE,
        is_verified=True,
        auth_updated_at=t0,
    )
    db_session.add(user)
    await db_session.commit()

    old_token = create_session_token(user.id, auth_updated_at=t0)
    client.cookies.set(SESSION_COOKIE_NAME, old_token)

    # User triggers sign out all other devices
    resp = await client.post("/profile/revoke-other-sessions", follow_redirects=False)
    assert resp.status_code == 302
    assert "/profile" in resp.headers["location"]
    assert SESSION_COOKIE_NAME in resp.cookies
    new_token = resp.cookies[SESSION_COOKIE_NAME]
    assert new_token != old_token

    # Verify user auth_updated_at in DB was updated
    await db_session.refresh(user)
    current_auth = user.auth_updated_at if user.auth_updated_at.tzinfo else user.auth_updated_at.replace(tzinfo=timezone.utc)
    assert current_auth > t0

    # Old token (simulating other devices) is now REJECTED
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, old_token)
    stale_resp = await client.get("/profile", follow_redirects=False)
    assert stale_resp.status_code in (401, 307, 302)

    # New token (current device) SUCCEEDS
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, new_token)
    active_resp = await client.get("/profile")
    assert active_resp.status_code == 200
    assert "Chimamanda Adichie" in active_resp.text


def test_feature_tracker_registry():
    """Verify FeatureTracker registers MFA as disabled and records v2 items."""
    assert FeatureTracker.is_enabled("mfa") is False
    mfa_meta = FeatureTracker.get_feature("mfa")
    assert mfa_meta["status"] == "disabled"
    assert "MFA is currently not enabled" in mfa_meta["notes"]

    v2_items = FeatureTracker.get_v2_roadmap()
    v2_keys = [item["key"] for item in v2_items]
    assert "mfa" in v2_keys
    assert "google_sign_in" in v2_keys
    assert "paywall" in v2_keys


# =========================================================================
# 8. Admin User State Controls (Suspend / Ban / Promote)
# =========================================================================

@pytest.mark.asyncio
async def test_admin_user_state_actions_and_audit(client: AsyncClient, db_session):
    """Admin can suspend, ban, and promote users, generating audit trails."""
    # Create Super Admin
    admin_user = User(
        first_name="Grand",
        last_name="Admin",
        email="grand.admin@kwuo.org",
        password_hash=hash_password("SuperSecret123!"),
        is_admin=True,
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    # Create regular user
    reg_user = User(
        first_name="Rogue",
        last_name="Debater",
        email="rogue@debate.org",
        password_hash=hash_password("RoguePass123!"),
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add_all([admin_user, reg_user])
    await db_session.commit()

    token = create_session_token(admin_user.id, auth_updated_at=admin_user.auth_updated_at)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    # 1. Admin suspends rogue user
    suspend_resp = await client.post(
        "/admin/users/action",
        data={"action": "suspend_users", "_selected_action": [reg_user.id]},
        follow_redirects=False,
    )
    assert suspend_resp.status_code == 302

    await db_session.refresh(reg_user)
    assert reg_user.status == UserStatus.SUSPENDED

    # Verify audit log for suspension
    suspend_log = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == AuditAction.USER_SUSPEND,
                AuditLog.resource_id == reg_user.id,
            )
        )
    ).scalar_one_or_none()
    assert suspend_log is not None
    assert suspend_log.actor_id == admin_user.id

    # 2. Admin bans rogue user
    ban_resp = await client.post(
        "/admin/users/action",
        data={"action": "ban_users", "_selected_action": [reg_user.id]},
        follow_redirects=False,
    )
    assert ban_resp.status_code == 302

    await db_session.refresh(reg_user)
    assert reg_user.status == UserStatus.BANNED

    # 3. Admin reactivates rogue user
    reactivate_resp = await client.post(
        "/admin/users/action",
        data={"action": "activate_users", "_selected_action": [reg_user.id]},
        follow_redirects=False,
    )
    assert reactivate_resp.status_code == 302

    await db_session.refresh(reg_user)
    assert reg_user.status == UserStatus.ACTIVE


# =========================================================================
# 9. Email Provider Absence Tracking
# =========================================================================

@pytest.mark.asyncio
async def test_email_absence_tracking():
    """Verify registry tracks unconfigured provider and send_email outputs cleanly."""
    status = EmailProviderRegistry.get_status()
    assert status["is_configured"] is False
    assert status["provider_name"] == "console_logger"
    assert status["total_dispatched"] >= 0

    # Test send_email utility
    res = await send_email(
        to_email="test@kwuo.org",
        subject="Test Dispatch",
        body="Hello Kwuo world",
    )
    assert res is True

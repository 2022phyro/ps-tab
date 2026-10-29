"""User self-service profile and security management routes."""

from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, status, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import json
import re

from kwuo.core.database import get_db_session
from kwuo.core.security import hash_password, verify_password, create_session_token, SESSION_COOKIE_NAME
from kwuo.core.rbac import get_current_user
from kwuo.models.user import User, UserStatus
from kwuo.models.audit import AuditAction, AuditSeverity
from kwuo.services.audit import record_audit_log
from kwuo.core.localization import (
    COUNTRY_CALLING_CODES,
    parse_phone_number,
    get_all_timezones_grouped,
)
from kwuo.web.templates import templates

router = APIRouter(prefix="/profile")


def get_relative_time_display(dt: Optional[datetime]) -> str:
    """Format datetime into humanized relative time (e.g. '3 weeks ago')."""
    if not dt:
        return "Never"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    total_seconds = int(diff.total_seconds())
    if total_seconds < 60:
        return "Just now"
    elif total_seconds < 3600:
        mins = total_seconds // 60
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif total_seconds < 604800:
        days = total_seconds // 86400
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif total_seconds < 2592000:
        weeks = max(1, total_seconds // 604800)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    else:
        months = max(1, total_seconds // 2592000)
        return f"{months} month{'s' if months != 1 else ''} ago"


def get_client_device_label(request: Request, user: User) -> str:
    """Parse client user agent and localization to display active session information."""
    ua = request.headers.get("user-agent", "")

    browser = "Browser"
    if "Firefox" in ua:
        browser = "Firefox"
    elif "Edg" in ua:
        browser = "Edge"
    elif "Chrome" in ua or "CriOS" in ua:
        browser = "Chrome"
    elif "Safari" in ua:
        browser = "Safari"

    os_name = "Windows"
    if "Windows" in ua:
        os_name = "Windows"
    elif "Macintosh" in ua or "Mac OS" in ua:
        os_name = "macOS"
    elif "Linux" in ua:
        os_name = "Linux"
    elif "Android" in ua:
        os_name = "Android"
    elif "iPhone" in ua or "iPad" in ua:
        os_name = "iOS"

    location = "Lagos, Nigeria"
    tz = user.timezone or "Africa/Lagos"
    if "Accra" in tz:
        location = "Accra, Ghana"
    elif "Nairobi" in tz:
        location = "Nairobi, Kenya"
    elif "Johannesburg" in tz:
        location = "Johannesburg, South Africa"
    elif "London" in tz:
        location = "London, UK"
    elif "New_York" in tz:
        location = "New York, USA"

    return f"{browser} on {os_name} • {location} (Current session)"


import json
import re

def _render_profile_response(
    request: Request,
    user: User,
    error: Optional[str] = None,
    success_msg: Optional[str] = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    password_last_changed = get_relative_time_display(user.auth_updated_at or user.created_at)
    session_device_label = get_client_device_label(request, user)
    country_code, local_phone = parse_phone_number(user.phone_number)
    grouped_timezones = get_all_timezones_grouped()

    return templates.TemplateResponse(
        request=request,
        name="profile/index.html",
        context={
            "user": user,
            "error": error,
            "success_msg": success_msg,
            "password_last_changed": password_last_changed,
            "session_device_label": session_device_label,
            "country_calling_codes": COUNTRY_CALLING_CODES,
            "current_country_code": country_code,
            "current_local_phone": local_phone,
            "grouped_timezones": grouped_timezones,
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Render user self-service profile & security management interface."""
    return _render_profile_response(
        request=request,
        user=user,
        success_msg=request.query_params.get("msg"),
    )


@router.post("", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    phone_country_code: Optional[str] = Form(None),
    phone_number_local: Optional[str] = Form(None),
    phone_number: Optional[str] = Form(None),
    timezone_name: Optional[str] = Form(None),
    timezone: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Update user basic personal identity and preferences."""
    changes = {}
    clean_fn = first_name.strip()
    clean_ln = last_name.strip()

    # Resolve phone number from split fields or legacy single field
    if phone_number_local is not None and phone_number_local.strip():
        clean_cc = (phone_country_code or "+234").strip()
        # Clean non-digit characters and strip leading 0s
        digits = re.sub(r"[^\d]", "", phone_number_local.strip()).lstrip("0")
        # Bound subscriber digits to international standard (max 15 digits per ITU E.164)
        digits = digits[:15]
        clean_ph = f"{clean_cc}{digits}" if digits else None
    elif phone_number is not None:
        clean_ph = phone_number.strip() if phone_number.strip() else None
        if clean_ph and len(clean_ph) > 16:
            clean_ph = clean_ph[:16]
    else:
        clean_ph = user.phone_number

    clean_tz = (timezone_name or timezone or "UTC").strip()

    if user.first_name != clean_fn:
        changes["first_name"] = {"old": user.first_name, "new": clean_fn}
        user.first_name = clean_fn
    if user.last_name != clean_ln:
        changes["last_name"] = {"old": user.last_name, "new": clean_ln}
        user.last_name = clean_ln
    if user.phone_number != clean_ph:
        changes["phone_number"] = {"old": user.phone_number, "new": clean_ph}
        user.phone_number = clean_ph
    if user.timezone != clean_tz:
        changes["timezone"] = {"old": user.timezone, "new": clean_tz}
        user.timezone = clean_tz

    if changes:
        await record_audit_log(
            db,
            action=AuditAction.USER_UPDATE,
            actor=user,
            request=request,
            resource_type="user",
            resource_id=user.id,
            changes=changes,
            severity=AuditSeverity.INFO.value,
            success=True,
            description=f"User {user.email} updated profile attributes",
        )
        await db.flush()

    msg = "Profile updated successfully."
    if request.headers.get("HX-Request"):
        return Response(
            content="",
            media_type="text/html",
            headers={"HX-Trigger": json.dumps({"toast": {"message": msg, "type": "success"}})},
        )

    return RedirectResponse(url="/profile?msg=Profile+updated+successfully", status_code=status.HTTP_302_FOUND)


@router.post("/change-password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Change account password with verification of current password."""
    if not verify_password(current_password, user.password_hash):
        error_msg = "Incorrect current password."
        if request.headers.get("HX-Request"):
            return Response(
                content="",
                status_code=status.HTTP_400_BAD_REQUEST,
                media_type="text/html",
                headers={"HX-Trigger": json.dumps({"toast": {"message": error_msg, "type": "error"}})},
            )
        return _render_profile_response(
            request=request,
            user=user,
            error=error_msg,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if new_password != confirm_password:
        error_msg = "New password and confirmation do not match."
        if request.headers.get("HX-Request"):
            return Response(
                content="",
                status_code=status.HTTP_400_BAD_REQUEST,
                media_type="text/html",
                headers={"HX-Trigger": json.dumps({"toast": {"message": error_msg, "type": "error"}})},
            )
        return _render_profile_response(
            request=request,
            user=user,
            error=error_msg,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if len(new_password) < 8:
        error_msg = "New password must be at least 8 characters."
        if request.headers.get("HX-Request"):
            return Response(
                content="",
                status_code=status.HTTP_400_BAD_REQUEST,
                media_type="text/html",
                headers={"HX-Trigger": json.dumps({"toast": {"message": error_msg, "type": "error"}})},
            )
        return _render_profile_response(
            request=request,
            user=user,
            error=error_msg,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    now = datetime.now(timezone.utc)
    user.password_hash = hash_password(new_password)
    user.auth_updated_at = now  # Invalidate other sessions
    await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.USER_PASSWORD_CHANGE,
        actor=user,
        request=request,
        resource_type="user",
        resource_id=user.id,
        severity=AuditSeverity.INFO.value,
        success=True,
        description=f"User {user.email} changed password via profile settings",
    )

    msg = "Password updated successfully. Other active sessions have been invalidated."
    if request.headers.get("HX-Request"):
        return Response(
            content="",
            media_type="text/html",
            headers={"HX-Trigger": json.dumps({"toast": {"message": msg, "type": "success"}})},
        )

    return RedirectResponse(url="/profile?msg=Password+updated+successfully", status_code=status.HTTP_302_FOUND)


@router.post("/revoke-other-sessions")
async def revoke_other_sessions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Sign out all other devices by updating auth_updated_at and reissuing current session token."""
    now = datetime.now(timezone.utc)
    user.auth_updated_at = now
    await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.USER_LOGOUT,
        actor=user,
        request=request,
        resource_type="user",
        resource_id=user.id,
        severity=AuditSeverity.INFO.value,
        success=True,
        description=f"User {user.email} signed out all other active devices",
    )

    # Issue fresh session token reflecting current auth_updated_at so this session remains logged in
    new_token = create_session_token(user.id, auth_updated_at=user.auth_updated_at)

    response = RedirectResponse(
        url="/profile?msg=All+other+devices+have+been+signed+out+successfully.",
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=new_token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return response


@router.post("/deactivate")
async def deactivate_account(
    request: Request,
    password: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """User self-service account deactivation."""
    if not verify_password(password, user.password_hash):
        error_msg = "Incorrect password. Cannot deactivate account."
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-xl bg-rose-50 dark:bg-rose-950/40 p-3 text-sm text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50">{error_msg}</div>'
            )
        return _render_profile_response(
            request=request,
            user=user,
            error=error_msg,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    now = datetime.now(timezone.utc)
    user.status = UserStatus.DELETED
    user.deleted_at = now
    user.auth_updated_at = now
    await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.USER_DEACTIVATE,
        actor=user,
        request=request,
        resource_type="user",
        resource_id=user.id,
        severity=AuditSeverity.WARNING.value,
        success=True,
        description=f"User {user.email} requested self-deactivation",
    )

    response = RedirectResponse(url="/?msg=Your+account+has+been+deactivated", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return response

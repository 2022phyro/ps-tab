"""Authentication routes: Login, Register, Verify, Password Reset, and Logout."""

from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, status, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from kwuo.core.database import get_db_session
from kwuo.core.security import (
    hash_password,
    verify_password,
    create_session_token,
    SESSION_COOKIE_NAME,
)
from kwuo.core.rbac import get_optional_current_user
from kwuo.models.user import User, UserStatus
from kwuo.models.audit import AuditAction, AuditSeverity
from kwuo.services.audit import record_audit_log, extract_request_context
from kwuo.services.otp import OtpService, OtpAction, OtpRateLimitExceeded
from kwuo.services.email import send_verification_otp_email, send_password_reset_otp_email
from kwuo.web.templates import templates

router = APIRouter(prefix="/auth")


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    next: Optional[str] = None,
    msg: Optional[str] = None,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render login page. Redirect if already authenticated."""
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"user": None, "next_url": next, "error": None, "success_msg": msg},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db_session),
):
    """Process user login with throttling, status checks, and audit logging."""
    email_clean = email.strip().lower()
    req_ctx = extract_request_context(request)
    client_ip = req_ctx["ip_address"]

    stmt = select(User).where(User.email == email_clean)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    # User existence and password validation
    if not user:
        # Prevent timing enumeration by verifying against dummy hash
        dummy_hash = "$argon2id$v=19$m=65536,t=3,p=4$dummyhashtopreventtimingattacks"
        verify_password("invalid", dummy_hash)
        await record_audit_log(
            db,
            action=AuditAction.USER_LOGIN_FAILED,
            actor=None,
            request=request,
            resource_type="user",
            resource_name=email_clean,
            severity=AuditSeverity.WARNING.value,
            success=False,
            error_message="User not found",
            description=f"Failed login attempt for non-existent email {email_clean}",
        )
        error_msg = "Invalid email or password"
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-xl bg-rose-50 dark:bg-rose-950/40 p-3 text-sm text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50">{error_msg}</div>'
            )
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"user": None, "next_url": next, "error": error_msg},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    now = datetime.now(timezone.utc)

    # 1. Check account lockout (brute force throttling)
    if user.is_locked:
        locked_time = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
        remaining_mins = max(1, int((locked_time - now).total_seconds() / 60))
        error_msg = f"Account is temporarily locked due to multiple failed login attempts. Please try again in {remaining_mins} minute(s)."
        await record_audit_log(
            db,
            action=AuditAction.USER_LOGIN_FAILED,
            actor=user,
            request=request,
            resource_type="user",
            resource_id=user.id,
            severity=AuditSeverity.WARNING.value,
            success=False,
            error_message="Account locked",
            description=f"Login attempt on locked account {user.email}",
        )
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-xl bg-rose-50 dark:bg-rose-950/40 p-3 text-sm text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50">{error_msg}</div>'
            )
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"user": None, "next_url": next, "error": error_msg},
            status_code=status.HTTP_423_LOCKED,
        )

    # 2. Check credentials
    if not user.password_hash or not verify_password(password, user.password_hash):
        user.login_failed_attempts += 1
        user.login_failed_at = now

        # Threshold: 5 failed attempts locks for 15 minutes
        if user.login_failed_attempts >= 5:
            user.locked_until = now + timedelta(minutes=15)
            await record_audit_log(
                db,
                action=AuditAction.USER_LOCKED,
                actor=user,
                request=request,
                resource_type="user",
                resource_id=user.id,
                severity=AuditSeverity.WARNING.value,
                success=False,
                error_message="Account locked for 15 minutes after 5 failed attempts",
                description=f"Account {user.email} locked after 5 consecutive failed login attempts",
            )
            error_msg = "Too many failed attempts. Your account has been temporarily locked for 15 minutes."
        else:
            await record_audit_log(
                db,
                action=AuditAction.USER_LOGIN_FAILED,
                actor=user,
                request=request,
                resource_type="user",
                resource_id=user.id,
                severity=AuditSeverity.WARNING.value,
                success=False,
                error_message=f"Invalid password (attempt {user.login_failed_attempts}/5)",
                description=f"Failed login attempt for {user.email} ({user.login_failed_attempts}/5)",
            )
            attempts_left = 5 - user.login_failed_attempts
            error_msg = f"Invalid email or password. {attempts_left} attempt(s) remaining before account lockout."

        await db.flush()
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-xl bg-rose-50 dark:bg-rose-950/40 p-3 text-sm text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50">{error_msg}</div>'
            )
        resp_status = status.HTTP_423_LOCKED if user.locked_until else status.HTTP_400_BAD_REQUEST
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"user": None, "next_url": next, "error": error_msg},
            status_code=resp_status,
        )

    # 3. Check account lifecycle status
    if user.status == UserStatus.BANNED:
        await record_audit_log(
            db,
            action=AuditAction.USER_LOGIN_FAILED,
            actor=user,
            request=request,
            resource_type="user",
            resource_id=user.id,
            severity=AuditSeverity.ERROR.value,
            success=False,
            error_message="Account banned",
        )
        error_msg = "This account has been permanently banned by platform administrators."
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-xl bg-rose-50 dark:bg-rose-950/40 p-3 text-sm text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50">{error_msg}</div>'
            )
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"user": None, "next_url": next, "error": error_msg},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if user.status == UserStatus.SUSPENDED:
        await record_audit_log(
            db,
            action=AuditAction.USER_LOGIN_FAILED,
            actor=user,
            request=request,
            resource_type="user",
            resource_id=user.id,
            severity=AuditSeverity.WARNING.value,
            success=False,
            error_message="Account suspended",
        )
        error_msg = "This account is currently suspended. Please contact tournament administration."
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-xl bg-rose-50 dark:bg-rose-950/40 p-3 text-sm text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50">{error_msg}</div>'
            )
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"user": None, "next_url": next, "error": error_msg},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if user.status == UserStatus.DELETED or user.deleted_at is not None:
        error_msg = "Account does not exist."
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-xl bg-rose-50 dark:bg-rose-950/40 p-3 text-sm text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50">{error_msg}</div>'
            )
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"user": None, "next_url": next, "error": error_msg},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # 4. Check email verification
    if user.status == UserStatus.UNVERIFIED or not user.is_verified:
        # Dispatch verification OTP
        try:
            otp_code = await OtpService.create_otp(user.email, action=OtpAction.ACCOUNT_VERIFY)
            await send_verification_otp_email(user.email, otp_code, user.first_name)
        except OtpRateLimitExceeded:
            pass  # Rate limit exceeded; existing code remains valid
        verify_url = f"/auth/verify?email={user.email}"
        if request.headers.get("HX-Request"):
            response = Response(status_code=status.HTTP_200_OK)
            response.headers["HX-Redirect"] = verify_url
            return response
        return RedirectResponse(url=verify_url, status_code=status.HTTP_302_FOUND)

    # 5. Successful login: reset throttling, record audit, issue session token
    user.login_failed_attempts = 0
    user.locked_until = None
    user.last_login = now
    user.last_login_ip = client_ip
    await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.USER_LOGIN,
        actor=user,
        request=request,
        resource_type="user",
        resource_id=user.id,
        severity=AuditSeverity.INFO.value,
        success=True,
        description=f"User {user.email} successfully logged in from IP {client_ip}",
    )

    token = create_session_token(user.id, auth_updated_at=user.auth_updated_at)
    redirect_url = next if next and next.startswith("/") else "/dashboard"

    if request.headers.get("HX-Request"):
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = redirect_url
    else:
        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render registration page."""
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="auth/register.html",
        context={"user": None, "error": None},
    )


@router.post("/register")
async def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    first_name: Optional[str] = Form(None),
    last_name: Optional[str] = Form(None),
    full_name: Optional[str] = Form(None),
    phone_number: Optional[str] = Form(None),
    timezone_name: str = Form("UTC"),
    db: AsyncSession = Depends(get_db_session),
):
    """Register a new user account with automatic verification OTP dispatch."""
    email_clean = email.strip().lower()

    # Resolve first_name and last_name
    if not first_name and not last_name and full_name:
        parts = full_name.strip().split(" ", 1)
        resolved_first = parts[0]
        resolved_last = parts[1] if len(parts) > 1 else ""
    else:
        resolved_first = (first_name or "").strip()
        resolved_last = (last_name or "").strip()

    # Check for existing user
    stmt = select(User).where(User.email == email_clean)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        error_msg = "An account with this email address already exists."
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-xl bg-rose-50 dark:bg-rose-950/40 p-3 text-sm text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50">{error_msg}</div>'
            )
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={"user": None, "error": error_msg},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Determine if initial super admin
    count_stmt = select(func.count(User.id))
    user_count = (await db.execute(count_stmt)).scalar() or 0
    is_first_user = (user_count == 0)

    now = datetime.now(timezone.utc)
    new_user = User(
        first_name=resolved_first,
        last_name=resolved_last,
        email=email_clean,
        phone_number=phone_number.strip() if phone_number else None,
        password_hash=hash_password(password),
        is_admin=is_first_user,
        status=UserStatus.ACTIVE if is_first_user else UserStatus.UNVERIFIED,
        is_verified=is_first_user,
        email_verified_at=now if is_first_user else None,
        timezone=timezone_name,
        auth_updated_at=now,
    )
    db.add(new_user)
    await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.USER_SIGNUP,
        actor=new_user,
        request=request,
        resource_type="user",
        resource_id=new_user.id,
        severity=AuditSeverity.INFO.value,
        success=True,
        description=f"New user {new_user.email} registered (Initial admin: {is_first_user})",
    )

    # If first user: directly active & logged into dashboard
    if is_first_user:
        token = create_session_token(new_user.id, auth_updated_at=new_user.auth_updated_at)
        redirect_url = "/dashboard"
        if request.headers.get("HX-Request"):
            response = Response(status_code=status.HTTP_200_OK)
            response.headers["HX-Redirect"] = redirect_url
        else:
            response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            httponly=True,
            samesite="lax",
            max_age=7 * 24 * 3600,
        )
        return response

    # For subsequent users: dispatch 6-digit verification OTP
    try:
        otp_code = await OtpService.create_otp(new_user.email, action=OtpAction.ACCOUNT_VERIFY)
        await send_verification_otp_email(new_user.email, otp_code, new_user.first_name)
    except OtpRateLimitExceeded:
        pass

    redirect_url = f"/auth/verify?email={new_user.email}"
    if request.headers.get("HX-Request"):
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = redirect_url
    else:
        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    token = create_session_token(new_user.id, auth_updated_at=new_user.auth_updated_at)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return response


@router.get("/verify", response_class=HTMLResponse)
async def verify_page(
    request: Request,
    email: str = "",
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render 6-digit OTP verification screen."""
    if user and user.is_verified:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request=request,
        name="auth/verify.html",
        context={"user": None, "email": email, "error": None, "success_msg": None},
    )


@router.post("/verify")
async def verify_submit(
    request: Request,
    email: str = Form(...),
    code: Optional[str] = Form(None),
    otp: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db_session),
):
    """Verify 6-digit OTP and activate account."""
    clean_email = email.strip().lower()
    clean_code = (code or otp or "").strip()

    if not clean_code:
        error_msg = "Please enter the 6-digit verification code."
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-xl bg-rose-50 dark:bg-rose-950/40 p-3 text-sm text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50">{error_msg}</div>'
            )
        return templates.TemplateResponse(
            request=request,
            name="auth/verify.html",
            context={"user": None, "email": clean_email, "error": error_msg},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    valid = await OtpService.verify_otp(clean_email, clean_code, action=OtpAction.ACCOUNT_VERIFY)
    if not valid:
        error_msg = "Invalid or expired verification code. Please request a new code."
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-xl bg-rose-50 dark:bg-rose-950/40 p-3 text-sm text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50">{error_msg}</div>'
            )
        return templates.TemplateResponse(
            request=request,
            name="auth/verify.html",
            context={"user": None, "email": clean_email, "error": error_msg},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Consume OTP permanently
    await OtpService.consume_otp(clean_email, action=OtpAction.ACCOUNT_VERIFY)

    # Activate user in database
    stmt = select(User).where(User.email == clean_email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        return RedirectResponse(url="/auth/register", status_code=status.HTTP_302_FOUND)

    now = datetime.now(timezone.utc)
    user.is_verified = True
    user.status = UserStatus.ACTIVE
    user.email_verified_at = now
    user.auth_updated_at = now
    await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.USER_VERIFY_EMAIL,
        actor=user,
        request=request,
        resource_type="user",
        resource_id=user.id,
        severity=AuditSeverity.INFO.value,
        success=True,
        description=f"User {user.email} completed 6-digit OTP email verification and activated account",
    )

    token = create_session_token(user.id, auth_updated_at=user.auth_updated_at)
    redirect_url = "/dashboard"

    if request.headers.get("HX-Request"):
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = redirect_url
    else:
        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return response


@router.post("/resend-otp")
async def resend_otp(
    request: Request,
    email: str = Form(...),
    action: str = Form(OtpAction.ACCOUNT_VERIFY),
    db: AsyncSession = Depends(get_db_session),
):
    """Resend a new 6-digit OTP code to the user's email."""
    clean_email = email.strip().lower()

    # Verify user exists
    stmt = select(User).where(User.email == clean_email)
    user = (await db.execute(stmt)).scalar_one_or_none()

    try:
        otp_code = await OtpService.create_otp(clean_email, action=action)
        if action == OtpAction.PASSWORD_RESET:
            await send_password_reset_otp_email(clean_email, otp_code, user.first_name if user else "")
        else:
            await send_verification_otp_email(clean_email, otp_code, user.first_name if user else "")

        msg = "A fresh 6-digit verification code has been dispatched to your email."
        return HTMLResponse(
            f'<div class="rounded-xl bg-emerald-50 dark:bg-emerald-950/40 p-3 text-sm text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">{msg}</div>'
        )
    except OtpRateLimitExceeded as e:
        return HTMLResponse(
            f'<div class="rounded-xl bg-amber-50 dark:bg-amber-950/40 p-3 text-sm text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800">{str(e)}</div>'
        )


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    """Render password reset request page."""
    return templates.TemplateResponse(
        request=request,
        name="auth/forgot_password.html",
        context={"user": None, "error": None, "success_msg": None},
    )


@router.post("/forgot-password")
async def forgot_password_submit(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db_session),
):
    """Request password reset OTP."""
    clean_email = email.strip().lower()

    stmt = select(User).where(User.email == clean_email)
    user = (await db.execute(stmt)).scalar_one_or_none()

    if user and user.status != UserStatus.BANNED:
        try:
            otp_code = await OtpService.create_otp(clean_email, action=OtpAction.PASSWORD_RESET)
            await send_password_reset_otp_email(clean_email, otp_code, user.first_name)
            await record_audit_log(
                db,
                action=AuditAction.USER_PASSWORD_RESET_REQUEST,
                actor=user,
                request=request,
                resource_type="user",
                resource_id=user.id,
                severity=AuditSeverity.INFO.value,
                success=True,
                description=f"Password reset OTP requested for {clean_email}",
            )
        except OtpRateLimitExceeded:
            pass

    redirect_url = f"/auth/reset-password?email={clean_email}"
    if request.headers.get("HX-Request"):
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = redirect_url
        return response

    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, email: str = ""):
    """Render reset password form (OTP + new password)."""
    return templates.TemplateResponse(
        request=request,
        name="auth/reset_password.html",
        context={"user": None, "email": email, "error": None},
    )


@router.post("/reset-password")
async def reset_password_submit(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    new_password: str = Form(...),
    db: AsyncSession = Depends(get_db_session),
):
    """Verify OTP and update user password, invalidating any active sessions."""
    clean_email = email.strip().lower()
    clean_code = code.strip()

    valid = await OtpService.verify_otp(clean_email, clean_code, action=OtpAction.PASSWORD_RESET)
    if not valid:
        error_msg = "Invalid or expired reset code. Please request a new code."
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-xl bg-rose-50 dark:bg-rose-950/40 p-3 text-sm text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50">{error_msg}</div>'
            )
        return templates.TemplateResponse(
            request=request,
            name="auth/reset_password.html",
            context={"user": None, "email": clean_email, "error": error_msg},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Consume OTP
    await OtpService.consume_otp(clean_email, action=OtpAction.PASSWORD_RESET)

    stmt = select(User).where(User.email == clean_email)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

    now = datetime.now(timezone.utc)
    user.password_hash = hash_password(new_password)
    user.auth_updated_at = now  # Kills all active sessions!
    user.login_failed_attempts = 0
    user.locked_until = None
    await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.USER_PASSWORD_RESET,
        actor=user,
        request=request,
        resource_type="user",
        resource_id=user.id,
        severity=AuditSeverity.INFO.value,
        success=True,
        description=f"Password successfully reset via OTP for {clean_email}. Active sessions invalidated.",
    )

    login_url = "/auth/login?msg=Password+updated+successfully.+Please+sign+in+with+your+new+password."
    if request.headers.get("HX-Request"):
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = login_url
        return response

    return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)


@router.post("/logout")
async def logout(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Clear session cookie, log audit, and redirect to home."""
    if user:
        await record_audit_log(
            db,
            action=AuditAction.USER_LOGOUT,
            actor=user,
            request=request,
            resource_type="user",
            resource_id=user.id,
            severity=AuditSeverity.INFO.value,
            success=True,
            description=f"User {user.email} logged out",
        )

    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return response

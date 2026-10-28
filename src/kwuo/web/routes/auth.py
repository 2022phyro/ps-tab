"""Authentication routes: Login, Register, Logout."""

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
from kwuo.models.user import User
from kwuo.web.templates import templates

router = APIRouter(prefix="/auth")


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    next: Optional[str] = None,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render login page. Redirect if already authenticated."""
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"user": None, "next_url": next, "error": None},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db_session),
):
    """Process user login."""
    email_clean = email.strip().lower()
    stmt = select(User).where(User.email == email_clean)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        error_msg = "Invalid email or password"
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-lg bg-rose-50 p-3 text-sm text-rose-700 border border-rose-200">{error_msg}</div>'
            )
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"user": None, "next_url": next, "error": error_msg},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not user.is_active:
        error_msg = "This account has been deactivated. Please contact support."
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-lg bg-rose-50 p-3 text-sm text-rose-700 border border-rose-200">{error_msg}</div>'
            )
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"user": None, "next_url": next, "error": error_msg},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # Issue session token
    token = create_session_token(user.id)
    redirect_url = next if next and next.startswith("/") else "/dashboard"

    if request.headers.get("HX-Request"):
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = redirect_url
    else:
        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    # Set secure HTTP-only cookie
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
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db_session),
):
    """Register a new user account."""
    email_clean = email.strip().lower()

    # Check if email is already registered
    stmt = select(User).where(User.email == email_clean)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        error_msg = "An account with this email address already exists."
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-lg bg-rose-50 p-3 text-sm text-rose-700 border border-rose-200">{error_msg}</div>'
            )
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={"user": None, "error": error_msg},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # If first user on platform, auto-promote to Super Admin
    count_stmt = select(func.count(User.id))
    user_count = (await db.execute(count_stmt)).scalar() or 0
    is_first_user = (user_count == 0)

    # Create user
    new_user = User(
        full_name=full_name.strip(),
        email=email_clean,
        password_hash=hash_password(password),
        is_super_admin=is_first_user,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()

    token = create_session_token(new_user.id)
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


@router.post("/logout")
async def logout():
    """Clear session cookie and redirect to home."""
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return response

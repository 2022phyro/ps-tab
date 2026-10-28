"""Role-Based Access Control (RBAC) engine, permission catalog, and FastAPI dependencies."""

from typing import Optional
from fastapi import Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kwuo.core.database import get_db_session
from kwuo.core.security import decode_session_token, SESSION_COOKIE_NAME
from kwuo.models.user import User, Group, GroupPermission, GroupMembership

# Permission Catalog
class Permissions:
    # System-level (Global)
    SYSTEM_MANAGE_USERS = "system:manage_users"
    SYSTEM_MANAGE_TOURNAMENTS = "system:manage_tournaments"
    SYSTEM_UNLOCK_ROUND = "system:unlock_round"
    SYSTEM_VIEW_AUDIT = "system:view_audit"

    # Tournament-scoped
    TOURNAMENT_MANAGE = "tournament:manage"
    TOURNAMENT_ROSTER = "tournament:roster"
    TOURNAMENT_CHECKIN = "tournament:checkin"
    TOURNAMENT_DRAW = "tournament:draw"
    TOURNAMENT_BALLOT_OVERRIDE = "tournament:ballot_override"
    TOURNAMENT_ROUND_ADVANCE = "tournament:round_advance"
    TOURNAMENT_PUBLISH = "tournament:publish"
    TOURNAMENT_AUDIT = "tournament:audit"


async def get_optional_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> Optional[User]:
    """Extract authenticated user if session cookie is present and valid."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        # Also check Authorization header for API callers
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]

    if not token:
        return None

    payload = decode_session_token(token)
    if not payload or "sub" not in payload:
        return None

    user_id = payload["sub"]
    stmt = (
        select(User)
        .where(User.id == user_id, User.is_active == True)
        .options(selectinload(User.group_memberships).selectinload(GroupMembership.group))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_current_user(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
) -> User:
    """Require an authenticated user. Redirects HTML requests to login or raises 401."""
    if user is None:
        if "text/html" in request.headers.get("accept", ""):
            # Web browser request
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": f"/auth/login?next={request.url.path}"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


async def user_has_permission(
    db: AsyncSession,
    user: User,
    permission: str,
    tournament_id: Optional[str] = None,
) -> bool:
    """Check if a user holds a permission globally or within a specific tournament."""
    if not user.is_active:
        return False

    # Super Admin bypasses all checks
    if user.is_super_admin:
        return True

    # Query matching group permissions
    stmt = (
        select(GroupPermission.id)
        .join(Group, Group.id == GroupPermission.group_id)
        .join(GroupMembership, GroupMembership.group_id == Group.id)
        .where(
            GroupMembership.user_id == user.id,
            GroupPermission.permission == permission,
        )
    )

    if tournament_id is not None:
        # Match either platform-global groups (tournament_id IS NULL) OR tournament-specific groups
        stmt = stmt.where((Group.tournament_id == None) | (Group.tournament_id == tournament_id))
    else:
        # Global permission check
        stmt = stmt.where(Group.tournament_id == None)

    result = await db.execute(stmt)
    return result.first() is not None


def require_super_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Ensure the user is a platform Super Admin."""
    if not user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin privileges required",
        )
    return user


def require_permission(permission: str):
    """Dependency factory checking global permission."""
    async def dependency(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db_session),
    ) -> User:
        allowed = await user_has_permission(db, user, permission, tournament_id=None)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: '{permission}' required",
            )
        return user

    return dependency


def require_tournament_permission(permission: str):
    """Dependency factory checking tournament-scoped permission from request path."""
    async def dependency(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db_session),
    ) -> User:
        tournament_id = request.path_params.get("tournament_id")
        allowed = await user_has_permission(db, user, permission, tournament_id=tournament_id)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied for tournament: '{permission}' required",
            )
        return user

    return dependency

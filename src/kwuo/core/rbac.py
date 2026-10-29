"""Role-Based Access Control (RBAC) engine, permission catalog, system groups, and FastAPI dependencies."""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from fastapi import Request, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kwuo.core.database import get_db_session
from kwuo.core.security import decode_session_token, SESSION_COOKIE_NAME
from kwuo.models.user import User, UserStatus, Group, GroupPermission, GroupMembership


# Permission Catalog
class Permissions:
    # System-level (Global)
    SYSTEM_MANAGE_USERS = "system:manage_users"
    SYSTEM_MANAGE_ROLES = "system:manage_roles"
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


# Pre-seeded system group definitions
SYSTEM_GROUP_TOURNAMENT_MANAGER = "Tournament Manager"
SYSTEM_GROUP_AUDITOR = "Auditor"
SYSTEM_GROUP_ADMIN = "Admin"

SYSTEM_GROUPS_CATALOG: Dict[str, Dict[str, Any]] = {
    SYSTEM_GROUP_TOURNAMENT_MANAGER: {
        "description": "Right to create and manage tournaments, section matrices, draws, round advances, and ballots.",
        "permissions": [
            Permissions.TOURNAMENT_MANAGE,
            Permissions.TOURNAMENT_ROSTER,
            Permissions.TOURNAMENT_CHECKIN,
            Permissions.TOURNAMENT_DRAW,
            Permissions.TOURNAMENT_BALLOT_OVERRIDE,
            Permissions.TOURNAMENT_ROUND_ADVANCE,
            Permissions.TOURNAMENT_PUBLISH,
            Permissions.TOURNAMENT_AUDIT,
        ],
    },
    SYSTEM_GROUP_AUDITOR: {
        "description": "Right to view system and tournament compliance audit logs.",
        "permissions": [
            Permissions.SYSTEM_VIEW_AUDIT,
            Permissions.TOURNAMENT_AUDIT,
        ],
    },
    SYSTEM_GROUP_ADMIN: {
        "description": "Right to take administrative action against users, manage groups, and inspect audit logs.",
        "permissions": [
            Permissions.SYSTEM_MANAGE_USERS,
            Permissions.SYSTEM_MANAGE_ROLES,
            Permissions.SYSTEM_VIEW_AUDIT,
            Permissions.TOURNAMENT_MANAGE,
            Permissions.TOURNAMENT_AUDIT,
        ],
    },
}


async def seed_system_groups(db: AsyncSession) -> None:
    """Idempotently seed the default global system security groups and permissions."""
    for group_name, group_meta in SYSTEM_GROUPS_CATALOG.items():
        stmt = select(Group).where(Group.name == group_name, Group.tournament_id == None)
        result = await db.execute(stmt)
        group = result.scalar_one_or_none()

        if not group:
            group = Group(
                name=group_name,
                description=group_meta["description"],
                tournament_id=None,
            )
            db.add(group)
            await db.flush()

        # Seed permissions for the group
        perm_stmt = select(GroupPermission.permission).where(GroupPermission.group_id == group.id)
        existing_perms = set((await db.execute(perm_stmt)).scalars().all())

        for perm in group_meta["permissions"]:
            if perm not in existing_perms:
                gp = GroupPermission(group_id=group.id, permission=perm)
                db.add(gp)

    await db.flush()


async def get_optional_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> Optional[User]:
    """Extract authenticated user if session cookie is present, valid, and unexpired.
    
    Enforces status checking (banned/suspended accounts rejected) and auth_updated_at
    timestamp validation (instant session invalidation upon password reset or account status changes).
    """
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
        .where(User.id == user_id)
        .options(selectinload(User.group_memberships).selectinload(GroupMembership.group))
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        return None

    # Block deactivated, suspended, banned, or deleted users
    if user.status in (UserStatus.BANNED, UserStatus.SUSPENDED, UserStatus.DELETED) or user.deleted_at is not None:
        return None

    # Validate session freshness against auth_updated_at (if token was issued before the last auth update, reject it)
    token_auth_ts = payload.get("auth_updated_at")
    if token_auth_ts and user.auth_updated_at:
        auth_dt = user.auth_updated_at
        if auth_dt.tzinfo is None:
            auth_dt = auth_dt.replace(tzinfo=timezone.utc)
        user_auth_ts = int(auth_dt.timestamp())
        # 2-second skew buffer for microsecond conversions
        if token_auth_ts < (user_auth_ts - 2):
            return None

    return user


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
    if not user.can_login:
        return False

    # Super Admin / Admin bypasses all checks
    if user.is_super_admin or user.is_admin:
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
    if not (user.is_super_admin or user.is_admin):
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

"""User, Group, GroupPermission, and Membership models for Scoped RBAC."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Any
from sqlalchemy import String, Boolean, Integer, ForeignKey, UniqueConstraint, DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.hybrid import hybrid_property
from kwuo.models.base import Base, TimestampMixin
from kwuo.core.typeid import TypeIDType, generate_typeid


class UserStatus(str, Enum):
    """Lifecycle status states for user accounts."""
    UNVERIFIED = "unverified"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BANNED = "banned"
    DELETED = "deleted"


class User(Base):
    """Standardized user account per Kwuo core architecture."""
    __tablename__ = "users"

    # 1. Primary Identifier (TypeID: usr_01h... or user_01h...)
    id: Mapped[str] = mapped_column(
        TypeIDType(("usr", "user")),
        primary_key=True,
        default=lambda: generate_typeid("usr"),
    )

    # 2. Basic Identity
    first_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # 3. Credentials & Security
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    mfa_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 4. Status & Verification Flags
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, name="user_status_enum", native_enum=False),
        default=UserStatus.UNVERIFIED,
        index=True,
        nullable=False,
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 5. Login Throttling & Session Security
    login_failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    login_failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    auth_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # 6. Preferences & Localization
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)

    # 7. Audit Timestamps & Soft Deletes
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    group_memberships: Mapped[List["GroupMembership"]] = relationship(
        "GroupMembership",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs: Any) -> None:
        if "full_name" in kwargs:
            fn = kwargs.pop("full_name")
            if fn and not ("first_name" in kwargs and "last_name" in kwargs):
                parts = str(fn).strip().split(" ", 1)
                kwargs.setdefault("first_name", parts[0])
                kwargs.setdefault("last_name", parts[1] if len(parts) > 1 else "")
        if "is_super_admin" in kwargs:
            kwargs.setdefault("is_admin", kwargs.pop("is_super_admin"))
        if "is_active" in kwargs:
            active_val = kwargs.pop("is_active")
            kwargs.setdefault("status", UserStatus.ACTIVE if active_val else UserStatus.SUSPENDED)
        super().__init__(**kwargs)

    # Compatibility & Helper Properties
    @hybrid_property
    def full_name(self) -> str:
        fn = f"{self.first_name} {self.last_name}".strip()
        return fn or self.email

    @full_name.setter
    def full_name(self, value: str) -> None:
        if not value:
            self.first_name = ""
            self.last_name = ""
            return
        parts = str(value).strip().split(" ", 1)
        self.first_name = parts[0]
        self.last_name = parts[1] if len(parts) > 1 else ""

    @full_name.expression
    def full_name(cls):
        return cls.first_name + " " + cls.last_name

    @hybrid_property
    def is_super_admin(self) -> bool:
        return self.is_admin

    @is_super_admin.setter
    def is_super_admin(self, val: bool) -> None:
        self.is_admin = bool(val)

    @is_super_admin.expression
    def is_super_admin(cls):
        return cls.is_admin

    @hybrid_property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    @is_active.setter
    def is_active(self, val: bool) -> None:
        self.status = UserStatus.ACTIVE if val else UserStatus.SUSPENDED

    @is_active.expression
    def is_active(cls):
        return cls.status == UserStatus.ACTIVE

    @property
    def is_locked(self) -> bool:
        if not self.locked_until:
            return False
        locked_time = self.locked_until
        if locked_time.tzinfo is None:
            locked_time = locked_time.replace(tzinfo=timezone.utc)
        return locked_time > datetime.now(timezone.utc)

    @property
    def can_login(self) -> bool:
        return self.status in (UserStatus.ACTIVE, UserStatus.UNVERIFIED) and not self.is_locked


class Group(Base, TimestampMixin):
    """Security group carrying permissions.
    
    Can be platform-global (tournament_id is NULL) or tournament-scoped (tournament_id is set).
    """
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(
        TypeIDType("grp"),
        primary_key=True,
        default=lambda: generate_typeid("grp"),
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Nullable tournament scope: None = Global group, Set = Scoped to specific tournament
    tournament_id: Mapped[Optional[str]] = mapped_column(
        TypeIDType("tourn"),
        nullable=True,
        index=True,
    )

    # Relationships
    permissions: Mapped[List["GroupPermission"]] = relationship(
        "GroupPermission",
        back_populates="group",
        cascade="all, delete-orphan",
    )
    memberships: Mapped[List["GroupMembership"]] = relationship(
        "GroupMembership",
        back_populates="group",
        cascade="all, delete-orphan",
    )


class GroupPermission(Base):
    """Individual permission assigned to a group."""
    __tablename__ = "group_permissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(
        TypeIDType("grp"),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Relationships
    group: Mapped["Group"] = relationship("Group", back_populates="permissions")

    __table_args__ = (
        UniqueConstraint("group_id", "permission", name="uq_group_permission"),
    )


class GroupMembership(Base, TimestampMixin):
    """User membership in a group."""
    __tablename__ = "group_memberships"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        TypeIDType(("user", "usr")),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[str] = mapped_column(
        TypeIDType("grp"),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="group_memberships")
    group: Mapped["Group"] = relationship("Group", back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("user_id", "group_id", name="uq_user_group_membership"),
    )

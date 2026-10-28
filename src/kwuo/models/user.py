"""User, Group, GroupPermission, and Membership models for Scoped RBAC."""

from typing import List, Optional
from sqlalchemy import String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from kwuo.models.base import Base, TimestampMixin
from kwuo.core.typeid import TypeIDType, generate_typeid


class User(Base, TimestampMixin):
    """Persistent user account (organizer, staff, administrator, or career participant)."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        TypeIDType("usr"),
        primary_key=True,
        default=lambda: generate_typeid("usr"),
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    group_memberships: Mapped[List["GroupMembership"]] = relationship(
        "GroupMembership",
        back_populates="user",
        cascade="all, delete-orphan",
    )


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
        TypeIDType("usr"),
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

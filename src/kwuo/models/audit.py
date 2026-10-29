"""Immutable compliance AuditLog model and event definitions for Kwuo."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any
from sqlalchemy import String, Boolean, Text, DateTime, JSON, event
from sqlalchemy.orm import Mapped, mapped_column
from kwuo.models.base import Base
from kwuo.core.typeid import TypeIDType, generate_typeid


class AuditSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AuditAction:
    USER_SIGNUP = "user.signup"
    USER_LOGIN = "user.login"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_LOCKED = "user.locked"
    USER_LOGOUT = "user.logout"
    USER_VERIFY_EMAIL = "user.verify_email"
    USER_PASSWORD_RESET_REQUEST = "user.password_reset_request"
    USER_PASSWORD_RESET = "user.password_reset"
    USER_PASSWORD_CHANGE = "user.password_change"
    USER_BAN = "user.ban"
    USER_SUSPEND = "user.suspend"
    USER_REACTIVATE = "user.reactivate"
    USER_UPDATE = "user.update"
    USER_DEACTIVATE = "user.deactivate"
    ROLE_GRANT = "role.grant"
    ROLE_REVOKE = "role.revoke"
    GROUP_CREATE = "group.create"
    GROUP_ASSIGN = "group.assign"
    GROUP_REMOVE = "group.remove"


class AuditLog(Base):
    """Immutable audit trail for compliance, security events, and governance.
    
    Append-only: updates and deletions are strictly prevented.
    """
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        TypeIDType("aud"),
        primary_key=True,
        default=lambda: generate_typeid("aud"),
    )

    # Actor Information
    user_id: Mapped[Optional[str]] = mapped_column(String(40), index=True, nullable=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Action Details
    action: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    action_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Resource Context
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), index=True, nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    resource_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Request Context
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), index=True, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_method: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    request_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)

    # Change Tracking & Additional Context
    changes: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    extra_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Classification & Outcome
    severity: Mapped[str] = mapped_column(
        String(20),
        default=AuditSeverity.INFO.value,
        index=True,
        nullable=False,
    )
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Immutable creation timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )

    def __init__(self, **kwargs: Any) -> None:
        if "actor_id" in kwargs:
            kwargs.setdefault("user_id", kwargs.pop("actor_id"))
        if "actor_email" in kwargs:
            kwargs.setdefault("user_email", kwargs.pop("actor_email"))
        if "description" in kwargs:
            kwargs.setdefault("action_description", kwargs.pop("description"))
        super().__init__(**kwargs)

    @property
    def actor_id(self) -> Optional[str]:
        return self.user_id

    @property
    def actor_email(self) -> Optional[str]:
        return self.user_email

    @property
    def description(self) -> Optional[str]:
        return self.action_description

    @description.setter
    def description(self, val: Optional[str]) -> None:
        self.action_description = val

    def __repr__(self) -> str:
        return f"<AuditLog {self.id}: [{self.severity}] {self.action} by {self.user_email or 'Anonymous'}>"


# Enforce Immutability via SQLAlchemy event listeners
@event.listens_for(AuditLog, "before_update")
def receive_before_update(mapper, connection, target):
    raise ValueError("AuditLog entries are immutable and cannot be updated.")


@event.listens_for(AuditLog, "before_delete")
def receive_before_delete(mapper, connection, target):
    raise ValueError("AuditLog entries cannot be deleted. Compliance records must be retained.")

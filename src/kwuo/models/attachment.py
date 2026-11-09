"""File handling and attachment models for tournament organization and tasks."""

from enum import Enum
from typing import Optional, TYPE_CHECKING
from sqlalchemy import (
    String,
    Boolean,
    Integer,
    ForeignKey,
    Text,
    Index,
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kwuo.models.base import Base, TimestampMixin
from kwuo.core.typeid import TypeIDType, generate_typeid

if TYPE_CHECKING:
    from kwuo.models.tournament import Tournament
    from kwuo.models.user import User


class AttachmentCategory(str, Enum):
    """Categorical classification of uploaded attachments."""
    BRIEFING = "briefing"         # Judge briefings, competitor briefings
    EQUITY = "equity"             # Equity policy, code of conduct, incident reporting guidelines
    RULES = "rules"               # Tournament rules, speech format guides, rubrics
    SCHEDULE = "schedule"         # Master schedule, room rosters, timetable
    TASK_MATERIAL = "task_material"  # Round/task prompts, reading materials, motion release sheets
    AWARDS_BREAKS = "awards_breaks"  # Awards ceremonies, break announcements, finalist slides
    GENERAL = "general"           # Other general files and documents


class FileAttachment(Base, TimestampMixin):
    """Uploaded document or media file attached to a tournament or a specific task.
    
    Supports:
    - Tournament-wide organization files (briefing documents, equity policies, rules).
    - Task-level files (speech prompts, reading materials, motion release sheets).
    - Public (accessible without login) vs staff-only visibility.
    """
    __tablename__ = "file_attachments"
    __table_args__ = (
        Index("ix_file_attachments_tournament_category", "tournament_id", "category"),
    )

    id: Mapped[str] = mapped_column(
        TypeIDType("att"),
        primary_key=True,
        default=lambda: generate_typeid("att"),
    )
    tournament_id: Mapped[str] = mapped_column(
        TypeIDType("tourn"),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[Optional[str]] = mapped_column(
        TypeIDType("task"),
        nullable=True,
        index=True,
    )
    uploader_id: Mapped[Optional[str]] = mapped_column(
        TypeIDType(("user", "usr")),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[AttachmentCategory] = mapped_column(
        SAEnum(AttachmentCategory, name="attachment_category_enum", native_enum=False),
        default=AttachmentCategory.GENERAL,
        nullable=False,
        index=True,
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream", nullable=False)
    sha256_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationships
    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="attachments")
    uploader: Mapped[Optional["User"]] = relationship("User")

    @property
    def formatted_size(self) -> str:
        """Human-readable representation of file size (e.g. 1.2 MB, 350 KB)."""
        bytes_val = float(self.file_size)
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_val < 1024.0:
                return f"{bytes_val:.1f} {unit}" if unit != "B" else f"{int(bytes_val)} B"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f} TB"

    @property
    def extension(self) -> str:
        """File extension without leading dot."""
        if "." in self.filename:
            return self.filename.rsplit(".", 1)[1].lower()
        return ""

    @property
    def phosphor_icon(self) -> str:
        """Phosphor icon name corresponding to file type."""
        ext = self.extension
        if ext == "pdf":
            return "file-pdf"
        elif ext in ("doc", "docx", "rtf", "odt", "txt", "md"):
            return "file-text"
        elif ext in ("csv", "xlsx", "xls"):
            return "table"
        elif ext in ("png", "jpg", "jpeg", "webp", "gif", "svg"):
            return "image"
        elif ext in ("zip", "tar", "gz"):
            return "archive"
        return "file"

"""Tournament organization models: Tournament, Division, Institution,
Participant, SpeakerProfile, JudgeProfile, OfficialProfile, RubricPreset, and RubricCriterion.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import secrets
from typing import Any, List, Optional, Tuple

from sqlalchemy import (
    String,
    Boolean,
    Integer,
    Float,
    ForeignKey,
    DateTime,
    Text,
    Enum as SAEnum,
    UniqueConstraint,
    inspect,
    Table,
    Column,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.hybrid import hybrid_property

from kwuo.models.base import Base, TimestampMixin
from kwuo.core.typeid import TypeIDType, generate_typeid
from kwuo.models.attachment import FileAttachment, AttachmentCategory


# =========================================================================
# Enumerations
# =========================================================================

class TournamentStatus(str, Enum):
    """Lifecycle state machine for a tournament."""
    DRAFT = "draft"
    ACTIVE = "active"
    CONCLUDED = "concluded"
    ARCHIVED = "archived"


class LocationType(str, Enum):
    """Event modality: physical in-person venue, virtual/online, or hybrid."""
    PHYSICAL = "physical"
    VIRTUAL = "virtual"
    HYBRID = "hybrid"


class BallotMode(str, Enum):
    """Ballot scoring mode."""
    DEMOCRACY = "democracy"  # Panelists score independently; totals are averaged
    STRICT = "strict"        # Panel deliberates; chair submits single consensus ballot


class DrawMethod(str, Enum):
    """Seeding methodology for sections."""
    RANDOM = "random"
    POWER_MATCHED = "power_matched"
    EQUAL = "equal"          # Average strength across rooms is equal


class RoomSizePreference(str, Enum):
    """Preference when room sizing has multiple valid configurations."""
    FEWEST_ROOMS = "fewest_rooms"    # Prefer fewer, fuller rooms
    SMALLER_ROOMS = "smaller_rooms"  # Prefer more, smaller rooms


class ParticipantStatus(str, Enum):
    """Live status of an attendee/participant."""
    REGISTERED = "registered"
    CHECKED_IN = "checked_in"
    WAITLISTED = "waitlisted"
    SCRATCHED = "scratched"
    ACTIVE = "active"
    INACTIVE = "inactive"


class OfficialRole(str, Enum):
    """Staff and governance roles for tournament officials."""
    DIRECTOR = "director"
    TAB = "tab"
    CAP = "ca"
    DCA = "dca"
    EQUITY = "equity"
    ORG_COMM = "org_comm"


# =========================================================================
# Core Entities
# =========================================================================

class Institution(Base, TimestampMixin):
    """School, university, or independent club.
    
    Operates on a grow-by-selection model: searched first via combobox,
    created only when no existing match fits.
    """
    __tablename__ = "institutions"

    id: Mapped[str] = mapped_column(
        TypeIDType("inst"),
        primary_key=True,
        default=lambda: generate_typeid("inst"),
    )
    tournament_id: Mapped[Optional[str]] = mapped_column(
        TypeIDType("tourn"),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), index=True, nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Relationships
    tournament: Mapped[Optional["Tournament"]] = relationship("Tournament", back_populates="institutions")
    primary_participants: Mapped[List["Participant"]] = relationship(
        "Participant",
        back_populates="institution",
        foreign_keys="Participant.institution_id",
    )
    affiliations: Mapped[List["ParticipantInstitution"]] = relationship(
        "ParticipantInstitution",
        back_populates="institution",
        cascade="all, delete-orphan",
    )
    participants: Mapped[List["Participant"]] = relationship(
        "Participant",
        secondary="participant_institutions",
        back_populates="institutions",
        viewonly=True,
    )

    __table_args__ = (
        UniqueConstraint("tournament_id", "name", name="uq_institutions_tournament_name"),
    )


class ParticipantInstitution(Base, TimestampMixin):
    """Many-to-many affiliation linking a participant to one or more institutions.
    
    Forms the foundation for institutional clash spreading and conflicts of interest.
    """
    __tablename__ = "participant_institutions"

    id: Mapped[str] = mapped_column(
        TypeIDType("affil"),
        primary_key=True,
        default=lambda: generate_typeid("affil"),
    )
    participant_id: Mapped[str] = mapped_column(
        TypeIDType("part"),
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    institution_id: Mapped[str] = mapped_column(
        TypeIDType("inst"),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    clash_type: Mapped[str] = mapped_column(
        String(50),
        default="primary",  # e.g. "primary", "alumni", "coach", "grad", "former", "other"
        nullable=False,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    participant: Mapped["Participant"] = relationship("Participant", back_populates="affiliations")
    institution: Mapped["Institution"] = relationship("Institution", back_populates="affiliations")

    __table_args__ = (
        UniqueConstraint("participant_id", "institution_id", name="uq_participant_institution"),
    )


class Tournament(Base, TimestampMixin):
    """Core tournament entity.
    
    Provides multi-tenant separation: accessed via [slug].kwuo.com.
    """
    __tablename__ = "tournaments"

    id: Mapped[str] = mapped_column(
        TypeIDType("tourn"),
        primary_key=True,
        default=lambda: generate_typeid("tourn"),
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    organizer_id: Mapped[str] = mapped_column(
        TypeIDType(("user", "usr")),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[TournamentStatus] = mapped_column(
        SAEnum(TournamentStatus, name="tournament_status_enum", native_enum=False),
        default=TournamentStatus.DRAFT,
        nullable=False,
        index=True,
    )
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    location_type: Mapped[LocationType] = mapped_column(
        SAEnum(LocationType, name="location_type_enum", native_enum=False),
        default=LocationType.PHYSICAL,
        nullable=False,
    )
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[Text]] = mapped_column(Text, nullable=True)
    feedback_window_closes_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Operational defaults for rounds & draw generation
    ballot_mode: Mapped[BallotMode] = mapped_column(
        SAEnum(BallotMode, name="ballot_mode_enum", native_enum=False),
        default=BallotMode.DEMOCRACY,
        nullable=False,
    )
    draw_method: Mapped[DrawMethod] = mapped_column(
        SAEnum(DrawMethod, name="draw_method_enum", native_enum=False),
        default=DrawMethod.RANDOM,
        nullable=False,
    )
    min_room_size: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    max_room_size: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    room_size_preference: Mapped[RoomSizePreference] = mapped_column(
        SAEnum(RoomSizePreference, name="room_size_pref_enum", native_enum=False),
        default=RoomSizePreference.FEWEST_ROOMS,
        nullable=False,
    )
    panel_size: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    minimum_panel_size: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    allow_prelim_ties: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ghost_round_limit: Mapped[int] = mapped_column(Integer, default=2, nullable=False)

    # Scoring standard & scale boundaries (presented as rubric in UI)
    base_score: Mapped[float] = mapped_column(Float, default=70.0, nullable=False)
    ceiling_score: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    max_time_penalty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Relationships
    organizer: Mapped["User"] = relationship("User")
    divisions: Mapped[List["Division"]] = relationship("Division", back_populates="tournament", cascade="all, delete-orphan", lazy="selectin")
    participants: Mapped[List["Participant"]] = relationship("Participant", back_populates="tournament", cascade="all, delete-orphan", lazy="selectin")
    rubric_criteria: Mapped[List["RubricCriterion"]] = relationship(
        "RubricCriterion",
        back_populates="tournament",
        cascade="all, delete-orphan",
        order_by="RubricCriterion.display_order",
        lazy="selectin",
    )
    attachments: Mapped[List[FileAttachment]] = relationship(
        "FileAttachment",
        back_populates="tournament",
        cascade="all, delete-orphan",
        order_by="FileAttachment.display_order",
        lazy="selectin",
    )
    schedule_items: Mapped[List["ScheduleItem"]] = relationship(
        "ScheduleItem",
        back_populates="tournament",
        cascade="all, delete-orphan",
        order_by="ScheduleItem.start_time, ScheduleItem.display_order",
        lazy="selectin",
    )
    institutions: Mapped[List["Institution"]] = relationship(
        "Institution",
        back_populates="tournament",
        cascade="all, delete-orphan",
        order_by="Institution.name",
        lazy="selectin",
    )

    @property
    def speakers(self) -> List["Participant"]:
        """Participants registered with a SpeakerProfile."""
        return [p for p in self.participants if p.is_speaker]

    @property
    def judges(self) -> List["Participant"]:
        """Participants registered with a JudgeProfile."""
        return [p for p in self.participants if p.is_judge]

    @property
    def officials(self) -> List["Participant"]:
        """Participants registered with an OfficialProfile."""
        return [p for p in self.participants if p.is_official]

    @property
    def total_speakers_count(self) -> int:
        return len(self.speakers)

    @property
    def total_judges_count(self) -> int:
        return len(self.judges)

    @property
    def total_officials_count(self) -> int:
        return len(self.officials)

    @property
    def total_institutions_count(self) -> int:
        return len(self.institutions)

    @property
    def briefing_docs(self) -> List[FileAttachment]:
        """Briefing documents for judges and competitors."""
        return [a for a in self.attachments if a.category == AttachmentCategory.BRIEFING]

    @property
    def equity_docs(self) -> List[FileAttachment]:
        """Equity policies and incident reporting guidelines."""
        return [a for a in self.attachments if a.category == AttachmentCategory.EQUITY]

    @property
    def rule_docs(self) -> List[FileAttachment]:
        """Rules, event guidelines, and rubric definitions."""
        return [a for a in self.attachments if a.category == AttachmentCategory.RULES]

    @property
    def schedule_docs(self) -> List[FileAttachment]:
        """Schedule, timetable, and room allocations."""
        return [a for a in self.attachments if a.category == AttachmentCategory.SCHEDULE]

    @property
    def task_materials(self) -> List[FileAttachment]:
        """Files attached to rounds or tasks (prompts, motions, manuscripts)."""
        return [a for a in self.attachments if a.category == AttachmentCategory.TASK_MATERIAL or a.task_id is not None]

    @property
    def public_attachments(self) -> List[FileAttachment]:
        """All public files accessible to attendees without login."""
        return [a for a in self.attachments if a.is_public]

    @property
    def total_speakers_count(self) -> int:
        """Count of active or registered speakers."""
        return len(self.speakers)

    @property
    def total_judges_count(self) -> int:
        """Count of active or registered judges."""
        return len(self.judges)

    @property
    def total_officials_count(self) -> int:
        """Count of registered tournament officials."""
        return len(self.officials)

    @property
    def total_institutions_count(self) -> int:
        """Count of unique institutions represented in the tournament."""
        insp = inspect(self)
        if "participants" in insp.unloaded:
            return 0
        inst_ids = {p.institution_id for p in self.participants if p.institution_id}
        return len(inst_ids)

    @property
    def discretionary_points_sum(self) -> float:
        """Sum of point caps across all evaluated rubric criteria."""
        insp = inspect(self)
        if "rubric_criteria" in insp.unloaded:
            return 0.0
        return sum(c.max_points for c in self.rubric_criteria)

    @property
    def rubric_max_points(self) -> float:
        """Tally of base score + discretionary rubric criteria points."""
        return self.base_score + self.discretionary_points_sum

    @property
    def has_active_round(self) -> bool:
        """True if the tab room has an active round running."""
        return self.status == TournamentStatus.ACTIVE

    @property
    def has_published_results(self) -> bool:
        """True if any round results or awards have been released."""
        return self.status in (TournamentStatus.ACTIVE, TournamentStatus.CONCLUDED)


# Association table for multi-category / multi-division participant eligibility (speakers & judges)
participant_divisions = Table(
    "participant_divisions",
    Base.metadata,
    Column(
        "participant_id",
        TypeIDType("part"),
        ForeignKey("participants.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "division_id",
        TypeIDType("div"),
        ForeignKey("divisions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Division(Base, TimestampMixin):
    """Eligibility category / competitive tier (e.g. Open, Novice, ESL).
    
    Participants (both speakers and judges) can be eligible for multiple divisions.
    During preliminary rounds, all divisions compete together in a unified draw.
    Divisions govern eligibility for outround breaks, judge flight allocations,
    and speaker awards.
    """
    __tablename__ = "divisions"

    id: Mapped[str] = mapped_column(
        TypeIDType("div"),
        primary_key=True,
        default=lambda: generate_typeid("div"),
    )
    tournament_id: Mapped[str] = mapped_column(
        TypeIDType("tourn"),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="divisions")
    participants: Mapped[List["Participant"]] = relationship(
        "Participant",
        secondary="participant_divisions",
        back_populates="divisions",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("tournament_id", "name", name="uq_divisions_tournament_name"),
    )

    @property
    def speakers(self) -> List["Participant"]:
        """Speakers enrolled in this division."""
        insp = inspect(self)
        if "participants" in insp.unloaded:
            return []
        return [p for p in self.participants if p.is_speaker]

    @property
    def judges(self) -> List["Participant"]:
        """Judges accredited/eligible for this division."""
        insp = inspect(self)
        if "participants" in insp.unloaded:
            return []
        return [p for p in self.participants if p.is_judge]


class RubricCriterion(Base):
    """Individual evaluated scoring dimension for a tournament (e.g. Content, Delivery).
    
    Belongs directly to the tournament. Presented together with base_score,
    ceiling_score, and max_time_penalty as the tournament's rubric in the UI.
    """
    __tablename__ = "rubric_criteria"

    id: Mapped[str] = mapped_column(
        TypeIDType("crit"),
        primary_key=True,
        default=lambda: generate_typeid("crit"),
    )
    tournament_id: Mapped[str] = mapped_column(
        TypeIDType("tourn"),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    max_points: Mapped[float] = mapped_column(Float, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationships
    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="rubric_criteria")


class ScheduleItem(Base, TimestampMixin):
    """Chronological event, round, or briefing on the tournament timetable."""
    __tablename__ = "schedule_items"

    id: Mapped[str] = mapped_column(
        TypeIDType("sch"),
        primary_key=True,
        default=lambda: generate_typeid("sch"),
    )
    tournament_id: Mapped[str] = mapped_column(
        TypeIDType("tourn"),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationships
    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="schedule_items")


# =========================================================================
# Unified Participant & Role Profiles
# =========================================================================

class Participant(Base, TimestampMixin):
    """Core attendee / human entity in a tournament.
    
    Encapsulates identity, institution affiliation, check-in status,
    and private access token (magic link) authentication.
    
    Specific operational capabilities are delegated to 1:1 role profiles:
    - SpeakerProfile (competitor in a division)
    - JudgeProfile (evaluator / chair eligibility)
    - OfficialProfile (director, tab staff, CAP, equity, org_comm)
    
    Officials who judge simply have both OfficialProfile and JudgeProfile attached.
    """
    __tablename__ = "participants"

    id: Mapped[str] = mapped_column(
        TypeIDType("part"),
        primary_key=True,
        default=lambda: generate_typeid("part"),
    )
    tournament_id: Mapped[str] = mapped_column(
        TypeIDType("tourn"),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    institution_id: Mapped[Optional[str]] = mapped_column(
        TypeIDType("inst"),
        ForeignKey("institutions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        TypeIDType(("user", "usr")),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    status: Mapped[ParticipantStatus] = mapped_column(
        SAEnum(ParticipantStatus, name="participant_status_enum", native_enum=False),
        default=ParticipantStatus.REGISTERED,
        nullable=False,
        index=True,
    )
    checked_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Magic link / Private URL bearer token authentication
    access_token_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=True,
    )
    access_token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    tournament: Mapped["Tournament"] = relationship("Tournament", back_populates="participants")
    institution: Mapped[Optional["Institution"]] = relationship(
        "Institution",
        back_populates="primary_participants",
        foreign_keys=[institution_id],
    )
    affiliations: Mapped[List["ParticipantInstitution"]] = relationship(
        "ParticipantInstitution",
        back_populates="participant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    institutions: Mapped[List["Institution"]] = relationship(
        "Institution",
        secondary="participant_institutions",
        back_populates="participants",
        viewonly=True,
        lazy="selectin",
    )
    user: Mapped[Optional["User"]] = relationship("User")

    speaker_profile: Mapped[Optional["SpeakerProfile"]] = relationship(
        "SpeakerProfile",
        back_populates="participant",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    judge_profile: Mapped[Optional["JudgeProfile"]] = relationship(
        "JudgeProfile",
        back_populates="participant",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    official_profile: Mapped[Optional["OfficialProfile"]] = relationship(
        "OfficialProfile",
        back_populates="participant",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    divisions: Mapped[List["Division"]] = relationship(
        "Division",
        secondary="participant_divisions",
        back_populates="participants",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("tournament_id", "email", name="uq_participants_tournament_email"),
    )

    def __init__(self, **kwargs: Any) -> None:
        # Support single name directly, or gracefully assemble first_name + last_name if passed
        if "name" not in kwargs:
            first = kwargs.pop("first_name", "")
            last = kwargs.pop("last_name", "")
            kwargs["name"] = f"{first} {last}".strip()
        kwargs.setdefault("speaker_profile", None)
        kwargs.setdefault("judge_profile", None)
        kwargs.setdefault("official_profile", None)
        super().__init__(**kwargs)

    @hybrid_property
    def full_name(self) -> str:
        """Alias for name for template and backward compatibility."""
        return self.name or self.email

    @property
    def institution_name(self) -> str:
        """Returns the institution name, or 'Independent' for unaffiliated entries."""
        return self.institution.name if self.institution else "Independent"

    @property
    def division_names(self) -> List[str]:
        insp = inspect(self)
        if "divisions" in insp.unloaded:
            return []
        return [d.name for d in self.divisions]

    @property
    def is_speaker(self) -> bool:
        insp = inspect(self)
        if "speaker_profile" in insp.unloaded:
            return False
        return self.speaker_profile is not None

    @property
    def is_judge(self) -> bool:
        insp = inspect(self)
        if "judge_profile" in insp.unloaded:
            return False
        return self.judge_profile is not None

    @property
    def is_official(self) -> bool:
        insp = inspect(self)
        if "official_profile" in insp.unloaded:
            return False
        return self.official_profile is not None

    @classmethod
    def generate_token(cls) -> Tuple[str, str]:
        """Generate a cryptographically secure raw URL token and its SHA-256 hash.
        
        Returns:
            Tuple of (raw_token, token_hash)
        """
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        return raw_token, token_hash

    @classmethod
    def hash_token(cls, raw_token: str) -> str:
        """Hash a candidate raw token using SHA-256 for database lookup."""
        return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


class SpeakerProfile(Base, TimestampMixin):
    """Speaker-specific attributes for a competitor."""
    __tablename__ = "speaker_profiles"

    id: Mapped[str] = mapped_column(
        TypeIDType("spkr"),
        primary_key=True,
        default=lambda: generate_typeid("spkr"),
    )
    participant_id: Mapped[str] = mapped_column(
        TypeIDType("part"),
        ForeignKey("participants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    waitlist_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pronouns: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationships
    participant: Mapped["Participant"] = relationship("Participant", back_populates="speaker_profile")

    @property
    def divisions(self) -> List["Division"]:
        return self.participant.divisions if self.participant else []

    @property
    def division_names(self) -> List[str]:
        return self.participant.division_names if self.participant else []


class JudgeProfile(Base, TimestampMixin):
    """Judge-specific capabilities and credentials for an evaluator."""
    __tablename__ = "judge_profiles"

    id: Mapped[str] = mapped_column(
        TypeIDType("adj"),
        primary_key=True,
        default=lambda: generate_typeid("adj"),
    )
    participant_id: Mapped[str] = mapped_column(
        TypeIDType("part"),
        ForeignKey("participants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    is_chair_eligible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_reserve: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_independent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fatigue_cap_rounds_per_day: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    participant: Mapped["Participant"] = relationship("Participant", back_populates="judge_profile")

    @property
    def divisions(self) -> List["Division"]:
        return self.participant.divisions if self.participant else []

    @property
    def division_names(self) -> List[str]:
        return self.participant.division_names if self.participant else []


class OfficialProfile(Base, TimestampMixin):
    """Official tournament administration credentials and roles."""
    __tablename__ = "official_profiles"

    id: Mapped[str] = mapped_column(
        TypeIDType("off"),
        primary_key=True,
        default=lambda: generate_typeid("off"),
    )
    participant_id: Mapped[str] = mapped_column(
        TypeIDType("part"),
        ForeignKey("participants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    role: Mapped[OfficialRole] = mapped_column(
        SAEnum(OfficialRole, name="official_role_enum", native_enum=False),
        default=OfficialRole.TAB,
        nullable=False,
        index=True,
    )
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    participant: Mapped["Participant"] = relationship("Participant", back_populates="official_profile")

    def set_password(self, password: str) -> None:
        """Hash and update official password."""
        from kwuo.core.security import hash_password
        self.password_hash = hash_password(password)

    def verify_password(self, password: str) -> bool:
        """Verify plain password against official's password hash."""
        from kwuo.core.security import verify_password
        if not self.password_hash:
            return False
        return verify_password(password, self.password_hash)

"""Tournament tab room metrics and single-query navigation badge aggregation."""

from typing import Dict, Any
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from kwuo.models.tournament import (
    Participant,
    ParticipantStatus,
    SpeakerProfile,
    JudgeProfile,
    OfficialProfile,
    Institution,
    Role,
)
from kwuo.models.attachment import FileAttachment


async def get_tournament_nav_counts(db: AsyncSession, tournament_id: str) -> Dict[str, int]:
    """Fetch all tab room navigation badge counts in a single consolidated SQL query.
    
    Replaces multiple un-indexed Python-side collection length evaluations.
    """
    participants_agg = (
        select(
            func.count(func.distinct(SpeakerProfile.id)).label("speakers_count"),
            func.count(
                func.distinct(
                    case((Participant.status == ParticipantStatus.CHECKED_IN, SpeakerProfile.id), else_=None)
                )
            ).label("speakers_checked_in"),
            func.count(func.distinct(JudgeProfile.id)).label("judges_count"),
            func.count(
                func.distinct(
                    case((Participant.status == ParticipantStatus.CHECKED_IN, JudgeProfile.id), else_=None)
                )
            ).label("judges_checked_in"),
            func.count(func.distinct(OfficialProfile.id)).label("officials_count"),
        )
        .select_from(Participant)
        .outerjoin(SpeakerProfile, SpeakerProfile.participant_id == Participant.id)
        .outerjoin(JudgeProfile, JudgeProfile.participant_id == Participant.id)
        .outerjoin(OfficialProfile, OfficialProfile.participant_id == Participant.id)
        .where(Participant.tournament_id == tournament_id)
        .subquery()
    )

    inst_sub = (
        select(func.count(Institution.id))
        .where(Institution.tournament_id == tournament_id)
        .scalar_subquery()
        .label("institutions_count")
    )
    att_sub = (
        select(func.count(FileAttachment.id))
        .where(FileAttachment.tournament_id == tournament_id)
        .scalar_subquery()
        .label("attachments_count")
    )
    roles_sub = (
        select(func.count(Role.id))
        .where(Role.tournament_id == tournament_id)
        .scalar_subquery()
        .label("roles_count")
    )

    combined_stmt = select(
        participants_agg.c.speakers_count,
        participants_agg.c.speakers_checked_in,
        participants_agg.c.judges_count,
        participants_agg.c.judges_checked_in,
        participants_agg.c.officials_count,
        inst_sub,
        att_sub,
        roles_sub,
    )

    row = (await db.execute(combined_stmt)).one_or_none()
    if not row:
        return {
            "speakers": 0,
            "speakers_checked_in": 0,
            "judges": 0,
            "judges_checked_in": 0,
            "officials": 0,
            "institutions": 0,
            "attachments": 0,
            "roles": 0,
        }

    return {
        "speakers": int(row.speakers_count or 0),
        "speakers_checked_in": int(row.speakers_checked_in or 0),
        "judges": int(row.judges_count or 0),
        "judges_checked_in": int(row.judges_checked_in or 0),
        "officials": int(row.officials_count or 0),
        "institutions": int(row.institutions_count or 0),
        "attachments": int(row.attachments_count or 0),
        "roles": int(row.roles_count or 0),
    }

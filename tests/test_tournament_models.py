"""Tests for Phase 2 Segment A Tournament Organization models (Unified Participant & Multi-Category Profiles)."""

import pytest
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kwuo.models.user import User, UserStatus
from kwuo.models.tournament import (
    Tournament,
    TournamentStatus,
    LocationType,
    Division,
    BallotMode,
    DrawMethod,
    RoomSizePreference,
    Institution,
    Participant,
    ParticipantStatus,
    SpeakerProfile,
    JudgeProfile,
    OfficialProfile,
    OfficialRole,
    RubricCriterion,
)


@pytest.mark.asyncio
async def test_tournament_and_division_creation(db_session: AsyncSession):
    """Test tournament creation with operational controls and multi-category divisions for speakers and judges."""
    # 1. Create organizer
    organizer = User(
        email="director@tournament.org",
        full_name="Tournament Director Terry",
        password_hash="dummy_hash",
        status=UserStatus.ACTIVE,
        is_verified=True,
    )
    db_session.add(organizer)
    await db_session.flush()

    # 2. Create tournament with operational round & draw defaults and links dict
    tournament = Tournament(
        name="Yale Public Speaking Invitational 2026",
        slug="yale-invitational-2026",
        organizer_id=organizer.id,
        status=TournamentStatus.DRAFT,
        location="New Haven, CT (Yale Campus)",
        location_type=LocationType.PHYSICAL,
        description="Annual collegiate public speaking championship.",
        ballot_mode=BallotMode.DEMOCRACY,
        draw_method=DrawMethod.RANDOM,
        min_room_size=4,
        max_room_size=8,
        panel_size=3,
        minimum_panel_size=1,
        room_size_preference=RoomSizePreference.FEWEST_ROOMS,
    )
    db_session.add(tournament)
    await db_session.flush()

    assert tournament.id.startswith("tourn_")
    assert tournament.status == TournamentStatus.DRAFT
    assert tournament.slug == "yale-invitational-2026"
    assert tournament.location_type == LocationType.PHYSICAL
    assert tournament.ballot_mode == BallotMode.DEMOCRACY
    assert tournament.draw_method == DrawMethod.RANDOM
    assert tournament.panel_size == 3

    # 3. Create eligibility divisions / categories
    open_div = Division(tournament_id=tournament.id, name="Open", description="General field")
    novice_div = Division(tournament_id=tournament.id, name="Novice", description="First-year competitors")
    esl_div = Division(tournament_id=tournament.id, name="ESL", description="English as a Second Language")
    db_session.add_all([open_div, novice_div, esl_div])
    await db_session.flush()

    assert open_div.id.startswith("div_")
    assert novice_div.id.startswith("div_")
    assert esl_div.id.startswith("div_")

    # 4. Create a speaker with single name / nickname eligible for multiple categories (Open + Novice + ESL)
    multicategory_speaker = Participant(
        tournament_id=tournament.id,
        name="Maya",
        email="maya@yale.edu",
        divisions=[open_div, novice_div, esl_div],
        speaker_profile=SpeakerProfile(),
    )

    # 5. Create a judge also allocated to divisions (e.g. Open and Novice)
    multicategory_judge = Participant(
        tournament_id=tournament.id,
        name="Judge Judy",
        email="judy@yale.edu",
        divisions=[open_div, novice_div],
        judge_profile=JudgeProfile(is_chair_eligible=True),
    )

    db_session.add_all([multicategory_speaker, multicategory_judge])
    await db_session.flush()

    assert multicategory_speaker.name == "Maya"
    assert multicategory_speaker.full_name == "Maya"
    assert multicategory_judge.name == "Judge Judy"
    assert multicategory_judge.full_name == "Judge Judy"

    # Verify speaker divisions
    assert len(multicategory_speaker.divisions) == 3
    div_names = multicategory_speaker.division_names
    assert "Open" in div_names
    assert "Novice" in div_names
    assert "ESL" in div_names
    # Speaker profile forwarder
    assert multicategory_speaker.speaker_profile.division_names == div_names

    # Verify judge divisions
    assert len(multicategory_judge.divisions) == 2
    judge_div_names = multicategory_judge.division_names
    assert "Open" in judge_div_names
    assert "Novice" in judge_div_names
    assert multicategory_judge.judge_profile.division_names == judge_div_names

    # Verify Division helper properties (speakers and judges)
    stmt = (
        select(Division)
        .options(
            selectinload(Division.participants).selectinload(Participant.speaker_profile),
            selectinload(Division.participants).selectinload(Participant.judge_profile),
        )
        .where(Division.id == open_div.id)
    )
    loaded_open = (await db_session.execute(stmt)).scalar_one()
    assert len(loaded_open.speakers) == 1
    assert loaded_open.speakers[0].id == multicategory_speaker.id
    assert len(loaded_open.judges) == 1
    assert loaded_open.judges[0].id == multicategory_judge.id


@pytest.mark.asyncio
async def test_institution_and_participant_profiles(db_session: AsyncSession):
    """Test institutions, unaffiliated participants, speakers, judges, and dual-role officials."""
    # 1. Setup tournament and organizer
    organizer = User(
        email="org@speech.org",
        full_name="Organizer Olivia",
        password_hash="dummy_hash",
        status=UserStatus.ACTIVE,
    )
    db_session.add(organizer)
    await db_session.flush()

    tournament = Tournament(
        name="Harvard Speech Open",
        slug="harvard-open-2026",
        organizer_id=organizer.id,
        status=TournamentStatus.ACTIVE,
    )
    db_session.add(tournament)
    await db_session.flush()

    division = Division(tournament_id=tournament.id, name="Open")
    db_session.add(division)
    await db_session.flush()

    # 2. Add institution (grow-by-selection)
    inst = Institution(
        name="Stanford Debate & Speech Society",
        code="STAN",
    )
    db_session.add(inst)
    await db_session.flush()
    assert inst.id.startswith("inst_")

    # 3. Add institution-affiliated speaker
    speaker = Participant(
        tournament_id=tournament.id,
        institution_id=inst.id,
        name="Sam Speaker",
        email="sam@stanford.edu",
        status=ParticipantStatus.REGISTERED,
        divisions=[division],
        speaker_profile=SpeakerProfile(),
    )
    db_session.add(speaker)
    await db_session.flush()

    assert speaker.id.startswith("part_")
    assert speaker.speaker_profile.id.startswith("spkr_")
    assert speaker.name == "Sam Speaker"
    assert speaker.full_name == "Sam Speaker"
    assert speaker.institution_name == "Stanford Debate & Speech Society"
    assert speaker.is_speaker is True
    assert speaker.is_judge is False
    assert speaker.is_official is False
    assert "Open" in speaker.division_names

    # 4. Add independent / unaffiliated speaker with mononym/nickname (institution is None)
    indep_speaker = Participant(
        tournament_id=tournament.id,
        institution_id=None,
        name="Indie",
        email="indie@freelance.org",
        status=ParticipantStatus.CHECKED_IN,
        divisions=[division],
        speaker_profile=SpeakerProfile(),
    )
    db_session.add(indep_speaker)
    await db_session.flush()

    assert indep_speaker.institution_id is None
    assert indep_speaker.name == "Indie"
    assert indep_speaker.full_name == "Indie"
    assert indep_speaker.institution_name == "Independent"
    assert indep_speaker.status == ParticipantStatus.CHECKED_IN

    # 5. Add adjudicator (JudgeProfile) with division
    judge = Participant(
        tournament_id=tournament.id,
        institution_id=inst.id,
        name="Justice Jordan",
        email="jordan@stanford.edu",
        status=ParticipantStatus.CHECKED_IN,
        divisions=[division],
        judge_profile=JudgeProfile(
            is_chair_eligible=True,
            is_reserve=True,
            fatigue_cap_rounds_per_day=4,
        ),
    )
    db_session.add(judge)
    await db_session.flush()

    assert judge.id.startswith("part_")
    assert judge.name == "Justice Jordan"
    assert judge.judge_profile.id.startswith("adj_")
    assert judge.judge_profile.is_chair_eligible is True
    assert judge.judge_profile.is_reserve is True
    assert judge.is_speaker is False
    assert judge.is_judge is True
    assert judge.is_official is False
    assert "Open" in judge.division_names

    # 6. Add Tournament Official who also judges (dual-role: OfficialProfile + JudgeProfile)
    ca_judge = Participant(
        tournament_id=tournament.id,
        institution_id=None,
        name="Chief Adjudicator",
        email="ca@tournament.org",
        status=ParticipantStatus.ACTIVE,
        divisions=[division],
        official_profile=OfficialProfile(role=OfficialRole.CAP),
        judge_profile=JudgeProfile(is_chair_eligible=True, is_reserve=False),
    )
    db_session.add(ca_judge)
    await db_session.flush()

    assert ca_judge.is_official is True
    assert ca_judge.is_judge is True
    assert ca_judge.is_speaker is False
    assert ca_judge.name == "Chief Adjudicator"
    assert ca_judge.official_profile.role == OfficialRole.CAP
    assert ca_judge.judge_profile.is_chair_eligible is True

    # 7. Verify tournament-level helper properties
    stmt = (
        select(Tournament)
        .options(
            selectinload(Tournament.participants).selectinload(Participant.speaker_profile),
            selectinload(Tournament.participants).selectinload(Participant.judge_profile),
            selectinload(Tournament.participants).selectinload(Participant.official_profile),
        )
        .where(Tournament.id == tournament.id)
    )
    loaded_t = (await db_session.execute(stmt)).scalar_one()

    assert len(loaded_t.participants) == 4
    assert len(loaded_t.speakers) == 2  # Sam + Indie
    assert len(loaded_t.judges) == 2    # Justice Jordan + Chief Adjudicator
    assert len(loaded_t.officials) == 1 # Chief Adjudicator


@pytest.mark.asyncio
async def test_participant_magic_links_and_token_lookup(db_session: AsyncSession):
    """Test Participant access_token_hash generation, SHA-256 lookup, and rotation."""
    organizer = User(email="t@t.org", full_name="T", password_hash="h")
    db_session.add(organizer)
    await db_session.flush()

    tournament = Tournament(name="Oxford IV", slug="oxford-iv", organizer_id=organizer.id)
    db_session.add(tournament)
    await db_session.flush()

    open_div = Division(tournament_id=tournament.id, name="Open")
    novice_div = Division(tournament_id=tournament.id, name="Novice")
    db_session.add_all([open_div, novice_div])
    await db_session.flush()

    # Generate secure raw URL token & hash
    raw_token, token_hash = Participant.generate_token()
    assert len(raw_token) >= 32
    assert len(token_hash) == 64

    # Alice is eligible for both Open and Novice (supports single name)
    speaker = Participant(
        tournament_id=tournament.id,
        name="Alice",
        email="alice@oxford.ac.uk",
        access_token_hash=token_hash,
        divisions=[open_div, novice_div],
        speaker_profile=SpeakerProfile(),
    )
    db_session.add(speaker)
    await db_session.flush()

    # Direct O(1) indexed lookup by hashing candidate raw token from query params
    candidate_hash = Participant.hash_token(raw_token)
    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.divisions),
        )
        .where(
            Participant.tournament_id == tournament.id,
            Participant.access_token_hash == candidate_hash,
        )
    )
    found_participant = (await db_session.execute(stmt)).scalar_one_or_none()

    assert found_participant is not None
    assert found_participant.name == "Alice"
    assert found_participant.email == "alice@oxford.ac.uk"
    assert found_participant.is_speaker is True
    assert "Open" in found_participant.division_names
    assert "Novice" in found_participant.division_names


@pytest.mark.asyncio
async def test_participant_unique_email_per_tournament(db_session: AsyncSession):
    """Test that duplicate registrations with the same email in a tournament are blocked."""
    organizer = User(email="admin@ps.org", full_name="Super Admin", password_hash="h")
    db_session.add(organizer)
    await db_session.flush()

    tournament = Tournament(name="Cambridge IV", slug="cambridge-iv", organizer_id=organizer.id)
    db_session.add(tournament)
    await db_session.flush()

    p1 = Participant(
        tournament_id=tournament.id,
        name="Duplicate Dan",
        email="dan@cambridge.ac.uk",
        judge_profile=JudgeProfile(),
    )
    db_session.add(p1)
    await db_session.flush()

    # Attempting to add another participant with the same email in the same tournament
    p2 = Participant(
        tournament_id=tournament.id,
        name="Duplicate Dan",
        email="dan@cambridge.ac.uk",
        official_profile=OfficialProfile(role=OfficialRole.TAB),
    )
    db_session.add(p2)

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_tournament_rubric_criteria_and_scoring_bounds(db_session: AsyncSession):
    """Test Tournament scoring boundaries (base, ceiling, max_time_penalty) and child RubricCriterion."""
    organizer = User(email="rubric@t.org", full_name="Rubric Admin", password_hash="h")
    db_session.add(organizer)
    await db_session.flush()

    tournament = Tournament(
        name="Rubric Cup",
        slug="rubric-cup",
        organizer_id=organizer.id,
        base_score=70.0,
        ceiling_score=100.0,
        max_time_penalty=5.0,
    )
    db_session.add(tournament)
    await db_session.flush()

    assert tournament.id.startswith("tourn_")
    assert tournament.base_score == 70.0
    assert tournament.ceiling_score == 100.0
    assert tournament.max_time_penalty == 5.0

    crit1 = RubricCriterion(tournament_id=tournament.id, name="Content & Argumentation", max_points=10.0, display_order=1)
    crit2 = RubricCriterion(tournament_id=tournament.id, name="Delivery & Style", max_points=10.0, display_order=2)
    crit3 = RubricCriterion(tournament_id=tournament.id, name="Structure & Flow", max_points=5.0, display_order=3)
    crit4 = RubricCriterion(tournament_id=tournament.id, name="Language Use & Nuance", max_points=5.0, display_order=4)
    db_session.add_all([crit1, crit2, crit3, crit4])
    await db_session.flush()

    assert crit1.id.startswith("crit_")

    # Fetch with criteria
    stmt = (
        select(Tournament)
        .options(selectinload(Tournament.rubric_criteria))
        .where(Tournament.id == tournament.id)
    )
    loaded_tournament = (await db_session.execute(stmt)).scalar_one()

    assert len(loaded_tournament.rubric_criteria) == 4
    total_criteria_cap = sum(c.max_points for c in loaded_tournament.rubric_criteria)
    # Total max score = base_score (70) + sum(criteria) (30) = 100
    assert loaded_tournament.base_score + total_criteria_cap == loaded_tournament.ceiling_score

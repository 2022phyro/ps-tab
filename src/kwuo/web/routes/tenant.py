"""Tenant subdomain routes for public tournament pages, zero-auth participant portals, and official administration."""

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import secrets
from typing import Optional, List, Dict, Any, Set
from fastapi import APIRouter, Request, Depends, Form, File, UploadFile, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from sqlalchemy import select, update, delete, or_, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from kwuo.core.database import get_db
from kwuo.core.rbac import get_optional_current_user
from kwuo.core.typeid import generate_typeid
from kwuo.core.localization import (
    get_country_info,
    normalize_country,
    normalize_region,
    COUNTRY_CATALOG,
    get_all_timezones_grouped,
)
from kwuo.services.storage import (
    save_upload_file,
    delete_stored_file,
    StorageError,
    FileTooLargeError,
    InvalidExtensionError,
)
from kwuo.services.email import send_official_invitation_email, send_magic_link_email
from kwuo.core.security import (
    create_participant_token,
    decode_participant_token,
    create_official_token,
    decode_official_token,
    verify_password as verify_plain_password,
)
from sqlalchemy.orm.attributes import flag_modified
from kwuo.models.user import User
from kwuo.models.tournament import (
    Tournament,
    TournamentStatus,
    LocationType,
    BallotMode,
    DrawMethod,
    RoomSizePreference,
    Participant,
    ParticipantStatus,
    SpeakerProfile,
    JudgeProfile,
    OfficialProfile,
    OfficialRole,
    Division,
    participant_divisions,
    Institution,
    ParticipantInstitution,
    RubricCriterion,
    ScheduleItem,
    Role,
    Permission,
    normalize_institution_name,
    LINK_PRESETS,
)
from kwuo.models.attachment import FileAttachment, AttachmentCategory
from kwuo.web.templates import templates

router = APIRouter(tags=["Tenant Subdomain"])

# =========================================================================
# RBAC Defaults & System Permissions Catalog
# =========================================================================

DEFAULT_TABROOM_PERMISSIONS = [
    ("settings:manage", "Tournament Settings", "Organization", "Configure tournament general settings, boundaries, and timetable"),
    ("documents:manage", "Documents & Repository", "Organization", "Upload, edit, and publish official documents and briefing slides"),
    ("rubric:manage", "Scoring Criteria & Rubric", "Organization", "Define scoring scales, speaker rubrics, and penalty rules"),
    ("speakers:manage", "Speakers Roster", "Organization", "Register, import, edit, and check in competitors"),
    ("judges:manage", "Judges & Panels", "Organization", "Accredit adjudicators, configure chair eligibility and independence"),
    ("officials:manage", "Officials & Staff", "Organization", "Manage official profiles and issue password setup links"),
    ("institutions:manage", "Institutions & Delegations", "Organization", "Merge, delete, export, and import delegation records"),
    ("authorization:manage", "Roles & Permissions (RBAC)", "Organization", "Create custom roles and grant/revoke access permissions"),
    ("rounds:manage", "Rounds & Pairings", "Rounds", "Generate draws, manage rooms, and verify ballots"),
    ("results:publish", "Publish Results", "Rounds", "Release round results, speaker tabs, and outround breaks"),
    ("equity:manage", "Equity & Complaints", "Equity", "Review equity incident reports and formal complaints"),
]

DEFAULT_TOURNAMENT_ROLES = [
    {
        "name": "Tournament Director",
        "description": "Full administrative control over all tournament organization and operations.",
        "permissions": [p[0] for p in DEFAULT_TABROOM_PERMISSIONS],
        "is_system": True,
    },
    {
        "name": "Tab Director",
        "description": "Full tabulation authority over speakers, judges, rounds, and pairings.",
        "permissions": [
            "documents:manage", "rubric:manage", "speakers:manage",
            "judges:manage", "institutions:manage", "rounds:manage", "results:publish"
        ],
        "is_system": True,
    },
    {
        "name": "Chief Adjudicator (CA)",
        "description": "Judging governance, rubric definition, panel assignments, and feedback.",
        "permissions": [
            "documents:manage", "rubric:manage", "judges:manage", "rounds:manage"
        ],
        "is_system": True,
    },
    {
        "name": "Deputy CA (DCA)",
        "description": "Adjudication team assistance, judge reviews, and panel assignments.",
        "permissions": [
            "documents:manage", "rubric:manage", "judges:manage", "rounds:manage"
        ],
        "is_system": True,
    },
    {
        "name": "Equity Officer",
        "description": "Equity guidelines, complaints handling, and participant welfare.",
        "permissions": [
            "documents:manage", "speakers:manage", "judges:manage", "equity:manage"
        ],
        "is_system": True,
    },
    {
        "name": "Organization Committee",
        "description": "Logistics, schedule, documents, institutions, and attendee registration.",
        "permissions": [
            "settings:manage", "documents:manage", "speakers:manage",
            "judges:manage", "institutions:manage"
        ],
        "is_system": True,
    },
    {
        "name": "Clerk / Room Staff",
        "description": "Participant check-in, document distribution, and ballot intake.",
        "permissions": [
            "documents:manage", "speakers:manage", "judges:manage"
        ],
        "is_system": True,
    },
]

ALL_TABROOM_PERMISSION_CODES = {p[0] for p in DEFAULT_TABROOM_PERMISSIONS} | {"*"}


async def ensure_tournament_roles_and_permissions(db: AsyncSession, tournament_id: str) -> List[Role]:
    """Ensure system permissions and default roles exist for this tournament."""
    perm_stmt = select(Permission)
    existing_perms = {p.code: p for p in (await db.execute(perm_stmt)).scalars().all()}

    for code, name, category, desc in DEFAULT_TABROOM_PERMISSIONS:
        if code not in existing_perms:
            new_p = Permission(code=code, name=name, category=category, description=desc)
            db.add(new_p)
            existing_perms[code] = new_p
    await db.flush()

    roles_stmt = select(Role).options(selectinload(Role.permissions)).where(Role.tournament_id == tournament_id)
    roles = (await db.execute(roles_stmt)).scalars().all()
    roles_by_name = {r.name: r for r in roles}

    created_any = False
    for r_spec in DEFAULT_TOURNAMENT_ROLES:
        if r_spec["name"] not in roles_by_name:
            new_role = Role(
                tournament_id=tournament_id,
                name=r_spec["name"],
                description=r_spec["description"],
                is_system=r_spec["is_system"],
            )
            for p_code in r_spec["permissions"]:
                if p_code in existing_perms:
                    new_role.permissions.append(existing_perms[p_code])
            db.add(new_role)
            roles_by_name[r_spec["name"]] = new_role
            created_any = True

    if created_any:
        await db.flush()

    return list(roles_by_name.values())


def get_current_tenant_tournament(request: Request) -> Tournament:
    """Ensure request is executing within a valid tenant tournament subdomain."""
    if not getattr(request.state, "is_tenant_domain", False):
        raise HTTPException(status_code=404, detail="This route is only available on tournament subdomains.")
    tournament = getattr(request.state, "tenant_tournament", None)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found.")
    return tournament


async def get_current_participant(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[Participant]:
    """Retrieve authenticated participant from zero-auth magic session cookie."""
    if not getattr(request.state, "is_tenant_domain", False):
        return None
    tournament = getattr(request.state, "tenant_tournament", None)
    if not tournament:
        return None

    cookie_name = f"kwuo_part_{tournament.id}"
    token = request.cookies.get(cookie_name)
    if not token:
        return None

    payload = decode_participant_token(token)
    if not payload or payload.get("tourn") != tournament.id:
        return None

    participant_id = payload.get("sub")
    if not participant_id:
        return None

    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.judge_profile),
            selectinload(Participant.official_profile),
            selectinload(Participant.divisions),
            selectinload(Participant.institution),
            selectinload(Participant.affiliations).selectinload(ParticipantInstitution.institution),
        )
        .where(
            Participant.id == participant_id,
            Participant.tournament_id == tournament.id,
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_current_official_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
) -> Optional[Dict[str, Any]]:
    """Verify whether caller is authenticated as an official with dynamic RBAC permissions."""
    if not getattr(request.state, "is_tenant_domain", False):
        return None
    tournament = getattr(request.state, "tenant_tournament", None)
    if not tournament:
        return None

    # 1. Platform super admin always has full official bypass access
    if user and user.is_super_admin:
        return {
            "is_organizer": True,
            "role": "Super Admin",
            "role_names": ["Super Admin"],
            "permissions": ALL_TABROOM_PERMISSION_CODES,
            "name": user.full_name,
            "email": user.email,
            "official_profile": None,
        }

    # 2. Tournament creator / organizer has full tab room access
    if user and tournament.organizer_id == user.id:
        return {
            "is_organizer": True,
            "role": "Tournament Director",
            "role_names": ["Tournament Director"],
            "permissions": ALL_TABROOM_PERMISSION_CODES,
            "name": user.full_name,
            "email": user.email,
            "official_profile": None,
        }

    # 3. Check official session cookie
    cookie_name = f"kwuo_off_{tournament.id}"
    token = request.cookies.get(cookie_name)
    if not token:
        return None

    payload = decode_official_token(token)
    if not payload or payload.get("tourn") != tournament.id:
        return None

    official_id = payload.get("sub")
    if not official_id:
        return None

    # Check if this token was issued to a platform User (organizer or super admin)
    if official_id.startswith(("usr_", "user_")):
        stmt_user = select(User).where(User.id == official_id)
        res_u = await db.execute(stmt_user)
        plat_user = res_u.scalar_one_or_none()
        if plat_user and (plat_user.is_super_admin or tournament.organizer_id == plat_user.id):
            return {
                "is_organizer": True,
                "role": "Tournament Director" if tournament.organizer_id == plat_user.id else "Super Admin",
                "role_names": ["Tournament Director"] if tournament.organizer_id == plat_user.id else ["Super Admin"],
                "permissions": ALL_TABROOM_PERMISSION_CODES,
                "name": plat_user.full_name,
                "email": plat_user.email,
                "official_profile": None,
            }
        return None

    stmt = (
        select(OfficialProfile)
        .options(
            selectinload(OfficialProfile.participant),
            selectinload(OfficialProfile.roles).selectinload(Role.permissions),
        )
        .where(OfficialProfile.id == official_id)
    )
    result = await db.execute(stmt)
    official = result.scalar_one_or_none()

    if not official or not official.is_active:
        return None

    perms = official.permission_codes
    if not perms and official.role:
        perms = ALL_TABROOM_PERMISSION_CODES

    role_names = official.role_names
    display_role = ", ".join(role_names) if role_names else (official.role.value.upper() if official.role else "Official")

    return {
        "is_organizer": False,
        "role": display_role,
        "role_names": role_names,
        "permissions": perms,
        "name": official.participant.name if official.participant else "Official",
        "email": official.participant.email if official.participant else "",
        "official_profile": official,
    }


# =========================================================================
# Public Tournament Pages
# =========================================================================

async def render_tenant_home(
    request: Request,
    user: Optional[User] = None,
) -> HTMLResponse:
    """Render public tournament overview on tenant subdomain."""
    tournament = get_current_tenant_tournament(request)
    return templates.TemplateResponse(
        request=request,
        name="tenant/home.html",
        context={
            "tournament": tournament,
            "user": user,
            "page_title": f"{tournament.name} — Overview",
        },
    )


@router.get("/documents", response_class=HTMLResponse)
async def tournament_documents_page(
    request: Request,
    cat: Optional[str] = None,
    user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Render dedicated Documents & Briefings repository with dynamic existing category filters."""
    tournament = get_current_tenant_tournament(request)

    # Query all public attachments from DB to ensure fresh state
    stmt = (
        select(FileAttachment)
        .where(
            FileAttachment.tournament_id == tournament.id,
            FileAttachment.is_public == True,
        )
        .order_by(FileAttachment.display_order, FileAttachment.created_at.desc())
    )
    res = await db.execute(stmt)
    all_public = list(res.scalars().all())

    CATEGORY_META = {
        "briefing": {"label": "Briefings", "icon": "ph-users"},
        "equity": {"label": "Equity & Conduct", "icon": "ph-scales"},
        "rules": {"label": "Rules & Rubrics", "icon": "ph-gavel"},
        "schedule": {"label": "Schedules", "icon": "ph-calendar"},
        "task_material": {"label": "Task Materials", "icon": "ph-lightning"},
        "awards_breaks": {"label": "Awards & Breaks", "icon": "ph-trophy"},
        "general": {"label": "General Files", "icon": "ph-file-text"},
    }

    # Count files for each category that actually exists in DB for this tournament
    cat_counts: Dict[str, int] = {}
    for doc in all_public:
        c_val = doc.category.value if hasattr(doc.category, "value") else str(doc.category)
        cat_counts[c_val] = cat_counts.get(c_val, 0) + 1

    existing_categories = []
    for c_val, count in cat_counts.items():
        meta = CATEGORY_META.get(c_val, {"label": c_val.replace("_", " ").title(), "icon": "ph-file"})
        existing_categories.append({
            "key": c_val,
            "label": meta["label"],
            "icon": meta["icon"],
            "count": count,
        })
    existing_categories.sort(key=lambda x: x["label"])

    filtered_attachments = all_public
    if cat and cat.strip():
        clean_cat = cat.lower().strip()
        filtered_attachments = [
            a for a in all_public
            if (a.category.value if hasattr(a.category, "value") else str(a.category)) == clean_cat
        ]

    return templates.TemplateResponse(
        request=request,
        name="tenant/documents.html",
        context={
            "tournament": tournament,
            "attachments": filtered_attachments,
            "existing_categories": existing_categories,
            "all_public_count": len(all_public),
            "active_category": cat.lower().strip() if cat else None,
            "user": user,
            "page_title": f"Documents & Briefings — {tournament.name}",
        },
    )


@router.get("/tasks", response_class=HTMLResponse)
async def tournament_tasks_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render round tasks, motions, and speech prompts with attached materials."""
    tournament = get_current_tenant_tournament(request)
    task_materials = tournament.task_materials

    return templates.TemplateResponse(
        request=request,
        name="tenant/tasks.html",
        context={
            "tournament": tournament,
            "task_materials": task_materials,
            "user": user,
            "page_title": f"Tasks & Motions — {tournament.name}",
        },
    )


@router.get("/schedule", response_class=HTMLResponse)
async def tournament_schedule_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render chronological tournament timetable and round milestones."""
    tournament = get_current_tenant_tournament(request)

    return templates.TemplateResponse(
        request=request,
        name="tenant/schedule.html",
        context={
            "tournament": tournament,
            "user": user,
            "page_title": f"Schedule & Timetable — {tournament.name}",
            "grouped_timezones": get_all_timezones_grouped(),
        },
    )


@router.get("/schedule/download.ics")
async def download_schedule_ics(request: Request):
    """Generate and stream RFC 5545 iCalendar (.ics) export of tournament timetable."""
    tournament = get_current_tenant_tournament(request)
    now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Kwuo Tabulation Platform//Schedule Export//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{tournament.name} Schedule",
        f"X-WR-TIMEZONE:{tournament.timezone or 'UTC'}",
    ]

    for item in tournament.schedule_items:
        st_utc = item.start_time.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        end_utc = (item.end_time or item.start_time).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        summary = (item.title or "").replace("\n", " ").replace(",", "\\,")
        desc = (item.description or "").replace("\n", "\\n").replace(",", "\\,")
        loc = (item.location or "").replace("\n", " ").replace(",", "\\,")

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{item.id}@kwuo.com",
            f"DTSTAMP:{now_str}",
            f"DTSTART:{st_utc}",
            f"DTEND:{end_utc}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{desc}",
            f"LOCATION:{loc}",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    ics_content = "\r\n".join(lines) + "\r\n"

    filename = f"{tournament.slug}-schedule.ics"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "text/calendar; charset=utf-8",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return Response(
        content=ics_content.encode("utf-8"),
        media_type="text/calendar",
        headers=headers,
    )


async def get_tournament_institutions_with_stats(db: AsyncSession, tournament_id: str) -> List[Dict[str, Any]]:
    """Retrieve all institutions associated with a tournament, computing speaker and judge tallies."""
    # 1. Fetch institutions belonging to tournament or referenced by participants
    stmt = (
        select(Institution)
        .where(
            or_(
                Institution.tournament_id == tournament_id,
                Institution.id.in_(
                    select(Participant.institution_id)
                    .where(Participant.tournament_id == tournament_id)
                    .scalar_subquery()
                ),
                Institution.id.in_(
                    select(ParticipantInstitution.institution_id)
                    .join(Participant, ParticipantInstitution.participant_id == Participant.id)
                    .where(Participant.tournament_id == tournament_id)
                    .scalar_subquery()
                ),
            )
        )
        .order_by(Institution.name.asc())
    )
    res = await db.execute(stmt)
    institutions = res.scalars().all()

    # 2. Query participants in this tournament with their profile types and affiliations
    p_stmt = (
        select(Participant)
        .where(Participant.tournament_id == tournament_id)
        .options(
            selectinload(Participant.affiliations),
            selectinload(Participant.speaker_profile),
            selectinload(Participant.judge_profile),
        )
    )
    p_res = await db.execute(p_stmt)
    participants = p_res.scalars().all()

    # Build tally
    speakers_by_inst: Dict[str, set] = defaultdict(set)
    judges_by_inst: Dict[str, set] = defaultdict(set)
    ias_by_inst: Dict[str, set] = defaultdict(set)
    total_by_inst: Dict[str, set] = defaultdict(set)

    for p in participants:
        inst_ids = set()
        if p.institution_id:
            inst_ids.add(p.institution_id)
        for aff in p.affiliations:
            inst_ids.add(aff.institution_id)

        is_indep = bool(p.judge_profile and p.judge_profile.is_independent)

        for i_id in inst_ids:
            if p.is_speaker:
                speakers_by_inst[i_id].add(p.id)
            if p.is_judge:
                if is_indep:
                    ias_by_inst[i_id].add(p.id)
                else:
                    judges_by_inst[i_id].add(p.id)
            total_by_inst[i_id].add(p.id)

    out = []
    for inst in institutions:
        c_info = get_country_info(inst.country)
        out.append({
            "id": inst.id,
            "name": inst.name,
            "code": inst.code or "",
            "country": inst.country or "",
            "country_name": c_info["name"],
            "flag": c_info["flag"],
            "region": inst.region or "",
            "region_display": inst.region.title() if inst.region else "",
            "speakers_count": len(speakers_by_inst.get(inst.id, set())),
            "judges_count": len(judges_by_inst.get(inst.id, set())),
            "ias_count": len(ias_by_inst.get(inst.id, set())),
            "total_count": len(total_by_inst.get(inst.id, set())),
        })

    return sorted(out, key=lambda x: (-x["total_count"], x["name"].lower()))


@router.get("/institutions", response_class=HTMLResponse)
async def tournament_institutions_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Render public participating institutions directory with contingent counts."""
    tournament = get_current_tenant_tournament(request)
    institutions_list = await get_tournament_institutions_with_stats(db, tournament.id)

    return templates.TemplateResponse(
        request=request,
        name="tenant/institutions.html",
        context={
            "tournament": tournament,
            "institutions": institutions_list,
            "user": user,
            "page_title": f"Participating Institutions — {tournament.name}",
        },
    )


@router.get("/participants", response_class=HTMLResponse)
async def tournament_participants_page(
    request: Request,
    role: str = "all",
    div: Optional[str] = None,
    q: Optional[str] = None,
    user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Render public participant directory with filterable speaker and judge tabs."""
    tournament = get_current_tenant_tournament(request)

    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.judge_profile),
            selectinload(Participant.divisions),
            selectinload(Participant.institution),
        )
        .where(
            Participant.tournament_id == tournament.id,
            or_(
                Participant.speaker_profile.has(),
                Participant.judge_profile.has(),
            ),
        )
        .order_by(Participant.name.asc())
    )
    all_parts = list((await db.execute(stmt)).scalars().all())

    speakers = [p for p in all_parts if p.is_speaker]
    judges = [p for p in all_parts if p.is_judge]

    # Pre-build unified serializable list for client-side Alpine search/filtering
    participants_data = [
        {
            "id": p.id,
            "name": p.name,
            "role": "speaker" if p.is_speaker else "adj",
            "role_label": "Speaker" if p.is_speaker else "Adj",
            "is_speaker": p.is_speaker,
            "is_judge": p.is_judge,
            "pronouns": (p.speaker_profile.pronouns if p.speaker_profile else "") or "",
            "institution": p.institution.name if p.institution else "Independent",
            "divisions": [d.name for d in p.divisions],
        }
        for p in all_parts
    ]

    # Division filtering for server-side initial state
    filtered_speakers = speakers
    filtered_judges = judges
    if div:
        filtered_speakers = [s for s in speakers if any(d.name.lower() == div.lower() for d in s.divisions)]
        filtered_judges = [j for j in judges if any(d.name.lower() == div.lower() for d in j.divisions)]

    # Search query filtering for server-side initial state
    if q and q.strip():
        query = q.strip().lower()
        filtered_speakers = [s for s in filtered_speakers if query in s.name.lower() or query in (s.institution.name.lower() if s.institution else "independent")]
        filtered_judges = [j for j in filtered_judges if query in j.name.lower() or query in (j.institution.name.lower() if j.institution else "independent")]

    return templates.TemplateResponse(
        request=request,
        name="tenant/participants.html",
        context={
            "tournament": tournament,
            "all_participants": all_parts,
            "participants_data": participants_data,
            "speakers": filtered_speakers,
            "judges": filtered_judges,
            "total_speakers_count": len(speakers),
            "total_judges_count": len(judges),
            "active_role": role,
            "active_division": div,
            "search_query": q or "",
            "divisions": tournament.divisions,
            "user": user,
            "page_title": f"Participants — {tournament.name}",
        },
    )


@router.get("/participants/{participant_id}", response_class=HTMLResponse)
async def tournament_participant_detail_page(
    participant_id: str,
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Render public profile and record for an individual participant."""
    tournament = get_current_tenant_tournament(request)
    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.judge_profile),
            selectinload(Participant.divisions),
            selectinload(Participant.institution),
            selectinload(Participant.affiliations).selectinload(ParticipantInstitution.institution),
        )
        .where(
            Participant.id == participant_id,
            Participant.tournament_id == tournament.id,
        )
    )
    participant = (await db.execute(stmt)).scalar_one_or_none()
    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found.")

    return templates.TemplateResponse(
        request=request,
        name="tenant/participant_detail.html",
        context={
            "tournament": tournament,
            "participant": participant,
            "speaker": participant.speaker_profile,
            "judge": participant.judge_profile,
            "user": user,
            "page_title": f"{participant.name} — {tournament.name}",
        },
    )


@router.get("/rankings", response_class=HTMLResponse)
async def tournament_rankings_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render tournament leaderboard, break line thresholds, and cumulative standings."""
    tournament = get_current_tenant_tournament(request)

    return templates.TemplateResponse(
        request=request,
        name="tenant/rankings.html",
        context={
            "tournament": tournament,
            "user": user,
            "page_title": f"Rankings & Standings — {tournament.name}",
        },
    )


@router.get("/current-round", response_class=HTMLResponse)
async def tournament_current_round_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render live in-progress round information, pairings, and motion prompts."""
    tournament = get_current_tenant_tournament(request)

    return templates.TemplateResponse(
        request=request,
        name="tenant/current_round.html",
        context={
            "tournament": tournament,
            "user": user,
            "page_title": f"Current Round — {tournament.name}",
        },
    )


@router.get("/results", response_class=HTMLResponse)
async def tournament_results_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render released round results, ballots, breaks, and final podium awards."""
    tournament = get_current_tenant_tournament(request)

    return templates.TemplateResponse(
        request=request,
        name="tenant/results.html",
        context={
            "tournament": tournament,
            "user": user,
            "page_title": f"Results & Awards — {tournament.name}",
        },
    )


# =========================================================================
# Public Competitor Self-Registration (/register)
# =========================================================================

@router.get("/register", response_class=HTMLResponse)
async def competitor_register_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render the public self-registration page for competitors."""
    tournament = get_current_tenant_tournament(request)
    if tournament.status != TournamentStatus.REGISTRATION:
        return templates.TemplateResponse(
            request=request,
            name="tenant/register.html",
            context={
                "tournament": tournament,
                "user": user,
                "registration_closed": True,
                "divisions": [],
                "institutions": [],
                "page_title": f"Registration Closed — {tournament.name}",
            },
        )

    # Fetch available divisions and institutions
    divisions_stmt = select(Division).where(Division.tournament_id == tournament.id).order_by(Division.name)
    divs_res = await db.execute(divisions_stmt)
    divisions = divs_res.scalars().all()

    institutions_stmt = select(Institution).where(Institution.tournament_id == tournament.id).order_by(Institution.name)
    insts_res = await db.execute(institutions_stmt)
    institutions = insts_res.scalars().all()

    msg = request.query_params.get("msg")
    error = request.query_params.get("error")

    return templates.TemplateResponse(
        request=request,
        name="tenant/register.html",
        context={
            "tournament": tournament,
            "user": user,
            "registration_closed": False,
            "divisions": divisions,
            "institutions": institutions,
            "msg": msg,
            "error": error,
            "page_title": f"Register as a Competitor — {tournament.name}",
        },
    )


@router.post("/register", response_class=HTMLResponse)
async def competitor_register_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    registration_role: str = Form("speaker"),
    name: str = Form(...),
    email: str = Form(...),
    phone_number: Optional[str] = Form(None),
    pronouns: Optional[str] = Form(None),
    division_ids: List[str] = Form([]),
    institution_id: Optional[str] = Form(None),
    new_institution_name: Optional[str] = Form(None),
    new_institution_code: Optional[str] = Form(None),
    new_institution_country: Optional[str] = Form(None),
    is_independent: bool = Form(False),
    secondary_affiliations_json: Optional[str] = Form(None),
):
    """Process public participant self-registration (speaker or judge) and issue magic link URL."""
    import json
    tournament = get_current_tenant_tournament(request)
    if tournament.status != TournamentStatus.REGISTRATION:
        raise HTTPException(status_code=400, detail="Registration is only open when the tournament is in the registration phase.")

    clean_name = name.strip()
    clean_email = email.strip().lower()
    clean_phone = phone_number.strip() if phone_number and phone_number.strip() else None
    clean_pronouns = pronouns.strip() if pronouns and pronouns.strip() else None
    is_judge_reg = (registration_role == "judge")

    if not clean_name:
        raise HTTPException(status_code=400, detail="Full name is required.")
    if not clean_email or "@" not in clean_email:
        raise HTTPException(status_code=400, detail="A valid email address is required.")

    # Check if participant is already registered in this tournament
    existing_stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.judge_profile),
            selectinload(Participant.divisions),
            selectinload(Participant.institution),
            selectinload(Participant.affiliations).selectinload(ParticipantInstitution.institution),
        )
        .where(
            Participant.tournament_id == tournament.id,
            Participant.email == clean_email,
        )
    )
    existing_part = (await db.execute(existing_stmt)).scalar_one_or_none()

    if existing_part:
        # If already registered, generate or issue token
        raw_token, token_hash = Participant.generate_token()
        existing_part.access_token_hash = token_hash
        existing_part.access_token_expires_at = None
        if clean_phone and not existing_part.phone_number:
            existing_part.phone_number = clean_phone
        if clean_pronouns and existing_part.speaker_profile and not existing_part.speaker_profile.pronouns:
            existing_part.speaker_profile.pronouns = clean_pronouns
        await db.commit()

        # Re-fetch with eager loaded relationships
        re_stmt = (
            select(Participant)
            .options(
                selectinload(Participant.speaker_profile),
                selectinload(Participant.judge_profile),
                selectinload(Participant.divisions),
                selectinload(Participant.institution),
                selectinload(Participant.affiliations).selectinload(ParticipantInstitution.institution),
            )
            .where(Participant.id == existing_part.id)
        )
        existing_part = (await db.execute(re_stmt)).scalar_one()

        magic_prefix = "j" if existing_part.is_judge else "s"
        magic_url = f"/{magic_prefix}/{raw_token}/me"

        # Dispatch magic link email asynchronously
        try:
            full_magic_url = f"{str(request.base_url).rstrip('/')}{magic_url}"
            await send_magic_link_email(
                to_email=existing_part.email,
                name=existing_part.name,
                magic_url=full_magic_url,
                tournament_name=tournament.name,
            )
        except Exception:
            pass

        return templates.TemplateResponse(
            request=request,
            name="tenant/register_success.html",
            context={
                "tournament": tournament,
                "participant": existing_part,
                "speaker": existing_part.speaker_profile,
                "judge": existing_part.judge_profile,
                "divisions": existing_part.divisions,
                "institution": existing_part.institution,
                "raw_token": raw_token,
                "magic_url": magic_url,
                "already_registered": True,
                "page_title": f"Registration Confirmed — {existing_part.name}",
            },
        )

    # Resolve or create primary institution
    resolved_institution: Optional[Institution] = None
    if institution_id == "new" or (not institution_id and new_institution_name):
        if new_institution_name and new_institution_name.strip():
            raw_inst_name = new_institution_name.strip()
            norm_name = normalize_institution_name(raw_inst_name)
            inst_check = await db.scalar(
                select(Institution).where(
                    Institution.tournament_id == tournament.id,
                    Institution.name_normalized == norm_name,
                )
            )
            if inst_check:
                resolved_institution = inst_check
            else:
                resolved_institution = Institution(
                    tournament_id=tournament.id,
                    name=raw_inst_name,
                    name_normalized=norm_name,
                    code=(new_institution_code.strip() if new_institution_code and new_institution_code.strip() else None),
                    country=(new_institution_country.strip() if new_institution_country and new_institution_country.strip() else None),
                )
                db.add(resolved_institution)
                await db.flush()
    elif institution_id and institution_id != "none":
        inst_check = await db.scalar(
            select(Institution).where(
                Institution.tournament_id == tournament.id,
                Institution.id == institution_id,
            )
        )
        if inst_check:
            resolved_institution = inst_check

    # Generate permanent zero-auth magic token
    raw_token, token_hash = Participant.generate_token()

    # Bind selected divisions
    selected_divisions: List[Division] = []
    if division_ids:
        divs_stmt = select(Division).where(
            Division.tournament_id == tournament.id,
            Division.id.in_(division_ids),
        )
        selected_divisions = list((await db.scalars(divs_stmt)).all())

    # Create participant record
    participant = Participant(
        tournament_id=tournament.id,
        name=clean_name,
        email=clean_email,
        phone_number=clean_phone,
        institution_id=resolved_institution.id if resolved_institution else None,
        status=ParticipantStatus.REGISTERED,
        access_token_hash=token_hash,
        access_token_expires_at=None,
        divisions=selected_divisions,
    )
    db.add(participant)
    await db.flush()

    if is_judge_reg:
        # Create judge profile
        judge_profile = JudgeProfile(
            participant_id=participant.id,
            is_independent=is_independent or (resolved_institution is None),
            is_chair_eligible=False,
            is_reserve=False,
            test_score=0.0,
            cv_score=0.0,
        )
        participant.judge_profile = judge_profile
        db.add(judge_profile)

        # Primary institution affiliation (if representing a school)
        if resolved_institution:
            aff = ParticipantInstitution(
                participant_id=participant.id,
                institution_id=resolved_institution.id,
                is_primary=True,
                tie_type="represents",
                clash_type="institution",
                clash_policy="hard",
            )
            db.add(aff)

        # Secondary institutional clash affiliations
        if secondary_affiliations_json:
            try:
                sec_items = json.loads(secondary_affiliations_json)
                if isinstance(sec_items, list):
                    for item in sec_items:
                        sec_inst_id = (item.get("institution_id") or "").strip()
                        sec_tie = (item.get("tie_type") or "alumnus").strip().lower()
                        if sec_inst_id and (resolved_institution is None or sec_inst_id != resolved_institution.id):
                            sec_aff = ParticipantInstitution(
                                participant_id=participant.id,
                                institution_id=sec_inst_id,
                                is_primary=False,
                                tie_type=sec_tie,
                                clash_type=sec_tie,
                                clash_policy="hard",
                            )
                            db.add(sec_aff)
            except Exception:
                pass
    else:
        # Create speaker profile
        speaker_profile = SpeakerProfile(
            participant_id=participant.id,
            pronouns=clean_pronouns,
        )
        participant.speaker_profile = speaker_profile
        db.add(speaker_profile)

        # Bind primary institution affiliation
        if resolved_institution:
            aff = ParticipantInstitution(
                participant_id=participant.id,
                institution_id=resolved_institution.id,
                is_primary=True,
                tie_type="represents",
                clash_type="institution",
                clash_policy="hard",
            )
            db.add(aff)

    await db.commit()

    # Re-fetch participant with eager loaded relationships
    re_stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.judge_profile),
            selectinload(Participant.divisions),
            selectinload(Participant.institution),
            selectinload(Participant.affiliations).selectinload(ParticipantInstitution.institution),
        )
        .where(Participant.id == participant.id)
    )
    participant = (await db.execute(re_stmt)).scalar_one()

    magic_prefix = "j" if is_judge_reg else "s"
    magic_url = f"/{magic_prefix}/{raw_token}/me"

    # Dispatch magic link email asynchronously
    try:
        full_magic_url = f"{str(request.base_url).rstrip('/')}{magic_url}"
        await send_magic_link_email(
            to_email=participant.email,
            name=participant.name,
            magic_url=full_magic_url,
            tournament_name=tournament.name,
        )
    except Exception:
        pass

    return templates.TemplateResponse(
        request=request,
        name="tenant/register_success.html",
        context={
            "tournament": tournament,
            "participant": participant,
            "speaker": participant.speaker_profile,
            "judge": participant.judge_profile,
            "divisions": participant.divisions,
            "institution": participant.institution,
            "raw_token": raw_token,
            "magic_url": magic_url,
            "already_registered": False,
            "page_title": f"Registration Confirmed — {participant.name}",
        },
    )


# =========================================================================
# Zero-Auth Magic URLs (Speakers & Judges)
# =========================================================================

@router.get("/s/{token}/me")
async def speaker_magic_url(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Zero-auth entrypoint for a competitor via their personal magic token."""
    tournament = get_current_tenant_tournament(request)
    token_hash = Participant.hash_token(token)

    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.judge_profile),
        )
        .where(
            Participant.tournament_id == tournament.id,
            Participant.access_token_hash == token_hash,
        )
    )
    result = await db.execute(stmt)
    participant = result.scalar_one_or_none()

    if not participant:
        return templates.TemplateResponse(
            request=request,
            name="tenant/token_required.html",
            context={
                "tournament": tournament,
                "message": "Invalid or revoked competitor magic link. Please check the URL or contact tournament staff.",
            },
            status_code=403,
        )

    # Update last accessed timestamp
    participant.last_accessed_at = datetime.now(timezone.utc)
    await db.commit()

    # Issue participant session token
    session_jwt = create_participant_token(
        participant_id=participant.id,
        tournament_id=tournament.id,
        role="speaker",
    )

    response = RedirectResponse(url="/portal/speaker", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=f"kwuo_part_{tournament.id}",
        value=session_jwt,
        httponly=True,
        samesite="lax",
        max_age=30 * 86400,
    )
    return response


@router.get("/j/{token}/me")
async def judge_magic_url(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Zero-auth entrypoint for an adjudicator via their personal magic token."""
    tournament = get_current_tenant_tournament(request)
    token_hash = Participant.hash_token(token)

    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.judge_profile),
        )
        .where(
            Participant.tournament_id == tournament.id,
            Participant.access_token_hash == token_hash,
        )
    )
    result = await db.execute(stmt)
    participant = result.scalar_one_or_none()

    if not participant:
        return templates.TemplateResponse(
            request=request,
            name="tenant/token_required.html",
            context={
                "tournament": tournament,
                "message": "Invalid or revoked adjudicator magic link. Please check the URL or contact tournament staff.",
            },
            status_code=403,
        )

    participant.last_accessed_at = datetime.now(timezone.utc)
    await db.commit()

    session_jwt = create_participant_token(
        participant_id=participant.id,
        tournament_id=tournament.id,
        role="judge",
    )

    response = RedirectResponse(url="/portal/judge", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=f"kwuo_part_{tournament.id}",
        value=session_jwt,
        httponly=True,
        samesite="lax",
        max_age=30 * 86400,
    )
    return response


@router.get("/m/{token}/me")
async def generic_magic_url(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Generic magic URL dispatcher that inspects participant profiles."""
    tournament = get_current_tenant_tournament(request)
    token_hash = Participant.hash_token(token)

    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.judge_profile),
        )
        .where(
            Participant.tournament_id == tournament.id,
            Participant.access_token_hash == token_hash,
        )
    )
    result = await db.execute(stmt)
    participant = result.scalar_one_or_none()

    if not participant:
        return templates.TemplateResponse(
            request=request,
            name="tenant/token_required.html",
            context={
                "tournament": tournament,
                "message": "Invalid or revoked personal magic link.",
            },
            status_code=403,
        )

    if participant.is_judge:
        return RedirectResponse(url=f"/j/{token}/me", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return RedirectResponse(url=f"/s/{token}/me", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/portal/speaker", response_class=HTMLResponse)
async def competitor_portal(
    request: Request,
    participant: Optional[Participant] = Depends(get_current_participant),
):
    """Scoped competitor personal portal."""
    tournament = get_current_tenant_tournament(request)
    if not participant or not participant.is_speaker:
        return templates.TemplateResponse(
            request=request,
            name="tenant/token_required.html",
            context={
                "tournament": tournament,
                "role_target": "competitor",
                "message": "To view your speaking assignments and ballots, please access this portal via your personal magic link.",
            },
            status_code=401,
        )

    msg = request.query_params.get("msg")
    return templates.TemplateResponse(
        request=request,
        name="tenant/portal_speaker.html",
        context={
            "tournament": tournament,
            "participant": participant,
            "speaker": participant.speaker_profile,
            "msg": msg,
            "page_title": f"Competitor Portal — {participant.name}",
        },
    )


@router.get("/portal/judge", response_class=HTMLResponse)
async def judge_portal(
    request: Request,
    participant: Optional[Participant] = Depends(get_current_participant),
):
    """Scoped adjudicator personal portal."""
    tournament = get_current_tenant_tournament(request)
    if not participant or not participant.is_judge:
        return templates.TemplateResponse(
            request=request,
            name="tenant/token_required.html",
            context={
                "tournament": tournament,
                "role_target": "adjudicator",
                "message": "To view your judging allocations and submit ballots, please access this portal via your personal ballot link.",
            },
            status_code=401,
        )

    msg = request.query_params.get("msg")
    return templates.TemplateResponse(
        request=request,
        name="tenant/portal_judge.html",
        context={
            "tournament": tournament,
            "participant": participant,
            "judge": participant.judge_profile,
            "msg": msg,
            "page_title": f"Adjudicator Portal — {participant.name}",
        },
    )


@router.post("/portal/check-in", response_class=HTMLResponse)
async def participant_self_checkin(
    request: Request,
    participant: Optional[Participant] = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
):
    """Self-service check-in action via magic session."""
    tournament = get_current_tenant_tournament(request)
    if not participant:
        raise HTTPException(status_code=401, detail="Valid magic session required for check-in.")

    participant.status = ParticipantStatus.CHECKED_IN
    participant.checked_in_at = datetime.now(timezone.utc)
    await db.commit()

    dest = "/portal/judge" if participant.is_judge else "/portal/speaker"
    return RedirectResponse(
        url=f"{dest}?msg=Check-in+successful!+You+are+marked+present.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# =========================================================================
# Officials Password Authentication & Tab Room Control Center
# =========================================================================

@router.get("/admin/login", response_class=HTMLResponse)
async def official_login_page(
    request: Request,
    official_ctx: Optional[Dict[str, Any]] = Depends(get_current_official_context),
):
    """Render tournament official login page."""
    tournament = get_current_tenant_tournament(request)
    if official_ctx:
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

    error = request.query_params.get("error")
    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/login.html",
        context={
            "tournament": tournament,
            "error": error,
            "page_title": f"Official Sign In — {tournament.name}",
        },
    )


@router.post("/admin/login", response_class=HTMLResponse)
async def official_login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Authenticate tournament official via password."""
    tournament = get_current_tenant_tournament(request)
    clean_email = email.strip().lower()

    # 1. Lookup Participant with OfficialProfile for this tournament
    stmt = (
        select(Participant)
        .options(selectinload(Participant.official_profile))
        .where(
            Participant.tournament_id == tournament.id,
            Participant.email == clean_email,
        )
    )
    result = await db.execute(stmt)
    participant = result.scalar_one_or_none()

    if participant and participant.official_profile:
        official = participant.official_profile
        if official.is_active and official.verify_password(password):
            official.last_login_at = datetime.now(timezone.utc)
            await db.commit()

            token = create_official_token(
                official_id=official.id,
                participant_id=participant.id,
                tournament_id=tournament.id,
                role=official.role.value if official.role else "official",
            )
            response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
            response.set_cookie(
                key=f"kwuo_off_{tournament.id}",
                value=token,
                httponly=True,
                samesite="lax",
                max_age=7 * 86400,
            )
            return response

    # 2. Check if credentials belong to platform User (e.g. Organizer or Super Admin)
    stmt_user = select(User).where(User.email == clean_email)
    res_user = await db.execute(stmt_user)
    platform_user = res_user.scalar_one_or_none()

    if platform_user and verify_plain_password(password, platform_user.password_hash):
        if platform_user.is_super_admin or tournament.organizer_id == platform_user.id:
            token = create_official_token(
                official_id=platform_user.id,
                participant_id=platform_user.id,
                tournament_id=tournament.id,
                role="director" if tournament.organizer_id == platform_user.id else "admin",
            )
            response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
            response.set_cookie(
                key=f"kwuo_off_{tournament.id}",
                value=token,
                httponly=True,
                samesite="lax",
                max_age=7 * 86400,
            )
            return response

    # Failed authentication
    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/login.html",
        context={
            "tournament": tournament,
            "error": "Invalid official credentials. Please check your email and password.",
            "email": clean_email,
            "page_title": f"Official Sign In — {tournament.name}",
        },
        status_code=401,
    )


@router.post("/admin/logout")
async def official_logout(request: Request):
    """Clear official session and redirect to login."""
    tournament = get_current_tenant_tournament(request)
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key=f"kwuo_off_{tournament.id}")
    return response


async def tournament_admin_dashboard(
    request: Request,
    official_ctx: Optional[Dict[str, Any]] = None,
) -> HTMLResponse:
    """Render Tournament Tab Room & Control Center."""
    tournament = get_current_tenant_tournament(request)
    if official_ctx is None:
        import kwuo.core.database as db_core
        from kwuo.core.rbac import get_optional_current_user
        async with db_core.async_session_factory() as session:
            current_user = await get_optional_current_user(request, session)
            official_ctx = await get_current_official_context(request, session, current_user)

    if not official_ctx:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/index.html",
        context={
            "tournament": tournament,
            "official": official_ctx,
            "page_title": f"Tab Room Control Center — {tournament.name}",
        },
    )


# =========================================================================
# Tab Room Side Drawer: Phase 1 — ORGANIZATION Modules
# =========================================================================

async def require_tenant_official(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
) -> Dict[str, Any]:
    """Ensure caller is an authenticated tournament official or super admin."""
    official = await get_current_official_context(request, db, user)
    if not official:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/admin/login"},
        )
    return official


def require_permission(permission_code: str):
    """Factory dependency guarding route access by specific RBAC permission."""
    async def _dependency(official: Dict[str, Any] = Depends(require_tenant_official)) -> Dict[str, Any]:
        if official.get("is_organizer"):
            return official
        perms = official.get("permissions", set())
        if permission_code in perms or "*" in perms:
            return official
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: You require the '{permission_code}' permission to access this section.",
        )
    return _dependency


# 1. Tournament Settings
@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings_page(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("settings:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Render Tab Room tournament settings form."""
    tournament = get_current_tenant_tournament(request)
    msg = request.query_params.get("msg")
    error = request.query_params.get("error")

    # Fetch fresh divisions with participants for accurate competitor and judge headcounts
    div_stmt = (
        select(Division)
        .options(
            selectinload(Division.participants).selectinload(Participant.speaker_profile),
            selectinload(Division.participants).selectinload(Participant.judge_profile),
        )
        .where(Division.tournament_id == tournament.id)
        .order_by(Division.name.asc())
    )
    divisions = list((await db.execute(div_stmt)).scalars().all())

    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/settings.html",
        context={
            "tournament": tournament,
            "divisions": divisions,
            "official": official,
            "msg": msg,
            "error": error,
            "link_presets": LINK_PRESETS,
            "page_title": f"Settings — {tournament.name}",
            "grouped_timezones": get_all_timezones_grouped(),
        },
    )


@router.post("/admin/settings")
async def admin_settings_save(
    request: Request,
    name: str = Form(...),
    location_type: str = Form(...),
    status_val: str = Form(..., alias="status"),
    ghost_round_limit: int = Form(2),
    location: Optional[str] = Form(None),
    start_date: Optional[str] = Form(None),
    end_date: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    active_tab: Optional[str] = Form("base"),
    # Rules & Config parameters (when submitted from the consolidated rules tab)
    ballot_mode: Optional[str] = Form(None),
    draw_method: Optional[str] = Form(None),
    min_room_size: Optional[int] = Form(None),
    max_room_size: Optional[int] = Form(None),
    room_size_preference: Optional[str] = Form(None),
    panel_size: Optional[int] = Form(None),
    minimum_panel_size: Optional[int] = Form(None),
    allow_prelim_ties: bool = Form(False),
    # Judge scoring weights ratio
    judge_weight_test: Optional[float] = Form(None),
    judge_weight_cv: Optional[float] = Form(None),
    judge_weight_feedback: Optional[float] = Form(None),
    official: Dict[str, Any] = Depends(require_permission("settings:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Save updated tournament parameters and rules."""
    tenant_tourn = get_current_tenant_tournament(request)
    stmt = select(Tournament).where(Tournament.id == tenant_tourn.id)
    res = await db.execute(stmt)
    tournament = res.scalar_one()

    tournament.name = name.strip()
    tournament.location_type = LocationType(location_type)
    tournament.status = TournamentStatus(status_val)
    tournament.ghost_round_limit = max(1, int(ghost_round_limit))
    tournament.location = location.strip() if location else None
    tournament.description = description.strip() if description else None

    if start_date:
        try:
            tournament.start_date = datetime.strptime(start_date.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if end_date:
        try:
            tournament.end_date = datetime.strptime(end_date.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # Update rules if provided from form
    if ballot_mode:
        tournament.ballot_mode = BallotMode(ballot_mode)
    if draw_method:
        tournament.draw_method = DrawMethod(draw_method)
    if min_room_size is not None:
        tournament.min_room_size = int(min_room_size)
    if max_room_size is not None:
        tournament.max_room_size = int(max_room_size)
    if room_size_preference:
        tournament.room_size_preference = RoomSizePreference(room_size_preference)
    if panel_size is not None:
        tournament.panel_size = int(panel_size)
    if minimum_panel_size is not None:
        tournament.minimum_panel_size = int(minimum_panel_size)
    tournament.allow_prelim_ties = allow_prelim_ties

    if judge_weight_test is not None:
        tournament.judge_weight_test = max(0.0, float(judge_weight_test))
    if judge_weight_cv is not None:
        tournament.judge_weight_cv = max(0.0, float(judge_weight_cv))
    if judge_weight_feedback is not None:
        tournament.judge_weight_feedback = max(0.0, float(judge_weight_feedback))

    await db.commit()
    target_tab = active_tab or "setup"
    if target_tab == "base":
        target_tab = "setup"
    elif target_tab == "rules":
        target_tab = "config"
    return RedirectResponse(
        url=f"/admin/settings?tab={target_tab}&msg=Tournament+settings+saved+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _parse_flexible_schedule_datetime(val: str, tourn_tz: Any) -> Optional[datetime]:
    """Parse ISO or 12-hour AM/PM datetime string and associate with tournament timezone."""
    if not val or not val.strip():
        return None
    cleaned = val.strip()

    # 1. Try standard ISO
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tourn_tz)
        return dt.astimezone(tourn_tz)
    except Exception:
        pass

    # 2. Try 12-hour AM/PM string formats
    formats = [
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %I:%M:%S %p",
        "%Y-%m-%dT%I:%M %p",
        "%Y-%m-%d %I %p",
        "%m/%d/%Y %I:%M %p",
        "%d/%m/%Y %I:%M %p",
        "%B %d, %Y %I:%M %p",
        "%b %d, %Y %I:%M %p",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.replace(tzinfo=tourn_tz)
        except Exception:
            continue

    return None


@router.post("/admin/settings/schedule")
async def admin_settings_add_schedule_item(
    request: Request,
    title: str = Form(...),
    start_time: str = Form(...),
    end_time: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    display_order: int = Form(1),
    official: Dict[str, Any] = Depends(require_permission("settings:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Add a new scheduled round or milestone to tournament timetable."""
    tournament = get_current_tenant_tournament(request)
    tourn_tz_name = getattr(tournament, "timezone", None) or "UTC"
    try:
        tourn_tz = ZoneInfo(tourn_tz_name)
    except Exception:
        tourn_tz = timezone.utc

    st_dt = _parse_flexible_schedule_datetime(start_time, tourn_tz)
    if not st_dt:
        st_dt = datetime.now(tourn_tz)

    end_dt = _parse_flexible_schedule_datetime(end_time, tourn_tz) if end_time else None

    item = ScheduleItem(
        tournament_id=tournament.id,
        title=title.strip(),
        start_time=st_dt,
        end_time=end_dt,
        location=location.strip() if location else None,
        description=description.strip() if description else None,
        display_order=display_order,
        is_published=True,
    )
    db.add(item)
    await db.commit()
    return RedirectResponse(
        url="/admin/settings?tab=schedule&msg=Schedule+milestone+added.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/settings/schedule/timezone")
async def admin_settings_update_schedule_timezone(
    request: Request,
    schedule_timezone: str = Form(...),
    official: Dict[str, Any] = Depends(require_permission("settings:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Update tournament master schedule timezone."""
    tournament = get_current_tenant_tournament(request)
    tz_str = schedule_timezone.strip()
    try:
        ZoneInfo(tz_str)
    except Exception:
        tz_str = "UTC"

    tournament.timezone = tz_str
    db.add(tournament)
    await db.commit()
    return RedirectResponse(
        url=f"/admin/settings?tab=schedule&msg=Tournament+schedule+timezone+set+to+{tz_str}.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/settings/schedule/{item_id}/delete")
async def admin_settings_delete_schedule_item(
    item_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("settings:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a schedule milestone."""
    tournament = get_current_tenant_tournament(request)
    stmt = select(ScheduleItem).where(
        ScheduleItem.id == item_id,
        ScheduleItem.tournament_id == tournament.id,
    )
    res = await db.execute(stmt)
    item = res.scalar_one_or_none()
    if item:
        await db.delete(item)
        await db.commit()
    return RedirectResponse(
        url="/admin/settings?tab=schedule&msg=Milestone+deleted.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/settings/links")
async def admin_settings_save_link(
    request: Request,
    label: str = Form(...),
    url: str = Form(...),
    preset: str = Form("custom"),
    link_id: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    is_public: bool = Form(True),
    official: Dict[str, Any] = Depends(require_permission("settings:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a tournament communication or external link."""
    tenant_tourn = get_current_tenant_tournament(request)
    stmt = select(Tournament).where(Tournament.id == tenant_tourn.id)
    res = await db.execute(stmt)
    tournament = res.scalar_one()

    clean_label = label.strip()
    clean_url = url.strip()
    if not clean_url:
        return RedirectResponse(
            url="/admin/settings?tab=links&error=URL+is+required.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # Auto-prepend https:// if protocol is omitted
    if not (
        clean_url.startswith("http://")
        or clean_url.startswith("https://")
        or clean_url.startswith("mailto:")
        or clean_url.startswith("tel:")
    ):
        clean_url = f"https://{clean_url}"

    clean_preset = preset.strip().lower()
    if clean_preset not in LINK_PRESETS:
        clean_preset = "custom"

    current_links = list(tournament.links or [])
    if link_id and link_id.strip():
        target_id = link_id.strip()
        updated = False
        for item in current_links:
            if item.get("id") == target_id:
                item["label"] = clean_label
                item["url"] = clean_url
                item["preset"] = clean_preset
                item["description"] = description.strip() if description else ""
                item["is_public"] = is_public
                updated = True
                break
        if not updated:
            current_links.append({
                "id": target_id,
                "label": clean_label,
                "url": clean_url,
                "preset": clean_preset,
                "description": description.strip() if description else "",
                "is_public": is_public,
            })
    else:
        new_id = f"link_{secrets.token_hex(6)}"
        current_links.append({
            "id": new_id,
            "label": clean_label,
            "url": clean_url,
            "preset": clean_preset,
            "description": description.strip() if description else "",
            "is_public": is_public,
        })

    tournament.links = current_links
    flag_modified(tournament, "links")
    await db.commit()

    return RedirectResponse(
        url="/admin/settings?tab=links&msg=Tournament+link+saved+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/settings/links/{link_id}/delete")
async def admin_settings_delete_link(
    link_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("settings:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a tournament communication or external link."""
    tenant_tourn = get_current_tenant_tournament(request)
    stmt = select(Tournament).where(Tournament.id == tenant_tourn.id)
    res = await db.execute(stmt)
    tournament = res.scalar_one()

    current_links = [item for item in (tournament.links or []) if item.get("id") != link_id]
    tournament.links = current_links
    flag_modified(tournament, "links")
    await db.commit()

    return RedirectResponse(
        url="/admin/settings?tab=links&msg=Link+deleted+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/settings/divisions")
async def admin_settings_create_division(
    request: Request,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    official: Dict[str, Any] = Depends(require_permission("settings:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new competitive division for the tournament."""
    tournament = get_current_tenant_tournament(request)
    clean_name = name.strip()
    clean_desc = description.strip() if description and description.strip() else None

    if not clean_name:
        return RedirectResponse(
            url="/admin/settings?tab=config&error=Division+name+is+required.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # Check for duplicate division name (case-insensitive) in this tournament
    stmt = select(Division).where(
        Division.tournament_id == tournament.id,
        func.lower(Division.name) == clean_name.lower(),
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return RedirectResponse(
            url=f"/admin/settings?tab=config&error=Division+'{clean_name}'+already+exists.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    new_division = Division(
        tournament_id=tournament.id,
        name=clean_name,
        description=clean_desc,
    )
    db.add(new_division)
    await db.commit()

    return RedirectResponse(
        url=f"/admin/settings?tab=config&msg=Division+'{clean_name}'+created+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/settings/divisions/update")
@router.post("/admin/settings/divisions/{division_id}")
async def admin_settings_update_division(
    request: Request,
    division_id: Optional[str] = None,
    division_id_form: Optional[str] = Form(None, alias="division_id"),
    name: str = Form(...),
    description: Optional[str] = Form(None),
    official: Dict[str, Any] = Depends(require_permission("settings:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing competitive division."""
    target_id = division_id or division_id_form
    if not target_id:
        return RedirectResponse(
            url="/admin/settings?tab=config&error=Division+ID+is+required.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    tournament = get_current_tenant_tournament(request)
    clean_name = name.strip()
    clean_desc = description.strip() if description and description.strip() else None

    if not clean_name:
        return RedirectResponse(
            url="/admin/settings?tab=config&error=Division+name+is+required.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    stmt = select(Division).where(
        Division.id == target_id,
        Division.tournament_id == tournament.id,
    )
    div_obj = (await db.execute(stmt)).scalar_one_or_none()
    if not div_obj:
        return RedirectResponse(
            url="/admin/settings?tab=config&error=Division+not+found.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # Check duplicate name with another division
    dup_stmt = select(Division).where(
        Division.tournament_id == tournament.id,
        Division.id != target_id,
        func.lower(Division.name) == clean_name.lower(),
    )
    dup = (await db.execute(dup_stmt)).scalar_one_or_none()
    if dup:
        return RedirectResponse(
            url=f"/admin/settings?tab=config&error=Another+division+is+already+named+'{clean_name}'.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    div_obj.name = clean_name
    div_obj.description = clean_desc
    await db.commit()

    return RedirectResponse(
        url=f"/admin/settings?tab=config&msg=Division+'{clean_name}'+updated+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/settings/divisions/delete")
@router.post("/admin/settings/divisions/{division_id}/delete")
async def admin_settings_delete_division(
    request: Request,
    division_id: Optional[str] = None,
    division_id_form: Optional[str] = Form(None, alias="division_id"),
    official: Dict[str, Any] = Depends(require_permission("settings:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a competitive division from the tournament."""
    target_id = division_id or division_id_form
    if not target_id:
        try:
            form = await request.form()
            target_id = form.get("division_id")
        except Exception:
            pass
    if not target_id:
        try:
            body = await request.json()
            target_id = body.get("division_id")
        except Exception:
            pass

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("accept", "")

    if not target_id:
        if is_ajax:
            return JSONResponse({"status": "error", "message": "Division ID is required."}, status_code=400)
        return RedirectResponse(
            url="/admin/settings?tab=config&error=Division+ID+is+required.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    tournament = get_current_tenant_tournament(request)

    stmt = (
        select(Division)
        .options(selectinload(Division.participants))
        .where(
            Division.id == target_id,
            Division.tournament_id == tournament.id,
        )
    )
    div_obj = (await db.execute(stmt)).scalar_one_or_none()
    if not div_obj:
        if is_ajax:
            return JSONResponse({"status": "error", "message": "Division not found."}, status_code=404)
        return RedirectResponse(
            url="/admin/settings?tab=config&error=Division+not+found.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    div_name = div_obj.name
    # Explicitly clear association records from participant_divisions
    await db.execute(delete(participant_divisions).where(participant_divisions.c.division_id == div_obj.id))
    await db.delete(div_obj)
    await db.commit()

    if is_ajax:
        return JSONResponse({"status": "ok", "message": f"Division '{div_name}' deleted successfully."})

    return RedirectResponse(
        url=f"/admin/settings?tab=config&msg=Division+'{div_name}'+deleted+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# 2. Documents & Files
@router.get("/admin/documents", response_class=HTMLResponse)
async def admin_documents_page(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("documents:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Render Tab Room documents management repository."""
    tournament = get_current_tenant_tournament(request)
    msg = request.query_params.get("msg")
    error = request.query_params.get("error")

    stmt = (
        select(FileAttachment)
        .where(FileAttachment.tournament_id == tournament.id)
        .order_by(FileAttachment.display_order, FileAttachment.created_at.desc())
    )
    res = await db.execute(stmt)
    attachments = list(res.scalars().all())

    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/documents.html",
        context={
            "tournament": tournament,
            "attachments": attachments,
            "official": official,
            "msg": msg,
            "error": error,
            "page_title": f"Documents & Files — {tournament.name}",
        },
    )


@router.post("/admin/documents/upload", response_class=HTMLResponse)
async def admin_documents_upload(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(...),
    category: str = Form("general"),
    task_id: Optional[str] = Form(None),
    is_public: Optional[str] = Form(None),
    display_order: int = Form(1),
    description: Optional[str] = Form(None),
    official: Dict[str, Any] = Depends(require_permission("documents:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Upload a tournament setup file or briefing document from the Tab Room."""
    tournament = get_current_tenant_tournament(request)
    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Document title is required.")

    try:
        cat = AttachmentCategory(category.lower().strip())
    except ValueError:
        cat = AttachmentCategory.GENERAL

    att_id = generate_typeid("att")

    try:
        clean_filename, rel_path, file_size, mime_type, file_hash = await save_upload_file(
            tournament_id=tournament.id,
            attachment_id=att_id,
            upload_file=file,
        )
    except InvalidExtensionError as e:
        return RedirectResponse(
            url=f"/admin/documents?error={str(e)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except FileTooLargeError as e:
        return RedirectResponse(
            url=f"/admin/documents?error={str(e)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except StorageError as e:
        return RedirectResponse(
            url=f"/admin/documents?error=Storage+failure:+{str(e)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    clean_task_id = task_id.strip() if task_id and task_id.strip() else None
    if clean_task_id and not clean_task_id.startswith("task_"):
        clean_task_id = None

    if is_public is None:
        is_pub_bool = False
    elif isinstance(is_public, bool):
        is_pub_bool = is_public
    else:
        is_pub_bool = str(is_public).strip().lower() in ("true", "1", "on", "yes", "public")

    attachment = FileAttachment(
        id=att_id,
        tournament_id=tournament.id,
        task_id=clean_task_id,
        title=clean_title,
        description=description.strip() if description and description.strip() else None,
        category=cat,
        filename=clean_filename,
        file_path=rel_path,
        file_size=file_size,
        mime_type=mime_type,
        sha256_hash=file_hash,
        is_public=is_pub_bool,
        display_order=int(display_order),
    )
    db.add(attachment)
    await db.commit()

    return RedirectResponse(
        url="/admin/documents?msg=Document+uploaded+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/documents/{attachment_id}/update", response_class=HTMLResponse)
async def admin_documents_update(
    attachment_id: str,
    request: Request,
    title: str = Form(...),
    category: str = Form("general"),
    task_id: Optional[str] = Form(None),
    is_public: Optional[str] = Form(None),
    display_order: int = Form(1),
    description: Optional[str] = Form(None),
    official: Dict[str, Any] = Depends(require_permission("documents:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Inline update of an existing document's metadata."""
    tournament = get_current_tenant_tournament(request)
    stmt = select(FileAttachment).where(
        FileAttachment.id == attachment_id,
        FileAttachment.tournament_id == tournament.id,
    )
    res = await db.execute(stmt)
    attachment = res.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Document not found")

    clean_title = title.strip()
    if clean_title:
        attachment.title = clean_title
    try:
        attachment.category = AttachmentCategory(category.lower().strip())
    except ValueError:
        pass

    clean_task_id = task_id.strip() if task_id and task_id.strip() else None
    if clean_task_id and not clean_task_id.startswith("task_"):
        clean_task_id = None
    attachment.task_id = clean_task_id

    if is_public is None:
        is_pub_bool = False
    elif isinstance(is_public, bool):
        is_pub_bool = is_public
    else:
        is_pub_bool = str(is_public).strip().lower() in ("true", "1", "on", "yes", "public")
    attachment.is_public = is_pub_bool

    attachment.display_order = int(display_order)
    if description is not None:
        attachment.description = description.strip() if description.strip() else None

    await db.commit()

    # If requested via fetch / AJAX, return JSON without page reload
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.headers.get("HX-Request"):
        from fastapi.responses import JSONResponse
        return JSONResponse({
            "status": "ok",
            "message": "Document updated successfully.",
            "id": attachment.id,
            "category": attachment.category.value,
            "title": attachment.title,
            "is_public": attachment.is_public,
        })

    return RedirectResponse(
        url="/admin/documents?msg=Document+updated+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/documents/delete", response_class=HTMLResponse)
@router.post("/admin/documents/{attachment_id}/delete", response_class=HTMLResponse)
async def admin_documents_delete(
    request: Request,
    attachment_id: Optional[str] = None,
    official: Dict[str, Any] = Depends(require_permission("documents:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document and purge the physical file from storage."""
    tournament = get_current_tenant_tournament(request)
    target_id = attachment_id
    if not target_id:
        form_data = await request.form()
        target_id = form_data.get("attachment_id")

    if not target_id:
        raise HTTPException(status_code=400, detail="Document ID is required.")

    stmt = select(FileAttachment).where(
        FileAttachment.id == str(target_id),
        FileAttachment.tournament_id == tournament.id,
    )
    res = await db.execute(stmt)
    attachment = res.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Document not found")

    if attachment.file_path:
        try:
            delete_stored_file(attachment.file_path)
        except Exception:
            pass

    await db.delete(attachment)
    await db.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.headers.get("HX-Request"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"status": "ok", "message": "Document deleted successfully.", "id": str(target_id)})

    return RedirectResponse(
        url="/admin/documents?msg=Document+deleted+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# 3. Scoring Criteria & Rubrics
@router.get("/admin/rubric", response_class=HTMLResponse)
async def admin_rubric_page(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("rubric:manage")),
):
    """Render Tab Room scoring rubric configuration."""
    tournament = get_current_tenant_tournament(request)
    msg = request.query_params.get("msg")
    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/rubric.html",
        context={
            "tournament": tournament,
            "official": official,
            "msg": msg,
            "page_title": f"Scoring Criteria — {tournament.name}",
        },
    )


@router.post("/admin/rubric")
async def admin_rubric_save(
    request: Request,
    base_score: float = Form(...),
    ceiling_score: float = Form(...),
    max_time_penalty: float = Form(...),
    official: Dict[str, Any] = Depends(require_permission("rubric:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Save score boundaries and penalty floors."""
    tenant_tourn = get_current_tenant_tournament(request)
    stmt = select(Tournament).where(Tournament.id == tenant_tourn.id)
    res = await db.execute(stmt)
    tournament = res.scalar_one()

    tournament.base_score = float(base_score)
    tournament.ceiling_score = float(ceiling_score)
    tournament.max_time_penalty = float(max_time_penalty)
    await db.commit()
    return RedirectResponse(
        url="/admin/rubric?msg=Scoring+scale+boundaries+saved+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/rubric/criterion")
async def admin_rubric_add_criterion(
    request: Request,
    name: str = Form(...),
    max_points: float = Form(...),
    display_order: int = Form(1),
    description: Optional[str] = Form(None),
    official: Dict[str, Any] = Depends(require_permission("rubric:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Add a new evaluation criterion dimension."""
    tournament = get_current_tenant_tournament(request)
    criterion = RubricCriterion(
        tournament_id=tournament.id,
        name=name.strip(),
        max_points=float(max_points),
        display_order=display_order,
        description=description.strip() if description else None,
    )
    db.add(criterion)
    await db.commit()
    return RedirectResponse(
        url="/admin/rubric?msg=Evaluation+dimension+added.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/rubric/criterion/{criterion_id}/delete")
async def admin_rubric_delete_criterion(
    criterion_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("rubric:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a rubric evaluation criterion."""
    tournament = get_current_tenant_tournament(request)
    stmt = select(RubricCriterion).where(
        RubricCriterion.id == criterion_id,
        RubricCriterion.tournament_id == tournament.id,
    )
    res = await db.execute(stmt)
    crit = res.scalar_one_or_none()
    if crit:
        await db.delete(crit)
        await db.commit()
    return RedirectResponse(
        url="/admin/rubric?msg=Criterion+removed.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# 4. Speakers Roster & Management
@router.get("/admin/speakers", response_class=HTMLResponse)
async def admin_speakers_page(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("speakers:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Render Tab Room speakers directory, live check-in desk, and participant manager."""
    tournament = get_current_tenant_tournament(request)
    msg = request.query_params.get("msg")
    error = request.query_params.get("error")

    # 1. Query all speakers enrolled in this tournament
    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.divisions),
            selectinload(Participant.institution),
            selectinload(Participant.affiliations).selectinload(ParticipantInstitution.institution),
        )
        .where(
            Participant.tournament_id == tournament.id,
            Participant.speaker_profile != None,
        )
        .order_by(Participant.name.asc())
    )
    speakers = list((await db.execute(stmt)).scalars().all())

    # 2. Query tournament institutions and divisions for comboboxes & filters
    inst_stmt = (
        select(Institution)
        .where(Institution.tournament_id == tournament.id)
        .order_by(Institution.name.asc())
    )
    institutions = list((await db.execute(inst_stmt)).scalars().all())

    div_stmt = (
        select(Division)
        .where(Division.tournament_id == tournament.id)
        .order_by(Division.name.asc())
    )
    divisions = list((await db.execute(div_stmt)).scalars().all())

    speakers_data = [
        {
            "id": s.id,
            "name": s.name,
            "email": s.email,
            "phone": s.phone_number or "",
            "pronouns": (s.speaker_profile.pronouns if s.speaker_profile else "") or "",
            "institution_id": s.institution_id or "",
            "institution_name": s.institution.name if s.institution else "Independent",
            "division_ids": [d.id for d in s.divisions],
            "divisions": [d.name for d in s.divisions],
        }
        for s in speakers
    ]

    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/speakers.html",
        context={
            "tournament": tournament,
            "official": official,
            "speakers": speakers,
            "speakers_data": speakers_data,
            "institutions": institutions,
            "divisions": divisions,
            "msg": msg,
            "error": error,
            "page_title": f"Speakers — {tournament.name}",
        },
    )


@router.post("/admin/speakers")
async def admin_speakers_register(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("speakers:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Register a new competitor with single/multiple divisions and institution (supports AJAX & Form)."""
    tournament = get_current_tenant_tournament(request)
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        data = await request.json()
        name = data.get("name", "").strip()
        email = data.get("email", "").strip().lower()
        phone = data.get("phone", "").strip() or None
        pronouns = data.get("pronouns", "").strip() or None
        division_ids = data.get("division_ids", [])
        institution_id = data.get("institution_id") or None
        institution_name = data.get("institution_name", "").strip() or None
        institution_code = data.get("institution_code", "").strip() or None
        institution_country = data.get("institution_country", "").strip() or None
    else:
        form = await request.form()
        name = form.get("name", "").strip()
        email = form.get("email", "").strip().lower()
        phone = form.get("phone", "").strip() or None
        pronouns = form.get("pronouns", "").strip() or None
        division_ids = form.getlist("division_ids")
        single_div = form.get("division_id")
        if single_div and single_div not in division_ids:
            division_ids.append(single_div)
        institution_id = form.get("institution_id") or None
        institution_name = form.get("institution_name", "").strip() or None
        institution_code = form.get("institution_code", "").strip() or None
        institution_country = form.get("institution_country", "").strip() or None

    if not name or not email:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in content_type:
            return JSONResponse({"status": "error", "message": "Name and email are required."}, status_code=400)
        return RedirectResponse(url="/admin/speakers?error=Name+and+email+are+required.", status_code=status.HTTP_303_SEE_OTHER)

    # Check for duplicate competitor email in this tournament
    stmt_check = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.divisions),
            selectinload(Participant.affiliations),
        )
        .where(
            Participant.tournament_id == tournament.id,
            Participant.email == email,
        )
    )
    existing_p = (await db.execute(stmt_check)).scalar_one_or_none()
    if existing_p and existing_p.speaker_profile:
        msg = f"A competitor with email {email} is already registered."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in content_type:
            return JSONResponse({"status": "error", "message": msg}, status_code=400)
        return RedirectResponse(url=f"/admin/speakers?error={msg.replace(' ', '+')}", status_code=status.HTTP_303_SEE_OTHER)

    # Resolve or create institution inline if requested
    inst_id = None
    if institution_id and institution_id != "new":
        inst_id = institution_id
    elif institution_name:
        norm_name = normalize_institution_name(institution_name)
        stmt_inst = select(Institution).where(
            Institution.tournament_id == tournament.id,
            Institution.name_normalized == norm_name,
        )
        inst_obj = (await db.execute(stmt_inst)).scalar_one_or_none()
        if not inst_obj:
            inst_code = institution_code.upper() if institution_code else institution_name[:4].upper()
            inst_obj = Institution(
                tournament_id=tournament.id,
                name=institution_name,
                code=inst_code,
                country=institution_country or None,
            )
            db.add(inst_obj)
            await db.flush()
        inst_id = inst_obj.id

    # Resolve divisions first before attaching to part
    selected_divs = []
    if division_ids:
        div_stmt = select(Division).where(Division.id.in_(division_ids), Division.tournament_id == tournament.id)
        selected_divs = list((await db.execute(div_stmt)).scalars().all())
    if not selected_divs:
        first_div = (await db.execute(select(Division).where(Division.tournament_id == tournament.id).order_by(Division.name))).scalars().first()
        if first_div:
            selected_divs = [first_div]

    raw_token, token_hash = Participant.generate_token()
    if existing_p:
        part = existing_p
        part.name = name
        part.phone_number = phone
        part.institution_id = inst_id
        if not part.access_token_hash:
            part.access_token_hash = token_hash
        if not part.speaker_profile:
            part.speaker_profile = SpeakerProfile(pronouns=pronouns)
        else:
            part.speaker_profile.pronouns = pronouns
        part.divisions = selected_divs
    else:
        sp_profile = SpeakerProfile(pronouns=pronouns)
        part = Participant(
            tournament_id=tournament.id,
            name=name,
            email=email,
            phone_number=phone,
            institution_id=inst_id,
            access_token_hash=token_hash,
            speaker_profile=sp_profile,
            divisions=selected_divs,
        )
        db.add(part)

    await db.flush()

    # Primary affiliation
    if inst_id:
        aff_stmt = select(ParticipantInstitution).where(
            ParticipantInstitution.participant_id == part.id,
            ParticipantInstitution.institution_id == inst_id,
            ParticipantInstitution.is_primary == True,
        )
        existing_aff = (await db.execute(aff_stmt)).scalar_one_or_none()
        if not existing_aff:
            new_aff = ParticipantInstitution(
                participant_id=part.id,
                institution_id=inst_id,
                is_primary=True,
                tie_type="represents",
                clash_policy="hard",
            )
            db.add(new_aff)

    await db.commit()

    # Re-fetch participant with all relationships eagerly loaded
    refetch_stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.divisions),
            selectinload(Participant.institution),
        )
        .where(Participant.id == part.id)
    )
    part = (await db.execute(refetch_stmt)).scalar_one()

    base_url = str(request.base_url).rstrip("/")
    magic_url = f"{base_url}/s/{raw_token}/me"

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in content_type:
        return JSONResponse({
            "status": "ok",
            "message": f"Speaker '{part.name}' registered successfully.",
            "speaker": {
                "id": part.id,
                "name": part.name,
                "email": part.email,
                "phone": part.phone_number or "",
                "pronouns": (part.speaker_profile.pronouns if part.speaker_profile else "") or "",
                "institution_id": part.institution_id or "",
                "institution_name": part.institution.name if part.institution else "Independent",
                "division_ids": [d.id for d in part.divisions],
                "division_names": [d.name for d in part.divisions],
                "divisions": [d.name for d in part.divisions],
                "magic_url": magic_url,
            }
        })

    return RedirectResponse(
        url="/admin/speakers?msg=Speaker+registered+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/speakers/{participant_id}/update")
async def admin_speakers_update(
    participant_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("speakers:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Update speaker credentials, divisions eligibility, and representing institution."""
    tournament = get_current_tenant_tournament(request)
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        data = await request.json()
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        phone = (data.get("phone") or "").strip() or None
        pronouns = (data.get("pronouns") or "").strip() or None
        division_ids = data.get("division_ids", [])
        institution_id = data.get("institution_id") or None
    else:
        form = await request.form()
        name = (form.get("name") or "").strip()
        email = (form.get("email") or "").strip().lower()
        phone = (form.get("phone") or "").strip() or None
        pronouns = (form.get("pronouns") or "").strip() or None
        division_ids = form.getlist("division_ids")
        institution_id = form.get("institution_id") or None

    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.divisions),
            selectinload(Participant.affiliations),
            selectinload(Participant.institution),
        )
        .where(
            Participant.id == participant_id,
            Participant.tournament_id == tournament.id,
        )
    )
    part = (await db.execute(stmt)).scalar_one_or_none()
    if not part or not part.speaker_profile:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in content_type:
            return JSONResponse({"status": "error", "message": "Speaker not found."}, status_code=404)
        return RedirectResponse(url="/admin/speakers?error=Speaker+not+found.", status_code=status.HTTP_303_SEE_OTHER)

    if name:
        part.name = name
    if email:
        part.email = email
    part.phone_number = phone
    part.speaker_profile.pronouns = pronouns

    # Primary institution update
    inst_obj = None
    if institution_id:
        inst_obj = (await db.execute(select(Institution).where(Institution.id == institution_id, Institution.tournament_id == tournament.id))).scalar_one_or_none()
    part.institution = inst_obj
    part.institution_id = inst_obj.id if inst_obj else None

    if inst_obj:
        primary_aff = next((a for a in part.affiliations if a.is_primary), None)
        if primary_aff:
            primary_aff.institution_id = inst_obj.id
        else:
            part.affiliations.append(
                ParticipantInstitution(
                    institution_id=inst_obj.id,
                    is_primary=True,
                    tie_type="represents",
                    clash_policy="hard",
                )
            )
    else:
        for aff in list(part.affiliations):
            if aff.is_primary:
                await db.delete(aff)
                part.affiliations.remove(aff)

    # Divisions update
    if division_ids is not None:
        div_stmt = select(Division).where(Division.id.in_(division_ids), Division.tournament_id == tournament.id)
        selected_divs = (await db.execute(div_stmt)).scalars().all()
        part.divisions = list(selected_divs)

    await db.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in content_type:
        return JSONResponse({
            "status": "ok",
            "message": f"Speaker '{part.name}' updated successfully.",
            "speaker": {
                "id": part.id,
                "name": part.name,
                "email": part.email,
                "phone": part.phone_number or "",
                "pronouns": (part.speaker_profile.pronouns if part.speaker_profile else "") or "",
                "institution_id": part.institution_id or "",
                "institution_name": inst_obj.name if inst_obj else "Independent",
                "division_ids": [d.id for d in part.divisions],
                "divisions": [d.name for d in part.divisions],
            }
        })

    return RedirectResponse(url=f"/admin/speakers?msg=Speaker+{part.name.replace(' ', '+')}+updated.", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/speakers/{participant_id}/delete")
async def admin_speakers_delete(
    participant_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("speakers:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Delete an individual speaker from tournament roster."""
    tournament = get_current_tenant_tournament(request)
    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.affiliations),
            selectinload(Participant.divisions),
        )
        .where(Participant.id == participant_id, Participant.tournament_id == tournament.id)
    )
    part = (await db.execute(stmt)).scalar_one_or_none()
    if not part:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse({"status": "error", "message": "Speaker not found."}, status_code=404)
        return RedirectResponse(url="/admin/speakers?error=Speaker+not+found.", status_code=status.HTTP_303_SEE_OTHER)

    part_name = part.name
    # Explicitly clear association records from participant_divisions
    await db.execute(delete(participant_divisions).where(participant_divisions.c.participant_id == part.id))
    await db.delete(part)
    await db.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JSONResponse({"status": "ok", "message": f"Speaker '{part_name}' deleted."})
    return RedirectResponse(url=f"/admin/speakers?msg=Speaker+{part_name.replace(' ', '+')}+deleted.", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/speakers/{participant_id}/toggle-checkin")
async def admin_speakers_toggle_checkin(
    participant_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("speakers:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Toggle speaker check-in status (supports AJAX and standard Form)."""
    tournament = get_current_tenant_tournament(request)
    stmt = select(Participant).where(Participant.id == participant_id, Participant.tournament_id == tournament.id)
    part = (await db.execute(stmt)).scalar_one_or_none()
    if not part:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse({"status": "error", "message": "Speaker not found."}, status_code=404)
        return RedirectResponse(url="/admin/speakers?error=Speaker+not+found.", status_code=status.HTTP_303_SEE_OTHER)

    if part.status == ParticipantStatus.CHECKED_IN:
        part.status = ParticipantStatus.REGISTERED
        part.checked_in_at = None
    else:
        part.status = ParticipantStatus.CHECKED_IN
        part.checked_in_at = datetime.now(timezone.utc)
    await db.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JSONResponse({
            "status": "ok",
            "is_checked_in": part.status == ParticipantStatus.CHECKED_IN,
            "checked_in": part.status == ParticipantStatus.CHECKED_IN,
            "status_label": part.status.value.replace("_", " ").title(),
            "checked_in_at": part.checked_in_at.strftime("%b %d, %H:%M") if part.checked_in_at else None,
        })
    status_text = "Checked+In" if part.status == ParticipantStatus.CHECKED_IN else "Checked+Out"
    return RedirectResponse(url=f"/admin/speakers?msg={part.name.replace(' ', '+')}+status+updated:+{status_text}.", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/speakers/{participant_id}/send-magic-link")
@router.post("/admin/speakers/{participant_id}/generate-link")
async def admin_speakers_send_magic_link(
    participant_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("speakers:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate a private magic token URL and email it to the competitor."""
    tournament = get_current_tenant_tournament(request)
    stmt = (
        select(Participant)
        .options(selectinload(Participant.speaker_profile))
        .where(Participant.id == participant_id, Participant.tournament_id == tournament.id)
    )
    part = (await db.execute(stmt)).scalar_one_or_none()
    if not part:
        return JSONResponse({"status": "error", "message": "Speaker not found."}, status_code=404)
    if not part.email:
        return JSONResponse({"status": "error", "message": "Speaker has no email address configured."}, status_code=400)

    raw_token, token_hash = Participant.generate_token()
    part.access_token_hash = token_hash
    part.access_token_expires_at = None
    await db.commit()

    base_url = str(request.base_url).rstrip("/")
    magic_url = f"{base_url}/s/{raw_token}/me"

    await send_magic_link_email(
        to_email=part.email,
        name=part.name,
        magic_url=magic_url,
        tournament_name=tournament.name,
    )

    return JSONResponse({
        "status": "ok",
        "message": f"Magic link sent to {part.email}.",
        "magic_url": magic_url,
    })


@router.post("/admin/speakers/bulk-action")
async def admin_speakers_bulk_action(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("speakers:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Perform bulk check-in, check-out, magic link dispatch, or deletion across selected competitors."""
    tournament = get_current_tenant_tournament(request)
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
        action = data.get("action", "")
        speaker_ids = data.get("speaker_ids", [])
    else:
        form = await request.form()
        action = form.get("action", "")
        speaker_ids = form.getlist("speaker_ids")

    if not speaker_ids:
        return JSONResponse({"status": "error", "message": "No speakers selected."}, status_code=400)

    stmt = select(Participant).where(Participant.id.in_(speaker_ids), Participant.tournament_id == tournament.id)
    targets = list((await db.execute(stmt)).scalars().all())
    now = datetime.now(timezone.utc)

    if action in ("send_magic_link", "send_link", "send-link", "magic_link"):
        base_url = str(request.base_url).rstrip("/")
        sent_count = 0
        for t in targets:
            if not t.email:
                continue
            raw_token, token_hash = Participant.generate_token()
            t.access_token_hash = token_hash
            t.access_token_expires_at = None
            magic_url = f"{base_url}/s/{raw_token}/me"
            await send_magic_link_email(
                to_email=t.email,
                name=t.name,
                magic_url=magic_url,
                tournament_name=tournament.name,
            )
            sent_count += 1
        await db.commit()
        return JSONResponse({
            "status": "ok",
            "message": f"Magic links dispatched to {sent_count} speaker(s).",
            "count": sent_count,
        })
    elif action in ("check_in", "checkin", "check-in"):
        for t in targets:
            t.status = ParticipantStatus.CHECKED_IN
            t.checked_in_at = now
        await db.commit()
        return JSONResponse({"status": "ok", "message": f"{len(targets)} speaker(s) checked in successfully."})
    elif action in ("check_out", "checkout", "check-out"):
        for t in targets:
            t.status = ParticipantStatus.REGISTERED
            t.checked_in_at = None
        await db.commit()
        return JSONResponse({"status": "ok", "message": f"{len(targets)} speaker(s) marked as registered."})
    elif action == "delete":
        for t in targets:
            await db.execute(delete(participant_divisions).where(participant_divisions.c.participant_id == t.id))
            await db.delete(t)
        await db.commit()
        return JSONResponse({"status": "ok", "message": f"{len(targets)} speaker(s) deleted from roster."})
    elif action == "delete":
        for t in targets:
            await db.delete(t)
        await db.commit()
        return JSONResponse({"status": "ok", "message": f"{len(targets)} speaker(s) deleted from roster."})

    return JSONResponse({"status": "error", "message": "Invalid bulk action."}, status_code=400)


@router.get("/admin/speakers/export.xlsx")
async def admin_speakers_export_xlsx(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("speakers:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Download an Excel spreadsheet (.xlsx) of all enrolled tournament speakers."""
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    tournament = get_current_tenant_tournament(request)
    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.divisions),
            selectinload(Participant.institution),
        )
        .where(
            Participant.tournament_id == tournament.id,
            Participant.speaker_profile != None,
        )
        .order_by(Participant.name.asc())
    )
    speakers = list((await db.execute(stmt)).scalars().all())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Speakers"

    header_fill = PatternFill(start_color="622B14", end_color="622B14", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style="thin", color="E0D9D1"),
        right=Side(style="thin", color="E0D9D1"),
        top=Side(style="thin", color="E0D9D1"),
        bottom=Side(style="thin", color="E0D9D1"),
    )

    headers = ["Speaker ID", "Full Name", "Pronouns", "Email", "Phone", "Institution", "Institution Code", "Divisions", "Check-In Status", "Checked In At"]
    ws.append(headers)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center" if cell.value != "Full Name" else "left", vertical="center")

    for s in speakers:
        inst_name = s.institution.name if s.institution else "Independent"
        inst_code = s.institution.code if s.institution and s.institution.code else ""
        divs_str = ", ".join(s.division_names) if s.division_names else ""
        status_str = "Checked In" if s.status == ParticipantStatus.CHECKED_IN else "Registered"
        checked_str = s.checked_in_at.strftime("%Y-%m-%d %H:%M") if s.checked_in_at else ""
        pronouns_str = s.speaker_profile.pronouns if s.speaker_profile and s.speaker_profile.pronouns else ""

        ws.append([
            s.id,
            s.name,
            pronouns_str,
            s.email,
            s.phone_number or "",
            inst_name,
            inst_code,
            divs_str,
            status_str,
            checked_str,
        ])

    for row in ws.iter_rows(min_row=2, max_row=len(speakers) + 1, min_col=1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"{tournament.slug}-speakers.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/speakers/import-template.xlsx")
async def admin_speakers_import_template():
    """Download sample template for importing speakers."""
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Speakers Template"

    header_fill = PatternFill(start_color="995F2F", end_color="995F2F", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

    headers = ["Name", "Email", "Phone", "Institution", "Division"]
    ws.append(headers)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    sample_rows = [
        ["Jane Doe", "jane@oxford.edu", "+44 7911 123456", "University of Oxford", "Open, ESL"],
        ["Kwame Mensah", "kwame@ug.edu.gh", "+233 24 123 4567", "University of Ghana", "Open"],
        ["Alex Chen", "alex@utoronto.ca", "", "University of Toronto", "Novice"],
    ]
    for r in sample_rows:
        ws.append(r)

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 15)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="speakers_import_template.xlsx"'},
    )


@router.post("/admin/speakers/import")
async def admin_speakers_import(
    request: Request,
    file: UploadFile = File(...),
    official: Dict[str, Any] = Depends(require_permission("speakers:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Import competitors from uploaded .xlsx or .csv."""
    import io
    import csv
    tournament = get_current_tenant_tournament(request)
    filename = (file.filename or "").lower()

    content = await file.read()
    rows = []

    if filename.endswith(".xlsx"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))
        if len(all_rows) > 0:
            header_map = {str(h).strip().lower(): idx for idx, h in enumerate(all_rows[0]) if h is not None}

            def find_col(aliases):
                for a in aliases:
                    if a in header_map:
                        return header_map[a]
                return None

            name_idx = find_col(["name", "speaker", "speaker name", "full name", "competitor"])
            email_idx = find_col(["email", "email address", "mail"])
            phone_idx = find_col(["phone", "phone number", "telephone", "mobile", "contact"])
            pronouns_idx = find_col(["pronouns", "pronoun"])
            inst_idx = find_col(["institution", "school", "university", "delegation", "inst", "club", "team"])
            div_idx = find_col(["divisions", "division", "tier", "category", "div"])

            if name_idx is None and email_idx is None:
                first_row_len = len(all_rows[0])
                name_idx = 0
                email_idx = 1
                if first_row_len == 4:
                    inst_idx = 2
                    div_idx = 3
                elif first_row_len == 5:
                    phone_idx = 2
                    inst_idx = 3
                    div_idx = 4
                elif first_row_len >= 6:
                    phone_idx = 2
                    pronouns_idx = 3
                    inst_idx = 4
                    div_idx = 5
                data_rows = all_rows
            else:
                data_rows = all_rows[1:]

            def get_val(row_tuple, col_idx):
                if col_idx is not None and 0 <= col_idx < len(row_tuple):
                    val = row_tuple[col_idx]
                    return str(val).strip() if val is not None else ""
                return ""

            for row in data_rows:
                if any(row):
                    rows.append({
                        "name": get_val(row, name_idx),
                        "email": get_val(row, email_idx).lower(),
                        "phone": get_val(row, phone_idx) or None,
                        "pronouns": get_val(row, pronouns_idx) or None,
                        "institution": get_val(row, inst_idx) or None,
                        "divisions": get_val(row, div_idx) or None,
                    })
    elif filename.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        csv_rows = list(csv.reader(io.StringIO(text)))
        if csv_rows:
            header_map = {str(h).strip().lower(): idx for idx, h in enumerate(csv_rows[0]) if h is not None}

            def find_csv_col(aliases):
                for a in aliases:
                    if a in header_map:
                        return header_map[a]
                return None

            name_idx = find_csv_col(["name", "speaker", "speaker name", "full name", "competitor"])
            email_idx = find_csv_col(["email", "email address", "mail"])
            phone_idx = find_csv_col(["phone", "phone number", "telephone", "mobile", "contact"])
            pronouns_idx = find_csv_col(["pronouns", "pronoun"])
            inst_idx = find_csv_col(["institution", "school", "university", "delegation", "inst", "club", "team"])
            div_idx = find_csv_col(["divisions", "division", "tier", "category", "div"])

            if name_idx is None and email_idx is None:
                first_row_len = len(csv_rows[0])
                name_idx = 0
                email_idx = 1
                if first_row_len == 4:
                    inst_idx = 2
                    div_idx = 3
                elif first_row_len == 5:
                    phone_idx = 2
                    inst_idx = 3
                    div_idx = 4
                elif first_row_len >= 6:
                    phone_idx = 2
                    pronouns_idx = 3
                    inst_idx = 4
                    div_idx = 5
                data_rows = csv_rows
            else:
                data_rows = csv_rows[1:]

            def get_csv_val(row_tuple, col_idx):
                if col_idx is not None and 0 <= col_idx < len(row_tuple):
                    val = row_tuple[col_idx]
                    return str(val).strip() if val is not None else ""
                return ""

            for row in data_rows:
                if any(row):
                    rows.append({
                        "name": get_csv_val(row, name_idx),
                        "email": get_csv_val(row, email_idx).lower(),
                        "phone": get_csv_val(row, phone_idx) or None,
                        "pronouns": get_csv_val(row, pronouns_idx) or None,
                        "institution": get_csv_val(row, inst_idx) or None,
                        "divisions": get_csv_val(row, div_idx) or None,
                    })
    else:
        return RedirectResponse(url="/admin/speakers?error=Unsupported+file+format.+Upload+.xlsx+or+.csv.", status_code=status.HTTP_303_SEE_OTHER)

    if not rows:
        return RedirectResponse(url="/admin/speakers?error=Uploaded+file+contains+no+speaker+data.", status_code=status.HTTP_303_SEE_OTHER)

    div_objs = list((await db.execute(select(Division).where(Division.tournament_id == tournament.id))).scalars().all())
    div_map = {d.name.lower(): d for d in div_objs}

    inst_objs = list((await db.execute(select(Institution).where(Institution.tournament_id == tournament.id))).scalars().all())
    inst_map = {i.name_normalized: i for i in inst_objs}

    # Pre-create any missing institutions upfront to avoid mid-loop flushes
    all_inst_names = {r["institution"].strip() for r in rows if r.get("institution") and r["institution"].strip()}
    for raw_in in all_inst_names:
        norm_inst = normalize_institution_name(raw_in)
        if norm_inst not in inst_map:
            new_inst = Institution(
                tournament_id=tournament.id,
                name=raw_in,
                code=raw_in[:4].upper(),
            )
            db.add(new_inst)
            await db.flush()
            inst_map[norm_inst] = new_inst

    # Pre-create any missing divisions upfront to avoid mid-loop flushes
    all_div_names = set()
    for r in rows:
        if r.get("divisions"):
            for d in r["divisions"].split(","):
                if d.strip():
                    all_div_names.add(d.strip())

    for raw_dn in all_div_names:
        dn_lower = raw_dn.lower()
        if dn_lower not in div_map:
            new_div = Division(
                tournament_id=tournament.id,
                name=raw_dn.title(),
            )
            db.add(new_div)
            await db.flush()
            div_map[dn_lower] = new_div
            div_objs.append(new_div)

    imported_count = 0
    for r in rows:
        c_name = r["name"]
        c_email = r["email"]
        if not c_name or not c_email or "@" not in c_email:
            continue

        existing = (await db.execute(
            select(Participant)
            .options(
                selectinload(Participant.speaker_profile),
                selectinload(Participant.affiliations),
                selectinload(Participant.divisions),
            )
            .where(Participant.tournament_id == tournament.id, Participant.email == c_email)
        )).scalar_one_or_none()
        if existing and existing.speaker_profile:
            continue

        inst_id = None
        if r.get("institution"):
            norm_inst = normalize_institution_name(r["institution"])
            if norm_inst in inst_map:
                inst_id = inst_map[norm_inst].id

        raw_token, token_hash = Participant.generate_token()
        part = existing or Participant(
            tournament_id=tournament.id,
            name=c_name,
            email=c_email,
            phone_number=r["phone"],
            institution_id=inst_id,
            access_token_hash=token_hash,
        )
        db.add(part)
        if not part.speaker_profile:
            part.speaker_profile = SpeakerProfile(pronouns=r["pronouns"])
        else:
            part.speaker_profile.pronouns = r["pronouns"]

        if inst_id:
            has_primary = any(a.institution_id == inst_id and a.is_primary for a in part.affiliations)
            if not has_primary:
                part.affiliations.append(
                    ParticipantInstitution(
                        institution_id=inst_id,
                        is_primary=True,
                        tie_type="represents",
                        clash_policy="hard",
                    )
                )

        assigned_div_ids = {d.id for d in part.divisions}
        if r.get("divisions"):
            div_names = [d.strip() for d in r["divisions"].split(",") if d.strip()]
            for raw_dn in div_names:
                dn_lower = raw_dn.lower()
                target_div = div_map.get(dn_lower)
                if target_div and target_div.id not in assigned_div_ids:
                    part.divisions.append(target_div)
                    assigned_div_ids.add(target_div.id)
        if not part.divisions and div_objs:
            part.divisions.append(div_objs[0])

        imported_count += 1

    await db.commit()
    return RedirectResponse(url=f"/admin/speakers?msg=Successfully+imported+{imported_count}+speaker(s).", status_code=status.HTTP_303_SEE_OTHER)



# 5. Judges & Panels
@router.get("/admin/judges", response_class=HTMLResponse)
async def admin_judges_page(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("judges:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Render Tab Room adjudicator pool and panel credentials."""
    tournament = get_current_tenant_tournament(request)
    msg = request.query_params.get("msg")
    error = request.query_params.get("error")

    # Fetch tournament divisions
    div_stmt = select(Division).where(Division.tournament_id == tournament.id).order_by(Division.name)
    divisions = list((await db.execute(div_stmt)).scalars().all())

    # Fetch institutions
    inst_stmt = select(Institution).where(Institution.tournament_id == tournament.id).order_by(Institution.name)
    institutions = list((await db.execute(inst_stmt)).scalars().all())

    # Fetch participants with JudgeProfile
    judges_stmt = (
        select(Participant)
        .join(Participant.judge_profile)
        .options(
            selectinload(Participant.judge_profile),
            selectinload(Participant.institution),
            selectinload(Participant.divisions),
            selectinload(Participant.affiliations).selectinload(ParticipantInstitution.institution),
        )
        .where(Participant.tournament_id == tournament.id)
        .order_by(Participant.name.asc())
    )
    raw_judges = list((await db.execute(judges_stmt)).scalars().all())

    # Calculate scores and serializable dictionary for Alpine.js
    judges_data = []
    for p in raw_judges:
        adj = p.judge_profile
        t_score = round(float(adj.test_score or 0.0), 1) if adj else 0.0
        c_score = round(float(adj.cv_score or 0.0), 1) if adj else 0.0
        fb_score = None
        composite = adj.calculate_composite_score(
            weight_test=tournament.judge_weight_test,
            weight_cv=tournament.judge_weight_cv,
            weight_feedback=tournament.judge_weight_feedback,
            feedback_avg=fb_score,
        ) if adj else 0.0

        sec_affils = [
            {
                "institution_id": a.institution_id,
                "institution_name": a.institution.name if a.institution else "",
                "tie_type": a.tie_type,
            }
            for a in p.affiliations
            if not a.is_primary and a.institution
        ]

        judges_data.append({
            "id": p.id,
            "name": p.name,
            "email": p.email,
            "phone": p.phone_number or "",
            "status": p.status.value,
            "institution_id": p.institution_id or "",
            "institution_name": p.institution.name if p.institution else ("Independent" if adj and adj.is_independent else "Independent / None"),
            "institution_code": (p.institution.code if p.institution else "") or "",
            "is_independent": adj.is_independent if adj else False,
            "is_chair_eligible": adj.is_chair_eligible if adj else False,
            "is_reserve": adj.is_reserve if adj else False,
            "test_score": t_score,
            "cv_score": c_score,
            "feedback_score": fb_score,
            "composite_score": composite,
            "divisions": [d.name for d in p.divisions],
            "division_ids": [d.id for d in p.divisions],
            "secondary_affiliations": sec_affils,
        })

    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/judges.html",
        context={
            "tournament": tournament,
            "official": official,
            "judges": raw_judges,
            "judges_data": judges_data,
            "divisions": divisions,
            "institutions": institutions,
            "msg": msg,
            "error": error,
            "page_title": f"Adjudicators Roster — {tournament.name}",
        },
    )


@router.post("/admin/judges")
async def admin_judges_register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: Optional[str] = Form(None),
    institution_id: Optional[str] = Form(None),
    new_institution_name: Optional[str] = Form(None),
    new_institution_code: Optional[str] = Form(None),
    new_institution_country: Optional[str] = Form(None),
    is_chair_eligible: bool = Form(False),
    is_reserve: bool = Form(False),
    is_independent: bool = Form(False),
    test_score: Optional[float] = Form(0.0),
    cv_score: Optional[float] = Form(0.0),
    division_ids: List[str] = Form([]),
    secondary_affiliations_json: Optional[str] = Form(None),
    official: Dict[str, Any] = Depends(require_permission("judges:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Accredit a new judge in the tournament pool."""
    import json
    tournament = get_current_tenant_tournament(request)
    clean_name = name.strip()
    clean_email = email.strip().lower()
    clean_phone = (phone or "").strip() or None

    if not clean_name:
        return RedirectResponse(url="/admin/judges?error=Judge+name+is+required.", status_code=status.HTTP_303_SEE_OTHER)
    if not clean_email or "@" not in clean_email:
        return RedirectResponse(url="/admin/judges?error=Valid+email+address+is+required.", status_code=status.HTTP_303_SEE_OTHER)

    # Resolve or create institution
    resolved_institution: Optional[Institution] = None
    if institution_id == "new" or (not institution_id and new_institution_name):
        if new_institution_name and new_institution_name.strip():
            raw_in = new_institution_name.strip()
            norm_in = normalize_institution_name(raw_in)
            inst_check = await db.scalar(
                select(Institution).where(
                    Institution.tournament_id == tournament.id,
                    Institution.name_normalized == norm_in,
                )
            )
            if inst_check:
                resolved_institution = inst_check
            else:
                resolved_institution = Institution(
                    tournament_id=tournament.id,
                    name=raw_in,
                    name_normalized=norm_in,
                    code=(new_institution_code.strip() if new_institution_code and new_institution_code.strip() else None),
                    country=(new_institution_country.strip() if new_institution_country and new_institution_country.strip() else None),
                )
                db.add(resolved_institution)
                await db.flush()
    elif institution_id and institution_id != "none":
        inst_check = await db.scalar(
            select(Institution).where(
                Institution.tournament_id == tournament.id,
                Institution.id == institution_id,
            )
        )
        if inst_check:
            resolved_institution = inst_check

    # Bind selected divisions
    selected_divisions: List[Division] = []
    if division_ids:
        divs_stmt = select(Division).where(
            Division.tournament_id == tournament.id,
            Division.id.in_(division_ids),
        )
        selected_divisions = list((await db.scalars(divs_stmt)).all())

    raw_token, token_hash = Participant.generate_token()
    part = Participant(
        tournament_id=tournament.id,
        institution_id=resolved_institution.id if resolved_institution else None,
        name=clean_name,
        email=clean_email,
        phone_number=clean_phone,
        status=ParticipantStatus.REGISTERED,
        access_token_hash=token_hash,
        divisions=selected_divisions,
    )
    part.judge_profile = JudgeProfile(
        is_chair_eligible=is_chair_eligible,
        is_reserve=is_reserve,
        is_independent=is_independent or (resolved_institution is None),
        test_score=min(10.0, max(0.0, float(test_score or 0.0))),
        cv_score=min(10.0, max(0.0, float(cv_score or 0.0))),
    )

    if resolved_institution:
        part.affiliations.append(
            ParticipantInstitution(
                institution_id=resolved_institution.id,
                is_primary=True,
                tie_type="represents",
                clash_policy="hard",
            )
        )

    # Attach secondary clash affiliations
    if secondary_affiliations_json:
        try:
            sec_items = json.loads(secondary_affiliations_json)
            if isinstance(sec_items, list):
                for item in sec_items:
                    sec_inst_id = (item.get("institution_id") or "").strip()
                    sec_tie = (item.get("tie_type") or "alumnus").strip().lower()
                    if sec_inst_id and (resolved_institution is None or sec_inst_id != resolved_institution.id):
                        part.affiliations.append(
                            ParticipantInstitution(
                                institution_id=sec_inst_id,
                                is_primary=False,
                                tie_type=sec_tie,
                                clash_type=sec_tie,
                                clash_policy="hard",
                            )
                        )
        except Exception:
            pass

    db.add(part)
    await db.commit()
    return RedirectResponse(
        url="/admin/judges?msg=Judge+accredited+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/judges/{participant_id}/update")
async def admin_judges_update(
    participant_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("judges:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Inline update endpoint for an individual judge."""
    tournament = get_current_tenant_tournament(request)
    data = await request.json()

    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.judge_profile),
            selectinload(Participant.divisions),
            selectinload(Participant.institution),
            selectinload(Participant.affiliations).selectinload(ParticipantInstitution.institution),
        )
        .where(
            Participant.id == participant_id,
            Participant.tournament_id == tournament.id,
        )
    )
    part = (await db.execute(stmt)).scalar_one_or_none()
    if not part or not part.judge_profile:
        raise HTTPException(status_code=404, detail="Judge not found")

    new_name = (data.get("name") or "").strip()
    new_email = (data.get("email") or "").strip().lower()
    if not new_name or not new_email:
        return JSONResponse({"status": "error", "message": "Name and email are required."}, status_code=400)

    part.name = new_name
    part.email = new_email
    part.phone_number = (data.get("phone") or "").strip() or None

    # Update judge profile attributes
    adj = part.judge_profile
    if "is_chair_eligible" in data:
        adj.is_chair_eligible = bool(data["is_chair_eligible"])
    if "is_reserve" in data:
        adj.is_reserve = bool(data["is_reserve"])
    if "is_independent" in data:
        adj.is_independent = bool(data["is_independent"])
    if "test_score" in data:
        try:
            adj.test_score = min(10.0, max(0.0, float(data["test_score"] or 0.0)))
        except (ValueError, TypeError):
            pass
    if "cv_score" in data:
        try:
            adj.cv_score = min(10.0, max(0.0, float(data["cv_score"] or 0.0)))
        except (ValueError, TypeError):
            pass

    # Update institution
    new_inst_id = data.get("institution_id")
    if new_inst_id:
        inst_stmt = select(Institution).where(
            Institution.id == new_inst_id,
            Institution.tournament_id == tournament.id,
        )
        inst_obj = (await db.execute(inst_stmt)).scalar_one_or_none()
        part.institution_id = inst_obj.id if inst_obj else None
        part.institution = inst_obj

        # Sync primary affiliation
        primary_aff = next((a for a in part.affiliations if a.is_primary), None)
        if primary_aff:
            if inst_obj:
                primary_aff.institution_id = inst_obj.id
            else:
                part.affiliations.remove(primary_aff)
        elif inst_obj:
            part.affiliations.append(
                ParticipantInstitution(
                    institution_id=inst_obj.id,
                    is_primary=True,
                    tie_type="represents",
                    clash_policy="hard",
                )
            )
    else:
        part.institution_id = None
        part.institution = None
        primary_aff = next((a for a in part.affiliations if a.is_primary), None)
        if primary_aff:
            part.affiliations.remove(primary_aff)

    # Update divisions
    if "division_ids" in data:
        target_ids = data.get("division_ids") or []
        divs_stmt = select(Division).where(
            Division.tournament_id == tournament.id,
            Division.id.in_(target_ids),
        )
        part.divisions = list((await db.scalars(divs_stmt)).all())

    # Update secondary affiliations (clashes) if provided
    if "secondary_affiliations" in data:
        non_primaries = [a for a in part.affiliations if not a.is_primary]
        for a in non_primaries:
            part.affiliations.remove(a)

        sec_items = data.get("secondary_affiliations") or []
        for s_item in sec_items:
            s_inst_id = (s_item.get("institution_id") or "").strip()
            s_tie = (s_item.get("tie_type") or "alumnus").strip().lower()
            if s_inst_id and s_inst_id != part.institution_id:
                part.affiliations.append(
                    ParticipantInstitution(
                        institution_id=s_inst_id,
                        is_primary=False,
                        tie_type=s_tie,
                        clash_type=s_tie,
                        clash_policy="hard",
                    )
                )

    await db.commit()

    # Recompute composite score
    t_score = round(float(adj.test_score or 0.0), 1)
    c_score = round(float(adj.cv_score or 0.0), 1)
    composite = adj.calculate_composite_score(
        weight_test=tournament.judge_weight_test,
        weight_cv=tournament.judge_weight_cv,
        weight_feedback=tournament.judge_weight_feedback,
        feedback_avg=None,
    )

    sec_affils = [
        {
            "institution_id": a.institution_id,
            "institution_name": a.institution.name if a.institution else "",
            "tie_type": a.tie_type,
        }
        for a in part.affiliations
        if not a.is_primary and a.institution
    ]

    return JSONResponse({
        "status": "ok",
        "judge": {
            "id": part.id,
            "name": part.name,
            "email": part.email,
            "phone": part.phone_number or "",
            "institution_id": part.institution_id or "",
            "institution_name": part.institution.name if part.institution else ("Independent" if adj.is_independent else "Independent / None"),
            "institution_code": (part.institution.code if part.institution else "") or "",
            "is_chair_eligible": adj.is_chair_eligible,
            "is_reserve": adj.is_reserve,
            "is_independent": adj.is_independent,
            "test_score": t_score,
            "cv_score": c_score,
            "composite_score": composite,
            "divisions": [d.name for d in part.divisions],
            "division_ids": [d.id for d in part.divisions],
            "secondary_affiliations": sec_affils,
        }
    })


@router.post("/admin/judges/{participant_id}/delete")
async def admin_judges_delete(
    participant_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("judges:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Delete an individual judge from the tournament roster."""
    tournament = get_current_tenant_tournament(request)
    stmt = select(Participant).where(
        Participant.id == participant_id,
        Participant.tournament_id == tournament.id,
    )
    part = (await db.execute(stmt)).scalar_one_or_none()
    if part:
        await db.delete(part)
        await db.commit()
    
    if request.headers.get("accept") == "application/json" or request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JSONResponse({"status": "ok", "message": "Judge deleted successfully."})

    return RedirectResponse(
        url="/admin/judges?msg=Judge+deleted+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/judges/{participant_id}/send-link")
async def admin_judges_send_link(
    participant_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("judges:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Asynchronously dispatch private magic link email to an adjudicator."""
    tournament = get_current_tenant_tournament(request)
    stmt = select(Participant).where(
        Participant.id == participant_id,
        Participant.tournament_id == tournament.id,
    )
    part = (await db.execute(stmt)).scalar_one_or_none()
    if not part:
        raise HTTPException(status_code=404, detail="Judge not found")

    raw_token, token_hash = Participant.generate_token()
    part.access_token_hash = token_hash
    part.access_token_expires_at = None
    await db.commit()

    base_url = str(request.base_url).rstrip("/")
    magic_url = f"{base_url}/j/{raw_token}/me"

    try:
        await send_magic_link_email(
            to_email=part.email,
            name=part.name,
            magic_url=magic_url,
            tournament_name=tournament.name,
        )
    except Exception as exc:
        logger.error(f"Failed to dispatch magic link to {part.email}: {exc}")

    return JSONResponse({
        "status": "ok",
        "message": f"Magic link dispatched to {part.email}.",
        "magic_url": magic_url,
    })


@router.post("/admin/judges/bulk-action")
async def admin_judges_bulk_action(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("judges:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Execute bulk operations (delete, send magic links) on selected judges."""
    tournament = get_current_tenant_tournament(request)
    form_data = await request.form()
    judge_ids = form_data.getlist("judge_ids")
    action = form_data.get("action")

    if not judge_ids:
        return JSONResponse({"status": "error", "message": "No judges selected."}, status_code=400)

    if action == "delete":
        stmt = delete(Participant).where(
            Participant.id.in_(judge_ids),
            Participant.tournament_id == tournament.id,
        )
        await db.execute(stmt)
        await db.commit()
        return JSONResponse({"status": "ok", "message": f"Successfully deleted {len(judge_ids)} judge(s)."})

    elif action == "send_links":
        stmt = select(Participant).where(
            Participant.id.in_(judge_ids),
            Participant.tournament_id == tournament.id,
        )
        parts = list((await db.scalars(stmt)).all())
        base_url = str(request.base_url).rstrip("/")

        for part in parts:
            raw_token, token_hash = Participant.generate_token()
            part.access_token_hash = token_hash
            part.access_token_expires_at = None
            magic_url = f"{base_url}/j/{raw_token}/me"
            try:
                await send_magic_link_email(
                    to_email=part.email,
                    name=part.name,
                    magic_url=magic_url,
                    tournament_name=tournament.name,
                )
            except Exception as exc:
                logger.error(f"Failed to dispatch magic link to {part.email}: {exc}")

        await db.commit()
        return JSONResponse({"status": "ok", "message": f"Dispatched magic links to {len(parts)} judge(s)."})

    return JSONResponse({"status": "error", "message": "Invalid bulk action."}, status_code=400)


@router.get("/admin/judges/export")
async def admin_judges_export(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("judges:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Export accredited tournament adjudicators to Excel (.xlsx)."""
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    tournament = get_current_tenant_tournament(request)
    stmt = (
        select(Participant)
        .join(Participant.judge_profile)
        .options(
            selectinload(Participant.judge_profile),
            selectinload(Participant.institution),
            selectinload(Participant.divisions),
            selectinload(Participant.affiliations).selectinload(ParticipantInstitution.institution),
        )
        .where(Participant.tournament_id == tournament.id)
        .order_by(Participant.name.asc())
    )
    judges = list((await db.execute(stmt)).scalars().all())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Adjudicators Roster"

    headers = [
        "Full Name", "Email Address", "Phone Number", "Primary Institution",
        "Secondary Clashes", "Divisions", "Chair Eligible", "Reserve", "Independent",
        "Test Score", "CV Score", "Composite Score", "Status"
    ]
    ws.append(headers)

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="8B4513", end_color="8B4513", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="D3D3D3"),
        right=Side(style="thin", color="D3D3D3"),
        top=Side(style="thin", color="D3D3D3"),
        bottom=Side(style="thin", color="D3D3D3"),
    )

    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for j in judges:
        adj = j.judge_profile
        t_score = float(adj.test_score or 0.0) if adj else 0.0
        c_score = float(adj.cv_score or 0.0) if adj else 0.0
        comp_score = adj.calculate_composite_score(
            weight_test=tournament.judge_weight_test,
            weight_cv=tournament.judge_weight_cv,
            weight_feedback=tournament.judge_weight_feedback,
            feedback_avg=None,
        ) if adj else 0.0

        sec_ties = ", ".join(f"{a.institution.name} ({a.tie_type})" for a in j.affiliations if not a.is_primary and a.institution)

        ws.append([
            j.name,
            j.email,
            j.phone_number or "",
            j.institution.name if j.institution else "Independent",
            sec_ties,
            ", ".join(d.name for d in j.divisions),
            "Yes" if adj and adj.is_chair_eligible else "No",
            "Yes" if adj and adj.is_reserve else "No",
            "Yes" if adj and adj.is_independent else "No",
            t_score,
            c_score,
            comp_score,
            j.status.value.replace("_", " ").title(),
        ])

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = col[0].column_letter
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"{tournament.slug}_judges.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/admin/judges/import")
async def admin_judges_import(
    request: Request,
    file: UploadFile = File(...),
    official: Dict[str, Any] = Depends(require_permission("judges:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Import tournament adjudicators from Excel (.xlsx) or CSV (.csv)."""
    import io
    import csv
    import openpyxl

    tournament = get_current_tenant_tournament(request)
    filename = (file.filename or "").lower()
    content = await file.read()

    rows = []
    if filename.endswith(".xlsx"):
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        sheet = wb.active
        all_raw = list(sheet.iter_rows(values_only=True))
        if all_raw:
            header_map = {str(h).strip().lower(): idx for idx, h in enumerate(all_raw[0]) if h is not None}

            def find_col(aliases):
                for a in aliases:
                    if a in header_map:
                        return header_map[a]
                return None

            name_idx = find_col(["full name", "name", "judge", "judge name", "adjudicator"])
            email_idx = find_col(["email address", "email", "mail"])
            phone_idx = find_col(["phone number", "phone", "telephone", "mobile", "contact"])
            inst_idx = find_col(["primary institution", "institution", "school", "university", "delegation", "inst", "club"])
            div_idx = find_col(["divisions", "division", "tier", "category", "div"])
            chair_idx = find_col(["chair eligible", "is chair eligible", "chair", "is_chair_eligible"])
            reserve_idx = find_col(["reserve", "is reserve", "is_reserve"])
            ia_idx = find_col(["independent", "ia", "is independent", "is_independent"])
            test_idx = find_col(["test score", "test", "test_score"])
            cv_idx = find_col(["cv score", "cv", "cv_score"])

            data_rows = all_raw[1:] if (name_idx is not None or email_idx is not None) else all_raw
            if name_idx is None:
                name_idx = 0
            if email_idx is None and len(all_raw[0]) > 1:
                email_idx = 1

            def get_val(row_tuple, col_idx):
                if col_idx is not None and 0 <= col_idx < len(row_tuple):
                    val = row_tuple[col_idx]
                    return str(val).strip() if val is not None else ""
                return ""

            for row in data_rows:
                if any(row):
                    rows.append({
                        "name": get_val(row, name_idx),
                        "email": get_val(row, email_idx).lower(),
                        "phone": get_val(row, phone_idx) or None,
                        "institution": get_val(row, inst_idx) or None,
                        "divisions": get_val(row, div_idx) or None,
                        "is_chair_eligible": get_val(row, chair_idx).lower() in ("yes", "true", "1", "y"),
                        "is_reserve": get_val(row, reserve_idx).lower() in ("yes", "true", "1", "y"),
                        "is_independent": get_val(row, ia_idx).lower() in ("yes", "true", "1", "y"),
                        "test_score": get_val(row, test_idx),
                        "cv_score": get_val(row, cv_idx),
                    })
    elif filename.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        csv_rows = list(csv.reader(io.StringIO(text)))
        if csv_rows:
            header_map = {str(h).strip().lower(): idx for idx, h in enumerate(csv_rows[0]) if h is not None}

            def find_csv_col(aliases):
                for a in aliases:
                    if a in header_map:
                        return header_map[a]
                return None

            name_idx = find_csv_col(["full name", "name", "judge", "judge name", "adjudicator"])
            email_idx = find_csv_col(["email address", "email", "mail"])
            phone_idx = find_csv_col(["phone number", "phone", "telephone", "mobile", "contact"])
            inst_idx = find_csv_col(["primary institution", "institution", "school", "university", "delegation", "inst", "club"])
            div_idx = find_csv_col(["divisions", "division", "tier", "category", "div"])
            chair_idx = find_csv_col(["chair eligible", "is chair eligible", "chair", "is_chair_eligible"])
            reserve_idx = find_csv_col(["reserve", "is reserve", "is_reserve"])
            ia_idx = find_csv_col(["independent", "ia", "is independent", "is_independent"])
            test_idx = find_csv_col(["test score", "test", "test_score"])
            cv_idx = find_csv_col(["cv score", "cv", "cv_score"])

            data_rows = csv_rows[1:] if (name_idx is not None or email_idx is not None) else csv_rows
            if name_idx is None:
                name_idx = 0
            if email_idx is None and len(csv_rows[0]) > 1:
                email_idx = 1

            def get_csv_val(row_tuple, col_idx):
                if col_idx is not None and 0 <= col_idx < len(row_tuple):
                    val = row_tuple[col_idx]
                    return str(val).strip() if val is not None else ""
                return ""

            for row in data_rows:
                if any(row):
                    rows.append({
                        "name": get_csv_val(row, name_idx),
                        "email": get_csv_val(row, email_idx).lower(),
                        "phone": get_csv_val(row, phone_idx) or None,
                        "institution": get_csv_val(row, inst_idx) or None,
                        "divisions": get_csv_val(row, div_idx) or None,
                        "is_chair_eligible": get_csv_val(row, chair_idx).lower() in ("yes", "true", "1", "y"),
                        "is_reserve": get_csv_val(row, reserve_idx).lower() in ("yes", "true", "1", "y"),
                        "is_independent": get_csv_val(row, ia_idx).lower() in ("yes", "true", "1", "y"),
                        "test_score": get_csv_val(row, test_idx),
                        "cv_score": get_csv_val(row, cv_idx),
                    })
    else:
        return RedirectResponse(url="/admin/judges?error=Unsupported+file+format.+Upload+.xlsx+or+.csv.", status_code=status.HTTP_303_SEE_OTHER)

    if not rows:
        return RedirectResponse(url="/admin/judges?error=Uploaded+file+contains+no+adjudicator+data.", status_code=status.HTTP_303_SEE_OTHER)

    div_objs = list((await db.execute(select(Division).where(Division.tournament_id == tournament.id))).scalars().all())
    div_map = {d.name.lower(): d for d in div_objs}

    inst_objs = list((await db.execute(select(Institution).where(Institution.tournament_id == tournament.id))).scalars().all())
    inst_map = {i.name_normalized: i for i in inst_objs}

    # Pre-create missing institutions upfront
    all_inst_names = {r["institution"].strip() for r in rows if r.get("institution") and r["institution"].strip() and r["institution"].strip().lower() != "independent"}
    for raw_in in all_inst_names:
        norm_inst = normalize_institution_name(raw_in)
        if norm_inst not in inst_map:
            new_inst = Institution(
                tournament_id=tournament.id,
                name=raw_in,
                code=raw_in[:4].upper(),
            )
            db.add(new_inst)
            await db.flush()
            inst_map[norm_inst] = new_inst

    # Pre-create missing divisions upfront
    all_div_names = set()
    for r in rows:
        if r.get("divisions"):
            for d in r["divisions"].split(","):
                if d.strip():
                    all_div_names.add(d.strip())

    for raw_dn in all_div_names:
        dn_lower = raw_dn.lower()
        if dn_lower not in div_map:
            new_div = Division(
                tournament_id=tournament.id,
                name=raw_dn.title(),
            )
            db.add(new_div)
            await db.flush()
            div_map[dn_lower] = new_div

    imported_count = 0
    for r in rows:
        name_val = r["name"]
        email_val = r["email"]
        if not name_val or not email_val or "@" not in email_val:
            continue

        stmt_existing = (
            select(Participant)
            .options(selectinload(Participant.judge_profile), selectinload(Participant.divisions))
            .where(
                Participant.tournament_id == tournament.id,
                Participant.email == email_val,
            )
        )
        existing_part = (await db.execute(stmt_existing)).scalar_one_or_none()

        inst_target = None
        if r.get("institution") and r["institution"].strip().lower() != "independent":
            norm_in = normalize_institution_name(r["institution"])
            inst_target = inst_map.get(norm_in)

        t_val = 0.0
        try:
            t_val = min(10.0, max(0.0, float(r.get("test_score") or 0.0)))
        except (ValueError, TypeError):
            pass

        c_val = 0.0
        try:
            c_val = min(10.0, max(0.0, float(r.get("cv_score") or 0.0)))
        except (ValueError, TypeError):
            pass

        if existing_part:
            part = existing_part
            part.name = name_val
            if r.get("phone"):
                part.phone_number = r["phone"].strip() or None
            if inst_target:
                part.institution_id = inst_target.id
                part.institution = inst_target
            if not part.judge_profile:
                part.judge_profile = JudgeProfile(
                    participant_id=part.id,
                    is_chair_eligible=r.get("is_chair_eligible", False),
                    is_reserve=r.get("is_reserve", False),
                    is_independent=r.get("is_independent", False) or (inst_target is None),
                    test_score=t_val,
                    cv_score=c_val,
                )
            else:
                part.judge_profile.is_chair_eligible = r.get("is_chair_eligible", False)
                part.judge_profile.is_reserve = r.get("is_reserve", False)
                part.judge_profile.is_independent = r.get("is_independent", False) or (inst_target is None)
                part.judge_profile.test_score = t_val
                part.judge_profile.cv_score = c_val
        else:
            raw_token, token_hash = Participant.generate_token()
            part = Participant(
                tournament_id=tournament.id,
                name=name_val,
                email=email_val,
                phone_number=r["phone"].strip() if r.get("phone") else None,
                institution_id=inst_target.id if inst_target else None,
                status=ParticipantStatus.REGISTERED,
                access_token_hash=token_hash,
            )
            part.judge_profile = JudgeProfile(
                is_chair_eligible=r.get("is_chair_eligible", False),
                is_reserve=r.get("is_reserve", False),
                is_independent=r.get("is_independent", False) or (inst_target is None),
                test_score=t_val,
                cv_score=c_val,
            )
            if inst_target:
                part.affiliations.append(
                    ParticipantInstitution(
                        institution_id=inst_target.id,
                        is_primary=True,
                        tie_type="represents",
                        clash_policy="hard",
                    )
                )
            db.add(part)

        # Assign divisions
        assigned_div_ids = {d.id for d in part.divisions}
        if r.get("divisions"):
            for d_name in r["divisions"].split(","):
                dn_lower = d_name.strip().lower()
                target_div = div_map.get(dn_lower)
                if target_div and target_div.id not in assigned_div_ids:
                    part.divisions.append(target_div)
                    assigned_div_ids.add(target_div.id)
        if not part.divisions and div_objs:
            part.divisions.append(div_objs[0])

        imported_count += 1

    await db.commit()
    return RedirectResponse(
        url=f"/admin/judges?msg=Successfully+imported+{imported_count}+adjudicator(s).",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/judges/{participant_id}/toggle-checkin")
async def admin_judges_toggle_checkin(
    participant_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("judges:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Toggle judge arrival check-in status."""
    tournament = get_current_tenant_tournament(request)
    stmt = select(Participant).where(Participant.id == participant_id, Participant.tournament_id == tournament.id)
    res = await db.execute(stmt)
    part = res.scalar_one_or_none()
    if part:
        if part.status == ParticipantStatus.CHECKED_IN:
            part.status = ParticipantStatus.REGISTERED
        else:
            part.status = ParticipantStatus.CHECKED_IN
        await db.commit()
    return RedirectResponse(url="/admin/judges", status_code=status.HTTP_303_SEE_OTHER)


# 6. Officials & Roles
@router.get("/admin/officials", response_class=HTMLResponse)
async def admin_officials_page(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("officials:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Render Tab Room staff directory, assigned roles, and password management."""
    tournament = get_current_tenant_tournament(request)
    msg = request.query_params.get("msg")
    error = request.query_params.get("error")

    # Ensure tournament roles exist
    roles = await ensure_tournament_roles_and_permissions(db, tournament.id)

    # Fetch officials with participant, roles, and affiliations
    stmt_officials = (
        select(OfficialProfile)
        .join(Participant, OfficialProfile.participant_id == Participant.id)
        .options(
            selectinload(OfficialProfile.participant).selectinload(Participant.affiliations).selectinload(ParticipantInstitution.institution),
            selectinload(OfficialProfile.participant).selectinload(Participant.institution),
            selectinload(OfficialProfile.roles),
        )
        .where(Participant.tournament_id == tournament.id)
        .order_by(Participant.name)
    )
    officials_list = (await db.execute(stmt_officials)).scalars().all()

    # Institutions for combobox selection
    stmt_inst = select(Institution).where(Institution.tournament_id == tournament.id).order_by(Institution.name)
    institutions = (await db.execute(stmt_inst)).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/officials.html",
        context={
            "tournament": tournament,
            "official": official,
            "officials": officials_list,
            "roles": roles,
            "institutions": institutions,
            "msg": msg,
            "error": error,
            "page_title": f"Officials & Staff — {tournament.name}",
        },
    )


@router.post("/admin/officials")
async def admin_officials_register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    title: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    is_phone_public: bool = Form(True),
    role_ids: List[str] = Form(default=[]),
    role: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    primary_institution_id: Optional[str] = Form(None),
    institution_name: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    official: Dict[str, Any] = Depends(require_permission("officials:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Register official with roles, affiliations, phone contact, and dispatch setup link."""
    tournament = get_current_tenant_tournament(request)
    clean_name = name.strip()
    clean_email = email.strip().lower()
    clean_phone = phone.strip() if phone and phone.strip() else None
    clean_title = title.strip() if title and title.strip() else None

    stmt_part = select(Participant).where(
        Participant.tournament_id == tournament.id,
        Participant.email == clean_email,
    )
    existing_part = (await db.execute(stmt_part)).scalar_one_or_none()
    if existing_part and existing_part.official_profile:
        return RedirectResponse(
            url=f"/admin/officials?error=An+official+with+email+{clean_email}+already+exists.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    inst_id = primary_institution_id
    if not inst_id and institution_name and institution_name.strip():
        norm_name = normalize_institution_name(institution_name.strip())
        stmt_inst = select(Institution).where(
            Institution.tournament_id == tournament.id,
            Institution.name_normalized == norm_name,
        )
        inst_obj = (await db.execute(stmt_inst)).scalar_one_or_none()
        if not inst_obj:
            inst_obj = Institution(
                tournament_id=tournament.id,
                name=institution_name.strip(),
                code=institution_name.strip()[:4].upper(),
            )
            db.add(inst_obj)
            await db.flush()
        inst_id = inst_obj.id

    part = existing_part or Participant(
        tournament_id=tournament.id,
        institution_id=inst_id,
        name=clean_name,
        email=clean_email,
        phone_number=clean_phone,
    )
    if existing_part:
        if clean_phone:
            part.phone_number = clean_phone
        if inst_id and not part.institution_id:
            part.institution_id = inst_id
    else:
        db.add(part)
        await db.flush()

    if inst_id:
        has_primary = any(a.institution_id == inst_id and a.is_primary for a in part.affiliations)
        if not has_primary:
            part.affiliations.append(
                ParticipantInstitution(
                    institution_id=inst_id,
                    is_primary=True,
                    tie_type="represents",
                    clash_policy="hard",
                )
            )

    off_profile = OfficialProfile(
        title=clean_title,
        phone=clean_phone,
        is_phone_public=is_phone_public,
        notes=notes,
    )
    if role:
        try:
            off_profile.role = OfficialRole(role)
        except ValueError:
            pass

    await ensure_tournament_roles_and_permissions(db, tournament.id)

    selected_role_ids = set(role_ids)
    if selected_role_ids:
        roles_stmt = select(Role).where(Role.id.in_(selected_role_ids), Role.tournament_id == tournament.id)
        selected_roles = (await db.execute(roles_stmt)).scalars().all()
        off_profile.roles.extend(selected_roles)
    elif off_profile.role:
        role_map = {
            OfficialRole.TAB: "Tab Director",
            OfficialRole.DIRECTOR: "Tournament Director",
            OfficialRole.CAP: "Chief Adjudicator (CA)",
            OfficialRole.DCA: "Deputy CA (DCA)",
            OfficialRole.EQUITY: "Equity Officer",
            OfficialRole.ORG_COMM: "Organization Committee",
        }
        target_name = role_map.get(off_profile.role)
        if target_name:
            r_obj = (await db.execute(select(Role).where(Role.tournament_id == tournament.id, Role.name == target_name))).scalar_one_or_none()
            if r_obj:
                off_profile.roles.append(r_obj)

    if password and password.strip():
        off_profile.set_password(password.strip())
        part.official_profile = off_profile
        await db.commit()
        return RedirectResponse(
            url="/admin/officials?msg=Official+registered+successfully.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # Setup token and email flow
    raw_token, token_hash = OfficialProfile.generate_reset_token()
    off_profile.reset_token_hash = token_hash
    off_profile.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(days=14)
    part.official_profile = off_profile
    await db.commit()

    base_url = str(request.base_url).rstrip("/")
    setup_url = f"{base_url}/admin/reset-password?token={raw_token}"
    role_labels = off_profile.role_names
    await send_official_invitation_email(
        to_email=clean_email,
        name=clean_name,
        setup_url=setup_url,
        tournament_name=tournament.name,
        roles=role_labels,
    )

    return RedirectResponse(
        url="/admin/officials?msg=Official+registered+successfully.+A+password+setup+link+has+been+emailed.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/officials/{official_id}/send-invite")
async def admin_officials_resend_invite(
    official_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("officials:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Resend password setup / reset invitation email to official."""
    tournament = get_current_tenant_tournament(request)
    stmt = (
        select(OfficialProfile)
        .options(selectinload(OfficialProfile.participant), selectinload(OfficialProfile.roles))
        .join(Participant, OfficialProfile.participant_id == Participant.id)
        .where(OfficialProfile.id == official_id, Participant.tournament_id == tournament.id)
    )
    target = (await db.execute(stmt)).scalar_one_or_none()
    if not target or not target.participant:
        raise HTTPException(status_code=404, detail="Official profile not found.")

    raw_token, token_hash = OfficialProfile.generate_reset_token()
    target.reset_token_hash = token_hash
    target.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(days=14)
    await db.commit()

    base_url = str(request.base_url).rstrip("/")
    setup_url = f"{base_url}/admin/reset-password?token={raw_token}"
    await send_official_invitation_email(
        to_email=target.participant.email,
        name=target.participant.name,
        setup_url=setup_url,
        tournament_name=tournament.name,
        roles=target.role_names,
    )

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JSONResponse({"status": "ok", "message": f"Invitation email sent to {target.participant.email}."})

    return RedirectResponse(
        url=f"/admin/officials?msg=Invitation+email+sent+to+{target.participant.email}.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/officials/bulk-send-invite")
async def admin_officials_bulk_send_invite(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("officials:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk dispatch or resend password setup invitation emails to selected officials."""
    tournament = get_current_tenant_tournament(request)
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
        official_ids = data.get("official_ids", [])
    else:
        form = await request.form()
        official_ids = form.getlist("official_ids")

    if not official_ids:
        return JSONResponse({"status": "error", "message": "No officials selected."}, status_code=400)

    stmt = (
        select(OfficialProfile)
        .options(selectinload(OfficialProfile.participant), selectinload(OfficialProfile.roles))
        .join(Participant, OfficialProfile.participant_id == Participant.id)
        .where(OfficialProfile.id.in_(official_ids), Participant.tournament_id == tournament.id)
    )
    targets = (await db.execute(stmt)).scalars().all()
    if not targets:
        return JSONResponse({"status": "error", "message": "No valid officials found to dispatch."}, status_code=404)

    base_url = str(request.base_url).rstrip("/")
    sent_count = 0
    now = datetime.now(timezone.utc)
    for target in targets:
        if not target.participant or not target.participant.email:
            continue
        raw_token, token_hash = OfficialProfile.generate_reset_token()
        target.reset_token_hash = token_hash
        target.reset_token_expires_at = now + timedelta(days=14)
        setup_url = f"{base_url}/admin/reset-password?token={raw_token}"
        await send_official_invitation_email(
            to_email=target.participant.email,
            name=target.participant.name,
            setup_url=setup_url,
            tournament_name=tournament.name,
            roles=target.role_names,
        )
        sent_count += 1

    await db.commit()
    msg = f"Setup invitation dispatched to {sent_count} official(s)."
    return JSONResponse({"status": "ok", "count": sent_count, "message": msg})


@router.post("/admin/officials/{official_id}/update")
async def admin_officials_update(
    official_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("officials:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Update official details: name, email, title, phone, phone visibility, roles, and school affiliations."""
    tournament = get_current_tenant_tournament(request)
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        data = await request.json()
        name = data.get("name", "").strip()
        email = data.get("email", "").strip().lower()
        title = data.get("title")
        phone = data.get("phone")
        is_phone_public = bool(data.get("is_phone_public", True))
        notes = data.get("notes")
        primary_institution_id = data.get("primary_institution_id") or None
        role_ids = data.get("role_ids", [])
        secondary_affils = data.get("secondary_affiliations", [])
    else:
        form = await request.form()
        name = form.get("name", "").strip()
        email = form.get("email", "").strip().lower()
        title = form.get("title")
        phone = form.get("phone")
        is_phone_public = form.get("is_phone_public") in ("true", "1", "on", True)
        notes = form.get("notes")
        primary_institution_id = form.get("primary_institution_id") or None
        role_ids = form.getlist("role_ids")
        sec_inst_ids = form.getlist("affil_institution_ids")
        sec_tie_types = form.getlist("affil_tie_types")
        secondary_affils = [{"institution_id": i, "tie_type": t} for i, t in zip(sec_inst_ids, sec_tie_types) if i]

    stmt = (
        select(OfficialProfile)
        .options(
            selectinload(OfficialProfile.participant).selectinload(Participant.affiliations).selectinload(ParticipantInstitution.institution),
            selectinload(OfficialProfile.participant).selectinload(Participant.institution),
            selectinload(OfficialProfile.roles),
        )
        .join(Participant, OfficialProfile.participant_id == Participant.id)
        .where(OfficialProfile.id == official_id, Participant.tournament_id == tournament.id)
    )
    target = (await db.execute(stmt)).scalar_one_or_none()
    if not target or not target.participant:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in content_type:
            return JSONResponse({"status": "error", "message": "Official not found."}, status_code=404)
        return RedirectResponse(url="/admin/officials?error=Official+not+found.", status_code=status.HTTP_303_SEE_OTHER)

    part = target.participant
    if name:
        part.name = name
    if email:
        part.email = email
    clean_phone = phone.strip() if phone and phone.strip() else None
    target.phone = clean_phone
    part.phone_number = clean_phone
    target.title = title.strip() if title and title.strip() else None
    target.is_phone_public = is_phone_public
    if notes is not None:
        target.notes = notes

    # Update roles
    if role_ids is not None:
        roles_stmt = select(Role).where(Role.id.in_(role_ids), Role.tournament_id == tournament.id)
        selected_roles = (await db.execute(roles_stmt)).scalars().all()
        target.roles = list(selected_roles)

    # Synchronize primary institution & affiliation
    part.institution_id = primary_institution_id
    if primary_institution_id:
        primary_aff = next((a for a in part.affiliations if a.is_primary), None)
        if primary_aff:
            primary_aff.institution_id = primary_institution_id
        else:
            part.affiliations.append(
                ParticipantInstitution(
                    institution_id=primary_institution_id,
                    is_primary=True,
                    tie_type="represents",
                    clash_policy="hard",
                )
            )
    else:
        for aff in list(part.affiliations):
            if aff.is_primary:
                await db.delete(aff)
                part.affiliations.remove(aff)

    # Synchronize secondary affiliations without overwriting existing retained ties
    desired_secondary: list[tuple[str, str]] = []
    seen_sec: set[tuple[str, str]] = set()
    for sec in secondary_affils:
        inst_id = sec.get("institution_id")
        tie_type = sec.get("tie_type", "alumnus")
        if inst_id and inst_id != primary_institution_id:
            pair = (inst_id, tie_type)
            if pair not in seen_sec:
                seen_sec.add(pair)
                desired_secondary.append(pair)

    # 1. Remove only secondary affiliations that the user actually removed/deleted
    for aff in list(part.affiliations):
        if not aff.is_primary:
            if (aff.institution_id, aff.tie_type) not in seen_sec:
                await db.delete(aff)
                part.affiliations.remove(aff)

    # 2. Add any newly added secondary affiliations that do not already exist on participant
    existing_sec_keys = {(a.institution_id, a.tie_type) for a in part.affiliations if not a.is_primary}
    for inst_id, tie_type in desired_secondary:
        if (inst_id, tie_type) not in existing_sec_keys:
            part.affiliations.append(
                ParticipantInstitution(
                    institution_id=inst_id,
                    is_primary=False,
                    tie_type=tie_type,
                    clash_policy="soft" if tie_type in ("alumnus", "former_member") else "hard",
                )
            )
            existing_sec_keys.add((inst_id, tie_type))

    await db.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in content_type:
        return JSONResponse({
            "status": "ok",
            "message": f"Official {part.name} updated successfully.",
            "official": {
                "id": target.id,
                "name": part.name,
                "email": part.email,
                "title": target.title,
                "phone": target.phone,
                "is_phone_public": target.is_phone_public,
                "role_names": target.role_names,
            }
        })

    return RedirectResponse(
        url=f"/admin/officials?msg=Official+{part.name.replace(' ', '+')}+updated+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/officials/{official_id}/delete")
async def admin_officials_delete(
    official_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("officials:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Delete an official and their administrator capabilities from the tournament."""
    tournament = get_current_tenant_tournament(request)
    stmt = (
        select(OfficialProfile)
        .options(selectinload(OfficialProfile.participant))
        .where(
            OfficialProfile.id == official_id,
        )
    )
    target = (await db.execute(stmt)).scalar_one_or_none()
    if not target or target.participant.tournament_id != tournament.id:
        raise HTTPException(status_code=404, detail="Official profile not found")

    # Safety check: Cannot delete self
    caller_profile = official.get("official_profile") if official else None
    if caller_profile and caller_profile.id == target.id:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"status": "error", "message": "You cannot delete your own active administrator account."}, status_code=400)
        return RedirectResponse(
            url="/admin/officials?error=You+cannot+delete+your+own+active+administrator+account.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    part = target.participant
    await db.delete(part)
    await db.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"status": "ok", "message": f"Official {part.name} deleted successfully."})

    return RedirectResponse(
        url=f"/admin/officials?msg=Official+{part.name.replace(' ', '+')}+deleted+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/officials/bulk-delete")
async def admin_officials_bulk_delete(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("officials:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk delete selected officials."""
    tournament = get_current_tenant_tournament(request)
    if "application/json" in request.headers.get("content-type", ""):
        body = await request.json()
        official_ids = body.get("official_ids") or []
    else:
        form_data = await request.form()
        official_ids = form_data.getlist("official_ids")

    if not official_ids:
        return JSONResponse({"status": "error", "message": "No officials selected."}, status_code=400)

    caller_profile = official.get("official_profile") if official else None
    current_off_id = caller_profile.id if caller_profile else None
    filtered_ids = [oid for oid in official_ids if oid != current_off_id]

    if not filtered_ids:
        return JSONResponse({"status": "error", "message": "Cannot delete your own active administrator account."}, status_code=400)

    stmt = (
        select(OfficialProfile)
        .options(selectinload(OfficialProfile.participant))
        .where(OfficialProfile.id.in_(filtered_ids))
    )
    targets = list((await db.scalars(stmt)).all())

    count = 0
    for t in targets:
        if t.participant.tournament_id == tournament.id:
            await db.delete(t.participant)
            count += 1

    await db.commit()
    return JSONResponse({"status": "ok", "message": f"Successfully deleted {count} official(s)."})


@router.get("/admin/officials/export.xlsx")
async def admin_officials_export_excel(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("officials:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Download an Excel spreadsheet (.xlsx) of all tournament officials."""
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    tournament = get_current_tenant_tournament(request)
    stmt = (
        select(OfficialProfile)
        .join(Participant, OfficialProfile.participant_id == Participant.id)
        .options(
            selectinload(OfficialProfile.participant).selectinload(Participant.institution),
            selectinload(OfficialProfile.roles),
        )
        .where(Participant.tournament_id == tournament.id)
        .order_by(Participant.name)
    )
    officials_list = (await db.execute(stmt)).scalars().all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Officials"

    header_fill = PatternFill(start_color="4A3A35", end_color="4A3A35", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    thin_border = Border(
        left=Side(style="thin", color="E0D9D1"),
        right=Side(style="thin", color="E0D9D1"),
        top=Side(style="thin", color="E0D9D1"),
        bottom=Side(style="thin", color="E0D9D1"),
    )

    headers = ["Full Name", "Email", "Roles", "Institution", "Status", "Notes"]
    ws.append(headers)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center" if cell.value != "Full Name" else "left", vertical="center")

    for off in officials_list:
        p = off.participant
        role_str = ", ".join(off.role_names) if off.role_names else (off.role.value if off.role else "Unassigned")
        inst_str = p.institution.name if p and p.institution else ""
        status_str = "Active" if off.password_hash else "Pending Setup"
        ws.append([
            p.name if p else "",
            p.email if p else "",
            role_str,
            inst_str,
            status_str,
            off.notes or "",
        ])

    for row in ws.iter_rows(min_row=2, max_row=len(officials_list) + 1, min_col=1, max_col=6):
        for idx, cell in enumerate(row):
            cell.font = data_font
            cell.border = thin_border
            if idx in (4,):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = col[0].column_letter
        ws.column_dimensions[col_letter].width = max(max_len + 4, 14)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"{tournament.slug}-officials.xlsx"
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@router.post("/admin/officials/import")
async def admin_officials_import_excel(
    request: Request,
    file: UploadFile = File(...),
    official: Dict[str, Any] = Depends(require_permission("officials:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Import tournament officials from an uploaded .xlsx or .csv spreadsheet."""
    import io
    import csv
    import openpyxl

    tournament = get_current_tenant_tournament(request)
    filename = (file.filename or "").lower()
    content = await file.read()

    rows = []
    if filename.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        for r in reader:
            rows.append({k.strip().lower(): (v or "").strip() for k, v in r.items() if k})
    else:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        ws = wb.active
        headers = [str(c.value or "").strip().lower() for c in ws[1]]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if any(row):
                row_dict = {}
                for h, val in zip(headers, row):
                    if h:
                        row_dict[h] = str(val or "").strip()
                rows.append(row_dict)

    if not rows:
        return JSONResponse({"status": "error", "message": "Spreadsheet is empty or has invalid headers."}, status_code=400)

    # Ensure tournament roles exist
    available_roles = await ensure_tournament_roles_and_permissions(db, tournament.id)
    role_map = {r.name.lower(): r for r in available_roles}
    role_alias_map = {
        "tab": "Tab Director",
        "tab director": "Tab Director",
        "director": "Tournament Director",
        "tournament director": "Tournament Director",
        "ca": "Chief Adjudicator (CA)",
        "chief adjudicator": "Chief Adjudicator (CA)",
        "dca": "Deputy CA (DCA)",
        "deputy ca": "Deputy CA (DCA)",
        "equity": "Equity Officer",
        "equity officer": "Equity Officer",
        "org comm": "Organization Committee",
        "org_comm": "Organization Committee",
        "organizing committee": "Organization Committee",
        "organization committee": "Organization Committee",
    }

    base_url = str(request.base_url).rstrip("/")
    now = datetime.now(timezone.utc)
    imported_count = 0
    updated_count = 0

    for r in rows:
        name = r.get("full name") or r.get("name")
        email = r.get("email")
        if not name or not email or "@" not in email:
            continue
        clean_name = name.strip()
        clean_email = email.strip().lower()

        # Find or create Participant
        stmt_p = (
            select(Participant)
            .options(selectinload(Participant.official_profile).selectinload(OfficialProfile.roles))
            .where(Participant.tournament_id == tournament.id, Participant.email == clean_email)
        )
        participant = (await db.execute(stmt_p)).scalar_one_or_none()

        inst_str = r.get("institution") or r.get("school") or r.get("representing")
        inst_id = None
        if inst_str:
            norm_inst = normalize_institution_name(inst_str)
            stmt_i = select(Institution).where(
                Institution.tournament_id == tournament.id,
                Institution.name_normalized == norm_inst,
            )
            inst_obj = (await db.execute(stmt_i)).scalar_one_or_none()
            if not inst_obj:
                inst_obj = Institution(
                    tournament_id=tournament.id,
                    name=inst_str.strip(),
                    code=inst_str.strip()[:4].upper(),
                )
                db.add(inst_obj)
                await db.flush()
            inst_id = inst_obj.id

        is_new = False
        if not participant:
            is_new = True
            participant = Participant(
                tournament_id=tournament.id,
                institution_id=inst_id,
                name=clean_name,
                email=clean_email,
            )
            db.add(participant)
            await db.flush()
        elif inst_id and not participant.institution_id:
            participant.institution_id = inst_id

        # Profile
        if not participant.official_profile:
            is_new = True
            raw_token, token_hash = OfficialProfile.generate_reset_token()
            prof = OfficialProfile(
                notes=r.get("notes"),
                reset_token_hash=token_hash,
                reset_token_expires_at=now + timedelta(days=14),
            )
            participant.official_profile = prof
            # Dispatch invite email for newly created official
            setup_url = f"{base_url}/admin/reset-password?token={raw_token}"
            await send_official_invitation_email(
                to_email=clean_email,
                name=clean_name,
                setup_url=setup_url,
                tournament_name=tournament.name,
                roles=[],
            )
        else:
            prof = participant.official_profile
            if r.get("notes"):
                prof.notes = r.get("notes")

        # Map and assign roles
        roles_raw = r.get("roles") or r.get("role") or ""
        if roles_raw:
            role_tokens = [tok.strip().lower() for tok in roles_raw.replace(";", ",").split(",") if tok.strip()]
            for tok in role_tokens:
                target_role_name = role_alias_map.get(tok, tok)
                matched_role = role_map.get(target_role_name.lower())
                if matched_role and matched_role not in prof.roles:
                    prof.roles.append(matched_role)

        if is_new:
            imported_count += 1
        else:
            updated_count += 1

    await db.commit()
    msg = f"Import completed: {imported_count} new official(s) added, {updated_count} updated."
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JSONResponse({"status": "ok", "message": msg, "imported": imported_count, "updated": updated_count})

    return RedirectResponse(
        url=f"/admin/officials?msg={msg.replace(' ', '+')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# Password Setup & Reset Pages
@router.get("/admin/reset-password", response_class=HTMLResponse)
async def admin_reset_password_page(
    request: Request,
    token: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Render password setup / reset view on tenant subdomain."""
    tournament = get_current_tenant_tournament(request)
    error = None
    target_official = None

    if not token or not token.strip():
        error = "No password setup token provided. Please check the link in your invitation email."
    else:
        token_hash = OfficialProfile.hash_reset_token(token)
        now = datetime.now(timezone.utc)
        stmt = (
            select(OfficialProfile)
            .options(selectinload(OfficialProfile.participant), selectinload(OfficialProfile.roles))
            .join(Participant, OfficialProfile.participant_id == Participant.id)
            .where(
                OfficialProfile.reset_token_hash == token_hash,
                Participant.tournament_id == tournament.id,
            )
        )
        res = await db.execute(stmt)
        target_official = res.scalar_one_or_none()
        if not target_official:
            error = "Invalid or expired password setup link. Please contact tournament tab staff for a new invitation."
        elif target_official.reset_token_expires_at and target_official.reset_token_expires_at < now:
            error = "This password setup link has expired. Please request a new setup link."

    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/reset_password.html",
        context={
            "tournament": tournament,
            "token": token or "",
            "official_profile": target_official,
            "error": error,
            "page_title": f"Set Password — {tournament.name}",
        },
    )


@router.post("/admin/reset-password")
async def admin_reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Establish official password using single-use setup token."""
    tournament = get_current_tenant_tournament(request)
    if password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="tenant/admin/reset_password.html",
            context={
                "tournament": tournament,
                "token": token,
                "error": "Passwords do not match. Please re-enter both fields.",
                "page_title": f"Set Password — {tournament.name}",
            },
            status_code=400,
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            request=request,
            name="tenant/admin/reset_password.html",
            context={
                "tournament": tournament,
                "token": token,
                "error": "Password must be at least 8 characters in length.",
                "page_title": f"Set Password — {tournament.name}",
            },
            status_code=400,
        )

    token_hash = OfficialProfile.hash_reset_token(token)
    now = datetime.now(timezone.utc)
    stmt = (
        select(OfficialProfile)
        .options(selectinload(OfficialProfile.participant))
        .join(Participant, OfficialProfile.participant_id == Participant.id)
        .where(
            OfficialProfile.reset_token_hash == token_hash,
            Participant.tournament_id == tournament.id,
        )
    )
    res = await db.execute(stmt)
    target_official = res.scalar_one_or_none()
    if not target_official or (target_official.reset_token_expires_at and target_official.reset_token_expires_at < now):
        return templates.TemplateResponse(
            request=request,
            name="tenant/admin/reset_password.html",
            context={
                "tournament": tournament,
                "token": token,
                "error": "This password setup link is invalid or has expired. Please contact tab staff.",
                "page_title": f"Set Password — {tournament.name}",
            },
            status_code=400,
        )

    target_official.set_password(password)
    target_official.is_active = True
    await db.commit()

    return RedirectResponse(
        url="/admin/login?msg=Password+set+successfully.+Please+sign+in+with+your+new+credentials.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# 7. Authorization & RBAC
@router.get("/admin/authorization", response_class=HTMLResponse)
async def admin_authorization_page(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("authorization:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Render Tab Room Authorization: Roles, Permissions matrix, and Staff Assignments."""
    tournament = get_current_tenant_tournament(request)
    msg = request.query_params.get("msg")
    error = request.query_params.get("error")

    roles = await ensure_tournament_roles_and_permissions(db, tournament.id)

    perm_stmt = select(Permission).order_by(Permission.category, Permission.name)
    all_permissions = (await db.execute(perm_stmt)).scalars().all()
    permissions_by_category = defaultdict(list)
    for p in all_permissions:
        permissions_by_category[p.category].append(p)

    stmt_officials = (
        select(OfficialProfile)
        .join(Participant, OfficialProfile.participant_id == Participant.id)
        .options(
            selectinload(OfficialProfile.participant),
            selectinload(OfficialProfile.roles),
        )
        .where(Participant.tournament_id == tournament.id)
        .order_by(Participant.name)
    )
    officials_list = (await db.execute(stmt_officials)).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/authorization.html",
        context={
            "tournament": tournament,
            "official": official,
            "roles": roles,
            "all_permissions": all_permissions,
            "permissions_by_category": dict(permissions_by_category),
            "officials": officials_list,
            "msg": msg,
            "error": error,
            "page_title": f"Roles & Authorization — {tournament.name}",
        },
    )


@router.post("/admin/authorization/roles")
async def admin_authorization_create_role(
    request: Request,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    permission_codes: List[str] = Form(default=[]),
    official: Dict[str, Any] = Depends(require_permission("authorization:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new custom tournament role with selected permissions."""
    tournament = get_current_tenant_tournament(request)
    content_type = request.headers.get("content-type", "")
    
    clean_name = (name or "").strip()
    clean_desc = (description or "").strip() if description else None
    codes = list(permission_codes)

    if "application/json" in content_type:
        try:
            data = await request.json()
            if "name" in data:
                clean_name = str(data.get("name") or "").strip()
            if "description" in data:
                clean_desc = str(data.get("description") or "").strip() or None
            if "permission_codes" in data:
                codes = data.get("permission_codes") or []
        except Exception:
            pass

    if not clean_name:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in content_type:
            return JSONResponse({"status": "error", "message": "Role name is required."}, status_code=400)
        raise HTTPException(status_code=400, detail="Role name is required.")

    existing = (await db.execute(select(Role).where(Role.tournament_id == tournament.id, Role.name.ilike(clean_name)))).scalar_one_or_none()
    if existing:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in content_type:
            return JSONResponse({"status": "error", "message": f"Role '{clean_name}' already exists."}, status_code=400)
        return RedirectResponse(
            url=f"/admin/authorization?error=Role+with+name+{clean_name}+already+exists.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    new_role = Role(
        tournament_id=tournament.id,
        name=clean_name,
        description=clean_desc,
        is_system=False,
    )
    if codes:
        perms = (await db.execute(select(Permission).where(Permission.code.in_(codes)))).scalars().all()
        new_role.permissions.extend(perms)

    db.add(new_role)
    await db.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in content_type:
        return JSONResponse({"status": "ok", "message": f"Role '{clean_name}' created successfully.", "role_id": new_role.id})

    return RedirectResponse(
        url=f"/admin/authorization?msg=Role+{clean_name}+created+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/authorization/roles/{role_id}/permissions")
async def admin_authorization_update_role_permissions(
    role_id: str,
    request: Request,
    permission_codes: List[str] = Form(default=[]),
    official: Dict[str, Any] = Depends(require_permission("authorization:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Update permissions associated with a tournament role."""
    tournament = get_current_tenant_tournament(request)
    stmt = select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id, Role.tournament_id == tournament.id)
    role_obj = (await db.execute(stmt)).scalar_one_or_none()
    if not role_obj:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse({"status": "error", "message": "Role not found."}, status_code=404)
        raise HTTPException(status_code=404, detail="Role not found.")

    content_type = request.headers.get("content-type", "")
    codes = list(permission_codes)
    if "application/json" in content_type:
        try:
            data = await request.json()
            if "permission_codes" in data:
                codes = data.get("permission_codes") or []
        except Exception:
            pass

    new_perms = (await db.execute(select(Permission).where(Permission.code.in_(codes)))).scalars().all()
    role_obj.permissions = list(new_perms)
    await db.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in content_type:
        return JSONResponse({"status": "ok", "message": f"Permissions updated for {role_obj.name}."})

    return RedirectResponse(
        url=f"/admin/authorization?msg=Permissions+updated+for+{role_obj.name}.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/authorization/officials/{official_id}/roles")
async def admin_authorization_update_official_roles(
    official_id: str,
    request: Request,
    role_ids: List[str] = Form(default=[]),
    official: Dict[str, Any] = Depends(require_permission("authorization:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Update role assignments for a tournament official."""
    tournament = get_current_tenant_tournament(request)
    stmt = (
        select(OfficialProfile)
        .options(selectinload(OfficialProfile.roles), selectinload(OfficialProfile.participant))
        .join(Participant, OfficialProfile.participant_id == Participant.id)
        .where(OfficialProfile.id == official_id, Participant.tournament_id == tournament.id)
    )
    off_obj = (await db.execute(stmt)).scalar_one_or_none()
    if not off_obj:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse({"status": "error", "message": "Official profile not found."}, status_code=404)
        raise HTTPException(status_code=404, detail="Official profile not found.")

    content_type = request.headers.get("content-type", "")
    target_ids = list(role_ids)
    if "application/json" in content_type:
        try:
            data = await request.json()
            if "role_ids" in data:
                target_ids = data.get("role_ids") or []
        except Exception:
            pass

    new_roles = (await db.execute(select(Role).where(Role.id.in_(target_ids), Role.tournament_id == tournament.id))).scalars().all()
    off_obj.roles = list(new_roles)
    await db.commit()

    name = off_obj.participant.name if off_obj.participant else "Official"
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in content_type:
        return JSONResponse({
            "status": "ok",
            "message": f"Roles updated for {name}.",
            "role_names": off_obj.role_names,
            "permissions_count": len(off_obj.permission_codes),
        })

    return RedirectResponse(
        url=f"/admin/authorization?msg=Roles+updated+for+{name}.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# 8. Institutions Directory & Delegation Management
@router.get("/admin/institutions", response_class=HTMLResponse)
async def admin_institutions_page(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("institutions:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Render Tab Room institutions directory with delegation stats, merge, and export/import."""
    tournament = get_current_tenant_tournament(request)
    msg = request.query_params.get("msg")
    error = request.query_params.get("error")

    institutions_list = await get_tournament_institutions_with_stats(db, tournament.id)

    # Collect unique regions across tournament institutions and database catalog
    region_set = set()
    for inst in institutions_list:
        if inst.get("region_display"):
            region_set.add(inst["region_display"])
    reg_stmt = select(Institution.region).where(Institution.region.isnot(None)).distinct()
    reg_res = await db.execute(reg_stmt)
    for r in reg_res.all():
        if r[0] and r[0].strip():
            region_set.add(r[0].strip().title())
    existing_regions = sorted(list(region_set))

    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/institutions.html",
        context={
            "tournament": tournament,
            "official": official,
            "institutions": institutions_list,
            "countries": COUNTRY_CATALOG,
            "regions": existing_regions,
            "msg": msg,
            "error": error,
            "page_title": f"Institutions & Delegations — {tournament.name}",
        },
    )


@router.get("/admin/institutions/search")
async def admin_institutions_search(
    request: Request,
    q: str = Query("", min_length=1),
    official: Dict[str, Any] = Depends(require_permission("institutions:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Combobox live search: query existing institutions matching name or code across DB."""
    clean_q = q.strip().lower()
    if not clean_q:
        return JSONResponse([])

    stmt = (
        select(Institution)
        .where(
            or_(
                Institution.name.ilike(f"%{clean_q}%"),
                Institution.code.ilike(f"%{clean_q}%"),
                Institution.country.ilike(f"%{clean_q}%"),
                Institution.region.ilike(f"%{clean_q}%"),
            )
        )
        .limit(10)
    )
    institutions = (await db.execute(stmt)).scalars().all()

    results = []
    seen_names = set()
    for inst in institutions:
        if inst.name.lower() in seen_names:
            continue
        seen_names.add(inst.name.lower())
        c_info = get_country_info(inst.country)
        results.append({
            "id": inst.id,
            "name": inst.name,
            "code": inst.code or "",
            "country": inst.country or "",
            "country_name": c_info["name"],
            "flag": c_info["flag"],
            "region": inst.region or "",
            "region_display": inst.region.title() if inst.region else "",
        })

    return JSONResponse(results)


@router.post("/admin/institutions")
async def admin_institutions_register(
    request: Request,
    name: str = Form(...),
    code: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    official: Dict[str, Any] = Depends(require_permission("institutions:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Register an institution for the tournament with autocomplete normalization."""
    tournament = get_current_tenant_tournament(request)
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Institution name is required.")

    clean_code = code.strip().upper() if code and code.strip() else clean_name[:4].upper()
    clean_country = normalize_country(country)
    clean_region = normalize_region(region)

    # Check for existing institution in tournament with same name
    stmt = select(Institution).where(
        Institution.tournament_id == tournament.id,
        Institution.name.ilike(clean_name),
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse({"status": "error", "message": f"Institution '{clean_name}' already exists in this tournament."}, status_code=400)
        return RedirectResponse(url=f"/admin/institutions?error=Institution+{clean_name}+already+exists.", status_code=status.HTTP_303_SEE_OTHER)

    inst = Institution(
        tournament_id=tournament.id,
        name=clean_name,
        code=clean_code,
        country=clean_country,
        region=clean_region,
    )
    db.add(inst)
    await db.commit()
    await db.refresh(inst)

    c_info = get_country_info(inst.country)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JSONResponse({
            "status": "ok",
            "message": "Institution registered successfully.",
            "institution": {
                "id": inst.id,
                "name": inst.name,
                "code": inst.code,
                "country": inst.country or "",
                "country_name": c_info["name"],
                "flag": c_info["flag"],
                "region": inst.region or "",
                "region_display": inst.region.title() if inst.region else "",
                "speakers_count": 0,
                "judges_count": 0,
                "total_count": 0,
            }
        })

    return RedirectResponse(
        url="/admin/institutions?msg=Institution+registered+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/institutions/{institution_id}/update")
async def admin_institutions_update(
    institution_id: str,
    request: Request,
    name: str = Form(...),
    code: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    official: Dict[str, Any] = Depends(require_permission("institutions:manage")),
    db: AsyncSession = Depends(get_db),
):
    """In-place AJAX update for institution properties."""
    tournament = get_current_tenant_tournament(request)
    stmt = select(Institution).where(
        Institution.id == institution_id,
        or_(Institution.tournament_id == tournament.id, Institution.tournament_id.is_(None)),
    )
    inst = (await db.execute(stmt)).scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=404, detail="Institution not found")

    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Institution name is required.")

    inst.name = clean_name
    inst.code = code.strip().upper() if code and code.strip() else inst.code
    inst.country = normalize_country(country)
    inst.region = normalize_region(region)
    inst.tournament_id = tournament.id

    await db.commit()
    await db.refresh(inst)

    c_info = get_country_info(inst.country)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JSONResponse({
            "status": "ok",
            "message": "Institution updated successfully.",
            "institution": {
                "id": inst.id,
                "name": inst.name,
                "code": inst.code,
                "country": inst.country or "",
                "country_name": c_info["name"],
                "flag": c_info["flag"],
                "region": inst.region or "",
                "region_display": inst.region.title() if inst.region else "",
            }
        })

    return RedirectResponse(
        url="/admin/institutions?msg=Institution+updated+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/institutions/{institution_id}/delete")
async def admin_institutions_delete(
    institution_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("institutions:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Delete an institution and decouple affiliated participants."""
    tournament = get_current_tenant_tournament(request)
    stmt = select(Institution).where(
        Institution.id == institution_id,
        or_(Institution.tournament_id == tournament.id, Institution.tournament_id.is_(None)),
    )
    inst = (await db.execute(stmt)).scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=404, detail="Institution not found")

    # Unlink participants where this was primary
    await db.execute(
        update(Participant)
        .where(Participant.tournament_id == tournament.id, Participant.institution_id == inst.id)
        .values(institution_id=None)
    )

    await db.delete(inst)
    await db.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JSONResponse({"status": "ok", "message": "Institution deleted successfully.", "id": institution_id})

    return RedirectResponse(
        url="/admin/institutions?msg=Institution+deleted+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/institutions/bulk-delete")
async def admin_institutions_bulk_delete(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("institutions:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk delete multiple institutions and unlink affiliated participants safely."""
    tournament = get_current_tenant_tournament(request)
    data = await request.json()
    institution_ids = data.get("institution_ids", [])
    if not institution_ids:
        return JSONResponse({"status": "error", "message": "No institutions selected for deletion."}, status_code=400)

    # 1. Unlink primary institution from participants in this tournament
    await db.execute(
        update(Participant)
        .where(
            Participant.tournament_id == tournament.id,
            Participant.institution_id.in_(institution_ids),
        )
        .values(institution_id=None)
    )

    # 2. Delete secondary affiliations in participant_institutions
    await db.execute(
        delete(ParticipantInstitution)
        .where(ParticipantInstitution.institution_id.in_(institution_ids))
    )

    # 3. Delete the institutions
    stmt = (
        delete(Institution)
        .where(
            Institution.id.in_(institution_ids),
            or_(Institution.tournament_id == tournament.id, Institution.tournament_id.is_(None)),
        )
    )
    result = await db.execute(stmt)
    await db.commit()

    deleted_count = result.rowcount or len(institution_ids)
    return JSONResponse({
        "status": "ok",
        "deleted_count": deleted_count,
        "message": f"Successfully deleted {deleted_count} institution(s).",
    })


@router.post("/admin/institutions/merge")
async def admin_institutions_merge(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("institutions:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Merge two or more institutions together, uniting participants into a unified institution."""
    tournament = get_current_tenant_tournament(request)

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
        source_ids = data.get("source_ids", [])
        target_name = (data.get("target_name") or "").strip()
        target_code = (data.get("target_code") or "").strip().upper()
        target_country = data.get("target_country")
        target_region = data.get("target_region")
    else:
        form = await request.form()
        source_ids = form.getlist("source_ids")
        target_name = (form.get("target_name") or "").strip()
        target_code = (form.get("target_code") or "").strip().upper()
        target_country = form.get("target_country")
        target_region = form.get("target_region")

    if len(source_ids) < 2:
        msg = "Please select at least 2 institutions to merge."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse({"status": "error", "message": msg}, status_code=400)
        return RedirectResponse(url=f"/admin/institutions?error={msg.replace(' ', '+')}", status_code=status.HTTP_303_SEE_OTHER)

    if not target_name:
        msg = "Target institution name is required."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse({"status": "error", "message": msg}, status_code=400)
        return RedirectResponse(url=f"/admin/institutions?error={msg.replace(' ', '+')}", status_code=status.HTTP_303_SEE_OTHER)

    clean_country = normalize_country(target_country)
    clean_region = normalize_region(target_region)
    target_norm = normalize_institution_name(target_name)

    stmt = select(Institution).where(
        Institution.id.in_(source_ids),
        or_(Institution.tournament_id == tournament.id, Institution.tournament_id.is_(None)),
    )
    sources = (await db.execute(stmt)).scalars().all()
    if len(sources) < 2:
        return JSONResponse({"status": "error", "message": "At least 2 valid institutions must be selected."}, status_code=400)

    # Check if an institution with target_normalized already exists in this tournament
    existing_target_stmt = select(Institution).where(
        Institution.tournament_id == tournament.id,
        Institution.name_normalized == target_norm,
    )
    target_inst = (await db.execute(existing_target_stmt)).scalar_one_or_none()

    if target_inst:
        primary_inst = target_inst
        other_sources = [s for s in sources if s.id != target_inst.id]
    else:
        primary_inst = sources[0]
        other_sources = sources[1:]

    other_source_ids = [s.id for s in other_sources]
    merged_id = primary_inst.id

    # 1. Update Participant primary institution_id
    if other_source_ids:
        await db.execute(
            update(Participant)
            .where(
                Participant.tournament_id == tournament.id,
                Participant.institution_id.in_(other_source_ids),
            )
            .values(institution_id=merged_id)
        )

        # 2. Update ParticipantInstitution M:N affiliations, avoiding duplicates
        existing_affil_keys = set(
            (await db.execute(
                select(ParticipantInstitution.participant_id, ParticipantInstitution.tie_type)
                .where(ParticipantInstitution.institution_id == merged_id)
            )).all()
        )

        other_affils = (
            await db.execute(
                select(ParticipantInstitution)
                .where(ParticipantInstitution.institution_id.in_(other_source_ids))
            )
        ).scalars().all()

        for aff in other_affils:
            key = (aff.participant_id, aff.tie_type)
            if key in existing_affil_keys:
                await db.delete(aff)
            else:
                aff.institution_id = merged_id
                existing_affil_keys.add(key)

        # 3. Delete old merged-from source institutions
        for s in other_sources:
            await db.delete(s)

        # Flush deletions immediately so PostgreSQL/SQLite frees up unique constraints
        await db.flush()

    # 4. Update primary institution attributes safely
    primary_inst.name = target_name
    primary_inst.name_normalized = target_norm
    if target_code:
        primary_inst.code = target_code
    if clean_country:
        primary_inst.country = clean_country
    if clean_region:
        primary_inst.region = clean_region
    primary_inst.tournament_id = tournament.id

    await db.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in content_type:
        return JSONResponse({
            "status": "ok",
            "message": f"Successfully merged {len(sources)} institutions into '{target_name}'.",
            "merged_id": merged_id,
        })

    return RedirectResponse(
        url=f"/admin/institutions?msg=Successfully+merged+{len(sources)}+institutions.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/admin/institutions/export.xlsx")
async def admin_institutions_export_excel(
    request: Request,
    official: Dict[str, Any] = Depends(require_permission("institutions:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Download an Excel spreadsheet (.xlsx) of all tournament institutions and counts."""
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    tournament = get_current_tenant_tournament(request)
    institutions = await get_tournament_institutions_with_stats(db, tournament.id)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Institutions"

    header_fill = PatternFill(start_color="4A3A35", end_color="4A3A35", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    thin_border = Border(
        left=Side(style="thin", color="E0D9D1"),
        right=Side(style="thin", color="E0D9D1"),
        top=Side(style="thin", color="E0D9D1"),
        bottom=Side(style="thin", color="E0D9D1"),
    )

    headers = ["Name", "Code", "Country", "Region", "Speakers", "Adjudicators", "IAs", "Total Participants"]
    ws.append(headers)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center" if cell.value != "Name" else "left", vertical="center")

    for inst in institutions:
        ws.append([
            inst["name"],
            inst["code"],
            inst["country_name"] or (inst["country"].upper() if inst["country"] else ""),
            inst["region_display"],
            inst["speakers_count"],
            inst["judges_count"],
            inst["ias_count"],
            inst["total_count"],
        ])

    for row in ws.iter_rows(min_row=2, max_row=len(institutions) + 1, min_col=1, max_col=8):
        for idx, cell in enumerate(row):
            cell.font = data_font
            cell.border = thin_border
            if idx in (1, 4, 5, 6, 7):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = col[0].column_letter
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"{tournament.slug}-institutions.xlsx"
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@router.post("/admin/institutions/import")
async def admin_institutions_import_excel(
    request: Request,
    file: UploadFile = File(...),
    official: Dict[str, Any] = Depends(require_permission("institutions:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Import institutions from an uploaded .xlsx or .csv spreadsheet."""
    import io
    import csv
    import openpyxl

    tournament = get_current_tenant_tournament(request)
    filename = (file.filename or "").lower()
    content = await file.read()

    rows = []
    if filename.endswith(".csv"):
        text_content = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text_content))
        for r in reader:
            rows.append({k.lower().strip(): v.strip() for k, v in r.items() if k})
    else:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            ws = wb.active
            header_row = [str(cell.value or "").strip().lower() for cell in ws[1]]
            for row_cells in ws.iter_rows(min_row=2, values_only=True):
                if not any(row_cells):
                    continue
                row_dict = {}
                for idx, val in enumerate(row_cells):
                    if idx < len(header_row) and header_row[idx]:
                        row_dict[header_row[idx]] = str(val or "").strip()
                rows.append(row_dict)
        except Exception as e:
            return RedirectResponse(
                url=f"/admin/institutions?error=Failed+to+read+spreadsheet:+{str(e)}",
                status_code=status.HTTP_303_SEE_OTHER,
            )

    imported_count = 0
    for r in rows:
        name = r.get("name") or r.get("institution") or r.get("institution name")
        if not name:
            continue
        code = r.get("code") or r.get("delegation code") or r.get("abbr")
        country = r.get("country") or r.get("country code") or r.get("nation")
        region = r.get("region") or r.get("continent") or r.get("zone")

        clean_name = name.strip()
        clean_code = code.strip().upper() if code else clean_name[:4].upper()
        clean_country = normalize_country(country)
        clean_region = normalize_region(region)

        norm_name = normalize_institution_name(clean_name)
        stmt = select(Institution).where(
            Institution.tournament_id == tournament.id,
            Institution.name_normalized == norm_name,
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()

        if existing:
            if clean_code and not existing.code:
                existing.code = clean_code
            if clean_country and not existing.country:
                existing.country = clean_country
            if clean_region and not existing.region:
                existing.region = clean_region
        else:
            inst = Institution(
                tournament_id=tournament.id,
                name=clean_name,
                code=clean_code,
                country=clean_country,
                region=clean_region,
            )
            db.add(inst)
            imported_count += 1

    await db.commit()
    return RedirectResponse(
        url=f"/admin/institutions?msg=Successfully+imported+{imported_count}+institutions.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# 8. Rules & Draw Configuration (Merged into Tournament Settings)
@router.get("/admin/rules")
async def admin_rules_page(request: Request):
    """Redirect rules tab into consolidated tournament settings."""
    return RedirectResponse(url="/admin/settings?tab=config", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.post("/admin/rules")
async def admin_rules_save(
    request: Request,
    ballot_mode: str = Form(...),
    draw_method: str = Form(...),
    min_room_size: int = Form(...),
    max_room_size: int = Form(...),
    room_size_preference: str = Form(...),
    panel_size: int = Form(...),
    minimum_panel_size: int = Form(...),
    allow_prelim_ties: bool = Form(False),
    official: Dict[str, Any] = Depends(require_permission("settings:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Save tournament draw rules, panel size floors, and room bounds."""
    tenant_tourn = get_current_tenant_tournament(request)
    stmt = select(Tournament).where(Tournament.id == tenant_tourn.id)
    res = await db.execute(stmt)
    tournament = res.scalar_one()

    tournament.ballot_mode = BallotMode(ballot_mode)
    tournament.draw_method = DrawMethod(draw_method)
    tournament.min_room_size = int(min_room_size)
    tournament.max_room_size = int(max_room_size)
    tournament.room_size_preference = RoomSizePreference(room_size_preference)
    tournament.panel_size = int(panel_size)
    tournament.minimum_panel_size = int(minimum_panel_size)
    tournament.allow_prelim_ties = allow_prelim_ties

    await db.commit()
    return RedirectResponse(
        url="/admin/settings?tab=config&msg=Rules+and+draw+configuration+saved+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )

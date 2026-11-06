"""Tenant subdomain routes for public tournament pages, zero-auth participant portals, and official administration."""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Request, Depends, Form, File, UploadFile, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from sqlalchemy import select, update, delete, or_
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
)
from kwuo.services.storage import (
    save_upload_file,
    delete_stored_file,
    StorageError,
    FileTooLargeError,
    InvalidExtensionError,
)
from kwuo.core.security import (
    create_participant_token,
    decode_participant_token,
    create_official_token,
    decode_official_token,
    verify_password as verify_plain_password,
)
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
    Institution,
    ParticipantInstitution,
    RubricCriterion,
    ScheduleItem,
)
from kwuo.models.attachment import FileAttachment, AttachmentCategory
from kwuo.web.templates import templates

router = APIRouter(tags=["Tenant Subdomain"])


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
    stmt = (
        select(Participant)
        .options(
            selectinload(Participant.speaker_profile),
            selectinload(Participant.judge_profile),
            selectinload(Participant.institution),
            selectinload(Participant.divisions),
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
    """Verify whether caller is authenticated as an official for this tournament."""
    if not getattr(request.state, "is_tenant_domain", False):
        return None
    tournament = getattr(request.state, "tenant_tournament", None)
    if not tournament:
        return None

    # 1. Platform super admin always has official access
    if user and user.is_super_admin:
        return {
            "is_organizer": True,
            "role": "Super Admin",
            "name": user.full_name,
            "email": user.email,
            "official_profile": None,
        }

    # 2. Tournament creator / organizer has full tab room access
    if user and tournament.organizer_id == user.id:
        return {
            "is_organizer": True,
            "role": "Tournament Director",
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
                "name": plat_user.full_name,
                "email": plat_user.email,
                "official_profile": None,
            }
        return None

    stmt = (
        select(OfficialProfile)
        .options(selectinload(OfficialProfile.participant))
        .where(OfficialProfile.id == official_id)
    )
    result = await db.execute(stmt)
    official = result.scalar_one_or_none()

    if not official or not official.is_active:
        return None

    return {
        "is_organizer": False,
        "role": official.role.value.upper(),
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
        "X-WR-TIMEZONE:UTC",
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
):
    """Render public participant directory with filterable speaker and judge tabs."""
    tournament = get_current_tenant_tournament(request)

    speakers = tournament.speakers
    judges = tournament.judges

    # Division filtering
    if div:
        speakers = [s for s in speakers if any(d.name.lower() == div.lower() for d in s.divisions)]
        judges = [j for j in judges if any(d.name.lower() == div.lower() for d in j.divisions)]

    # Search query filtering
    if q and q.strip():
        query = q.strip().lower()
        speakers = [s for s in speakers if query in s.name.lower() or query in s.institution_name.lower()]
        judges = [j for j in judges if query in j.name.lower() or query in j.institution_name.lower()]

    return templates.TemplateResponse(
        request=request,
        name="tenant/participants.html",
        context={
            "tournament": tournament,
            "speakers": speakers,
            "judges": judges,
            "active_role": role,
            "active_division": div,
            "search_query": q or "",
            "divisions": tournament.divisions,
            "user": user,
            "page_title": f"Participants — {tournament.name}",
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
                role=official.role.value,
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


# 1. Tournament Settings
@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings_page(
    request: Request,
    official: Dict[str, Any] = Depends(require_tenant_official),
):
    """Render Tab Room tournament settings form."""
    tournament = get_current_tenant_tournament(request)
    msg = request.query_params.get("msg")
    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/settings.html",
        context={
            "tournament": tournament,
            "official": official,
            "msg": msg,
            "page_title": f"Settings — {tournament.name}",
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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


@router.post("/admin/settings/schedule")
async def admin_settings_add_schedule_item(
    request: Request,
    title: str = Form(...),
    start_time: str = Form(...),
    end_time: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    display_order: int = Form(1),
    official: Dict[str, Any] = Depends(require_tenant_official),
    db: AsyncSession = Depends(get_db),
):
    """Add a new scheduled round or milestone to tournament timetable."""
    tournament = get_current_tenant_tournament(request)
    try:
        st_dt = datetime.fromisoformat(start_time.strip())
        if st_dt.tzinfo is None:
            st_dt = st_dt.replace(tzinfo=timezone.utc)
    except Exception:
        st_dt = datetime.now(timezone.utc)

    end_dt = None
    if end_time and end_time.strip():
        try:
            end_dt = datetime.fromisoformat(end_time.strip())
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

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


@router.post("/admin/settings/schedule/{item_id}/delete")
async def admin_settings_delete_schedule_item(
    item_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_tenant_official),
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


# 2. Documents & Files
@router.get("/admin/documents", response_class=HTMLResponse)
async def admin_documents_page(
    request: Request,
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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


# 4. Speakers Roster
@router.get("/admin/speakers", response_class=HTMLResponse)
async def admin_speakers_page(
    request: Request,
    official: Dict[str, Any] = Depends(require_tenant_official),
):
    """Render Tab Room speakers directory and check-in desk."""
    tournament = get_current_tenant_tournament(request)
    msg = request.query_params.get("msg")
    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/speakers.html",
        context={
            "tournament": tournament,
            "official": official,
            "msg": msg,
            "page_title": f"Speakers Roster — {tournament.name}",
        },
    )


@router.post("/admin/speakers")
async def admin_speakers_register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    division_id: str = Form(...),
    institution_name: Optional[str] = Form(None),
    official: Dict[str, Any] = Depends(require_tenant_official),
    db: AsyncSession = Depends(get_db),
):
    """Register a new competitor with single name, division, and institution."""
    tournament = get_current_tenant_tournament(request)
    clean_name = name.strip()
    clean_email = email.strip().lower()

    # Find or create institution if specified
    inst_id = None
    if institution_name and institution_name.strip():
        inst_clean = institution_name.strip()
        stmt_inst = select(Institution).where(Institution.name == inst_clean)
        res_inst = await db.execute(stmt_inst)
        inst_obj = res_inst.scalar_one_or_none()
        if not inst_obj:
            inst_obj = Institution(name=inst_clean, code=inst_clean[:4].upper())
            db.add(inst_obj)
            await db.flush()
        inst_id = inst_obj.id

    raw_token, token_hash = Participant.generate_token()
    part = Participant(
        tournament_id=tournament.id,
        institution_id=inst_id,
        name=clean_name,
        email=clean_email,
        access_token_hash=token_hash,
    )
    part.speaker_profile = SpeakerProfile()

    # Division association
    stmt_div = select(Division).where(Division.id == division_id, Division.tournament_id == tournament.id)
    res_div = await db.execute(stmt_div)
    div_obj = res_div.scalar_one_or_none()
    if div_obj:
        part.divisions.append(div_obj)

    db.add(part)
    await db.commit()
    return RedirectResponse(
        url="/admin/speakers?msg=Speaker+registered+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/speakers/{participant_id}/toggle-checkin")
async def admin_speakers_toggle_checkin(
    participant_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_tenant_official),
    db: AsyncSession = Depends(get_db),
):
    """Toggle speaker check-in status."""
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
    return RedirectResponse(url="/admin/speakers", status_code=status.HTTP_303_SEE_OTHER)


# 5. Judges & Panels
@router.get("/admin/judges", response_class=HTMLResponse)
async def admin_judges_page(
    request: Request,
    official: Dict[str, Any] = Depends(require_tenant_official),
):
    """Render Tab Room adjudicator pool and panel credentials."""
    tournament = get_current_tenant_tournament(request)
    msg = request.query_params.get("msg")
    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/judges.html",
        context={
            "tournament": tournament,
            "official": official,
            "msg": msg,
            "page_title": f"Judges & Panels — {tournament.name}",
        },
    )


@router.post("/admin/judges")
async def admin_judges_register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    institution_name: Optional[str] = Form(None),
    is_chair_eligible: bool = Form(False),
    is_reserve: bool = Form(False),
    is_independent: bool = Form(False),
    official: Dict[str, Any] = Depends(require_tenant_official),
    db: AsyncSession = Depends(get_db),
):
    """Accredit a new judge in the tournament pool."""
    tournament = get_current_tenant_tournament(request)
    clean_name = name.strip()
    clean_email = email.strip().lower()

    inst_id = None
    if institution_name and institution_name.strip():
        inst_clean = institution_name.strip()
        stmt_inst = select(Institution).where(Institution.name == inst_clean)
        res_inst = await db.execute(stmt_inst)
        inst_obj = res_inst.scalar_one_or_none()
        if not inst_obj:
            inst_obj = Institution(name=inst_clean, code=inst_clean[:4].upper())
            db.add(inst_obj)
            await db.flush()
        inst_id = inst_obj.id

    raw_token, token_hash = Participant.generate_token()
    part = Participant(
        tournament_id=tournament.id,
        institution_id=inst_id,
        name=clean_name,
        email=clean_email,
        access_token_hash=token_hash,
    )
    part.judge_profile = JudgeProfile(
        is_chair_eligible=is_chair_eligible,
        is_reserve=is_reserve,
        is_independent=is_independent,
    )
    db.add(part)
    await db.commit()
    return RedirectResponse(
        url="/admin/judges?msg=Judge+accredited+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/judges/{participant_id}/toggle-checkin")
async def admin_judges_toggle_checkin(
    participant_id: str,
    request: Request,
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
):
    """Render Tab Room staff directory and official password management."""
    tournament = get_current_tenant_tournament(request)
    msg = request.query_params.get("msg")
    return templates.TemplateResponse(
        request=request,
        name="tenant/admin/officials.html",
        context={
            "tournament": tournament,
            "official": official,
            "msg": msg,
            "page_title": f"Officials & Staff — {tournament.name}",
        },
    )


@router.post("/admin/officials")
async def admin_officials_register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    role: str = Form(...),
    password: str = Form(...),
    official: Dict[str, Any] = Depends(require_tenant_official),
    db: AsyncSession = Depends(get_db),
):
    """Register official with role and password credentials."""
    tournament = get_current_tenant_tournament(request)
    clean_name = name.strip()
    clean_email = email.strip().lower()

    part = Participant(
        tournament_id=tournament.id,
        name=clean_name,
        email=clean_email,
    )
    off_profile = OfficialProfile(role=OfficialRole(role))
    off_profile.set_password(password)
    part.official_profile = off_profile

    db.add(part)
    await db.commit()
    return RedirectResponse(
        url="/admin/officials?msg=Official+registered+successfully.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# 7. Institutions Directory & Delegation Management
@router.get("/admin/institutions", response_class=HTMLResponse)
async def admin_institutions_page(
    request: Request,
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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

    stmt = select(Institution).where(
        Institution.id.in_(source_ids),
        or_(Institution.tournament_id == tournament.id, Institution.tournament_id.is_(None)),
    )
    sources = (await db.execute(stmt)).scalars().all()
    if len(sources) < 2:
        return JSONResponse({"status": "error", "message": "At least 2 valid institutions must be selected."}, status_code=400)

    # Retain the first source as the merged target
    primary_inst = sources[0]
    other_sources = sources[1:]
    other_source_ids = [s.id for s in other_sources]

    primary_inst.name = target_name
    primary_inst.code = target_code or primary_inst.code
    primary_inst.country = clean_country or primary_inst.country
    primary_inst.region = clean_region or primary_inst.region
    primary_inst.tournament_id = tournament.id

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
        existing_affils = (
            await db.execute(
                select(ParticipantInstitution.participant_id)
                .where(ParticipantInstitution.institution_id == merged_id)
            )
        ).scalars().all()
        existing_part_set = set(existing_affils)

        other_affils = (
            await db.execute(
                select(ParticipantInstitution)
                .where(ParticipantInstitution.institution_id.in_(other_source_ids))
            )
        ).scalars().all()

        for aff in other_affils:
            if aff.participant_id in existing_part_set:
                await db.delete(aff)
            else:
                aff.institution_id = merged_id
                existing_part_set.add(aff.participant_id)

        # 3. Delete old merged-from source institutions
        for s in other_sources:
            await db.delete(s)

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
    official: Dict[str, Any] = Depends(require_tenant_official),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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

        stmt = select(Institution).where(
            Institution.tournament_id == tournament.id,
            Institution.name.ilike(clean_name),
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
    official: Dict[str, Any] = Depends(require_tenant_official),
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

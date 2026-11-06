"""Tournament provisioning and management routes on apex platform."""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kwuo.core.database import get_db
from kwuo.core.rbac import get_current_user
from kwuo.core.subdomain import slugify, is_valid_slug, is_reserved_slug, get_tournament_url
from kwuo.models.user import User
from kwuo.models.tournament import (
    Tournament,
    TournamentStatus,
    LocationType,
    Division,
    RubricCriterion,
)
from kwuo.web.templates import templates

router = APIRouter(prefix="/tournaments", tags=["Tournaments"])


@router.post("", response_class=HTMLResponse)
async def create_tournament(
    request: Request,
    name: str = Form(...),
    slug: Optional[str] = Form(None),
    location_type: str = Form("PHYSICAL"),
    location: Optional[str] = Form(None),
    start_date_str: Optional[str] = Form(None, alias="start_date"),
    end_date_str: Optional[str] = Form(None, alias="end_date"),
    description: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new tournament from the organizer dashboard."""
    clean_name = name.strip()
    if not clean_name or len(clean_name) < 3:
        raise HTTPException(status_code=400, detail="Tournament name must be at least 3 characters long.")

    # Generate or sanitize slug
    clean_slug = slug.strip().lower() if slug and slug.strip() else slugify(clean_name)

    if not is_valid_slug(clean_slug):
        raise HTTPException(
            status_code=400,
            detail="Slug must be 3-63 characters and contain only lowercase letters, numbers, and hyphens.",
        )

    if is_reserved_slug(clean_slug):
        raise HTTPException(
            status_code=400,
            detail=f"The slug '{clean_slug}' is reserved for platform operations. Please choose another slug.",
        )

    # Check database uniqueness
    existing = await db.scalar(select(Tournament).where(Tournament.slug == clean_slug))
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"A tournament with slug '{clean_slug}' already exists. Please choose a unique slug.",
        )

    # Parse optional dates
    start_date = None
    if start_date_str and start_date_str.strip():
        try:
            start_date = datetime.fromisoformat(start_date_str.strip())
        except ValueError:
            pass

    end_date = None
    if end_date_str and end_date_str.strip():
        try:
            end_date = datetime.fromisoformat(end_date_str.strip())
        except ValueError:
            pass

    # Parse location type
    try:
        loc_type = LocationType(location_type.lower().strip())
    except ValueError:
        loc_type = LocationType.PHYSICAL

    # Create tournament
    tournament = Tournament(
        name=clean_name,
        slug=clean_slug,
        organizer_id=user.id,
        status=TournamentStatus.DRAFT,
        location_type=loc_type,
        location=location.strip() if location and location.strip() else None,
        description=description.strip() if description and description.strip() else None,
        start_date=start_date,
        end_date=end_date,
        base_score=70.0,
        ceiling_score=100.0,
        max_time_penalty=5.0,
    )
    db.add(tournament)
    await db.flush()

    # Automatically seed default "Open" division
    open_division = Division(
        tournament_id=tournament.id,
        name="Open",
        description="General competitive division",
    )
    db.add(open_division)

    # Automatically seed standard criteria
    crit1 = RubricCriterion(tournament_id=tournament.id, name="Content & Argumentation", max_points=10.0, display_order=1)
    crit2 = RubricCriterion(tournament_id=tournament.id, name="Delivery & Style", max_points=10.0, display_order=2)
    crit3 = RubricCriterion(tournament_id=tournament.id, name="Structure & Flow", max_points=5.0, display_order=3)
    crit4 = RubricCriterion(tournament_id=tournament.id, name="Language & Nuance", max_points=5.0, display_order=4)
    db.add_all([crit1, crit2, crit3, crit4])

    await db.commit()

    # If this is an HTMX request, redirect via HX-Redirect header
    if request.headers.get("HX-Request"):
        response = HTMLResponse(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = "/dashboard?msg=Tournament+created+successfully"
        return response

    return RedirectResponse(
        url="/dashboard?msg=Tournament+created+successfully",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{tournament_id}/delete", response_class=HTMLResponse)
async def delete_tournament(
    tournament_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a tournament and its divisions/records."""
    stmt = select(Tournament).where(Tournament.id == tournament_id)
    tournament = await db.scalar(stmt)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Access control: only creator or platform super admin can delete
    if tournament.organizer_id != user.id and not user.is_super_admin:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to delete this tournament.",
        )

    await db.delete(tournament)
    await db.commit()

    if request.headers.get("HX-Request"):
        response = HTMLResponse(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = "/dashboard?msg=Tournament+deleted+successfully"
        return response

    return RedirectResponse(
        url="/dashboard?msg=Tournament+deleted+successfully",
        status_code=status.HTTP_303_SEE_OTHER,
    )

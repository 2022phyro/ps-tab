"""Organizer dashboard routes."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from kwuo.core.database import get_db
from kwuo.core.rbac import get_current_user
from kwuo.models.user import User
from kwuo.models.tournament import Tournament
from kwuo.web.templates import templates

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Render the protected organizer dashboard with tournament list."""
    stmt = (
        select(Tournament)
        .options(
            selectinload(Tournament.divisions),
            selectinload(Tournament.participants),
            selectinload(Tournament.attachments),
        )
        .where(
            Tournament.organizer_id == user.id,
            Tournament.deleted_at.is_(None),
        )
        .order_by(Tournament.created_at.desc())
    )
    result = await db.execute(stmt)
    tournaments = result.scalars().all()

    msg = request.query_params.get("msg")

    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={"request": request, "user": user, "tournaments": tournaments, "msg": msg},
    )

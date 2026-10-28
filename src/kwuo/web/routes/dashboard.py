"""Organizer dashboard routes."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from kwuo.web.templates import templates
from kwuo.core.rbac import get_current_user
from kwuo.models.user import User

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Render the protected organizer dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={"user": user},
    )

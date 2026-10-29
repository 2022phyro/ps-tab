"""Public landing, about, contact, and legal page routes."""

from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from kwuo.web.templates import templates
from kwuo.core.rbac import get_optional_current_user
from kwuo.models.user import User

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render public landing page with features showcase and contact form."""
    msg = request.query_params.get("msg")
    msg_type = request.query_params.get("msg_type", "success")
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"user": user, "msg": msg, "msg_type": msg_type},
    )


@router.get("/about", response_class=HTMLResponse)
async def about_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render comprehensive platform About page."""
    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context={"user": user},
    )


@router.get("/design", response_class=HTMLResponse)
async def design_showcase_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render high-fidelity Kwuo Editorial Design System & Component Specification."""
    return templates.TemplateResponse(
        request=request,
        name="design/index.html",
        context={"user": user},
    )


@router.get("/design/button")
async def design_button_redirect():
    """Redirect legacy /design/button to consolidated /design showcase."""
    return RedirectResponse(url="/design", status_code=status.HTTP_301_MOVED_PERMANENTLY)


@router.get("/contact", response_class=HTMLResponse)
async def contact_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render dedicated contact and tournament inquiry page."""
    msg = request.query_params.get("msg")
    msg_type = request.query_params.get("msg_type", "success")
    return templates.TemplateResponse(
        request=request,
        name="contact.html",
        context={"user": user, "msg": msg, "msg_type": msg_type},
    )


@router.post("/contact")
async def contact_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    subject: str = Form("general"),
    message: str = Form(...),
    organization: Optional[str] = Form(None),
):
    """Handle contact form submissions (HTMX partial or redirect)."""
    # Acknowledge inquiry
    clean_name = name.strip()
    msg = f"Thank you, <strong>{clean_name}</strong>! Your message regarding '{subject}' has been received. Our tabulation team will respond shortly."

    if request.headers.get("HX-Request"):
        return HTMLResponse(
            f'<div class="rounded-xl border border-emerald-300 dark:border-emerald-900/60 bg-emerald-50 dark:bg-emerald-950/40 p-4 text-xs text-emerald-800 dark:text-emerald-300 space-y-1">'
            f'<p class="font-bold text-sm">Message Sent Successfully</p>'
            f'<p>{msg}</p>'
            f'</div>'
        )

    return RedirectResponse(
        url=f"/contact?msg={msg}&msg_type=success",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render platform Privacy Policy."""
    return templates.TemplateResponse(
        request=request,
        name="legal/privacy.html",
        context={"user": user},
    )


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render platform Terms of Service."""
    return templates.TemplateResponse(
        request=request,
        name="legal/terms.html",
        context={"user": user},
    )

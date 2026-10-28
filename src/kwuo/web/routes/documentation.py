"""Dynamic documentation reader routes."""

from typing import Optional
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

from kwuo.web.templates import templates
from kwuo.core.rbac import get_optional_current_user
from kwuo.models.user import User
from kwuo.services.documentation import get_documentation_tree, get_document

router = APIRouter(prefix="/documentation")


@router.get("", response_class=HTMLResponse)
async def documentation_root(
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Redirect to the first documentation page in the tree."""
    tree, flat_docs = get_documentation_tree()
    if flat_docs:
        first_slug = flat_docs[0].slug
        return RedirectResponse(
            url=f"/documentation/{first_slug}",
            status_code=status.HTTP_302_FOUND,
        )

    # Empty documentation folder fallback
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"user": user, "error": "No documentation files found."},
    )


@router.get("/{path:path}", response_class=HTMLResponse)
async def documentation_page(
    path: str,
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Render a specific documentation page with active navigation and outline tracker."""
    doc = get_document(path)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Documentation page '{path}' was not found.",
        )

    tree, _ = get_documentation_tree()

    return templates.TemplateResponse(
        request=request,
        name="documentation/layout.html",
        context={
            "user": user,
            "doc": doc,
            "tree": tree,
        },
    )

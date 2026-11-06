"""File handling and attachment management routes."""

from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Form, File, UploadFile, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kwuo.core.database import get_db
from kwuo.core.rbac import get_current_user, get_optional_current_user
from kwuo.core.typeid import generate_typeid
from kwuo.models.user import User
from kwuo.models.tournament import Tournament
from kwuo.models.attachment import FileAttachment, AttachmentCategory
from kwuo.services.storage import (
    save_upload_file,
    delete_stored_file,
    resolve_file_path,
    StorageError,
    FileTooLargeError,
    InvalidExtensionError,
)

router = APIRouter(tags=["Attachments"])


@router.post("/tournaments/{tournament_id}/attachments", response_class=HTMLResponse)
async def upload_tournament_attachment(
    tournament_id: str,
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(...),
    category: str = Form("general"),
    description: Optional[str] = Form(None),
    task_id: Optional[str] = Form(None),
    is_public: bool = Form(True),
    display_order: int = Form(1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document or material attached to a tournament or a specific task."""
    tournament = await db.scalar(select(Tournament).where(Tournament.id == tournament_id))
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    # Access control: only creator or platform super admin can upload tournament documents
    if tournament.organizer_id != user.id and not user.is_super_admin:
        raise HTTPException(status_code=403, detail="You do not have permission to upload files to this tournament")

    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Document title is required")

    # Parse category
    try:
        cat = AttachmentCategory(category.lower().strip())
    except ValueError:
        cat = AttachmentCategory.GENERAL

    # Generate TypeID for attachment
    att_id = generate_typeid("att")

    try:
        clean_filename, rel_path, file_size, mime_type, file_hash = await save_upload_file(
            tournament_id=tournament.id,
            attachment_id=att_id,
            upload_file=file,
        )
    except InvalidExtensionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except StorageError as e:
        raise HTTPException(status_code=500, detail=f"Storage failure: {str(e)}")

    attachment = FileAttachment(
        id=att_id,
        tournament_id=tournament.id,
        task_id=task_id.strip() if task_id and task_id.strip() else None,
        uploader_id=user.id,
        title=clean_title,
        description=description.strip() if description and description.strip() else None,
        category=cat,
        filename=clean_filename,
        file_path=rel_path,
        file_size=file_size,
        mime_type=mime_type,
        sha256_hash=file_hash,
        is_public=is_public,
        display_order=display_order,
    )
    db.add(attachment)
    await db.commit()

    if request.headers.get("HX-Request"):
        response = HTMLResponse(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = f"/tournaments/{tournament.id}/attachments?msg=File+uploaded+successfully"
        return response

    return RedirectResponse(
        url=f"/tournaments/{tournament.id}/attachments?msg=File+uploaded+successfully",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/files/{attachment_id}/download")
@router.get("/tournaments/{tournament_id}/attachments/{attachment_id}/download")
async def download_attachment(
    attachment_id: str,
    tournament_id: Optional[str] = None,
    inline: bool = Query(False),
    user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Securely stream/download an attachment."""
    stmt = select(FileAttachment).where(FileAttachment.id == attachment_id)
    if tournament_id:
        stmt = stmt.where(FileAttachment.tournament_id == tournament_id)
    
    attachment = await db.scalar(stmt)
    if not attachment:
        raise HTTPException(status_code=404, detail="File attachment not found")

    # If the file is not public, require authenticated user
    if not attachment.is_public:
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required to access this document")
        
        # Check authorization (organizer or super admin)
        tourn = await db.scalar(select(Tournament).where(Tournament.id == attachment.tournament_id))
        if tourn and tourn.organizer_id != user.id and not user.is_super_admin:
            raise HTTPException(status_code=403, detail="You do not have permission to view this private document")

    try:
        physical_path = resolve_file_path(attachment.file_path)
    except StorageError:
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not physical_path.exists() or not physical_path.is_file():
        raise HTTPException(status_code=404, detail="File not found on storage server")

    disposition = "inline" if inline else "attachment"
    return FileResponse(
        path=physical_path,
        media_type=attachment.mime_type,
        filename=attachment.filename,
        content_disposition_type=disposition,
    )


@router.post("/tournaments/{tournament_id}/attachments/{attachment_id}/delete", response_class=HTMLResponse)
async def delete_tournament_attachment(
    tournament_id: str,
    attachment_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an attachment record and remove the file from storage."""
    stmt = select(FileAttachment).where(
        FileAttachment.id == attachment_id,
        FileAttachment.tournament_id == tournament_id,
    )
    attachment = await db.scalar(stmt)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    tournament = await db.scalar(select(Tournament).where(Tournament.id == tournament_id))
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    if tournament.organizer_id != user.id and not user.is_super_admin:
        raise HTTPException(status_code=403, detail="Permission denied")

    # Delete physical file
    delete_stored_file(attachment.file_path)

    # Delete database record
    await db.delete(attachment)
    await db.commit()

    if request.headers.get("HX-Request"):
        response = HTMLResponse(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = f"/tournaments/{tournament.id}/attachments?msg=File+deleted+successfully"
        return response

    return RedirectResponse(
        url=f"/tournaments/{tournament.id}/attachments?msg=File+deleted+successfully",
        status_code=status.HTTP_303_SEE_OTHER,
    )

"""Django-esque Super Admin routes: Model changelists, change forms, bulk & extended actions."""

import json
from typing import List, Optional, Dict, Any
from urllib.parse import urlencode
from datetime import datetime, timezone
import secrets
from fastapi import APIRouter, Request, Depends, Form, Query, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy import select, func, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kwuo.core.database import get_db_session
from kwuo.core.rbac import require_super_admin, get_optional_current_user, get_current_user
from kwuo.core.security import hash_password
from kwuo.models.user import User, UserStatus, Group, GroupPermission, GroupMembership
from kwuo.models.audit import AuditLog, AuditAction, AuditSeverity
from kwuo.services.audit import record_audit_log
from kwuo.admin.site import admin_site
from kwuo.web.templates import templates

router = APIRouter(prefix="/admin")


# =========================================================================
# Admin Index / Dashboard
# =========================================================================

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_index(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Admin Index: routes to tournament tab room on tenant domains, or platform super admin on apex."""
    if getattr(request.state, "is_tenant_domain", False):
        from kwuo.web.routes.tenant import tournament_admin_dashboard
        return await tournament_admin_dashboard(request)

    user = await get_optional_current_user(request, db)
    current_user = await get_current_user(request, user)
    current_admin: User = require_super_admin(current_user)
    app_sections = await admin_site.get_app_sections(db)

    # Calculate platform-wide overview metrics
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    super_admins = (await db.execute(select(func.count(User.id)).where(User.is_super_admin == True))).scalar() or 0
    active_users = (await db.execute(select(func.count(User.id)).where(User.is_active == True))).scalar() or 0
    total_groups = (await db.execute(select(func.count(Group.id)))).scalar() or 0
    total_permissions = (await db.execute(select(func.count(GroupPermission.id)))).scalar() or 0

    stats = {
        "total_users": total_users,
        "super_admins": super_admins,
        "active_users": active_users,
        "total_groups": total_groups,
        "total_permissions": total_permissions,
    }

    # Success/error message from query string if present
    msg = request.query_params.get("msg")
    msg_type = request.query_params.get("msg_type", "success")

    return templates.TemplateResponse(
        request=request,
        name="admin/index.html",
        context={
            "user": current_admin,
            "app_sections": app_sections,
            "current_slug": None,
            "stats": stats,
            "msg": msg,
            "msg_type": msg_type,
            "title": "Site Administration",
        },
    )


# =========================================================================
# Model Changelist View (/admin/{model_slug})
# =========================================================================

@router.get("/{model_slug}", response_class=HTMLResponse)
async def admin_model_changelist(
    model_slug: str,
    request: Request,
    q: Optional[str] = Query(None),
    ordering: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Django-style changelist view with search, filter sidebar, ordering, and bulk actions."""
    model_admin = admin_site.get_model_admin(model_slug)
    if not model_admin:
        raise HTTPException(status_code=404, detail=f"Admin for '{model_slug}' not found")

    # Extract filter params matching model_admin.list_filter
    filters: Dict[str, str] = {}
    for param_name in model_admin.get_list_filter():
        param_val = request.query_params.get(param_name)
        if param_val is not None and param_val != "":
            filters[param_name] = param_val

    items, total_count, total_pages = await model_admin.get_paginated_list(
        db=db,
        search_query=q,
        filters=filters,
        ordering_param=ordering,
        page=page,
    )

    # Format table data
    list_display = model_admin.get_list_display()
    headers = [col.replace("_", " ").title() for col in list_display]

    rows = []
    for item in items:
        row_cells = []
        for col in list_display:
            val = model_admin.format_cell_value(item, col)
            row_cells.append({"column": col, "value": val})
        rows.append({"item": item, "id": getattr(item, "id", None), "cells": row_cells})

    actions = model_admin.get_available_actions()
    all_admins = admin_site.get_all_admins()
    app_sections = await admin_site.get_app_sections(db)
    filter_specs = await model_admin.get_filter_specs(db)

    def make_filter_url(param_name: str, param_val: Optional[str] = None) -> str:
        qp = dict(request.query_params)
        qp.pop("page", None)
        qp.pop("msg", None)
        qp.pop("msg_type", None)
        if param_val is None:
            qp.pop(param_name, None)
        else:
            qp[param_name] = str(param_val)
        qs = urlencode(qp)
        return f"/admin/{model_slug}?{qs}" if qs else f"/admin/{model_slug}"

    # Success/error message from query string if present
    msg = request.query_params.get("msg")
    msg_type = request.query_params.get("msg_type", "success")

    action_verb = "inspect" if getattr(model_admin, "is_read_only", False) else "change"

    return templates.TemplateResponse(
        request=request,
        name="admin/change_list.html",
        context={
            "user": current_admin,
            "model_admin": model_admin,
            "all_admins": all_admins,
            "app_sections": app_sections,
            "current_slug": model_slug,
            "filter_specs": filter_specs,
            "make_filter_url": make_filter_url,
            "headers": headers,
            "list_display": list_display,
            "rows": rows,
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
            "q": q or "",
            "ordering": ordering or "",
            "filters": filters,
            "actions": actions,
            "msg": msg,
            "msg_type": msg_type,
            "title": f"Select {model_admin.verbose_name.lower()} to {action_verb}",
        },
    )


# =========================================================================
# Model Add Form View (/admin/{model_slug}/add)
# =========================================================================

@router.get("/{model_slug}/add", response_class=HTMLResponse)
async def admin_model_add_view(
    model_slug: str,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Django-style Add object view."""
    model_admin = admin_site.get_model_admin(model_slug)
    if not model_admin:
        raise HTTPException(status_code=404, detail=f"Admin for '{model_slug}' not found")

    if not getattr(model_admin, "can_add", True):
        msg = f"Records for {model_admin.verbose_name_plural} are strictly immutable and cannot be added manually."
        return RedirectResponse(
            url=f"/admin/{model_slug}?msg={msg}&msg_type=warning",
            status_code=status.HTTP_302_FOUND,
        )

    # Fetch auxiliary choices if needed
    groups = (await db.execute(select(Group).order_by(Group.name))).scalars().all()
    users = (await db.execute(select(User).order_by(User.first_name, User.last_name))).scalars().all()
    app_sections = await admin_site.get_app_sections(db)

    return templates.TemplateResponse(
        request=request,
        name="admin/change_form.html",
        context={
            "user": current_admin,
            "model_admin": model_admin,
            "app_sections": app_sections,
            "current_slug": model_slug,
            "instance": None,
            "is_add": True,
            "groups": groups,
            "users": users,
            "title": f"Add {model_admin.verbose_name}",
        },
    )


@router.post("/{model_slug}/add")
async def admin_model_add_submit(
    model_slug: str,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Handle creation of new model instance."""
    model_admin = admin_site.get_model_admin(model_slug)
    if not model_admin:
        raise HTTPException(status_code=404, detail=f"Admin for '{model_slug}' not found")

    if not getattr(model_admin, "can_add", True):
        raise HTTPException(status_code=403, detail="Manual creation not permitted for this model.")

    form = await request.form()
    submit_action = form.get("_action", "_save")

    new_obj = None

    if model_slug == "users":
        email = str(form.get("email", "")).strip().lower()
        full_name = str(form.get("full_name", "")).strip()
        raw_password = str(form.get("password", "")).strip()
        is_super = form.get("is_super_admin") is not None
        is_active = form.get("is_active") is not None
        status_val = form.get("status")

        if not email or not full_name:
            raise HTTPException(status_code=400, detail="Email and Full Name are required.")

        # Check existing email
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail=f"User with email '{email}' already exists.")

        pwd_hash = hash_password(raw_password) if raw_password else hash_password(secrets.token_urlsafe(16))
        
        if status_val and status_val in [s.value for s in UserStatus]:
            user_status = UserStatus(status_val)
        else:
            user_status = UserStatus.ACTIVE if is_active else UserStatus.SUSPENDED

        new_obj = User(
            email=email,
            full_name=full_name,
            password_hash=pwd_hash,
            is_super_admin=is_super,
            status=user_status,
            is_verified=True,
        )
        db.add(new_obj)
        await db.flush()

        # Group assignments
        selected_groups = form.getlist("groups")
        for g_id in selected_groups:
            membership = GroupMembership(user_id=new_obj.id, group_id=g_id)
            db.add(membership)
        await db.flush()

    elif model_slug == "groups":
        name = str(form.get("name", "")).strip()
        description = str(form.get("description", "")).strip() or None
        scope_type = str(form.get("scope_type", "global"))
        tourn_id = str(form.get("tournament_id", "")).strip() or None
        scoped_tourn = tourn_id if scope_type == "tournament" else None

        if not name:
            raise HTTPException(status_code=400, detail="Group Name is required.")

        new_obj = Group(
            name=name,
            description=description,
            tournament_id=scoped_tourn,
        )
        db.add(new_obj)
        await db.flush()

    elif model_slug == "group-permissions":
        group_id = str(form.get("group_id", "")).strip()
        permission = str(form.get("permission", "")).strip()
        if not group_id or not permission:
            raise HTTPException(status_code=400, detail="Group and Permission string are required.")

        new_obj = GroupPermission(group_id=group_id, permission=permission)
        db.add(new_obj)
        await db.flush()

    elif model_slug == "group-memberships":
        user_id = str(form.get("user_id", "")).strip()
        group_id = str(form.get("group_id", "")).strip()
        if not user_id or not group_id:
            raise HTTPException(status_code=400, detail="User and Group are required.")

        new_obj = GroupMembership(user_id=user_id, group_id=group_id)
        db.add(new_obj)
        await db.flush()

    if new_obj:
        await record_audit_log(
            db,
            action=AuditAction.ADMIN_MODEL_CREATE,
            actor=current_admin,
            request=request,
            resource_type=model_slug,
            resource_id=str(new_obj.id),
            severity=AuditSeverity.INFO.value,
            success=True,
            description=f"Admin {current_admin.email} created new {model_admin.verbose_name} (ID: {new_obj.id})",
        )

    msg = f"The {model_admin.verbose_name.lower()} was added successfully."
    if submit_action == "_addanother":
        return RedirectResponse(
            url=f"/admin/{model_slug}/add?msg={msg}",
            status_code=status.HTTP_302_FOUND,
        )
    elif submit_action == "_continue" and new_obj:
        return RedirectResponse(
            url=f"/admin/{model_slug}/{new_obj.id}?msg={msg}",
            status_code=status.HTTP_302_FOUND,
        )
    return RedirectResponse(
        url=f"/admin/{model_slug}?msg={msg}",
        status_code=status.HTTP_302_FOUND,
    )


# =========================================================================
# Bulk Actions Executor (/admin/{model_slug}/action)
# Registered BEFORE parameterized /{model_slug}/{object_id} to avoid conflicts!
# =========================================================================

@router.post("/{model_slug}/action")
async def admin_bulk_action(
    model_slug: str,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Execute selected bulk actions on chosen records."""
    model_admin = admin_site.get_model_admin(model_slug)
    if not model_admin:
        raise HTTPException(status_code=404, detail="Model not found")

    form = await request.form()
    action = str(form.get("action", ""))
    selected_ids = form.getlist("_selected_action")

    if not action or not selected_ids:
        msg = "No action or objects were selected."
        return RedirectResponse(
            url=f"/admin/{model_slug}?msg={msg}&msg_type=error",
            status_code=status.HTTP_302_FOUND,
        )

    count = len(selected_ids)

    if action == "delete_selected":
        if not getattr(model_admin, "can_delete", True):
            msg = f"Records for {model_admin.verbose_name_plural} are strictly immutable and cannot be deleted."
            return RedirectResponse(
                url=f"/admin/{model_slug}?msg={msg}&msg_type=error",
                status_code=status.HTTP_302_FOUND,
            )

        # Disallow deleting self
        clean_ids = [i for i in selected_ids if not (model_slug == "users" and i == current_admin.id)]
        if clean_ids:
            pk_col = getattr(model_admin.model, "id", None)
            type_str = str(getattr(getattr(pk_col, "type", None), "__class__", "")).lower() if pk_col is not None else ""
            is_int_pk = "integer" in type_str or "int" in type_str
            typed_ids = []
            for i in clean_ids:
                if is_int_pk and str(i).isdigit():
                    typed_ids.append(int(i))
                else:
                    typed_ids.append(i)
            stmt = delete(model_admin.model).where(model_admin.model.id.in_(typed_ids))
            await db.execute(stmt)
            await db.flush()

            await record_audit_log(
                db,
                action=AuditAction.ADMIN_BULK_DELETE,
                actor=current_admin,
                request=request,
                resource_type=model_slug,
                severity=AuditSeverity.WARNING.value,
                success=True,
                description=f"Admin {current_admin.email} bulk deleted {len(clean_ids)} {model_admin.verbose_name_plural.lower()} (IDs: {clean_ids})",
                extra_data={"deleted_ids": clean_ids},
            )
        msg = f"Successfully deleted {len(clean_ids)} {model_admin.verbose_name_plural.lower()}."

    elif action == "activate_users" and model_slug == "users":
        stmt = select(User).where(User.id.in_(selected_ids))
        users = (await db.execute(stmt)).scalars().all()
        now = datetime.now(timezone.utc)
        for u in users:
            u.status = UserStatus.ACTIVE
            u.is_verified = True
            u.auth_updated_at = now
            await record_audit_log(
                db,
                action=AuditAction.USER_REACTIVATE,
                actor=current_admin,
                request=request,
                resource_type="user",
                resource_id=u.id,
                severity=AuditSeverity.INFO.value,
                success=True,
                description=f"Admin {current_admin.email} activated user {u.email}",
            )
        await db.flush()
        msg = f"Activated {len(users)} user accounts."

    elif action == "suspend_users" and model_slug == "users":
        stmt = select(User).where(User.id.in_(selected_ids))
        users = (await db.execute(stmt)).scalars().all()
        now = datetime.now(timezone.utc)
        suspended = 0
        for u in users:
            if u.id != current_admin.id:
                u.status = UserStatus.SUSPENDED
                u.auth_updated_at = now
                await record_audit_log(
                    db,
                    action=AuditAction.USER_SUSPEND,
                    actor=current_admin,
                    request=request,
                    resource_type="user",
                    resource_id=u.id,
                    severity=AuditSeverity.WARNING.value,
                    success=True,
                    description=f"Admin {current_admin.email} suspended user {u.email}",
                )
                suspended += 1
        await db.flush()
        msg = f"Suspended {suspended} user accounts."

    elif action == "ban_users" and model_slug == "users":
        stmt = select(User).where(User.id.in_(selected_ids))
        users = (await db.execute(stmt)).scalars().all()
        now = datetime.now(timezone.utc)
        banned = 0
        for u in users:
            if u.id != current_admin.id:
                u.status = UserStatus.BANNED
                u.auth_updated_at = now
                await record_audit_log(
                    db,
                    action=AuditAction.USER_BAN,
                    actor=current_admin,
                    request=request,
                    resource_type="user",
                    resource_id=u.id,
                    severity=AuditSeverity.WARNING.value,
                    success=True,
                    description=f"Admin {current_admin.email} permanently banned user {u.email}",
                )
                banned += 1
        await db.flush()
        msg = f"Banned {banned} user accounts."

    elif action == "make_super_admin" and model_slug == "users":
        stmt = select(User).where(User.id.in_(selected_ids))
        users = (await db.execute(stmt)).scalars().all()
        now = datetime.now(timezone.utc)
        for u in users:
            u.is_super_admin = True
            u.auth_updated_at = now
            await record_audit_log(
                db,
                action=AuditAction.ROLE_GRANT,
                actor=current_admin,
                request=request,
                resource_type="user",
                resource_id=u.id,
                severity=AuditSeverity.WARNING.value,
                success=True,
                description=f"Admin {current_admin.email} granted Super Admin to {u.email}",
            )
        await db.flush()
        msg = f"Granted Super Admin privileges to {len(users)} users."

    elif action == "remove_super_admin" and model_slug == "users":
        stmt = select(User).where(User.id.in_(selected_ids))
        users = (await db.execute(stmt)).scalars().all()
        now = datetime.now(timezone.utc)
        demoted = 0
        for u in users:
            if u.id != current_admin.id:
                u.is_super_admin = False
                u.auth_updated_at = now
                await record_audit_log(
                    db,
                    action=AuditAction.ROLE_REVOKE,
                    actor=current_admin,
                    request=request,
                    resource_type="user",
                    resource_id=u.id,
                    severity=AuditSeverity.WARNING.value,
                    success=True,
                    description=f"Admin {current_admin.email} revoked Super Admin from {u.email}",
                )
                demoted += 1
        await db.flush()
        msg = f"Revoked Super Admin privileges from {demoted} users."

    elif action == "clone_groups" and model_slug == "groups":
        stmt = select(Group).options(selectinload(Group.permissions)).where(Group.id.in_(selected_ids))
        groups = (await db.execute(stmt)).scalars().all()
        cloned = 0
        for g in groups:
            new_g = Group(
                name=f"Copy of {g.name}",
                description=g.description,
                tournament_id=g.tournament_id,
            )
            db.add(new_g)
            await db.flush()
            for p in g.permissions:
                db.add(GroupPermission(group_id=new_g.id, permission=p.permission))
            cloned += 1
        await db.flush()
        await record_audit_log(
            db,
            action=AuditAction.GROUP_CREATE,
            actor=current_admin,
            request=request,
            resource_type="groups",
            severity=AuditSeverity.INFO.value,
            success=True,
            description=f"Admin {current_admin.email} bulk cloned {cloned} security groups",
            extra_data={"source_ids": selected_ids},
        )
        msg = f"Cloned {cloned} security groups with permissions."

    elif action == "export_json" and model_slug == "audit-logs":
        stmt = select(AuditLog).where(AuditLog.id.in_(selected_ids)).order_by(AuditLog.created_at.desc())
        logs = (await db.execute(stmt)).scalars().all()
        await record_audit_log(
            db,
            action=AuditAction.AUDIT_EXPORT,
            actor=current_admin,
            request=request,
            resource_type="audit-logs",
            severity=AuditSeverity.INFO.value,
            success=True,
            description=f"Admin {current_admin.email} exported {len(logs)} compliance audit logs as JSON",
            extra_data={"exported_count": len(logs)},
        )
        data = [
            {
                "id": l.id,
                "created_at": l.created_at.isoformat() if l.created_at else None,
                "action": l.action,
                "severity": l.severity,
                "user_email": l.user_email,
                "user_id": l.user_id,
                "resource_type": l.resource_type,
                "resource_id": l.resource_id,
                "ip_address": l.ip_address,
                "request_method": l.request_method,
                "request_path": l.request_path,
                "success": l.success,
                "action_description": l.action_description,
                "changes": l.changes,
                "extra_data": l.extra_data,
            }
            for l in logs
        ]
        filename = f"audit_logs_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        return JSONResponse(
            content=data,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    else:
        msg = f"Unknown action: {action}"

    return RedirectResponse(
        url=f"/admin/{model_slug}?msg={msg}",
        status_code=status.HTTP_302_FOUND,
    )


# =========================================================================
# Model Change Form View (/admin/{model_slug}/{object_id})
# =========================================================================

@router.get("/{model_slug}/{object_id}", response_class=HTMLResponse)
async def admin_model_change_view(
    model_slug: str,
    object_id: str,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Django-style Change/Edit object view."""
    model_admin = admin_site.get_model_admin(model_slug)
    if not model_admin:
        raise HTTPException(status_code=404, detail=f"Admin for '{model_slug}' not found")

    instance = await model_admin.get_object(db, object_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"{model_admin.verbose_name} not found")

    # Fetch auxiliary options for relations
    groups = (await db.execute(select(Group).order_by(Group.name))).scalars().all()
    users = (await db.execute(select(User).order_by(User.first_name, User.last_name))).scalars().all()

    # User's currently assigned group IDs
    assigned_group_ids = []
    if model_slug == "users" and hasattr(instance, "group_memberships"):
        assigned_group_ids = [m.group_id for m in instance.group_memberships]

    # Permissions for Group
    group_permissions = []
    if model_slug == "groups" and hasattr(instance, "permissions"):
        group_permissions = instance.permissions

    app_sections = await admin_site.get_app_sections(db)
    msg = request.query_params.get("msg")
    msg_type = request.query_params.get("msg_type", "success")

    action_label = "Inspect" if getattr(model_admin, "is_read_only", False) else "Change"

    return templates.TemplateResponse(
        request=request,
        name="admin/change_form.html",
        context={
            "user": current_admin,
            "model_admin": model_admin,
            "app_sections": app_sections,
            "current_slug": model_slug,
            "instance": instance,
            "is_add": False,
            "groups": groups,
            "users": users,
            "assigned_group_ids": assigned_group_ids,
            "group_permissions": group_permissions,
            "msg": msg,
            "msg_type": msg_type,
            "title": f"{action_label} {model_admin.verbose_name}",
        },
    )


@router.post("/{model_slug}/{object_id}")
async def admin_model_change_submit(
    model_slug: str,
    object_id: str,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Handle updates to existing model instance."""
    model_admin = admin_site.get_model_admin(model_slug)
    if not model_admin:
        raise HTTPException(status_code=404, detail=f"Admin for '{model_slug}' not found")

    if not getattr(model_admin, "can_change", True):
        msg = f"Records for {model_admin.verbose_name_plural} are strictly immutable and cannot be edited."
        return RedirectResponse(
            url=f"/admin/{model_slug}/{object_id}?msg={msg}&msg_type=error",
            status_code=status.HTTP_302_FOUND,
        )

    instance = await model_admin.get_object(db, object_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"{model_admin.verbose_name} not found")

    form = await request.form()
    submit_action = form.get("_action", "_save")

    if model_slug == "users":
        target_user: User = instance
        target_user.full_name = str(form.get("full_name", target_user.full_name)).strip()
        new_email = str(form.get("email", target_user.email)).strip().lower()

        # Prevent duplicate email
        if new_email != target_user.email:
            existing = (await db.execute(select(User).where(User.email == new_email))).scalar_one_or_none()
            if existing:
                raise HTTPException(status_code=400, detail="Email already registered to another user.")
            target_user.email = new_email

        # Update password if provided
        raw_pwd = str(form.get("password", "")).strip()
        if raw_pwd:
            target_user.password_hash = hash_password(raw_pwd)

        # Handle booleans & status safely (self demotion guard)
        wants_super = form.get("is_super_admin") is not None
        status_val = form.get("status")

        if target_user.id != current_admin.id:
            target_user.is_super_admin = wants_super
            if status_val and status_val in [s.value for s in UserStatus]:
                target_user.status = UserStatus(status_val)
            else:
                wants_active = form.get("is_active") is not None
                target_user.is_active = wants_active

        # Update groups
        selected_groups = set(form.getlist("groups"))
        current_memberships = {m.group_id: m for m in target_user.group_memberships}

        # Remove unchecked groups
        for g_id, m in current_memberships.items():
            if g_id not in selected_groups:
                await db.delete(m)

        # Add new checked groups
        for g_id in selected_groups:
            if g_id not in current_memberships:
                db.add(GroupMembership(user_id=target_user.id, group_id=g_id))

        await db.flush()

    elif model_slug == "groups":
        target_group: Group = instance
        target_group.name = str(form.get("name", target_group.name)).strip()
        target_group.description = str(form.get("description", "")).strip() or None
        scope_type = str(form.get("scope_type", "global"))
        tourn_id = str(form.get("tournament_id", "")).strip() or None
        target_group.tournament_id = tourn_id if scope_type == "tournament" else None
        await db.flush()

    elif model_slug == "group-permissions":
        target_perm: GroupPermission = instance
        group_id = str(form.get("group_id", target_perm.group_id)).strip()
        permission = str(form.get("permission", target_perm.permission)).strip().lower()
        if not group_id or not permission:
            raise HTTPException(status_code=400, detail="Group and Permission string are required.")
        target_perm.group_id = group_id
        target_perm.permission = permission
        await db.flush()

    elif model_slug == "group-memberships":
        target_membership: GroupMembership = instance
        user_id = str(form.get("user_id", target_membership.user_id)).strip()
        group_id = str(form.get("group_id", target_membership.group_id)).strip()
        if not user_id or not group_id:
            raise HTTPException(status_code=400, detail="User and Group are required.")
        target_membership.user_id = user_id
        target_membership.group_id = group_id
        await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.ADMIN_MODEL_UPDATE,
        actor=current_admin,
        request=request,
        resource_type=model_slug,
        resource_id=str(instance.id),
        severity=AuditSeverity.INFO.value,
        success=True,
        description=f"Admin {current_admin.email} modified {model_admin.verbose_name} (ID: {instance.id})",
    )

    msg = f"The {model_admin.verbose_name.lower()} was changed successfully."
    if submit_action == "_addanother":
        return RedirectResponse(
            url=f"/admin/{model_slug}/add?msg={msg}",
            status_code=status.HTTP_302_FOUND,
        )
    elif submit_action == "_continue":
        return RedirectResponse(
            url=f"/admin/{model_slug}/{object_id}?msg={msg}",
            status_code=status.HTTP_302_FOUND,
        )
    return RedirectResponse(
        url=f"/admin/{model_slug}?msg={msg}",
        status_code=status.HTTP_302_FOUND,
    )


# =========================================================================
# Object Delete View (/admin/{model_slug}/{object_id}/delete)
# =========================================================================

@router.post("/{model_slug}/{object_id}/delete")
async def admin_model_delete(
    model_slug: str,
    object_id: str,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Delete a single model instance."""
    model_admin = admin_site.get_model_admin(model_slug)
    if not model_admin:
        raise HTTPException(status_code=404, detail="Model not found")

    if not getattr(model_admin, "can_delete", True):
        msg = f"Records for {model_admin.verbose_name_plural} are strictly immutable and cannot be deleted."
        return RedirectResponse(
            url=f"/admin/{model_slug}?msg={msg}&msg_type=error",
            status_code=status.HTTP_302_FOUND,
        )

    instance = await model_admin.get_object(db, object_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Object not found")

    # Guard self-deletion
    if model_slug == "users" and str(instance.id) == str(current_admin.id):
        msg = "You cannot delete your own active administrator account."
        return RedirectResponse(
            url=f"/admin/{model_slug}?msg={msg}&msg_type=error",
            status_code=status.HTTP_302_FOUND,
        )

    await db.delete(instance)
    await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.ADMIN_MODEL_DELETE,
        actor=current_admin,
        request=request,
        resource_type=model_slug,
        resource_id=str(instance.id),
        severity=AuditSeverity.WARNING.value,
        success=True,
        description=f"Admin {current_admin.email} deleted {model_admin.verbose_name} (ID: {instance.id})",
    )

    msg = f"Successfully deleted {model_admin.verbose_name}."
    return RedirectResponse(
        url=f"/admin/{model_slug}?msg={msg}",
        status_code=status.HTTP_302_FOUND,
    )


# =========================================================================
# Extended Row & Object Actions (User, Group, Permissions)
# =========================================================================

@router.post("/users/{user_id}/toggle-admin")
async def toggle_super_admin(
    user_id: str,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Toggle a user's platform Super Admin status."""
    stmt = select(User).where(User.id == user_id)
    target_user = (await db.execute(stmt)).scalar_one_or_none()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if target_user.id == current_admin.id:
        msg = "You cannot remove your own Super Admin privileges."
        if request.headers.get("HX-Request"):
            return HTMLResponse(f'<div class="rounded-lg bg-amber-50 p-3 text-sm text-amber-800 border border-amber-200">{msg}</div>')
        return RedirectResponse(url=f"/admin/users/{user_id}?msg={msg}&msg_type=error", status_code=status.HTTP_302_FOUND)

    target_user.is_super_admin = not target_user.is_super_admin
    target_user.auth_updated_at = datetime.now(timezone.utc)
    await record_audit_log(
        db,
        action=AuditAction.ROLE_GRANT if target_user.is_super_admin else AuditAction.ROLE_REVOKE,
        actor=current_admin,
        request=request,
        resource_type="user",
        resource_id=target_user.id,
        severity=AuditSeverity.WARNING.value,
        success=True,
        description=f"Admin {current_admin.email} toggled Super Admin on {target_user.email} (is_super_admin={target_user.is_super_admin})",
    )
    await db.flush()

    status_label = "promoted to Super Admin" if target_user.is_super_admin else "demoted from Super Admin"
    msg = f"User {target_user.full_name} was {status_label}."

    if request.headers.get("HX-Request"):
        return HTMLResponse(
            f'<div class="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800 border border-emerald-200">{msg}</div>',
            headers={"HX-Trigger": json.dumps({"toast": {"message": msg, "type": "success"}})},
        )
    return RedirectResponse(url=f"/admin/users?msg={msg}", status_code=status.HTTP_302_FOUND)


@router.post("/users/{user_id}/toggle-status")
async def toggle_user_active_status(
    user_id: str,
    request: Request,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Suspend or activate a user account."""
    stmt = select(User).where(User.id == user_id)
    target_user = (await db.execute(stmt)).scalar_one_or_none()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if target_user.id == current_admin.id:
        msg = "You cannot suspend your own account."
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<div class="rounded-lg bg-amber-50 p-3 text-sm text-amber-800 border border-amber-200">{msg}</div>',
                headers={"HX-Trigger": json.dumps({"toast": {"message": msg, "type": "warning"}})},
            )
        return RedirectResponse(url=f"/admin/users/{user_id}?msg={msg}&msg_type=error", status_code=status.HTTP_302_FOUND)

    target_user.is_active = not target_user.is_active
    target_user.auth_updated_at = datetime.now(timezone.utc)
    await record_audit_log(
        db,
        action=AuditAction.USER_REACTIVATE if target_user.is_active else AuditAction.USER_SUSPEND,
        actor=current_admin,
        request=request,
        resource_type="user",
        resource_id=target_user.id,
        severity=AuditSeverity.WARNING.value,
        success=True,
        description=f"Admin {current_admin.email} toggled status on {target_user.email} (is_active={target_user.is_active})",
    )
    await db.flush()

    action = "activated" if target_user.is_active else "suspended"
    msg = f"User {target_user.full_name} has been {action}."

    if request.headers.get("HX-Request"):
        return HTMLResponse(
            f'<div class="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800 border border-emerald-200">{msg}</div>',
            headers={"HX-Trigger": json.dumps({"toast": {"message": msg, "type": "success"}})},
        )
    return RedirectResponse(url=f"/admin/users?msg={msg}", status_code=status.HTTP_302_FOUND)


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    new_password: str = Form(...),
    request: Request = None,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Set a new password for a user account directly."""
    stmt = select(User).where(User.id == user_id)
    target_user = (await db.execute(stmt)).scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    target_user.password_hash = hash_password(new_password.strip())
    target_user.auth_updated_at = datetime.now(timezone.utc)
    await record_audit_log(
        db,
        action=AuditAction.USER_PASSWORD_CHANGE,
        actor=current_admin,
        request=request,
        resource_type="user",
        resource_id=target_user.id,
        severity=AuditSeverity.WARNING.value,
        success=True,
        description=f"Admin {current_admin.email} directly reset password for {target_user.email}",
    )
    await db.flush()

    msg = f"Password for {target_user.full_name} was updated successfully."
    return RedirectResponse(url=f"/admin/users/{user_id}?msg={msg}", status_code=status.HTTP_302_FOUND)


# Legacy & Direct Form Support for Groups
@router.post("/groups")
async def create_security_group_direct(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    scope_type: str = Form("global"),
    tournament_id: Optional[str] = Form(None),
    request: Request = None,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Direct handler for creating security group, compatible with tests."""
    scoped_tournament_id = tournament_id if scope_type == "tournament" and tournament_id else None

    group = Group(
        name=name.strip(),
        description=description.strip() if description else None,
        tournament_id=scoped_tournament_id,
    )
    db.add(group)
    await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.GROUP_CREATE,
        actor=current_admin,
        request=request,
        resource_type="groups",
        resource_id=str(group.id),
        severity=AuditSeverity.INFO.value,
        success=True,
        description=f"Admin {current_admin.email} created security group '{group.name}'",
    )

    msg = f"Security group '{group.name}' created."
    return RedirectResponse(url=f"/admin/groups?msg={msg}", status_code=status.HTTP_302_FOUND)


@router.post("/groups/{group_id}/permissions/add")
async def add_group_permission(
    group_id: str,
    permission: str = Form(...),
    request: Request = None,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Add a permission string to a security group."""
    perm_clean = permission.strip().lower()
    existing = (
        await db.execute(
            select(GroupPermission).where(
                GroupPermission.group_id == group_id,
                GroupPermission.permission == perm_clean,
            )
        )
    ).scalar_one_or_none()

    if not existing:
        perm = GroupPermission(group_id=group_id, permission=perm_clean)
        db.add(perm)
        await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.GROUP_ASSIGN,
        actor=current_admin,
        request=request,
        resource_type="group_permissions",
        resource_id=str(group_id),
        severity=AuditSeverity.INFO.value,
        success=True,
        description=f"Admin {current_admin.email} added permission '{perm_clean}' to group {group_id}",
    )

    msg = f"Permission '{perm_clean}' added to group."
    return RedirectResponse(url=f"/admin/groups/{group_id}?msg={msg}", status_code=status.HTTP_302_FOUND)


@router.post("/groups/{group_id}/permissions/{perm_id}/delete")
async def delete_group_permission(
    group_id: str,
    perm_id: int,
    request: Request = None,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Remove a permission from a security group."""
    stmt = select(GroupPermission).where(
        GroupPermission.id == perm_id,
        GroupPermission.group_id == group_id,
    )
    perm = (await db.execute(stmt)).scalar_one_or_none()
    if perm:
        await db.delete(perm)
        await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.GROUP_REMOVE,
        actor=current_admin,
        request=request,
        resource_type="group_permissions",
        resource_id=str(perm_id),
        severity=AuditSeverity.WARNING.value,
        success=True,
        description=f"Admin {current_admin.email} removed permission {perm_id} from group {group_id}",
    )

    msg = "Permission removed."
    return RedirectResponse(url=f"/admin/groups/{group_id}?msg={msg}", status_code=status.HTTP_302_FOUND)


@router.post("/groups/{group_id}/clone")
async def clone_group(
    group_id: str,
    request: Request = None,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Clone an existing security group with its permissions."""
    stmt = select(Group).options(selectinload(Group.permissions)).where(Group.id == group_id)
    group = (await db.execute(stmt)).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    cloned = Group(
        name=f"Copy of {group.name}",
        description=group.description,
        tournament_id=group.tournament_id,
    )
    db.add(cloned)
    await db.flush()

    for p in group.permissions:
        db.add(GroupPermission(group_id=cloned.id, permission=p.permission))
    await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.GROUP_CREATE,
        actor=current_admin,
        request=request,
        resource_type="groups",
        resource_id=str(cloned.id),
        severity=AuditSeverity.INFO.value,
        success=True,
        description=f"Admin {current_admin.email} cloned group '{group.name}' as '{cloned.name}'",
    )

    msg = f"Cloned group as '{cloned.name}'."
    return RedirectResponse(url=f"/admin/groups/{cloned.id}?msg={msg}", status_code=status.HTTP_302_FOUND)


@router.post("/groups/{group_id}/assign-all")
async def assign_all_users_to_group(
    group_id: str,
    request: Request = None,
    current_admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Assign all active platform users to this security group."""
    group = (await db.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    active_users = (await db.execute(select(User).where(User.is_active == True))).scalars().all()
    assigned = 0

    for u in active_users:
        existing = (
            await db.execute(
                select(GroupMembership).where(
                    GroupMembership.user_id == u.id,
                    GroupMembership.group_id == group_id,
                )
            )
        ).scalar_one_or_none()
        if not existing:
            db.add(GroupMembership(user_id=u.id, group_id=group_id))
            assigned += 1

    await db.flush()

    await record_audit_log(
        db,
        action=AuditAction.GROUP_ASSIGN,
        actor=current_admin,
        request=request,
        resource_type="groups",
        resource_id=str(group.id),
        severity=AuditSeverity.INFO.value,
        success=True,
        description=f"Admin {current_admin.email} bulk-assigned {assigned} active users to group '{group.name}'",
    )

    msg = f"Assigned {assigned} active users to group '{group.name}'."
    return RedirectResponse(url=f"/admin/groups/{group_id}?msg={msg}", status_code=status.HTTP_302_FOUND)

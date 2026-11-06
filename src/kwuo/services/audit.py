"""Audit logging service for immutable compliance event tracking."""

from typing import Any, Dict, Optional
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from kwuo.models.audit import AuditLog, AuditSeverity
from kwuo.models.user import User
from kwuo.core.queue import enqueue_job
from kwuo.core.database import async_session_factory


def extract_request_context(request: Optional[Request]) -> Dict[str, Optional[str]]:
    """Extract client IP, user agent, request method, path, and request ID safely from a FastAPI Request."""
    if not request:
        return {
            "ip_address": None,
            "user_agent": None,
            "request_method": None,
            "request_path": None,
            "request_id": None,
        }

    # IP resolution: prefer X-Forwarded-For if reverse proxy (NGINX/Cloudflare) is in place
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip_address = forwarded.split(",")[0].strip()
    elif request.client:
        ip_address = request.client.host
    else:
        ip_address = None

    user_agent = request.headers.get("user-agent")
    request_method = request.method
    request_path = request.url.path
    request_id = request.headers.get("x-request-id")

    return {
        "ip_address": ip_address[:45] if ip_address else None,
        "user_agent": user_agent,
        "request_method": request_method,
        "request_path": request_path[:500] if request_path else None,
        "request_id": request_id,
    }


async def record_audit_log(
    db: Optional[AsyncSession] = None,
    action: str = "",
    actor: Optional[User] = None,
    request: Optional[Request] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    resource_name: Optional[str] = None,
    changes: Optional[Dict[str, Any]] = None,
    severity: str = AuditSeverity.INFO.value,
    success: bool = True,
    error_message: Optional[str] = None,
    extra_data: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
) -> Optional[AuditLog]:
    """Record an immutable AuditLog entry in the database.
    
    Dispatches to the ARQ background worker queue when running in development/production.
    Falls back to direct DB persistence when testing or when the worker queue is offline.
    """
    req_ctx = extract_request_context(request)

    user_id = str(actor.id) if actor and actor.id else None
    user_email = actor.email if actor and actor.email else None
    user_type = "admin" if (actor and actor.is_admin) else ("user" if actor else "anonymous")

    payload = {
        "user_id": user_id,
        "user_email": user_email,
        "user_type": user_type,
        "action": action,
        "action_description": description or f"Action {action} performed",
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id else None,
        "resource_name": resource_name,
        "ip_address": req_ctx["ip_address"],
        "user_agent": req_ctx["user_agent"],
        "request_method": req_ctx["request_method"],
        "request_path": req_ctx["request_path"],
        "request_id": req_ctx["request_id"],
        "changes": changes or {},
        "extra_data": extra_data or {},
        "severity": severity,
        "success": success,
        "error_message": error_message,
    }

    # Dispatch to ARQ background worker
    enqueued = await enqueue_job("write_audit_log_task", payload)
    if enqueued:
        return None

    # Fallback to direct database write
    if db is not None:
        log_entry = AuditLog(**payload)
        db.add(log_entry)
        await db.flush()
        return log_entry
    else:
        async with async_session_factory() as session:
            log_entry = AuditLog(**payload)
            session.add(log_entry)
            await session.commit()
            return log_entry

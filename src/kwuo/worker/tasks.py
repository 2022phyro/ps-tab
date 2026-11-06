"""ARQ background worker tasks and settings for Kwuo."""

from typing import Any, Dict, Optional
from arq.connections import RedisSettings
from kwuo.core.config import settings
from kwuo.core.database import async_session_factory
from kwuo.models.audit import AuditLog
from kwuo.services.email import send_email


def print_audit_box(payload: Dict[str, Any]) -> None:
    """Print an eye-catching ASCII audit log box in the ARQ worker process."""
    action = payload.get("action", "unknown")
    user_email = payload.get("user_email") or "anonymous"
    severity = payload.get("severity", "INFO")
    ip = payload.get("ip_address") or "unknown"
    desc = payload.get("action_description", "")
    box_width = 72

    print("\n" + "=" * box_width)
    print(f"| KWUO ARQ WORKER [AUDIT EVENT RECORDED] |".center(box_width))
    print("-" * box_width)
    print(f"  ACTION:      {action} ({severity})")
    print(f"  ACTOR:       {user_email}")
    print(f"  IP ADDRESS:  {ip}")
    if desc:
        print(f"  DETAILS:     {desc}")
    print("=" * box_width + "\n")


async def write_audit_log_task(ctx: Dict[Any, Any], payload: Dict[str, Any]) -> None:
    """Persist an audit log entry from background worker queue."""
    print_audit_box(payload)
    if "session" in ctx:
        log_entry = AuditLog(**payload)
        ctx["session"].add(log_entry)
        await ctx["session"].flush()
        return

    session_factory = ctx.get("session_factory", async_session_factory)
    async with session_factory() as session:
        log_entry = AuditLog(**payload)
        session.add(log_entry)
        await session.commit()


async def send_email_task(
    ctx: Dict[Any, Any],
    to_email: str,
    subject: str,
    body: str,
    otp_code: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Dispatch email via background worker."""
    print(f"\n[KWUO ARQ WORKER] Processing background email dispatch to {to_email}...")
    await send_email(
        to_email=to_email,
        subject=subject,
        body=body,
        otp_code=otp_code,
        metadata=metadata,
    )


async def startup(ctx: Dict[Any, Any]) -> None:
    """Worker startup hook."""
    print("\n" + "=" * 72)
    print("| KWUO ARQ BACKGROUND WORKER ONLINE [LISTENING TO REDIS QUEUE] |".center(72))
    print("=" * 72 + "\n")


async def shutdown(ctx: Dict[Any, Any]) -> None:
    """Worker shutdown hook."""
    print("\n[KWUO ARQ WORKER] Shutting down...\n")


class WorkerSettings:
    """ARQ Worker configuration."""
    functions = [write_audit_log_task, send_email_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)

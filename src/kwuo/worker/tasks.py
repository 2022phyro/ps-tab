"""ARQ background worker tasks and settings for Kwuo."""

from typing import Any, Dict, Optional
from arq.connections import RedisSettings
from kwuo.core.config import settings
from kwuo.core.database import async_session_factory
from kwuo.models.audit import AuditLog
from kwuo.services.email import send_email


async def write_audit_log_task(ctx: Dict[Any, Any], payload: Dict[str, Any]) -> None:
    """Persist an audit log entry from background worker queue."""
    async with async_session_factory() as session:
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
    await send_email(
        to_email=to_email,
        subject=subject,
        body=body,
        otp_code=otp_code,
        metadata=metadata,
    )


async def startup(ctx: Dict[Any, Any]) -> None:
    """Worker startup hook."""
    pass


async def shutdown(ctx: Dict[Any, Any]) -> None:
    """Worker shutdown hook."""
    pass


class WorkerSettings:
    """ARQ Worker configuration."""
    functions = [write_audit_log_task, send_email_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)

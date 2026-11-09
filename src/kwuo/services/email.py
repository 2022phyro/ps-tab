"""Console-based email dispatch engine and email provider tracking registry for Kwuo."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger("kwuo.email")


class EmailProviderRegistry:
    """Tracks the status and absence of external transactional email providers.
    
    Since no live SMTP / SendGrid / Postmark provider is currently configured,
    all transactional emails (OTPs, password resets, security alerts) are logged
    directly to the terminal with clear visual demarcation.
    """
    has_active_provider: bool = False
    provider_name: str = "console_logger"
    dispatched_messages: List[Dict[str, Any]] = []

    @classmethod
    def record_dispatch(cls, email: str, subject: str, body: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        entry = {
            "to": email,
            "subject": subject,
            "body": body,
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        cls.dispatched_messages.append(entry)
        # Keep rolling buffer of last 100 messages
        if len(cls.dispatched_messages) > 100:
            cls.dispatched_messages.pop(0)

    @classmethod
    def get_latest_email_for(cls, email: str) -> Optional[Dict[str, Any]]:
        clean_email = email.strip().lower()
        for item in reversed(cls.dispatched_messages):
            if item["to"].strip().lower() == clean_email:
                return item
        return None

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Return diagnostic status of the transactional email dispatch engine."""
        return {
            "is_configured": cls.has_active_provider,
            "provider_name": cls.provider_name,
            "total_dispatched": len(cls.dispatched_messages),
        }

    @classmethod
    def clear_history(cls) -> None:
        cls.dispatched_messages.clear()


def print_email_box(to_email: str, subject: str, body_content: str, otp_code: Optional[str] = None) -> None:
    """Print an eye-catching ASCII email notification to stdout/console for local development and tabroom admins."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    box_width = 72

    print("\n" + "=" * box_width)
    print(f"| KWUO EMAIL DISPATCHER [PROVIDER STATUS: CONSOLE LOGGING (NO LIVE SMTP)] |".center(box_width))
    print("-" * box_width)
    print(f"  TO:        {to_email}")
    print(f"  SUBJECT:   {subject}")
    print(f"  TIMESTAMP: {ts}")
    if otp_code:
        print(f"  OTP CODE:  >>> [ {otp_code} ] <<< (Expires in 5 minutes)")
    print("-" * box_width)
    for line in body_content.strip().split("\n"):
        print(f"  {line}")
    print("=" * box_width + "\n")


async def send_email(
    to_email: str,
    subject: str,
    body: str,
    otp_code: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Dispatch an email by printing to console and recording in registry."""
    EmailProviderRegistry.record_dispatch(
        email=to_email,
        subject=subject,
        body=body,
        metadata={"otp_code": otp_code, **(metadata or {})},
    )
    print_email_box(to_email=to_email, subject=subject, body_content=body, otp_code=otp_code)
    return True


from kwuo.core.queue import enqueue_job


async def send_verification_otp_email(to_email: str, otp_code: str, name: str = "") -> bool:
    """Send account verification 6-digit OTP code."""
    greeting = f"Hello {name.strip()}," if name else "Hello,"
    body = (
        f"{greeting}\n\n"
        f"Welcome to Kwuo! To verify your email address and activate your tabroom account,\n"
        f"please enter the 6-digit verification code below:\n\n"
        f"    Verification Code: {otp_code}\n\n"
        f"This code will expire in 5 minutes. If you did not create this account, please ignore this email."
    )
    subject = "Verify your Kwuo account"
    enqueued = await enqueue_job(
        "send_email_task",
        to_email=to_email,
        subject=subject,
        body=body,
        otp_code=otp_code,
        metadata={"action": "account_verify", "name": name},
    )
    if not enqueued:
        return await send_email(
            to_email=to_email,
            subject=subject,
            body=body,
            otp_code=otp_code,
            metadata={"action": "account_verify"},
        )
    return True


async def send_password_reset_otp_email(to_email: str, otp_code: str, name: str = "") -> bool:
    """Send password reset 6-digit OTP code."""
    greeting = f"Hello {name.strip()}," if name else "Hello,"
    body = (
        f"{greeting}\n\n"
        f"A password reset request was received for your Kwuo account.\n"
        f"To reset your password, please enter the following 6-digit authorization code:\n\n"
        f"    Password Reset Code: {otp_code}\n\n"
        f"This code will expire in 5 minutes. If you did not request a password reset,\n"
        f"someone may be trying to access your account. Please log in and check your security settings."
    )
    subject = "Kwuo Password Reset Code"
    enqueued = await enqueue_job(
        "send_email_task",
        to_email=to_email,
        subject=subject,
        body=body,
        otp_code=otp_code,
        metadata={"action": "password_reset", "name": name},
    )
    if not enqueued:
        return await send_email(
            to_email=to_email,
            subject=subject,
            body=body,
            otp_code=otp_code,
            metadata={"action": "password_reset"},
        )
    return True


async def send_official_invitation_email(
    to_email: str,
    name: str,
    setup_url: str,
    tournament_name: str,
    roles: Optional[List[str]] = None,
) -> bool:
    """Send Tab Room official setup / password reset invitation link."""
    greeting = f"Hello {name.strip()}," if name else "Hello,"
    roles_text = f" ({', '.join(roles)})" if roles else ""
    body = (
        f"{greeting}\n\n"
        f"You have been accredited as a Tab Room Official{roles_text} for:\n"
        f"    {tournament_name}\n\n"
        f"To complete your registration and establish your secure password, please visit:\n"
        f"    {setup_url}\n\n"
        f"This setup link is unique to your credentials and will remain active for the duration of the tournament.\n"
        f"If you did not expect this invitation, please contact the tournament administration."
    )
    subject = f"Accreditation & Password Setup — {tournament_name}"
    enqueued = await enqueue_job(
        "send_email_task",
        to_email=to_email,
        subject=subject,
        body=body,
        metadata={"action": "official_invitation", "name": name, "setup_url": setup_url},
    )
    if not enqueued:
        return await send_email(
            to_email=to_email,
            subject=subject,
            body=body,
            metadata={"action": "official_invitation", "setup_url": setup_url},
        )
    return True


async def send_magic_link_email(
    to_email: str,
    name: str,
    magic_url: str,
    tournament_name: str,
) -> bool:
    """Send private zero-auth competitor magic access link via ARQ background worker."""
    greeting = f"Hello {name.strip()}," if name else "Hello,"
    body = (
        f"{greeting}\n\n"
        f"Here is your private magic access link for {tournament_name}:\n\n"
        f"{magic_url}\n\n"
        f"Keep this link safe. You can use it anytime to view your speaking times, room allocations, and ballots.\n\n"
        f"Best regards,\n{tournament_name} Tab Room"
    )
    subject = f"Your Magic Access Link — {tournament_name}"
    enqueued = await enqueue_job(
        "send_email_task",
        to_email=to_email,
        subject=subject,
        body=body,
        metadata={"action": "magic_link", "name": name, "magic_url": magic_url},
    )
    if not enqueued:
        return await send_email(
            to_email=to_email,
            subject=subject,
            body=body,
            metadata={"action": "magic_link", "magic_url": magic_url},
        )
    return True

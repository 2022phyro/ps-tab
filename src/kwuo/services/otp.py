"""Redis-backed One-Time Password (OTP) verification engine with dual rate limiting."""

import hashlib
import secrets
from typing import Optional, Tuple
from kwuo.core.cache import get_redis_client

# In-memory fallback if Redis is temporarily unavailable in lightweight tests
_fallback_cache = {}
_fallback_rate_limits = {}


class OtpAction:
    ACCOUNT_VERIFY = "account_verify"
    PASSWORD_RESET = "password_reset"
    EMAIL_CHANGE = "email_change"
    SENSITIVE_ACTION = "sensitive_action"
    DEFAULT = "default"


class OtpRateLimitExceeded(Exception):
    """Raised when OTP generation requests exceed rate limits."""
    pass


class OtpService:
    """Ephemeral, cryptographically verified OTP engine backed by Redis."""

    RATE_LIMIT_DEVICE = 5  # Max OTPs per 60 seconds per (email, action, fingerprint)
    RATE_LIMIT_EMAIL = 5   # Max OTPs per 60 seconds per (email, action)
    DEFAULT_TTL_SECONDS = 300  # 5 minutes

    @staticmethod
    def _otp_key(email: str, action: str, fingerprint: str) -> str:
        clean_email = email.strip().lower()
        return f"otp:{clean_email}:{action}:{fingerprint}"

    @staticmethod
    def _rate_key_device(email: str, action: str, fingerprint: str) -> str:
        clean_email = email.strip().lower()
        return f"otp_rate:dev:{clean_email}:{action}:{fingerprint}"

    @staticmethod
    def _rate_key_email(email: str, action: str) -> str:
        clean_email = email.strip().lower()
        return f"otp_rate:email:{clean_email}:{action}"

    @staticmethod
    def _hash_code(code: str, email: str) -> str:
        """Hash code with email salt to prevent plaintext storage in Redis."""
        salt = email.strip().lower()
        return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()

    @classmethod
    async def check_and_increment_rate_limits(
        cls, email: str, action: str, fingerprint: str = "default"
    ) -> bool:
        """Check and increment dual rate limits: per-fingerprint and per-email."""
        try:
            client = get_redis_client()
            dev_key = cls._rate_key_device(email, action, fingerprint)
            email_key = cls._rate_key_email(email, action)

            # Device limit
            dev_count = await client.incr(dev_key)
            if dev_count == 1:
                await client.expire(dev_key, 60)

            # Email limit
            email_count = await client.incr(email_key)
            if email_count == 1:
                await client.expire(email_key, 60)

            if dev_count > cls.RATE_LIMIT_DEVICE or email_count > cls.RATE_LIMIT_EMAIL:
                return False
            return True
        except Exception:
            # Fallback to in-memory rate limiting
            e_key = cls._rate_key_email(email, action)
            count = _fallback_rate_limits.get(e_key, 0) + 1
            _fallback_rate_limits[e_key] = count
            return count <= cls.RATE_LIMIT_EMAIL

    @classmethod
    async def create_otp(
        cls,
        email: str,
        action: str = OtpAction.DEFAULT,
        fingerprint: str = "default",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> str:
        """Generate a cryptographically secure 6-digit numeric OTP and store its hash in Redis."""
        allowed = await cls.check_and_increment_rate_limits(email, action, fingerprint)
        if not allowed:
            raise OtpRateLimitExceeded("Too many OTP requests. Please wait a minute before trying again.")

        # Delete any previous OTPs for this email and action
        await cls.delete_otp(email, action, fingerprint)

        # Generate 6-digit random code
        code = "".join(secrets.choice("0123456789") for _ in range(6))
        hashed = cls._hash_code(code, email)
        key = cls._otp_key(email, action, fingerprint)

        payload = {
            "hashed": hashed,
            "action": action,
            "used": "0",
        }

        try:
            client = get_redis_client()
            # Store hash as a mapping
            # Convert values to strings
            mapping = {k.encode(): v.encode() for k, v in payload.items()}
            await client.hset(key, mapping=mapping)
            await client.expire(key, ttl_seconds)
        except Exception:
            _fallback_cache[key] = payload

        return code

    @classmethod
    async def verify_otp(
        cls,
        email: str,
        code: str,
        action: str = OtpAction.DEFAULT,
        fingerprint: str = "default",
    ) -> bool:
        """Verify the user-supplied 6-digit code against Redis hash without consuming it yet."""
        key = cls._otp_key(email, action, fingerprint)
        expected_hash = cls._hash_code(code.strip(), email)

        try:
            client = get_redis_client()
            data = await client.hgetall(key)
            if not data:
                # Check fallback
                data_dict = _fallback_cache.get(key)
                if not data_dict:
                    return False
                stored_hash = data_dict.get("hashed")
                stored_action = data_dict.get("action")
            else:
                stored_hash = data.get(b"hashed", b"").decode("utf-8")
                stored_action = data.get(b"action", b"").decode("utf-8")
        except Exception:
            data_dict = _fallback_cache.get(key)
            if not data_dict:
                return False
            stored_hash = data_dict.get("hashed")
            stored_action = data_dict.get("action")

        if stored_action != action:
            return False

        if secrets.compare_digest(stored_hash, expected_hash):
            # Mark as used in Redis
            try:
                client = get_redis_client()
                await client.hset(key, b"used", b"1")
                # Keep verified OTP for another 180s for multi-step form consumption
                await client.expire(key, 180)
            except Exception:
                if key in _fallback_cache:
                    _fallback_cache[key]["used"] = "1"
            return True

        return False

    @classmethod
    async def consume_otp(
        cls,
        email: str,
        action: str = OtpAction.DEFAULT,
        fingerprint: str = "default",
    ) -> bool:
        """Consume and permanently delete the verified OTP."""
        key = cls._otp_key(email, action, fingerprint)
        try:
            client = get_redis_client()
            used_val = await client.hget(key, b"used")
            if not used_val:
                used_str = _fallback_cache.get(key, {}).get("used")
            else:
                used_str = used_val.decode("utf-8")

            if used_str != "1":
                return False

            await client.delete(key)
        except Exception:
            _fallback_cache.pop(key, None)

        return True

    @classmethod
    async def delete_otp(
        cls,
        email: str,
        action: str = OtpAction.DEFAULT,
        fingerprint: str = "default",
    ) -> None:
        """Clear OTP from Redis."""
        key = cls._otp_key(email, action, fingerprint)
        try:
            client = get_redis_client()
            await client.delete(key)
        except Exception:
            _fallback_cache.pop(key, None)

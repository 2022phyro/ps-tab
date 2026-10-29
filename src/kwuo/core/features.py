"""Feature flags and roadmap capability tracker for Kwuo platform."""

from typing import Dict, Any, List


class FeatureTracker:
    """Central registry tracking active, deferred, and v2 roadmap capabilities."""

    FEATURES: Dict[str, Dict[str, Any]] = {
        "mfa": {
            "name": "Two-Factor Authentication (2FA)",
            "status": "disabled",
            "target_version": "v2",
            "notes": "MFA is currently not enabled. Data model fields (mfa_secret, mfa_enabled) and UI controls exist but activation is scheduled for v2.",
        },
        "google_sign_in": {
            "name": "Google Sign-In",
            "status": "planned",
            "target_version": "v2",
            "notes": "OAuth2 / Google Workspace SSO login flow scheduled for v2.",
        },
        "paywall": {
            "name": "Paywall for Features",
            "status": "planned",
            "target_version": "v2",
            "notes": "Monetization paywall, billing tiers, and premium tournament quotas scheduled for v2.",
        },
        "email_provider": {
            "name": "Live Transactional Email Provider",
            "status": "console_only",
            "target_version": "v2",
            "notes": "Console logger with absence tracking active; live SMTP/Postmark/SendGrid integration scheduled for v2.",
        },
    }

    @classmethod
    def is_enabled(cls, feature_key: str) -> bool:
        """Check if a capability is currently active and enabled."""
        feature = cls.FEATURES.get(feature_key)
        return feature is not None and feature.get("status") == "enabled"

    @classmethod
    def get_feature(cls, feature_key: str) -> Dict[str, Any]:
        """Fetch specification metadata for a tracked feature."""
        return cls.FEATURES.get(feature_key, {})

    @classmethod
    def get_v2_roadmap(cls) -> List[Dict[str, Any]]:
        """Return all features and capabilities scheduled for Phase 2 / v2."""
        return [
            {"key": k, **v}
            for k, v in cls.FEATURES.items()
            if v.get("target_version") == "v2"
        ]

# Kwuo Feature & Roadmap Tracker

This tracker records the activation state, architectural readiness, and forward-looking roadmap for platform capabilities.

## 1. Current Feature Status

| Feature / Capability | Status | Target | Architecture & Implementation Notes |
| :--- | :--- | :--- | :--- |
| **Two-Factor Authentication (2FA / MFA)** | `DISABLED` | **v2** | **MFA is currently not enabled.** Database columns (`mfa_secret`, `mfa_enabled`) exist on `users`. Profile UI displays disabled state. Pairing and TOTP verification are scheduled for v2. |
| **Google Sign-In** | `PLANNED` | **v2** | OAuth2 federated identity / Google Workspace integration for 1-click organizer and debater onboarding. |
| **Paywall for Features** | `PLANNED` | **v2** | Tiered subscription access, paid tournament quotas, commercial billing, and payment gateway integration. |
| **Transactional Email Provider** | `CONSOLE_LOGGING` | **v2** | Currently dispatches formatted ASCII email boxes to stdout via `EmailProviderRegistry` (absence tracker active). Production SMTP / SendGrid / Postmark connection scheduled for v2. |

---

## 2. Phase 2 (v2) Deliverables

1. **MFA (Two-Factor Authentication)**:
   - TOTP secret generation (`pyotp` / QR code generation).
   - Recovery scratch codes.
   - Dual challenge during `/auth/login`.

2. **Google Sign-In**:
   - Google Identity Services / OAuth2 redirect flow.
   - Account linking with existing email identities.
   - Role preservation for verified institutional emails.

3. **Paywall for Features**:
   - Tournament tier limits (e.g. Free up to $N$ speakers, Pro for multi-division championships).
   - Stripe / Paystack webhook processing.
   - Feature entitlement checks in Scoped RBAC.

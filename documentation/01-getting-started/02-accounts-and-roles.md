---
title: "Accounts, Access & Security"
badge: "Authentication"
---

# Accounts, Access & Security

Kwuo balances stringent tab-room data integrity with rapid, frictionless access for attendees on mobile devices.

---

## User Roles & Privileges

The platform defines five distinct participant and administrative roles:

| Role | Access Tier | Authentication Method | Primary Responsibilities |
| :--- | :--- | :--- | :--- |
| **Tournament Director** | Full Admin | Email + Password / Session | Tournament provisioning, global settings, director sign-off |
| **Tab Staff Official** | Granular RBAC | Setup Link -> Password | Schedule management, roster entries, draw generation, ballot audit |
| **Equity Officer** | Dedicated Desk | Private Link | Confidential incident tracking, policy enforcement |
| **Adjudicator** | Portal Access | Zero-Auth Magic Link | Live ballot scoring, electronic signatures, judge feedback |
| **Competitor (Speaker)**| Portal Access | Zero-Auth Magic Link | Profile, schedule viewing, task downloads, speaker tab release |

---

## Zero-Auth Magic Link Architecture

Adjudicators and speakers do not create usernames or passwords. Instead, they receive unique time-ordered links:

```
https://tournament.kwuo.com/portal/speaker?token=eyJh...
https://tournament.kwuo.com/portal/judge?token=eyJh...
```

> [!TIP]
> Magic links are cryptographically signed using HS256 tokens bound to the specific participant ID and tournament tenant. They survive browser tab refreshes, mobile app switching, and network reconnection without re-prompting.

### Sending Magic Links
Tab staff can distribute magic links at any point:
- **Individual Dispatch**: Click the paper plane or link icon on any attendee card or row in the **Speakers** or **Adjudicators** roster.
- **Batch Dispatch**: Use the **Actions &rarr; Send Magic Links** batch operator to email links to all selected participants simultaneously.

---

## Staff Invitations & Setup Links

When a new official is appointed to the tab room staff:
1. The Director or Staff Administrator adds the official's name, email, and role assignment.
2. The system generates an immediate single-use setup link.
3. The official clicks the link to set their tab room password and activate their session.
4. Permissions are automatically governed by the role's permission matrix.

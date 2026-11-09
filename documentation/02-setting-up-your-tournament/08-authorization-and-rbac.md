---
title: "Authorization & RBAC"
badge: "Phase 1: Step 8"
---

# Authorization & Role-Based Access Control (RBAC)

Kwuo implements a granular permissions model that prevents accidental state modifications and guarantees clean separation of concerns.

---

## Permission Scopes & Categories

Permissions are organized into clear operational functional groups:

- **Settings Management (`settings:manage`)**: Editing tournament title, schedule timezones, room capacity policies, and draw rules.
- **Documents & Media (`documents:manage`)**: Uploading, deleting, and categorizing attachments.
- **Rubrics & Scoring Criteria (`rubric:manage`)**: Configuring scoring criteria weights and scale boundaries.
- **Speakers Roster (`speakers:manage`)**: Adding, editing, importing, and assigning competitors.
- **Adjudicators Roster (`judges:manage`)**: Calibrating judge composite scores, test weights, and availability.
- **Institutions (`institutions:manage`)**: Adding, merging, and assigning delegation boundaries.
- **Staff Administration (`officials:manage`)**: Appointing staff and issuing initialization setup links.
- **Round Draws & Pairing (`draws:manage`)**: Generating section allocations and panel assignments.
- **Ballots & Audit (`ballots:audit`)**: Reviewing, verifying, and unlocking digital scorecards.

---

## Custom Role Provisioning

Tab directors can create custom organizational roles (e.g., *Logistics Volunteer*, *Equity Lead*, *Tab Room Runner*) and select the exact permission checkboxes appropriate for that position. Changes take effect instantly across active sessions.

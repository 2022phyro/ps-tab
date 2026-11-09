---
title: "Master Schedule & Timezones"
badge: "Deep Dive"
---

# Master Schedule & Timezones

In modern hybrid and international tournaments, attendees join flights from multiple continents and time zones. Kwuo eliminates time zone confusion through an automated dual-timezone display architecture.

---

## 1. Storage & Canonical Time

- **Universal Anchor**: The tournament director designates the **Master Event Timezone** (e.g. `Africa/Harare`).
- **Database Normalization**: Milestones entered by tab staff in the admin cockpit are mapped to the master timezone and stored as timezone-aware UTC timestamps in PostgreSQL.
- **iCalendar Standardization**: The public `.ics` calendar export streams standards-compliant RFC 5545 events tagged with `X-WR-TIMEZONE`, syncing directly to Google Calendar, Apple Calendar, and Outlook with correct local conversion.

---

## 2. Client-Side Dual Timezone Toggle

Both the administrative cockpit and public schedule directory feature a persistent dual-timezone switcher:

- **Official Tournament Time**: Displays the authoritative event clock according to the host venue (e.g. *10:00 AM CAT / GMT+2*).
- **Your Local Device Time**: Automatically resolves the attendee's device timezone (e.g. *08:00 AM GMT / Europe/London*) and converts every milestone dynamically using standard browser `Intl.DateTimeFormat`.

> [!TIP]
> The active mode selection is remembered across page navigation using local browser storage, ensuring attendees always see times formatted to their preference.

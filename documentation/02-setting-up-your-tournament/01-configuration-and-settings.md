---
title: "Configuration & Settings"
badge: "Phase 1: Step 1"
---

# Configuration & Settings

The **Settings** cockpit is the administrative command center where you define baseline tournament rules, operational defaults, external communication channels, and master timetables.

---

## 1. Core Event Metadata

- **Tournament Name & Tenant Slug**: Defines the branded URL where your attendees access the public portal and tab room (`https://your-slug.kwuo.com`).
- **Dates & Venue**: Specify whether the event is physical, virtual (e.g., Zoom/Discord), or hybrid, alongside primary campus/hotel coordinates.

---

## 2. Master Schedule Timezone

All rounds, briefings, and roll calls are anchored to the tournament's official timezone.

> [!IMPORTANT]
> Always configure your master timezone before entering schedule milestones. When tab staff enter dates and times in the schedule tab, the platform interprets them in your tournament's official timezone and stores them as timezone-aware records.

### Supported Timezones
Kwuo supports all standard IANA timezones across all circuits, including:
- **Africa**: `Africa/Harare` (CAT, GMT+2), `Africa/Lagos` (WAT, GMT+1), `Africa/Johannesburg` (SAST, GMT+2), `Africa/Cairo` (EET, GMT+2), `Africa/Nairobi` (EAT, GMT+3).
- **Europe**: `Europe/London` (GMT/BST), `Europe/Paris` (CET), `Europe/Berlin` (CET).
- **Americas**: `America/New_York` (ET), `America/Chicago` (CT), `America/Denver` (MT), `America/Los_Angeles` (PT).
- **Asia & Oceania**: `Asia/Dubai` (GST), `Asia/Kolkata` (IST), `Asia/Singapore` (SGT), `Asia/Tokyo` (JST), `Australia/Sydney` (AEST).
- **Global**: `UTC`.

---

## 3. Draw & Pairing Parameters

- **Room Sizing Policy**:
  - `Min Room Size`: The minimum number of speakers assigned to a section (default: `4`).
  - `Max Room Size`: The ceiling capacity of a speaking section (default: `8`).
  - `Room Size Preference`: Choose between `FEWEST_ROOMS` (packs rooms closer to max size) or `BALANCED` (evens out speaker distributions across all sections).
- **Panel Sizing**: Minimum and target number of adjudicators assigned per section (typically `3` judges per room, minimum `1`).
- **Prelim Ties**: Whether preliminary round ballots allow ties on identical rank/score composites.
- **Ghost Speaker Policy**: Maximum allowable rounds a ghost (unseeded placeholder) speaker may be drawn to maintain round viability.

---

## 4. Communication Links

Configure quick-access communication widgets directly in the public and competitor portals:
- **WhatsApp Announcements Community**
- **Discord / Slack Server**
- **Zoom / Google Meet Room Links**
- **Live Motion / Task Drive Folders**

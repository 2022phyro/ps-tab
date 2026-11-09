---
title: "Platform Overview"
badge: "Core Architecture"
---

# Platform Overview

Welcome to **Kwuo**, a specialized tabulation engine and tournament management platform purpose-built for competitive public speaking, forensics, and expressive speech championships.

Unlike parliamentary debate (which pairs two or four opposing teams in binary head-to-head clashes), competitive public speaking takes place in **multi-speaker sections (4 to 8 speakers per room)** evaluated by adjudicator panels across multi-criteria scoring rubrics. Kwuo is engineered specifically around these mechanics.

> [!NOTE]
> Competitive public speaking demands section-based speaker rotation, judge composite weighting (CV, test scores, and live peer feedback), strict conflict-of-interest isolation, and monotonic ranking normalization.

---

## Key Principles of the Tab Room

1. **Zero-Friction Offline Resilience**: Everything runs seamlessly without dependence on external third-party CDNs. If campus or hotel Wi-Fi degrades during a championship weekend, local operation continues unabated.
2. **Zero-Auth Magic Access**: Competitors and adjudicators never have to remember passwords or configure credentials under pressure. Every participant receives a secure, time-delimited cryptographic magic link that provides instant access to their ballots, schedule, and flight status.
3. **Ergonomic Live Operations**: High-density tables, collapsible phase-based rails, instant client-side filtering, and persistent sticky controls keep tab staff fast and focused during tight turnaround windows.

---

## Tournament Lifecyle Phases

Every tournament on Kwuo moves through four structured phases:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 1. Organization │ ──> │   2. Rounds     │ ──> │  3. Outrounds   │ ──> │  4. Conclusion  │
│  Setup & Roster │     │  Live Flighting │     │   Break Ladder  │     │ Results Release │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

- **Phase 1: Organization**: Configuring settings, schedule timezones, document attachments, rubrics, competitor rosters, adjudicators, institutions, and staff authorization.
- **Phase 2: Preliminary Rounds**: Drawing rooms, assigning balanced judge panels, releasing tasks and motions, collecting digital ballots, and tracking verification gates.
- **Phase 3: Outrounds & Breaks**: Calculating cumulative ranks, breaking speakers into elimination brackets (Quarterfinals, Semifinals, Grand Final).
- **Phase 4: Conclusion & Tab Release**: Certifying final standings, publishing individual speaker trophies, and generating audited tab sheets.

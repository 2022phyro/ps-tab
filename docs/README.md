# PS Tab — Documentation

PS Tab is a standalone tabulation and event-management system for **public speaking tournaments**: individual speech events judged by rubric and rank, run in multi-speaker sections rather than debate's paired binary rooms.

This folder is the system's single source of truth for how it works — detailed enough to build from, plain enough that a competitor, judge, or organizer can read a page and understand the rule or workflow it describes. It intentionally contains **no database schemas or data models** — those are a later, separate design pass. What's here is the conceptual architecture: the rules engine, the workflows, the roles, and the UI logic.

## How this system differs from debate tab tools

Tools like Tabbycat are built around two-team (or multi-team) pairings, sides, and institutional clash rules that resolve at the level of a single room with a small number of competing units. PS Tab's unit of competition is the **individual speaker**, and a single "round" is many speakers competing simultaneously in a **section**, scored independently by each judge on a panel and converted to a **rank**. That shift changes almost everything downstream: room sizing is a headcount problem, not a pairing problem; clash-avoidance is a spreading problem across many speakers per room, not a pairing constraint; and speaking order — which barely matters in a two-team debate room — becomes its own fairness problem across multiple rounds.

## Reading order

If you're new to the system, read in this order. If you already know what you're looking for, jump straight to the relevant file.

1. **[01-tournament-mechanics.md](01-tournament-mechanics.md)** — the core rules engine: roster ingestion, dynamic check-in sizing, rubric scoring pipeline, section allocation, speaking-order bias balancing, tab/tie-breaks, and break/finals generation. Start here — everything else assumes this.
2. **[02-judging-contingencies.md](02-judging-contingencies.md)** — what happens when the judging pool doesn't cooperate: no-shows, swing judges, hot-swaps, degraded panels.
3. **[03-roles-and-access.md](03-roles-and-access.md)** — who can do what: the full permission hierarchy from Super Admin down to the general public.
4. **[04-identity-and-auth.md](04-identity-and-auth.md)** — how people get into the system: zero-auth tokenized links for tournament day, and persistent accounts for career-long tracking.
5. **[05-publishing-and-state.md](05-publishing-and-state.md)** — the state machine controlling what's public and when, plus the audit trail behind it.
6. **[06-ux-and-views.md](06-ux-and-views.md)** — the four core surfaces: organizer control center, public portal, digital scorecard, participant feedback loop.
7. **[07-architecture-and-resilience.md](07-architecture-and-resilience.md)** — lessons from existing tab tools and how PS Tab handles bad wifi, late scratches, concurrent edits, lost tokens, token-security hardening, and multi-tenancy.
8. **[08-cross-tournament-ecosystem.md](08-cross-tournament-ecosystem.md)** — what happens once results accumulate across many tournaments: circuits/series standings, cross-tournament ratings, institutional sweepstakes, and the identity-integrity work (disambiguation, merging, minors, data rights) that makes career-long tracking trustworthy.

Unfamiliar term? Check **[glossary.md](glossary.md)** first — every file assumes its definitions.

## Design principles behind everything in this folder

- **Speaker-centric, not team-centric.** No side constraints, no team clash logic — the constraint surface is institutional spreading and judge conflicts, applied per-speaker.
- **Rank is the primary currency, points are the tie-breaker.** Scores exist to produce a rank per section per round; cumulative standings are decided by ranks first, raw points second — a deliberate hierarchy, detailed in [01-tournament-mechanics.md](01-tournament-mechanics.md).
- **Nothing is public until an organizer says so.** Every round-level artifact (draw, results, standings) has its own visibility gate — see [05-publishing-and-state.md](05-publishing-and-state.md).
- **Every override is logged, nothing is silently mutated.** Manual judge swaps, score edits, and re-draws are always audit-stamped with who and when.
- **Tournament day should need zero passwords.** Access during a live event is token-based; accounts are an optional, opt-in layer for people who compete or judge repeatedly.
- **A single tournament is the atomic unit; a career is built by aggregating published tournaments, never by reaching into their internals.** Circuits, ratings, and sweepstakes (see [08-cross-tournament-ecosystem.md](08-cross-tournament-ecosystem.md)) all read from what's already published — none of them grant operational access into any tournament they aggregate.
- **Identity claims are anchored, never guessed.** Linking a result to a career profile always requires an email match or an explicit claim code — never a name match — so two people who share a name can never be conflated.

# Glossary

Shared vocabulary used across every document in this folder. If a term is used two different ways in the wild (e.g. debate tab tools vs. speech tab tools), this page states which meaning PS Tab uses.

| Term | Meaning in PS Tab |
|---|---|
| **Speaker** | An individual competitor. PS Tab has no teams — the speaker is the atomic competitive unit. May be **independent** (no school/institution) or **institution-affiliated**. |
| **Institution** | The school, club, or organization a speaker or judge is affiliated with. Used only for clash-avoidance (spreading), never for scoring. |
| **Section** (a.k.a. **Heat**, a.k.a. **Room**) | A group of speakers (typically 4–8) who compete against each other in the same place, same time slot, judged by the same panel. The three words are used interchangeably in this docset: "section" when talking about the roster of speakers, "room" when talking about the physical/virtual venue, "heat" when talking about the round-local field they're compared within. |
| **Round** | One full cycle of sections running concurrently across the tournament, each producing ballots that feed into standings. |
| **Panel** | The set of judges (1 or more) assigned to score a single section. |
| **Chair** | The senior/lead judge on a panel, when one is designated — breaks ties in deliberation-based formats, or is the tie-break authority when ballots disagree procedurally (not on score, which is always averaged). |
| **Ballot** | One judge's complete scoring submission for one section: per-speaker rubric scores, time-penalty flags, rank, and comments. |
| **Rubric** | The organizer-configured set of scoring criteria (e.g., Content, Delivery, Structure) and their point caps, applied per event type. |
| **Judge Total** | One judge's summed score for one speaker in one round: rubric criteria summed, minus time penalties. See [01-tournament-mechanics.md](01-tournament-mechanics.md). |
| **Round Score** | A speaker's panel-averaged score for a round (mean of all Judge Totals on that panel for that speaker). |
| **Rank** | A speaker's ordinal placement (1st, 2nd, 3rd, …) within their section for a round, derived by sorting Round Scores. |
| **Low-point win** | When a speaker earns a better rank than another speaker with a numerically lower Round Score than them — legal, but tab flags it for review in some configurations. |
| **Speaker Points** | Cumulative Round Score total across all rounds — the tie-breaker beneath ranks in standings. |
| **Break** | The threshold cut that advances a subset of the field into elimination/final rounds. |
| **Partial break** | A break where only the top few finishers *in each room* advance automatically; the rest of each room's eligible finishers compete in a **bubble round** to fill the remaining slots. See [01-tournament-mechanics.md](01-tournament-mechanics.md) §8. |
| **Bubble round** | A supplemental round, scored like any other, played only by the pool of speakers who didn't auto-advance in a partial break — its results decide who fills the outstanding slots in the next stage. |
| **Iron man / in-and-out** | Not applicable in the same sense as team debate; used loosely here only if a tournament runs multiple concurrent events and a speaker double-enters — see edge cases in [01-tournament-mechanics.md](01-tournament-mechanics.md). |
| **Swing / reserve judge** | A judge not pre-assigned to a panel, held available to cover a gap (no-show, conflict, panel expansion). |
| **Clash** | A conflict of interest between a judge and a speaker/institution in the same section (shared institution, personal relationship, prior coaching relationship) that should prevent that judge from being on that panel. |
| **Draw** | The generated pairing of speakers to sections and judges to panels for a round. |
| **Tab** (verb/noun) | The act of computing standings from ballots, or the standings themselves ("check the tab"). Also used for the staff role, "tab staff." |
| **Token** | A scoped, permanent (organizer-revocable, never time-expiring) credential — usually delivered as a URL or QR code — granting passwordless access to exactly one person's data. See [04-identity-and-auth.md](04-identity-and-auth.md). |
| **Group** | A named, scoped bundle of Permissions (Tab Staff, Institution Coordinator, Circuit Administrator, Super Admin, or an organizer-created custom group) that a user is a member of — the mechanism behind every role in [03-roles-and-access.md](03-roles-and-access.md). See `prisma/schema.prisma` "Roles & permissions (Grouped RBAC)". |
| **Permission** | An atomic capability (e.g. "generate a draw", "publish results") from a fixed, system-seeded catalog. Organizers choose which Groups get which Permissions; they don't invent new Permission keys. |
| **Claim** | The act of an authenticated user linking a persistent account to a roster entry in a specific tournament (via email match or claim code). |
| **Claim dispute** | Two accounts attempting to claim the same roster entry — resolved by tab staff, never by claim order. See [08-cross-tournament-ecosystem.md](08-cross-tournament-ecosystem.md) §4. |
| **Division** | An experience-based sub-field within a tournament (e.g., Novice vs. Open) that runs its own independent draw, tab, and break. See [01-tournament-mechanics.md](01-tournament-mechanics.md) §9. |
| **Circuit / Series** | An organizer-defined group of tournaments whose results roll up into a season-long standing, owned by a Circuit Administrator. See [08-cross-tournament-ecosystem.md](08-cross-tournament-ecosystem.md) §1. |
| **Circuit points** | The organizer-configured conversion of a single tournament's placement into season-long points within a circuit — distinct from cross-tournament rating below. |
| **Cross-tournament rating** | An optional, opt-in statistical estimate of a speaker's strength across events (Elo/Glicko-style), used for seeding — never an official standing. See [08-cross-tournament-ecosystem.md](08-cross-tournament-ecosystem.md) §2. |
| **Sweepstakes** | An institution-level aggregate score (within one tournament or across a circuit), computed from its speakers' results but never feeding back into individual standings. See [01-tournament-mechanics.md](01-tournament-mechanics.md) §12. |
| **Power-matching** | A draw method that seeds rooms by current standings (high-high or high-low) rather than randomly. See [01-tournament-mechanics.md](01-tournament-mechanics.md) §11. |
| **Embargo** | A targeted hold on one section's or speaker's results within an otherwise-released round, distinct from the round-level publish gates. See [05-publishing-and-state.md](05-publishing-and-state.md) §3. |
| **Coordinator (Coach)** | A role scoped to one institution's entries within one tournament — registers/scratches their own speakers, no operational tab access. See [03-roles-and-access.md](03-roles-and-access.md). |

# Architectural Research & Resilience Strategies

This document synthesizes operational lessons from established open-source tabulation software (Tabbycat and similar debate/speech tab tools) and applies them to the specific failure modes a live PS Tab tournament will actually hit. The theme across all of it: **live events fail at the network and human-process layer far more often than at the algorithm layer**, so resilience design matters at least as much as the rules engine in [01-tournament-mechanics.md](01-tournament-mechanics.md).

## Lessons from existing tab tools

Mature debate/speech tab systems converge on a few hard-won patterns worth carrying forward:
- **Publication is always a manual, reversible gate**, never automatic on computation — this is why [05-publishing-and-state.md](05-publishing-and-state.md) treats draws/results/standings as independent toggles rather than "compute = publish."
- **Every manual intervention is logged with a human-readable reason**, because post-tournament disputes are common and "the software did something" is never an acceptable answer to a competitor asking why their round changed.
- **Draws must be regenerable from a stable, deterministic process** — if a room's makeup is questioned, staff need to be able to explain *why* that allocation happened (institution spread, position-bias history), not just that an algorithm produced it. This is why §5–6 of [01-tournament-mechanics.md](01-tournament-mechanics.md) are described as transparent heuristics with explicit penalty scores, not opaque optimizers.
- **The system must degrade gracefully under judge/room shortfall rather than block the tournament** — codified in [02-judging-contingencies.md](02-judging-contingencies.md).

## Offline resilience & venue wifi

Tournament venues — school gyms, church halls, hotel conference floors — routinely have unreliable or absent wifi, and this hits hardest exactly where it matters most: judges submitting ballots from inside a room with a shared connection under load.

**Strategy: PWA-style local-first ballot capture.**
- The scorecard interface (§[06-ux-and-views.md](06-ux-and-views.md)) is designed to function fully offline once a judge's assignment data has loaded: scores, timer readings, and comments are captured and held locally on the device the moment they're entered.
- Submission is attempted immediately, but a failed network call doesn't block the judge from finishing their ballot — the ballot queues locally and retries submission in the background.
- Once connectivity returns, queued ballots sync automatically. Conceptually, this is a **queue-and-reconcile** pattern rather than a locking pattern: the system never assumes real-time connectivity is available at the moment a judge finishes scoring.
- If a device is lost or the app is closed before sync completes, the ballot isn't gone — surfacing a "pending submissions" indicator to the judge (and to tab staff, aggregated across all judges) makes an unsynced ballot visible as a known gap rather than a silent one, so staff can chase it down like any other missing-ballot case (§[02-judging-contingencies.md](02-judging-contingencies.md)) rather than treating it as a mysterious data loss.

## Late speaker scratches

A speaker withdrawing after a draw has already been generated and released is common (illness, scheduling conflict) and shouldn't force a full-tournament re-draw.

**Strategy: targeted, scoped re-draw.**
- Only the affected room(s) are recomputed — remaining speakers in that room keep their room assignment where possible; only if the room now falls below $R_{\min}$ (§[01-tournament-mechanics.md](01-tournament-mechanics.md) §3) does the system consider merging remaining speakers into a neighboring room.
- Speaking-order history (§[01-tournament-mechanics.md](01-tournament-mechanics.md) §6) is preserved for everyone unaffected — a scratch in Room 3 doesn't perturb the bias calculations already locked in for Room 5.
- If the scratch happens **after** judging has started but before the round locks, the ballot pipeline simply treats that speaker as absent for aggregation purposes (excluded from that round's rank computation, not scored as a zero) — this mirrors how a partial panel is handled in [02-judging-contingencies.md](02-judging-contingencies.md): missing data shrinks the computation, it never gets backfilled with an invented value.
- The re-draw is itself an audit-logged event (§[05-publishing-and-state.md](05-publishing-and-state.md)), same as any manual override, so "why did my room change after the draw was posted" always has a traceable answer.

## Concurrent edit / pattern collisions

Multiple staff members working the same tournament simultaneously (common at larger events with a full tab team) can collide — two people editing the same round's draw, or one publishing while another is mid-override.

**Strategy: last-write-wins with visible staleness detection, not silent overwrite.**
- Rather than a heavyweight locking scheme, the practical approach is to timestamp every mutation and warn a staff member if the data they're about to submit a change against has moved since they loaded it ("this round was modified by [other staff member] 40 seconds ago — reload before continuing?") — cheap to reason about, and matches how small tab teams actually coordinate (verbally, in the room), rather than forcing a formal locking protocol on top of people already talking to each other.
- Truly conflicting simultaneous actions on the *same* entity (e.g., two staff both hot-swapping the same panel slot at once) resolve to whichever write lands first at the system; the second write is rejected with a clear "this was already changed" message rather than silently clobbering the first — the audit trail (§[05-publishing-and-state.md](05-publishing-and-state.md)) makes the accepted change and its author visible immediately, so the second staffer isn't left guessing what happened.

## Sudden token loss

A competitor or judge loses their device, or their token link stops working mid-tournament (accidental revocation, expired TTL misconfigured too aggressively).

**Strategy: fast, low-friction reissuance, not account recovery ceremony.**
- Because the zero-auth token (§[04-identity-and-auth.md](04-identity-and-auth.md)) carries no password to "reset," recovery is simply: the person identifies themselves to tab staff at the check-in desk (or, for remote participation, via a lightweight verification like confirming the email on file), and staff reissues a fresh token for that roster entry — the old one is explicitly revoked in the same action so a lost/stolen device's old link can't be used afterward.
- If the person holds an authenticated account with this tournament already claimed (§[04-identity-and-auth.md](04-identity-and-auth.md)), they can instead simply log in and reach the same scoped view without needing staff intervention at all — this is one of the concrete practical payoffs of the optional account layer, not just career-tracking convenience.

## Token security hardening

Beyond the entropy and scoping design in [04-identity-and-auth.md](04-identity-and-auth.md), the token layer needs defense against automated abuse, not just accidental leakage:

- **Rate limiting** on token validation attempts, per source, so a brute-force guessing attempt against the token space is throttled long before it becomes viable — this is a standard defensive layer on top of, not a replacement for, the high-entropy design already described.
- **Anomaly detection on access patterns** (the same token suddenly used from many disparate locations in a short window) surfaces as a flag to tab staff, the same way a no-show or clash warning surfaces — a signal for a human to look at, not an automatic lockout, since a legitimate person switching between phone and laptop shouldn't get themselves silently locked out.
- Revocation (§[04-identity-and-auth.md](04-identity-and-auth.md)) remains the actual remedy once a suspicious pattern is confirmed — hardening buys time and visibility, it doesn't substitute for the organizer's revoke action.

## Multi-tenancy & concurrent tournaments

The platform runs many tournaments simultaneously, owned by unrelated organizers, and this needs to be a hard isolation boundary, not just a convention:

- **Tournament-scoped isolation:** every role's access (§[03-roles-and-access.md](03-roles-and-access.md)) is checked against a specific tournament's ownership, not just "is this user tab staff somewhere" — a collaborator on one tournament has zero implicit visibility into another, even one run by the same organizing body, unless explicitly added to it.
- **Resource contention:** draw generation, check-in processing, and ballot submission for a large concurrent slate of tournaments (e.g., a busy competition weekend across many host schools) must not let one tournament's heavy load (a big room-count recompute, a bulk CSV import) visibly slow down another's live round — this is a capacity/scaling concern for whatever compute layer eventually implements the engines in [01-tournament-mechanics.md](01-tournament-mechanics.md), flagged here so it's designed for rather than discovered under load.
- **Circuit-layer aggregation** (§[08-cross-tournament-ecosystem.md](08-cross-tournament-ecosystem.md)) reads across tournament boundaries by design, but strictly through each tournament's own publishing gates (§[05-publishing-and-state.md](05-publishing-and-state.md)) — the multi-tenancy boundary for *operational* access stays intact even though the *data* boundary is deliberately porous for published results.

## Data retention & backup

Conceptually (not as a schema decision): archived tournaments (§[05-publishing-and-state.md](05-publishing-and-state.md)) are a long-term historical record that the platform commits to keeping available and intact — this implies routine backups of tournament state independent of any single organizer's action, and a recovery point objective tight enough that an in-progress round's data loss window (between a ballot submission and its durable storage) is small. Unclaimed-roster-PII purging (§[05-publishing-and-state.md](05-publishing-and-state.md) §6) is the one deliberate exception to "keep everything" — a scheduled deletion, not a backup gap.

## Summary principle

Every strategy above shares one shape: **detect and surface the failure quickly, keep the degraded state usable, log the recovery action, and never quietly fabricate data to paper over a gap.** That principle — established for judging shortfalls in [02-judging-contingencies.md](02-judging-contingencies.md) — is the same one applied here to network, process, and identity failures.

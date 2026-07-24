# User Roles & Access Hierarchy

PS Tab has five core tiers of access, scoped from platform-wide control down to unauthenticated public viewing, plus three narrower auxiliary roles (§"Extended roles" below) that slot into this hierarchy at a fixed scope rather than introducing new privilege levels. Every permission below is enforced against the state gates described in [05-publishing-and-state.md](05-publishing-and-state.md) — a role having "access" to results doesn't override a round that hasn't been published; it only means that role *isn't blocked by* the standard visibility gate the way the public is.

## Permission matrix

| Capability | Super Admin | Tab Staff (owner/collaborator) | Adjudicator | Competitor | Public |
|---|:---:|:---:|:---:|:---:|:---:|
| Create/delete tournaments | ✅ (any) | ✅ (own) | ❌ | ❌ | ❌ |
| Configure rubrics, break rules, room bounds | ✅ | ✅ (own tournament) | ❌ | ❌ | ❌ |
| Run check-in, generate draws | ✅ | ✅ | ❌ | ❌ | ❌ |
| Manual draw / judge overrides, hot-swaps | ✅ | ✅ | ❌ | ❌ | ❌ |
| Advance/lock/unlock rounds | ✅ | ✅ | ❌ | ❌ | ❌ |
| Override a **locked** round (emergency) | ✅ | ❌ | ❌ | ❌ | ❌ |
| View/edit any tournament's audit log | ✅ | 🔶 own tournament, view-only for own actions + read access to all entries in it | ❌ | ❌ | ❌ |
| Submit ballots for assigned rooms | ❌ | ❌ | ✅ (own assignments) | ❌ | ❌ |
| View own ballot history / assignments | ❌ | ❌ | ✅ | ❌ | ❌ |
| View own scores, ranks, judge comments | ❌ | ❌ | ❌ | ✅ (own only) | ❌ |
| View published draws, results, standings | ✅ | ✅ | ✅ | ✅ | ✅ (once published) |
| View another competitor's private feedback | ❌ | 🔶 for dispute resolution only, audit-logged | ❌ | ❌ | ❌ |
| Suspend/ban a user platform-wide | ✅ | ❌ | ❌ | ❌ | ❌ |
| Recover from a system-level error (corrupted round state, stuck lock) | ✅ | ❌ | ❌ | ❌ | ❌ |

🔶 = conditional/elevated access, always audit-logged (see [05-publishing-and-state.md](05-publishing-and-state.md)).

## Role definitions

### Global Super Admin
Platform operators, not tournament staff. Super Admins can act across *any* tournament on the platform — this is an emergency/support capability, not a routine one. Their unique powers:
- **Unlock a locked round** anywhere on the platform, for cases tab staff can't self-resolve (e.g., a scoring bug requires reopening a round already marked final).
- **System error recovery** — resolve stuck states (a round stuck mid-lock after a crash, a corrupted draw) that no tournament-scoped role has the access to touch.
- Cross-tournament visibility for support purposes, not for competitive purposes — a Super Admin can see into any tournament's operations to help, not to publish or alter its competitive outcomes on a whim.

Every Super Admin action is audit-logged with elevated visibility — these are the actions most likely to be questioned after the fact, so they get the most scrutiny.

### Tournament Director / Tab Staff (owners & collaborators)
Full operational control over **their own** tournament(s) only. An **owner** can add/remove collaborators and delete the tournament; a **collaborator** has the same day-of operational powers (draws, overrides, publishing) but can't delete the tournament or manage who else has staff access. Distinguishing owner vs. collaborator matters for accountability on structural changes, not for day-of tab operations, where both act identically.
- Full lifecycle control: configure rubrics/break rules, run check-in, generate draws, advance rounds, publish/hide draws-results-standings independently (§[05-publishing-and-state.md](05-publishing-and-state.md)).
- Manual override authority: drag-and-drop re-pairing, judge hot-swaps (§[02-judging-contingencies.md](02-judging-contingencies.md)), score corrections before a round locks.
- Cannot unlock a round after it's locked without escalating to a Super Admin — this boundary is deliberate: once a round is locked, tab staff shouldn't be able to unilaterally reopen and re-score it without a second party involved, protecting competitors from quiet post-hoc changes.

**Terminology: CAP & OrgComm.** Many real-world PS circuits don't say "Tab Staff" — they say **CAP** (Chief Adjudicator/Panel) and **OrgComm** (Organizing Committee). These aren't a sixth privilege tier; they're circuit-conventional names for this same Tab Staff tier, or a permission subset of it. A CAP is typically scoped to judge-facing capabilities specifically — initial judge allocation weighting, reviewing judge feedback and determining judge breaks, instant hot-swaps, and manually reassigning *any* judge (§1 and §7, [02-judging-contingencies.md](02-judging-contingencies.md)) — while an OrgComm typically holds the fuller Tab Staff set (draws, publishing, round locking) plus everything CAP has, including the same authority to manually reassign a speaker (e.g., via the re-pairing grid). Because roles are configurable rather than a hardcoded list, a tournament names and scopes these groups however its own circuit conventionally does; the capability levels described in this document don't change, only the label and, optionally, which subset of Tab Staff's permissions a given group is granted. Whatever it's named, manual reassignment authority is unconditional in scope but never silent — it still runs through the same clash-check-and-warn, audit-logged override flow as any other Tab Staff action (§4, [02-judging-contingencies.md](02-judging-contingencies.md)).

### Adjudicators (Judges)
Scoped strictly to their own assignments:
- See only the rooms/rounds they're assigned to judge, never another panel's ballots.
- Submit rubric scores, time-penalty flags, and comments through the digital scorecard (§[06-ux-and-views.md](06-ux-and-views.md)).
- Can view their own judging history/reliability metrics if they hold an authenticated account (§[04-identity-and-auth.md](04-identity-and-auth.md)), but cannot see competitor standings beyond what's publicly published.
- Cannot edit a ballot once submitted and locked — a correction request goes through tab staff, which is itself an audited override.

### Competitors (Speakers)
- Full public visibility into anything the tournament has published (draws, results, standings) — same as the general public, no extra unlock.
- Private, additional access restricted to **themselves**: their own per-judge score breakdowns, comments, and feedback history, accessible via their personal token or authenticated account.
- No visibility into other competitors' private feedback, judge identities behind anonymized comments (if the tournament anonymizes), or unpublished rounds.

### General Public / Spectators
- Fully unauthenticated, read-only.
- Sees exactly what's been published at the tournament level and round level — nothing more, nothing pre-release. If a tournament chooses to keep standings unpublished until awards, the public sees nothing until that toggle flips, no matter how long the tournament runs.

## Extended roles

These three roles don't add new privilege *levels* — each is a narrower lens applied to an existing tier's scope, introduced because the core five don't cleanly cover them.

### Institution Coordinator / Coach
Scoped to **their own institution's entries within one tournament** — a real-world role (the coach who registers their team, manages last-minute scratches, and checks their own students in) that sits below Tab Staff and above Competitor in capability, but narrower than either in scope:
- Can bulk-register and edit their own institution's speaker/judge entries pre-tournament, and mark their own students as scratched — the same single-row correction path described in [01-tournament-mechanics.md](01-tournament-mechanics.md) §2, restricted to rows tagged with their institution.
- Can view their own speakers' published results and private feedback (with each speaker's own consent, since a coach viewing a minor's feedback is exactly the guardian-viewer case described in [08-cross-tournament-ecosystem.md](08-cross-tournament-ecosystem.md) §5) but has **no access** to draw generation, judge assignment, scoring, or any other institution's data — a coordinator is not a partial Tab Staff member, it's a scoped registrar role.
- Cannot see other institutions' rosters, even in aggregate, beyond whatever the tournament has already published publicly.

### Circuit / Series Administrator
Scoped to **a circuit** (§[08-cross-tournament-ecosystem.md](08-cross-tournament-ecosystem.md)) rather than to any single tournament:
- Defines circuit-points conversion tables, circuit qualification thresholds, and credential tiers for judges within that circuit.
- Reads only **published** results from member tournaments — has no operational access into any member tournament's draws, judging, or live overrides, since those remain fully owned by that tournament's own Tab Staff.
- Can remove a tournament from the circuit (e.g., a member event that stopped reporting results) but cannot alter that tournament's own data.

### Parent / Guardian Viewer
Scoped to **one minor competitor**, mirroring exactly what that competitor could see themselves:
- Views the minor's own results, private feedback, and (if applicable) a claimed cross-tournament career profile — nothing broader than the Competitor tier already allows for that one person.
- Cannot act on the minor's behalf for anything requiring consent (account creation, rating opt-in, data deletion) without it being logged as a guardian-initiated action, per [08-cross-tournament-ecosystem.md](08-cross-tournament-ecosystem.md) §5.

## Cross-role interaction: worked examples

**Judge data-entry correction.** A judge submits a ballot with an accidental data-entry error (e.g., transposed two speakers' scores). The judge can't self-correct post-submission. They flag it to tab staff (out-of-band, e.g. in person or via a note field). Tab staff, before the round locks, opens the override UI, corrects the specific score, and the action is written to the audit trail with staff identity, timestamp, and the before/after values. The judge sees the corrected ballot reflected in their own history; the affected competitors see the corrected score once results publish — they never see an intermediate "wrong" version, and they never see *who* fixed it beyond what the tournament chooses to disclose in its public change log, if any.

**Coordinator-initiated scratch.** A coach discovers one of their speakers is sick the morning of Round 3. The coordinator marks that speaker scratched through their own scoped view — this reaches the same targeted re-draw path Tab Staff would trigger manually (§[01-tournament-mechanics.md](01-tournament-mechanics.md) §14, §[07-architecture-and-resilience.md](07-architecture-and-resilience.md)), but the coordinator only *initiates* the scratch flag; Tab Staff still owns confirming the resulting re-draw, since room/panel recomputation is a tournament-wide operational action outside the coordinator's scope.

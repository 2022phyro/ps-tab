# UI/UX Views, Metrics & Visual Layouts

Four distinct surfaces cover every role defined in [03-roles-and-access.md](03-roles-and-access.md). Each is designed around how that role actually behaves on tournament day — a judge is on a phone with 90 seconds between speakers; an organizer is watching a dozen moving parts at once; a spectator is glancing at a leaderboard on their own time.

## 1. The Organizer Control Center

The tab staff's single working surface for an Active tournament. Structured as a dashboard-first layout, not a form-first one — staff should be able to see problems before they go looking for them.

**Layout:**
- **Status monitor strip** (top, always visible): current round, check-in progress (`N of M checked in`), live no-show/unresponsive alerts (§[02-judging-contingencies.md](02-judging-contingencies.md)) rendered as a small badge count that turns from neutral to warning color the moment an alert fires.
- **Round advancement wizard** (center): a linear, step-gated flow — Check-in → Generate Draw → Release Draw → Judging in progress → Collect Results → Release Results → Release Standings → Advance to next round. Each step shows its state plainly and the "next" action is always the one prominent button; skipping ahead (e.g., releasing results before all rooms report) requires an explicit confirmation, not a silent block, since organizers sometimes legitimately need to move on without a straggling room.
- **Manual override zone** (accessible from any step, not just its "natural" step): a drag-and-drop pairing grid — rooms as columns, speakers as draggable cards — for re-pairing, plus a judge-panel editor with the hot-swap flow from [02-judging-contingencies.md](02-judging-contingencies.md) surfaced inline (dragging a reserve judge onto an empty/red-flagged panel slot is the same gesture as re-pairing a speaker, for UI consistency).
- **Publishing toggle matrix** (per round): a small grid — rows are rounds, columns are Draws/Results/Standings — each cell a toggle reflecting the state machine in [05-publishing-and-state.md](05-publishing-and-state.md). Staff can see the whole tournament's publication state at a glance rather than digging into each round individually.

```
┌─ Round Advancement ───────────────────────────────────────┐
│  ✅ Check-in (24/24)  ✅ Draw generated  ✅ Draw released  │
│  🟡 Judging (5/6 rooms reported)   ⬜ Release Results       │
└─────────────────────────────────────────────────────────────┘

┌─ Publish Matrix ───────────┬────────┬─────────┬───────────┐
│                            │ Draws  │ Results │ Standings │
├────────────────────────────┼────────┼─────────┼───────────┤
│ Round 1                    │  ●On   │  ●On    │   ●On     │
│ Round 2                    │  ●On   │  ●On    │   ○Off    │
│ Round 3 (current)          │  ●On   │  ○Off   │   ○Off    │
└────────────────────────────┴────────┴─────────┴───────────┘
```

## 2. The Public Tournament Portal

Unauthenticated, mobile-first, and fast — most visitors are checking one thing (their room, or the leaderboard) on a phone with venue wifi.

- **Landing page:** tournament name, current round indicator, and a prominent link into whichever of {schedule, draws, standings} is currently the most relevant published artifact.
- **Dynamic room matrix:** a live view of the current round's rooms — room number/location, assigned speakers (once Draws are released), panel judges. Structured as a responsive card grid on mobile, a table on desktop.
- **Global leaderboard:** cumulative standings (once released), sorted by the tie-break hierarchy from [01-tournament-mechanics.md](01-tournament-mechanics.md) §7, with a clear **qualification indicator** — a visual marker (e.g., a colored line or badge) at the break cutoff so it's immediately obvious who's inside the break line without needing to know the threshold number.

```
 Rank  Speaker            Institution     Total Ranks   Points
 ─────────────────────────────────────────────────────────────
  1    A. Okafor          Lincoln HS           4          267.5
  2    J. Reyes           Independent          6          261.0
  3    M. Chen            Brookfield           7          258.5
 ─────────────  BREAK LINE (Top 6)  ──────────────────────────
  6    T. Adeyemi         Lincoln HS          11          249.0
  7    S. Patel           Riverside           13          247.5
```

## 3. The Digital Scorecard Interface

The judge's tool, optimized hard for mobile-in-hand use during a live speech — this is the highest-frequency, highest-time-pressure interface in the system.

- **Rubric input controls:** large tap targets per criterion (steppers or a slider, not a free-text number field) matching the point cap configured for that rubric (§[01-tournament-mechanics.md](01-tournament-mechanics.md) §4) — fast enough to adjust one-handed between speakers.
- **Built-in digital stopwatch:** starts/stops with the speech, visually flags entry into the grace period, and **automatically computes the time penalty** once the rubric's penalty schedule is configured — the judge never does penalty math by hand; the number is simply presented, adjustable only if the judge disputes the automatic reading.
- **Qualitative comment field:** a plain text box per speaker, clearly separated from the numeric score so judges are prompted to actually write feedback rather than treating it as optional filler.
- **Submission flow:** one ballot per section, all speakers scored on one continuous screen (swipe or scroll between speakers, not a full page reload) — minimizes the chance a judge submits an incomplete ballot without noticing.

```
┌─ Speaker 3 of 6 — Content (0–30) ────────┐
│        [ - ]      24      [ + ]           │
├─ Delivery (0–30) ─────────────────────────┤
│        [ - ]      27      [ + ]           │
├─ Structure (0–20) ─────────────────────────┤
│        [ - ]      16      [ + ]           │
├─ Timer ────────────────────────────────────┤
│   05:42 / 06:00   grace ends 06:10         │
│   Time penalty: 0 (within grace)           │
├─ Comments ─────────────────────────────────┤
│  [ strong opening, rushed conclusion... ]  │
└────────────────────────────────────────────┘
        ◀ Prev speaker   Next speaker ▶
```

## 4. The Participant Feedback Loop

Where competitors close the loop on their own performance, privately.

- **Performance trajectory view:** a per-round breakdown of the competitor's own Round Scores and ranks across the tournament (and, for authenticated users, across their entire claimed career — [04-identity-and-auth.md](04-identity-and-auth.md)), so a speaker can see whether they trended up or down, not just their final placement.
- **Judge feedback archive:** every comment and score breakdown they've personally received, attached to the round/judge (or anonymized judge label, if the tournament anonymizes), searchable rather than buried in a single flat list once a career spans many tournaments.
- **Structured post-round evaluations:** where a tournament requires competitors to submit feedback on their own judges (a common integrity/quality-control mechanism), the UI gates this as a short required form tied to the feedback window (§[05-publishing-and-state.md](05-publishing-and-state.md)) — simple enough to complete in under a minute between rounds, not an obstacle to seeing their own results (viewing their own results is never blocked on submitting judge feedback, even if the tournament strongly encourages it).

## 5. Institution Coordinator & Circuit Administrator views

Two smaller, purpose-built surfaces for the auxiliary roles defined in [03-roles-and-access.md](03-roles-and-access.md):

- **Coordinator dashboard:** a scoped slice of the control center (§1) showing only that coordinator's own institution's entries — a roster list with inline scratch/edit actions, and a read-only view of their speakers' published results. No draw, judging, or publishing controls appear here at all, since those are outside the role's scope entirely, not just hidden by default.
- **Circuit dashboard:** for a Circuit Administrator (§[08-cross-tournament-ecosystem.md](08-cross-tournament-ecosystem.md)) — a season-standings table aggregated across member tournaments, a simple points-conversion-table editor, and a qualification-threshold control, all reading from published tournament results only. No member tournament's internal operations are reachable from here.

## 6. Accessibility & notifications

Design constraints that cut across every surface above, easy to bolt on as an afterthought and much worse if treated that way:

- **Accessibility:** every control described above (rubric steppers, publish toggles, the drag-and-drop pairing grid) needs a non-pointer equivalent — keyboard navigation and screen-reader labeling, not just visual affordances. The break-line indicator on the leaderboard (§2) and any other purely color-coded status (no-show alerts, embargo flags) always pairs color with a text/icon label, since color alone excludes color-blind users. Text scales without breaking layout, particularly on the scorecard (§3), which is used one-handed and often in poor lighting.
- **Notifications:** beyond the control center's live-updating alert badges (§1, and §[02-judging-contingencies.md](02-judging-contingencies.md)), the same events that raise a staff alert can optionally push a **notification** to the affected person directly — a judge gets notified the moment they're hot-swapped onto a room, a competitor gets notified the moment their round's results release, without either needing to be actively watching the portal. Delivery channel (push, email, SMS) is an organizer/tournament configuration, since venue connectivity and participant preferences vary; the notification content itself is always a pointer back to the relevant view, never a duplicate of private data sent insecurely (e.g., an SMS says "your Round 3 results are ready" with a link, not the score itself in plaintext).
- **Paper fallback:** for judges without a reliable device or in a format that mandates a physical ballot backup, a printable paper ballot mirroring the digital rubric (§3) is available as a fallback — filled by hand and transcribed into the system by tab staff afterward as a normal ballot-entry action, distinguishable in the audit trail (§[05-publishing-and-state.md](05-publishing-and-state.md)) as staff-transcribed rather than judge-submitted, so a discrepancy has an obvious explanation later if one arises.

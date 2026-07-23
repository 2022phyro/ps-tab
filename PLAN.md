# PS Tab — Implementation Plan

**How to use this file:** work top to bottom. Each Section has a checkbox task list and ends with a **Definition of done**. Check items off as you go. If a session ends mid-section, update the **Progress Log** at the bottom before stopping — the next session's first move is to read that log, not to re-derive state from scratch.

Every section references the `docs/0X-*.md` file(s) it implements. If an implementation decision diverges from what a doc says, update the doc in the same commit — `docs/` and the code should never quietly drift apart.

---

## Tech stack (decided)

| Concern | Choice |
|---|---|
| Framework | Next.js 16 (App Router), TypeScript strict — scaffolded with 16.2.11, the actual current release at build time (plan originally said 15; the version note below covers what changed) |
| Package manager | pnpm |
| Database | **Local PostgreSQL, running in WSL** — used for local dev and this session's "test production." A cloud-reachable Postgres (e.g. Neon) is still required before any real deploy to Vercel, since Vercel's serverless functions cannot reach a local WSL instance — revisit at that point, don't forget it. |
| ORM | Prisma |
| Auth (persistent accounts) | Auth.js (NextAuth v5), email magic-link via Resend |
| Zero-auth tokens | Custom — DB-backed opaque tokens, hashed at rest, scope + TTL + revoked columns |
| Background/scheduled jobs | Inngest |
| Rate limiting | **Local Redis** (already running, reachable at `localhost:6379`) via `ioredis` + `rate-limiter-flexible` — same caveat as the database: swap to a cloud-hosted Redis (Upstash was the original pick, still fine) before deploying to Vercel. |
| Transactional email | Resend + `react-email` |
| Validation | Zod |
| Forms | `react-hook-form` + `@hookform/resolvers/zod` |
| UI components | Tailwind CSS + shadcn/ui (Radix primitives), themed from `branding.config.ts` (root) |
| Client data / polling | TanStack Query |
| CSV parsing | `papaparse` |
| QR codes | `qrcode` |
| Error tracking | Sentry |
| Testing | Vitest (unit) + Playwright (e2e) |
| CI | GitHub Actions |
| Hosting | Vercel (serverless) |
| API layer | Server Actions + Route Handlers (no tRPC) |
| Realtime | Polling via TanStack Query (MVP — swap for push later without touching the data layer) |

### Next.js 16 specifics (read before writing App Router code)

The scaffold generated an `AGENTS.md`/`CLAUDE.md` pair with a standing warning: this Next.js version has breaking changes vs. most training data — check `node_modules/next/dist/docs/` before assuming an API. The load-bearing ones already hit while bootstrapping:

- **`params`/`searchParams`/`cookies`/`headers` are fully async now** — always `await` them, no synchronous fallback exists (removed in 16, was deprecated-but-working in 15).
- **`middleware.ts` → `proxy.ts`** — the file and exported function are renamed (`export function proxy(request)`), `edge` runtime is no longer supported there (use the old `middleware.ts` name only if edge runtime is required). **This matters directly for Section 4** (role/permission middleware) — use `proxy.ts`, not `middleware.ts`.
- **Turbopack is default** for both `next dev` and `next build` — no `--turbopack` flag needed; a custom webpack config would now need an explicit opt-in flag instead.
- **`next lint` is removed** — lint via the ESLint CLI directly (already wired: `pnpm lint` → `eslint .`).

## Local infrastructure setup (do this first)

- [x] Postgres role + database created in the local WSL instance — done; `DATABASE_URL` present in `.env`.
- [x] Confirm the resulting `DATABASE_URL` connects from the Windows side — confirmed via TCP reachability check on port 5432; full auth check happens in Section 2 during `prisma migrate dev`.
- [x] Local Redis already running and confirmed reachable (`redis-cli ping` → `PONG`) — confirmed; `REDIS_URL` present in `.env`.

### Local Postgres setup

Run in your WSL terminal:

```bash
# 1) Generate a random local password and print it — copy it into .env in the next step
PSTAB_DB_PASSWORD=$(openssl rand -hex 16)
echo "Generated password (save this): $PSTAB_DB_PASSWORD"

# 2) Create the role. CREATEDB lets Prisma manage its own shadow DB during `migrate dev`.
sudo -u postgres psql -c "CREATE ROLE ps_tab_user WITH LOGIN PASSWORD '${PSTAB_DB_PASSWORD}' CREATEDB;"

# 3) Create the database, owned by that role
sudo -u postgres psql -c "CREATE DATABASE ps_tab OWNER ps_tab_user;"

# 4) Postgres 15+ revokes CREATE on the public schema by default — grant it back
sudo -u postgres psql -d ps_tab -c "GRANT ALL ON SCHEMA public TO ps_tab_user;"

# 5) Sanity check — connect as the new role
PGPASSWORD="${PSTAB_DB_PASSWORD}" psql -U ps_tab_user -h localhost -d ps_tab -c "SELECT current_user, current_database();"
```

Resulting `.env` line:
```
DATABASE_URL="postgresql://ps_tab_user:<the-generated-password>@localhost:5432/ps_tab?schema=public"
```

## Third-party accounts checklist

Create these before/during Section 1–2. Free tiers cover all of local dev.

- [ ] **Vercel** — hosting + deploy
- [x] ~~Neon~~ — deferred; using local Postgres for now (see above). Revisit before any real Vercel deploy.
- [ ] **Resend** — transactional email (domain verification needed before production sending works)
- [ ] **Inngest** — background jobs / scheduled functions
- [x] ~~Upstash~~ — deferred; using local Redis for now (see above). Revisit before any real Vercel deploy.
- [ ] **Sentry** — error tracking
- [ ] GitHub repo + Actions enabled (assuming GitHub as the git host)
- [ ] *(Deferred — not needed for MVP)* Twilio, for SMS notifications (docs/06 §6)
- [ ] *(Deferred — not needed for MVP)* Google Cloud OAuth client, if OAuth sign-in is added beyond email magic-link

Env vars these will produce (fill in `.env.example` as each is created): `DATABASE_URL` (local Postgres, see above), `AUTH_SECRET`, `RESEND_API_KEY`, `INNGEST_EVENT_KEY`, `INNGEST_SIGNING_KEY`, `REDIS_URL` (local, e.g. `redis://localhost:6379`), `SENTRY_DSN`, `NEXT_PUBLIC_APP_URL`.

---

## Section 1 — Project bootstrap

*Implements: n/a (infrastructure only)*

- [x] `pnpm create next-app` — TypeScript, App Router, Tailwind, `src/` directory, ESLint (scaffolded to a temp dir and merged in, since the repo already had `docs/`/`PLAN.md`/`branding.config.ts`/`.env` that create-next-app's non-empty-dir check doesn't allow)
- [x] Configure `tsconfig.json` strict mode (`strict: true` was already default from the scaffold; added `noUncheckedIndexedAccess: true`)
- [x] Prettier config + ESLint integration, `pnpm format` / `pnpm lint` scripts (`eslint-config-prettier` + `prettier-plugin-tailwindcss`)
- [x] Initialize shadcn/ui (`pnpm dlx shadcn@latest init --yes --defaults --force` — non-interactive; the plain `init` prompts even with `--yes` if `components.json` already exists, `--force` is needed on a retry)
- [x] Map `branding.config.ts` onto the Tailwind theme (`src/app/globals.css` — primary/brand-accent/semantic colors, radius) and register the three fonts via `next/font/google` in `src/app/layout.tsx` (Space Grotesk/Inter/JetBrains Mono). Tailwind v4's CSS-first config can't import a `.ts` file, so `globals.css` is a hand-mirror of `branding.config.ts` — a comment at the top of each points to the other; keep them in sync manually on rebrand.
- [x] Create `.env.example` with every var from the checklist above (empty/placeholder values) — also added `NEXT_PUBLIC_SENTRY_DSN`/`SENTRY_ORG`/`SENTRY_PROJECT`/`SENTRY_AUTH_TOKEN` once Sentry setup clarified exactly which vars it needs
- [ ] **Link repo to a Vercel project — needs you.** `vercel` CLI is installed (`pnpm add -D vercel`, present in `package.json`), but `vercel login`/`vercel link` need an interactive browser auth this session can't complete. Run from the project root: `pnpm exec vercel login` then `pnpm exec vercel link`. No deploy yet — link only.
- [x] Install + init Sentry — the `@sentry/wizard` needs a real TTY (it crashed here with `ERR_TTY_INIT_FAILED`), so this was done manually instead: `sentry.server.config.ts`, `sentry.edge.config.ts`, `src/instrumentation.ts` (`register()` + `onRequestError`), `src/instrumentation-client.ts` (`Sentry.init` + `onRouterTransitionStart`), `next.config.ts` wrapped with `withSentryConfig`. Sentry is disabled at runtime until `SENTRY_DSN`/`NEXT_PUBLIC_SENTRY_DSN` are set in `.env` — **needs you**: create a Sentry project and paste its DSN in; source-map upload additionally needs `SENTRY_ORG`/`SENTRY_PROJECT`/`SENTRY_AUTH_TOKEN`.
- [x] Install Vitest, add `pnpm test` script, one placeholder test passing (`src/app/page.test.tsx`, asserts the brand tagline renders — doubles as a branding-wiring smoke test)
- [x] Install Playwright, add `pnpm test:e2e` script, one placeholder spec passing (`e2e/home.spec.ts`, same assertion end-to-end against a real build); Chromium browser binary installed via `pnpm exec playwright install chromium --with-deps`
- [x] `.gitignore` review — merged the scaffold's newer version (adds `.pnpm-debug.log*`, generalizes `.env*`) over the original, then added Playwright's `test-results/`, `playwright-report/`, `blob-report/`
- [ ] Commit: "Project bootstrap" — not yet committed, see Progress Log

**Definition of done:** `pnpm dev` runs the app locally, `pnpm lint`, `pnpm test`, and `pnpm test:e2e` all pass (confirmed). Vercel project link is the one item still needing you — see above.

**Windows/pnpm note for future sessions:** running two `pnpm add`/`pnpm install` commands concurrently in this repo reliably produces `ERR_PNPM_EPERM` rename errors (two pnpm processes racing on the same `node_modules/.pnpm` store) — always run pnpm commands one at a time, sequentially, and wait for each to fully exit before starting the next. A same-command retry after a transient `EPERM` has been sufficient every time it happened.

---

## Section 2 — Database & Prisma schema

*Implements: docs/01, docs/03, docs/04, docs/05, docs/08*

- [ ] Local Postgres role/db created (see "Local Postgres setup" above); `DATABASE_URL` set in `.env`
- [ ] `pnpm add prisma @prisma/client`, `pnpm prisma init`
- [ ] Model: **Auth.js tables** (`User`, `Account`, `Session`, `VerificationToken`) — use the standard Prisma adapter schema, extend `User` with a `superAdmin: Boolean` flag (docs/03) and `isMinor` / `guardianEmail` fields (docs/08 §5)
- [ ] Model: **Tournament** (state: Draft/Active/Concluded/Archived per docs/05 §1), owner + collaborator relation to `User` (docs/03)
- [ ] Model: **Division** (docs/01 §9) — belongs to Tournament, own break config
- [ ] Model: **Round** (belongs to Division), with independent `drawsState` / `resultsState` / `standingsState` enums (docs/05 §2) and `lockedAt` (docs/05 §4)
- [ ] Model: **Institution** — no pre-seeded list; grows organically as roster entries reference it (docs/01 §2). Add a case-insensitive/trigram index (`pg_trgm`) to support the fuzzy-match lookup the registration UI and CSV-import flagging both depend on
- [ ] Model: **RosterEntry** (speaker or judge, independent-or-institution-affiliated via nullable Institution FK, `isMinor`, division FK) (docs/01 §2, §9) — minimum fields for a self-service-registered row are `email`, `name`, `institutionId` (nullable)
- [ ] Server Action: institution search (`searchInstitutions(query)`) backing the registration combobox — returns existing matches first; "create new" is a separate explicit action, never implicit on submit (docs/01 §2)
- [ ] Model: **Section/Room** + join table to RosterEntry (speakers) and to judges (**Panel**) (docs/01 §5)
- [ ] Model: **Rubric**, **RubricCriterion** (point caps), **TimePenaltyPolicy** (docs/01 §4)
- [ ] Model: **Ballot** (one per judge per section per round) + **Score** (per criterion) + computed `judgeTotal` (docs/01 §4)
- [ ] Model: **PositionHistory** (per speaker per round, for bias balancing — docs/01 §6)
- [ ] Model: **Token** (zero-auth) — `hashedValue`, `scope`, `expiresAt`, `revokedAt`, FK to RosterEntry (docs/04 §1)
- [ ] Model: **Claim** / **ClaimDispute** (docs/04 §2, docs/08 §4)
- [ ] Model: **Circuit**, **CircuitMembership**, **CircuitPointsRule** (docs/08 §1)
- [ ] Model: **AuditLogEntry** — append-only, action/actor/timestamp/before/after/reason (docs/05 §5)
- [ ] Model: **Embargo** (per-entity hold, docs/05 §3)
- [ ] Model: role-scoping join tables for **InstitutionCoordinator** and **CircuitAdministrator** (docs/03 "Extended roles")
- [ ] First migration: `pnpm prisma migrate dev --name init`
- [ ] Write `prisma/seed.ts` — one sample tournament, 2 divisions, ~20 roster entries across 3 institutions, 1 completed round with ballots
- [ ] `pnpm prisma db seed` runs clean; spot-check via Prisma Studio

**Definition of done:** `pnpm prisma migrate dev` and the seed script run clean against the local Postgres database; Prisma Studio shows a coherent seeded tournament matching the shape described in docs/01.

---

## Section 3 — Core rules engine (pure logic)

*Implements: docs/01 in full*

Build under `src/lib/rules-engine/`, framework-agnostic (plain TS functions/classes, no Next.js or Prisma imports inside the algorithms themselves — they take/return plain data; a thin adapter layer wires them to Prisma later in Section 4+).

- [ ] `roomSizing.ts` — §3 algorithm ($R_{\min}$/$R_{\max}$ → room count/sizes); unit test against the $N=27$ worked example
- [ ] `scoringPipeline.ts` — §4 (Judge Total → Round Score → Rank), incl. tie handling; unit tests for single- and multi-judge cases
- [ ] `sectionAllocation.ts` — §5 greedy + local-repair clash-avoidance heuristic; unit test with a deliberately unresolvable clash case (verify it flags rather than errors)
- [ ] `positionBias.ts` — §6 bias-score + slot assignment; unit test verifying convergence over several simulated rounds
- [ ] `tabulation.ts` — §7 tie-break hierarchy (Total Ranks → Speaker Points → Adjusted Ranks); unit test against the worked A/B example
- [ ] `breaksAndFinals.ts` — §8 threshold rules + §11 multi-stage elimination chaining
- [ ] `divisions.ts` — §9 eligibility gating helpers
- [ ] `schedulingCollisions.ts` — §10 speaker/judge double-booking detection across concurrent events
- [ ] `drawMethods.ts` — §11 power-matching seeding variant
- [ ] `sweepstakes.ts` — §12 institutional aggregate scoring
- [ ] `waitlist.ts` — §13 cap + promotion-in-order logic
- [ ] `edgeCases.spec.ts` — one test per §14 edge case (byes, uneven rooms, single-judge panels)
- [ ] `pnpm test` — full rules-engine suite green, no DB/network involved

**Definition of done:** `pnpm vitest run src/lib/rules-engine` passes in full, in isolation, with every worked example from docs/01 encoded as an assertion.

---

## Section 4 — Identity & access backend

*Implements: docs/03, docs/04, docs/08 §4–5*

- [ ] Auth.js config: Prisma adapter, Resend email provider (magic link), session strategy
- [ ] Role/permission helper (`src/lib/auth/permissions.ts`) encoding the full matrix from docs/03 — one function per capability check, not scattered `if` checks
- [ ] Middleware / route-group guards for each of the 5 core roles + 3 extended roles
- [ ] Zero-auth token service (`src/lib/tokens/`): `issue()`, `validate()`, `revoke()`, TTL enforcement — hashed-at-rest lookup, never store raw token server-side
- [ ] QR code generation for token delivery (`qrcode` package) — Server Action returning a data URI
- [ ] Roster-to-account claim flow: email-match auto-suggestion + manual claim-code entry, always requiring explicit user confirmation (docs/04 §2)
- [ ] Account recovery flow (docs/04 §4) — standard Auth.js email reset; document the support-mediated fallback path (manual, no code needed yet — flag as a support runbook item)
- [ ] Account merge flow (docs/08 §4) — verify-both-accounts step, combine claimed history, retire the losing account, reversible for a grace period
- [ ] Claim dispute flagging + Tab-Staff resolution UI hook (backend only here — UI in Section 9)
- [ ] Guardian-consent gate (docs/08 §5) — blocks account creation / rating opt-in for `isMinor` roster entries without a confirmed guardian step

**Definition of done:** a seeded roster entry can be claimed by a test account end-to-end (magic link → claim confirmation), a token can be issued/validated/revoked via unit tests, and every role's permission check has a corresponding test asserting both an allowed and a denied case.

---

## Section 5 — Judging contingencies backend

*Implements: docs/02*

- [ ] Reserve-pool state on RosterEntry (judge): `InReservePool` / `CheckedIn` / `Deployed`
- [ ] Inngest scheduled function: no-show sweep (checked-in signal missing at round start) + unresponsive sweep (no ballot past grace period) — writes alerts, doesn't email yet (Section 8 wires notifications)
- [ ] Hot-swap Server Action: candidate list (checked-in + idle reserves only), re-run clash check from Section 3, write AuditLogEntry
- [ ] Degraded-panel logic: collapse below configured panel size, minimum-panel floor enforcement (blocks if zero), partial-ballot preservation (exclude judge only for unreached speakers)
- [ ] Judge fatigue caps: max-rounds-per-day check feeding into assignment-pool exclusion
- [ ] Self-reported recusal Server Action (judge-initiated, same clash machinery as automatic detection)
- [ ] Live calibration flag: per-room ranking-divergence check on ballot submission, surfaced as a review flag (no auto-correction)

**Definition of done:** simulated no-show scenario (seed a checked-in-false judge) produces a flagged alert via the sweep function; a hot-swap in a unit/integration test correctly re-runs the clash check and logs an audit entry.

---

## Section 6 — Publishing & state machine backend

*Implements: docs/05*

- [ ] Tournament state transitions (Draft → Active → Concluded → Archived) as a guarded state machine, not free-form enum writes
- [ ] Round-level independent gates: Draws (Hidden/Released), Results (Held/Released), Standings (Held/Released)
- [ ] Per-entity embargo model + check woven into every results-read path (docs/05 §3)
- [ ] Scheduled auto-publish: Inngest scheduled function per gate-with-a-future-timestamp, cancellable
- [ ] Lock trigger (on Results release or all-ballots-submitted, per tournament config) → immutability enforcement on Ballot/Score writes
- [ ] Super Admin unlock escalation flow — requires reason, auto re-locks after correction, audit-logged both ends
- [ ] `AuditLogEntry` writer used by every mutating action across all sections — retrofit Sections 4–5's actions to call it if not already
- [ ] Retention job (Inngest scheduled): purge unclaimed-roster PII past configured window; leave competitive result data intact

**Definition of done:** a round can be advanced through all three gates independently via direct Server Action calls (no UI yet), a locked round rejects a direct score edit unless the Super Admin escalation path is used, and every mutation in this section produces exactly one AuditLogEntry.

---

## Section 7 — Cross-tournament ecosystem backend

*Implements: docs/08, docs/01 §12*

- [ ] Circuit CRUD + CircuitMembership (tournament opts in)
- [ ] Circuit points conversion engine (configurable table/curve) reading only *published* tournament standings
- [ ] Cross-tournament rating computation (Inngest job triggered on tournament conclusion) — opt-in per account, clearly labeled as distinct from circuit points
- [ ] Sweepstakes aggregation: single-tournament (from Section 3's `sweepstakes.ts`) + circuit-level rollup
- [ ] Claim-dispute resolution backend (org-facing) — surfaces contested claims for Tab Staff to resolve
- [ ] Data-deletion request handling: unlink account from claimed history (revert to unclaimed roster entries), delete account + aggregated view, leave tournament-of-record data intact

**Definition of done:** a seeded 2-tournament circuit produces correct cumulative circuit-points standings and a correctly-computed (test-fixture) rating delta after the second tournament concludes.

---

## Section 8 — Notifications & background jobs wiring

*Implements: docs/07, docs/06 §6*

- [ ] Inngest client wired into Next.js (`src/app/api/inngest/route.ts`)
- [ ] React Email templates: token delivery, results-released, judge hot-swap notice, round-advance reminder
- [ ] Wire Section 5's no-show/unresponsive alerts and Section 6's publish events to actually send email via Resend
- [ ] Redis-backed (`rate-limiter-flexible`) rate limiter middleware applied to: token validation route, magic-link request route, claim-code entry route
- [ ] Local dev loop: Inngest dev server + Resend test mode — trigger one event manually, confirm email received

**Definition of done:** triggering a results-release Server Action in a local dev environment results in a real (test-mode) email being sent, and hammering the token-validation endpoint past the configured rate limit returns a 429 instead of continuing to hit the DB.

---

## Section 9 — Frontend: Organizer Control Center

*Implements: docs/06 §1, §5*

- [ ] Dashboard shell + status monitor strip (current round, check-in progress, live alerts via polling)
- [ ] Round advancement wizard (step-gated UI over Section 6's state machine)
- [ ] Publish toggle matrix (rounds × Draws/Results/Standings)
- [ ] Manual override zone: drag-and-drop pairing grid + judge panel editor (hot-swap UI wired to Section 5)
- [ ] Audit log viewer (own-tournament scope)
- [ ] Institution Coordinator scoped dashboard (own-institution roster + scratch actions)
- [ ] Circuit Administrator dashboard (circuit standings + points-table editor + qualification threshold control)
- [ ] Claim-dispute resolution UI (surfaces Section 7's contested claims to Tab Staff)

**Definition of done:** a tab-staff test user can, entirely through the UI against the seeded tournament, run check-in → generate a draw → release it → hot-swap a judge → collect/release results → release standings.

---

## Section 10 — Frontend: Digital Scorecard (judge)

*Implements: docs/06 §3, docs/07*

- [ ] Mobile-first rubric input controls (steppers/sliders per criterion)
- [ ] Built-in stopwatch + automatic grace-period time-penalty calculation
- [ ] Comment field per speaker
- [ ] One-continuous-screen submission flow (swipe/scroll between speakers)
- [ ] Offline-first local queue: capture scores/comments locally, attempt submit, queue-and-retry on failure, "pending submissions" indicator
- [ ] Background sync on reconnect

**Definition of done:** with devtools network throttled to offline, a full ballot can be entered and is visibly queued; restoring network causes it to sync and appear server-side without data loss.

---

## Section 11 — Frontend: Public Portal

*Implements: docs/06 §2, docs/08*

- [ ] Landing page (tournament name, current round, links to published artifacts)
- [ ] Dynamic room matrix (responsive card grid / table)
- [ ] Global leaderboard with break-line indicator (color + text/icon per a11y requirement)
- [ ] Circuit standings page
- [ ] Self-service registration form (email, name, institution combobox — search-existing-first, explicit "add new" fallback; wired to Section 2's `searchInstitutions` action) (docs/01 §2)

**Definition of done:** all four views render correctly against the seeded tournament in both a released-everything state and a mostly-held-back state (confirming the gates from Section 6 are actually respected, not just present in the schema).

---

## Section 12 — Frontend: Participant feedback loop & career profile

*Implements: docs/06 §4, docs/04, docs/08*

- [ ] Performance trajectory view (per-round, and cross-tournament for claimed accounts)
- [ ] Judge feedback archive (searchable across events)
- [ ] Structured post-round evaluation form (gated to feedback window, never blocks viewing own results)
- [ ] Claimed cross-tournament profile page (career stats, opt-in rating display)
- [ ] Parent/Guardian viewer surface (mirrors competitor's own view for one minor)

**Definition of done:** a claimed test account viewing their profile sees correctly-aggregated stats across 2 seeded tournaments, and a guardian-linked view is scoped to exactly one minor's data.

---

## Section 13 — Accessibility, notifications UI, paper fallback, polish

*Implements: docs/06 §6*

- [ ] Keyboard-navigation + screen-reader pass on every interactive surface from Sections 9–12
- [ ] Color-independent status indicators audit (no-show alerts, embargo flags, break line)
- [ ] In-app notification center (mirrors the email events from Section 8)
- [ ] Printable paper ballot template (mirrors the digital rubric) + staff-transcription entry path, distinguishable in the audit log

**Definition of done:** an automated a11y check (e.g. `axe` via Playwright) reports no critical violations on the four core surfaces; a paper-transcribed ballot is visibly distinguishable from a judge-submitted one in the audit log.

---

## Section 14 — Testing, hardening, launch prep

*Implements: all docs — final reconciliation pass*

- [ ] Playwright e2e: full tournament golden path (check-in → awards) including one no-show/hot-swap and one late scratch
- [ ] Rules-engine edge-case/load test (large N room-sizing, worst-case clash scenarios)
- [ ] Security pass: confirm token entropy/hashing, rate limits actually enforced in a staging deploy, Super Admin escalation cannot be bypassed
- [ ] Deployment checklist: all env vars set in Vercel, Resend domain verified, cloud-hosted Postgres + Redis provisioned (local WSL instances won't be reachable from Vercel — see the Database/Rate limiting rows in the tech stack table), Sentry receiving events
- [ ] Diff `docs/` against final implementation; update any doc that drifted during build

**Definition of done:** the Playwright golden-path suite passes against a Vercel preview deployment, and `docs/` accurately describes the shipped system.

---

## Progress Log

*Update this every time a session stops. Newest entry on top.*

- **[2026-07-23]** — Section 1 (Project bootstrap) essentially complete: Next.js 16 app scaffolded and merged into the existing repo, TS strict, Prettier/ESLint, shadcn/ui initialized and themed from `branding.config.ts`, Vitest + Playwright both installed with a passing placeholder test each, Sentry wired manually (wizard needs a TTY this environment doesn't have). Two items need the user directly and are left unchecked: (1) `vercel login` + `vercel link` — interactive browser auth; (2) a real Sentry DSN — needs a Sentry project created. Everything else in Section 1 is checked off. **Not yet committed** — do that next (git add the new app files + PLAN.md/docs changes, commit "Project bootstrap"), then move on to Section 2 (Database & Prisma schema); local Postgres role/db already exist (see Section 2's first checklist item) so that part is a head start.
- **[unstarted]** — Plan created and approved. No sections started yet. Next action: begin Section 1 (project bootstrap).

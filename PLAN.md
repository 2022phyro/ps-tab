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
| Zero-auth tokens | Custom — DB-backed opaque tokens, hashed at rest, scope + revoked columns. **Permanent by default (no expiry)** — revocation is the only thing that ends one; see docs/04 §1. |
| Authorization | Grouped RBAC — `Group` (scoped to a tournament, a circuit, or platform-global) holds `Permission`s from a system-seeded catalog; `User`s join via `GroupMembership`. Organizer-configurable beyond the seeded defaults (Super Admin, Tab Staff, Institution Coordinator, Circuit Administrator). See docs/03 and `prisma/schema.prisma`. |
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

- [x] Local Postgres role/db created (see "Local Postgres setup" above); `DATABASE_URL` set in `.env`
- [x] `pnpm add prisma @prisma/client`, `pnpm prisma init --datasource-provider postgresql`
- [x] Model: **Auth.js tables** (`User`, `Account`, `Session`, `VerificationToken`) — standard adapter shape. `isMinor`/`guardianEmail` live on `Speaker`, not `User`. **`isSuperAdmin` was removed** in a follow-up change once role modeling was redone as Grouped RBAC — see below.
- [x] Model: **Tournament** (`TournamentState`: Draft/Active/Concluded/Archived per docs/05 §1), `ownerId → User` for the one true owner (kept as a dedicated FK, not a group — see RBAC note below)
- [x] Model: **Division** (docs/01 §9) — belongs to Tournament, own break config (`BreakType`, `breakCount`/`breakPercentage`, `dropWorstCount`, `includeTiesAtBreak`), plus its own `roomSizeMin`/`roomSizeMax`
- [x] Model: **Round** (belongs to Division), independent `DrawsState`/`ResultsState`/`StandingsState` enums (docs/05 §2), `lockedAt` (docs/05 §4), plus `kind`/`stageName`/`advancesFromRoundId` self-relation for multi-stage elimination (docs/01 §11)
- [x] Model: **Institution** — no pre-seeded list, scoped per-tournament, grows organically (docs/01 §2). Trigram search done as a **schema-native** GIN index (`@@index([name(ops: raw("gin_trgm_ops"))], type: Gin)`) rather than only a hand-written migration — this way `prisma migrate dev` doesn't see phantom drift on every future run (see "Prisma 7 gotchas" below for why that matters)
- [ ] Server Action: institution search (`searchInstitutions(query)`) backing the registration combobox — **deferred to whichever section first builds the registration form** (Section 9 or 11); the index it needs is in place now
- [x] Models: **Speaker** and **Judge** as two distinct models rather than one polymorphic `RosterEntry` — their relations diverge enough (reserve-pool/fatigue/chair-eligibility for judges vs. position/waitlist/guardian for speakers) that a shared table would mean nullable-everything. Both carry their own `institutionId` (nullable), `email`, `name`; `Speaker` additionally carries `isMinor`/`guardianEmail`/`waitlisted`/`waitlistOrder`/`scratchedAt`; `Judge` carries `chairEligible`/`isReserve`/`maxRoundsPerDay`. Both carry a denormalized `userId?` (the currently-confirmed claim, cache only — `Claim` stays the source of truth)
- [x] Model: **Section** (room) + **SectionAssignment** (speaker↔section, `position`, `clashFlag`) + **Panel** (judge↔section, `isChair`, `status` enum incl. `DEPLOYED_RESERVE`/`REMOVED_FOR_CONFLICT`) (docs/01 §5, docs/02 §3–4)
- [x] Model: **Rubric**, **RubricCriterion** (`maxPoints`, `order`), **TimePenaltyPolicy** (1:1 with Rubric) (docs/01 §4)
- [x] Model: **Ballot** (unique per section+judge+speaker) + **BallotScore** (per criterion) + cached `judgeTotal`; `isPartial`/`calibrationFlag` for docs/02 §4–5
- [x] **Dropped `PositionHistory` as its own table** — a speaker's position history (docs/01 §6) is just `SectionAssignment.position` joined across a division's rounds; storing it separately would be duplicated state with a sync-drift risk for no benefit. The rules engine (Section 3) queries it directly.
- [x] Model: **RoundResult** (cached panel-averaged Round Score + Rank per speaker per round, docs/01 §4/§7) — added beyond the original plan; standings/tie-break queries need this cached rather than recomputed from raw ballots on every view
- [x] Model: **AccessToken** (zero-auth token; docs/04 §1) — `hashedValue` unique, nullable `speakerId`/`judgeId` (exactly one set, enforced at the application level, not the DB), `scope`, `revokedAt`. **`expiresAt` is nullable and null by default — tokens are permanent, revocation is the only thing that ends one** (product decision changed mid-session; docs/04 §1 updated to match)
- [x] Model: **Claim** / **ClaimDispute** (docs/04 §2, docs/08 §4) — `Claim` has nullable `speakerId`/`judgeId` (same one-of-two pattern as `AccessToken`)
- [x] Model: **GuardianLink** (docs/08 §5) — added beyond the original plan; explicit confirmable speaker↔guardian-account link, not automatic
- [x] Model: **Circuit** (with season-level break config), **CircuitMembership**, **CircuitPointsRule** (`conversionTable` kept as `Json` — deliberately flexible/organizer-authored rather than decomposed into rigid rows) (docs/08 §1)
- [x] Model: **CrossTournamentRating** (docs/08 §2) — added beyond the original plan; one row per `User`, `optedIn` flag, kept structurally separate from `CircuitPointsRule`
- [x] Model: **AuditLogEntry** — append-only (no update/delete path exposed anywhere), `actionType` is a free-form indexed `String` rather than an enum since this list will keep growing across every future section (docs/05 §5)
- [x] Model: **Embargo** (per-speaker-per-round hold, docs/05 §3)
- [x] **Grouped RBAC** (docs/03) — a follow-up change replaced the original per-role tables (`TournamentCollaborator`, `InstitutionCoordinator`, `CircuitAdmin`, `User.isSuperAdmin`) with a unified **`Group`** + **`Permission`** + **`GroupPermission`** + **`GroupMembership`** system: a `Group` is scoped to a tournament, a circuit, or neither (platform-global — Super Admin), holds a many-to-many set of `Permission`s from a system-seeded catalog, and `GroupMembership` links a `User` in (with an optional `institutionId` narrowing for Institution Coordinator specifically). Organizers can create custom groups beyond the seeded defaults and assign whichever permissions they want — this was the actual ask, not just a refactor for its own sake. `Tournament.ownerId` stays a dedicated field (not a group) since ownership is a hard one-per-tournament invariant with two extra powers (`tournament.delete`, `tournament.manage_staff`) that the docs deliberately keep separate from the day-of-operations permission set. Known caveat, documented directly in the schema: Postgres treats `NULL` as distinct in unique constraints, so `GroupMembership`'s `@@unique([groupId, userId, institutionId])` won't catch two plain (no-institution) memberships for the same user/group — de-duplicate in application code when creating one.
- [x] First migration: `pnpm prisma migrate dev --name init --create-only`, then hand-edited the generated SQL to add `CREATE EXTENSION IF NOT EXISTS pg_trgm;` before applying (see "Prisma 7 gotchas")
- [x] Second migration (`grouped_rbac_and_permanent_tokens`): generated non-interactively via `prisma migrate diff` + `migrate deploy` rather than `migrate dev` — see "Prisma 7 gotchas" for why that's now the standard approach here
- [x] `src/lib/prisma.ts` — singleton client using the required `@prisma/adapter-pg` driver adapter (see gotchas)
- [x] Write `prisma/seed.ts` — one sample tournament, **1 division** (not 2 — kept the seed minimal for this pass; a second division is cheap to add whenever Section 3's division-eligibility logic needs a second one to test against), 20 speakers across 3 institutions + independents, 1 judge, 1 completed round/section with 6 ballots + cached `RoundResult` rows, plus a full RBAC demo: the `Permission` catalog, `Super Admin`/`Tab Staff`/`Institution Coordinator`/`Circuit Administrator` default `Group`s with real permission assignments, and one `GroupMembership` each (including the institution-narrowed Coordinator case)
- [x] `pnpm prisma db seed` runs clean; spot-checked via throwaway query scripts (Prisma Studio itself needs a browser this session doesn't have — checked the relational shape directly instead, same effective verification), including confirming a freshly-created `AccessToken` defaults to `expiresAt: null`
- [x] **Judge domain-knowledge addendum** (schema): added `Rubric.baseScore` (docs/01 §4 — every speaker starts from this before criteria points are added), `Division.ballotMode`/`drawMethod`/`allowTiesInPrelims` + `Round.ballotModeOverride`/`drawMethodOverride` (docs/01 §4/§7/§11 — same point-in-time-override pattern as break config), and a new `JudgeFeedback` model (docs/02 §7 — speaker→judge and judge→judge ratings feeding judge breaks; exactly-one-of `raterSpeakerId`/`raterJudgeId`, same shape as `AccessToken`/`Claim`). Migration `20260724051742_judge_feedback_and_settings`, applied via the standard diff+deploy pattern; seed data extended with 3 sample `JudgeFeedback` rows.

**Definition of done:** `pnpm prisma migrate dev` and the seed script run clean against the local Postgres database (confirmed); the seeded tournament's relations were verified coherent (institutions → speakers → division → round → section → assignments/panel/ballots → cached RoundResult, correctly ordered by rank).

### Prisma 7 gotchas hit this session (read before touching the schema again)

Prisma 7 turned out to be a bigger jump than the plan assumed (written assuming Prisma 6-era conventions) — this project's `prisma init` scaffolded actual Prisma 7 defaults, so these apply going forward:

- **Driver adapters are mandatory for SQL providers now** — there's no more "just give Prisma a connection string and it works." Every `PrismaClient` instantiation needs `@prisma/adapter-pg` (`pg` under the hood) wired explicitly. See `src/lib/prisma.ts` and `prisma/seed.ts` for the pattern; any future script/route that touches the DB directly needs the same adapter wiring, not a bare `new PrismaClient()`.
- **The generator is `prisma-client`, not `prisma-client-js`**, and `output` is mandatory — ours generates to `src/generated/prisma` (gitignored automatically by `prisma init`). Import from `@/generated/prisma/client`, not `@prisma/client`, everywhere in app code.
- **Connection config lives in `prisma.config.ts`, not `schema.prisma`** — the `datasource` block in the schema only declares the `provider`; the actual `url` (and seed command) are in `prisma.config.ts`, which does `import "dotenv/config"` to read `.env` manually (env loading is no longer automatic in v7).
- **Hand-written raw SQL in a migration that isn't representable in `schema.prisma` causes phantom drift** on every subsequent `migrate dev` (it'll applied fine once, then prompt to "name a new migration" forever after, trying to reconcile the untracked SQL). Fixed by using Prisma's native extended-index syntax (`@@index([name(ops: raw("gin_trgm_ops"))], type: Gin)`) instead of leaving the trigram index as pure hand-written SQL — do this for any future Postgres-extension-backed index rather than only patching the migration file.
- **Windows note**: `prisma migrate dev` can sit at 0% CPU indefinitely on this machine right after "migration(s) have been applied" — it's not hung, it's waiting at an interactive "Enter a name for the new migration" prompt that a non-interactive shell can't answer (see the phantom-drift point above; fixing the drift is what makes the prompt stop appearing). If a `migrate dev` run seems stuck, check for that prompt before assuming it crashed.
- **Standard non-interactive migration workflow for this project, going forward**: `migrate dev` also refuses outright (rather than hanging) whenever it detects an actual data-loss-risking change (e.g. dropping a column with existing rows), printing "Prisma Migrate has detected that the environment is non-interactive" and pointing at `migrate deploy`. Since `migrate deploy` only *applies* migrations already on disk — it can't generate a new one — the working pattern is: `prisma migrate diff --from-config-datasource --to-schema ./prisma/schema.prisma --script` to render the SQL, write it into a manually-created `prisma/migrations/<timestamp>_<name>/migration.sql`, then `prisma migrate deploy` to apply. No prompts anywhere in that path.
- **Prisma's CLI recognizes when it's being driven by an AI agent and hard-blocks destructive commands** (`migrate reset`, and presumably similar ones) with an explicit message that the agent must stop, explain the action/reason/irreversibility to the user, and get real confirmation before retrying with a `PRISMA_USER_CONSENT_FOR_DANGEROUS_AI_ACTION` env var set to the user's actual consent text. This is a good guardrail, not a bug to route around — treat a block like this as a hard stop requiring the user's explicit sign-off in the moment, every time, not something to pre-authorize for future sessions.

---

## Section 3 — Core rules engine (pure logic)

*Implements: docs/01 in full*

Build under `src/lib/rules-engine/`, framework-agnostic (plain TS functions/classes, no Next.js or Prisma imports inside the algorithms themselves — they take/return plain data; a thin adapter layer wires them to Prisma later in Section 4+).

- [x] `roomSizing.ts` — §3 algorithm ($R_{\min}$/$R_{\max}$ → room count/sizes) plus `capRoomPlanByJudges` for the judge-shortfall edge case; unit test against the $N=27$ worked example (`[7,7,7,6]`, matched exactly), plus a brute-force check across N=4..60 that no room ever differs by more than one seat
- [x] `scoringPipeline.ts` — §4 (Judge Total → Round Score → Rank); `computeRanks` supports both **fractional** (average-rank ties, the default) and **whole** (distinct integer ranks via a caller-supplied tie-break comparator) methods, since docs/01 §4 leaves this an organizer-level setting; unit tests for single/multi-judge averaging and both tie methods
- [x] `sectionAllocation.ts` — §5 greedy + local-repair clash-avoidance heuristic; also carries the `roomTieBreak` ("fill-first"/"least-filled") option that `drawMethods.ts` needs for high-high vs. high-low placement (added ahead of schedule to avoid a later refactor). Unit test reproduces docs/01 §5's own unresolvable-clash example (5 speakers from one institution into 4-person rooms, 4 rooms total) — confirms it terminates with exactly 1 unit of clash penalty flagged rather than throwing, plus a zero-clash-achievable case and a full-field placement integrity check
- [x] `positionBias.ts` — §6 bias-score + slot assignment; convergence test simulates 6 rounds for 4 speakers and asserts (not just eyeballs) that every speaker ends up with an identical count of early-slot assignments — the simulation was hand-traced first to confirm the expected numbers, then the test encoded that trace
- [x] `tabulation.ts` — §7 tie-break hierarchy; unit tests reproduce the docs/01 §7 worked example at **both** tie levels (Total Ranks tie resolved by Total Points, then a second case where Total Points also ties and Adjusted Ranks resolves it)
- [x] `breaksAndFinals.ts` — §8 threshold rules (FIXED_COUNT/PERCENTAGE/RANK_FLOOR, `includeTies`) + §14's too-small-a-field clamp-and-flag; §11 multi-stage elimination chaining is proven by a test chaining `applyBreak` three times in sequence (prelims → quarters → semis → finals, 32 speakers down to 2) with **no dedicated chaining function**, per the doc's explicit "no new algorithm is needed per stage." **Extended post-completion** with two things the original plan didn't anticipate, both now documented in docs/01 §8 too: (1) **partial breaks** — `splitForPartialBreak` (top-N-per-room auto-advance, the rest into a bubble pool) + `resolvePartialBreak` (merges the bubble round's survivors with the auto-advancers to hit the next stage's target roster size) — proven end-to-end with the exact scenario described: 4 rooms of 6, top 2 per room auto-advance, 3rd–6th fight in a bubble round for the remaining slots into a 12-person semifinal; (2) **point-in-time break-config overrides** — `resolveBreakConfig`/`resolvePartialBreakConfig` make "tab staff overrides the configured default for just this one stage" an explicit, tested function rather than an implicit side effect of "well, you can pass whatever config you want." Both `applyBreak` and the partial-break functions were already stateless/config-as-argument, so neither change touched their signatures — this was additive, not a refactor.
- [x] `divisions.ts` — kept intentionally minimal: division *assignment* is a roster attribute per docs/01 §9, not something this engine computes, so this is just `partitionByDivision` (the boundary-enforcing utility every other module relies on) plus `computeCrossDivisionAward` for the one genuine cross-division concern
- [x] `schedulingCollisions.ts` — §10 speaker/judge double-booking detection; one generic `findDoubleBookings` serves both speakers and judges (a judge is just "a person assigned to an event at a time slot," same as a speaker), plus `computeAvailableJudgesForSlot` for the shared-pool scoping docs/01 §10 calls out
- [x] `drawMethods.ts` — §11 power-matching; `seedSpeakers` reorders by standing (institution-size as the tie-break), and `roomTieBreakFor` maps high-high/high-low onto `sectionAllocation`'s `roomTieBreak` option. This is a documented **interpretation**, not a literal transcription — docs/01 §11 only says power-matching "changes the seeding order," but high-high (pack top standings into one room) vs. high-low (spread them) also needs a room-selection preference, not just an input order, so that preference is exposed as the `fill-first`/`least-filled` option added to `sectionAllocation.ts`. Verified with a clash-free 8-speaker scenario: high-high packs standings 1-4 into room 0 exactly; high-low splits 1 and 2 into different rooms.
- [x] `sweepstakes.ts` — §12 institutional aggregate scoring (`top-k-sum` and `placement-scale` rules); confirmed independents are excluded and the computation never mutates its input (read-only derived view, per the doc)
- [x] `waitlist.ts` — §13 cap + promotion-in-order logic, plus `admitOverride` for the "cap is a soft ceiling" behavior docs/01 §13 explicitly calls for
- [x] `edgeCases.spec.ts` — covers 4 of docs/01 §14's 6 edge cases directly (byes, uneven rooms, single-judge panels, too-small-a-division-to-break); the other two (late-scratch ripple effect, waitlist promotion after check-in closes) depend on round/check-in *state* that doesn't exist at this pure-logic layer — noted in the file as Section 6/7 concerns, not skipped silently
- [x] `pnpm test` — full rules-engine suite green (63 tests across 13 files after the partial-break/override addendum), no DB/network involved; full project build/lint also re-verified clean afterward
- [x] **Judge domain-knowledge addendum**: extended `scoringPipeline.ts` with base-score arithmetic (`JudgeScore.baseScore`), `computeRoundScoreForMode` (Democracy — independent ballots averaged — vs. Strict — one panel-consensus ballot, conventionally the chair's), and `resolveRankMethod` (tie-permissiveness: optional in prelims, never in outrounds, docs/01 §7); extended `drawMethods.ts` with `resolveDrawMethod`/`toSeedMethod` bridging the new `DrawMethod` schema enum onto the existing `SeedMethod` seeding logic; added `judgeFeedback.ts` (cumulative feedback averages, tie-break by sample size, `applyJudgeBreak` mirroring `applyBreak`'s tie-extension/clamp-and-flag shape) and `judgeAllocation.ts` (clash-filter → chair-eligibility-weight-first-slot → randomize — the initial judge-to-panel assignment docs/02 never actually described before this addendum, only its post-assignment contingencies). 28 new tests (154 total, up from 126 after Section 4), all green; one real TS build error caught by `pnpm build` (not by `vitest` or `eslint`) — `noUncheckedIndexedAccess` rejected the destructuring-swap form of the Fisher-Yates shuffle in `judgeAllocation.ts`, fixed with an explicit temp variable.

**Definition of done:** `pnpm vitest run src/lib/rules-engine` passes in full, in isolation, with every worked example from docs/01 encoded as an assertion. **Confirmed** — every module's tests passed on first run except one (a test-authoring mistake in `breaksAndFinals.test.ts`'s tie fixture, not an implementation bug — fixed by equalizing all three tie-break tiers in the test data, not by changing the algorithm).

---

## Section 4 — Identity & access backend

*Implements: docs/03, docs/04, docs/08 §4–5*

- [x] Auth.js config: `src/auth.ts` (NextAuth v5 beta — `next-auth@5.0.0-beta.32`), `@auth/prisma-adapter`, Resend email provider (`next-auth/providers/resend`), `session: { strategy: "database" }` (matches our `Session` table). Route handler at `src/app/api/auth/[...nextauth]/route.ts`. No custom sign-in/verify-request pages yet — those come with Section 9's UI; Auth.js's defaults are fine until then.
- [x] Permission system (`src/lib/auth/permissions.ts` + `permissionsService.ts`) — **one general `can()` function, not one hand-written function per capability** as originally planned. Given Grouped RBAC (Section 2 revision) replaced fixed named roles with data-driven Group/Permission rows, "one function per capability" would mean hardcoding the same 16 permission keys twice; instead `can(grants, permissionKey, options)` is the single decision point, fed by `computeEffectiveGrants` (pure — tournament/circuit/global scoping + institution narrowing) and `getUserGrants`/`userCan` (Prisma-backed wrapper, plus the tournament-owner bypass for `tournament.delete`/`tournament.manage_staff`). Pure logic unit-tested with no DB; `userCan` integration-tested against the real seeded Groups.
- [x] ~~Middleware / route-group guards for each of the 5 core roles + 3 extended roles~~ — **deferred, deliberately**. There are no real protected routes/pages yet (that's what Section 9 builds), so writing a `proxy.ts` (Next 16's renamed `middleware.ts`) now would mean guessing route patterns against pages that don't exist. `userCan()` is the guard primitive Section 9's Server Actions/Route Handlers will call directly; a route-matching `proxy.ts` gets written once there are real routes to match.
- [x] Zero-auth token service (`src/lib/tokens/`): `crypto.ts` (pure — `generateRawToken`/`hashToken`, sha256, never store raw), `service.ts` (`issueToken`/`validateToken`/`revokeToken`/`reissueToken`, Prisma-backed). **No TTL enforcement** — per the Section 2 revision, tokens are permanent by default (`expiresAt` stays null); `validateToken` only checks expiry *if* one was explicitly set, which nothing in the app does yet.
- [x] QR code generation (`src/lib/tokens/qrcode.ts`) — `generateTokenQrDataUri(url)` wrapping the `qrcode` package, returns a `data:image/png;base64,...` URI. Kept as a plain function rather than a Server Action for now since there's no page yet to call it from (Section 9).
- [x] Roster-to-account claim flow (`src/lib/claims/service.ts`) — `findEmailMatchSuggestions` (suggestion only, excludes already-claimed entries) + `confirmEmailMatchClaim` / `claimByCode` (both funnel through a shared, transaction-wrapped `attemptClaim` so two near-simultaneous claims on the same entry can't both succeed). Added `generateClaimCode` — this needed a schema addition beyond the original plan: **`claimCode String? @unique` on `Speaker`/`Judge`** (single-use, cleared on any successful claim), since nothing in the Section 2 schema actually stored the "short code" docs/04 §2 describes.
- [x] Account recovery — standard Auth.js email-based recovery *is* the whole flow here: there's no password to reset with a magic-link-only provider, so "recovery" is just requesting another sign-in link to the verified email — no separate code needed. The support-mediated fallback (verified email itself is inaccessible) stays a human support-process note, not code, per the original plan.
- [x] Account merge (`src/lib/claims/merge.ts`) — `mergeAccounts`/`undoMergeAccounts`, transaction-wrapped, reassigning Claims/ClaimDisputes/GroupMemberships/GuardianLinks/owned Tournaments & Circuits/AuditLogEntries from secondary → primary. **"Reversible for a grace period" needed a schema addition**: `User.mergedIntoUserId`/`mergedAt`/`mergeSnapshot` (a JSON record of exactly which row IDs moved), so undo reverts precisely those records rather than guessing — anything the primary account does on its own after the merge is untouched by an undo. `CrossTournamentRating` is 1:1 per user; if both accounts already have one, the merge flags a conflict and leaves both alone rather than silently dropping one.
- [x] Claim dispute flagging + resolution (`resolveClaimDispute` in `service.ts`) — `attemptClaim` creates a `ClaimDispute` (never silently overwrites or grants by request order) when a roster entry is already claimed by someone else; `resolveClaimDispute` is the tab-staff-only resolution backend, ruling for either the original claimant or the disputer. UI hook is Section 9, as planned.
- [x] Guardian-consent gate (`src/lib/claims/guardianConsent.ts`) — `hasConfirmedGuardianConsent`/`assertGuardianConsent` (true automatically for non-minors), `requestGuardianLink`/`confirmGuardianLink` (explicit two-step, never automatic, refuses non-minor targets).

**New this section, not in the original plan:** while building the merge/claims flow, noticed `AuditLogEntry.actorUserId` has no `onDelete` cascade (Prisma default is `Restrict`) — meaning a real account-deletion flow (docs/08 §5) can't hard-delete a `User` who has ever performed an audited action without first reassigning or clearing their audit entries. Section 7 (cross-tournament ecosystem backend, which owns the data-deletion request handling) needs to account for this — noted here so it isn't rediscovered the hard way.

**Definition of done:** a seeded roster entry can be claimed by a test account end-to-end (magic link → claim confirmation) — **confirmed via `claims/service.test.ts`** (DB integration tests, not a literal magic-link email in this pass, but same underlying claim-confirmation code path). A token can be issued/validated/revoked via unit tests — **confirmed** (`tokens/service.test.ts`, 14 tests). Every role's permission check has a corresponding allowed + denied test — **confirmed** (`auth/permissionsService.test.ts`, all four seeded Groups from Section 2's RBAC addendum, both directions each).

---

## Section 5 — Judging contingencies backend

*Implements: docs/02*

**Pure-logic groundwork already done** (Section 3 addendum): `judgeAllocation.ts` (initial clash/chair-weighted/randomized judge-to-panel assignment, docs/02 §1) and `judgeFeedback.ts` (cumulative feedback averages, judge tie-break, judge breaks, docs/02 §7) were written and unit-tested there. This section built the DB-backed wrappers around them plus two more pure modules this section needed: `panelDegradation.ts` (`resolvePanelSize` — collapse-vs-block decision) and `calibration.ts` (Spearman-correlation-based ranking-divergence detection), both under `src/lib/rules-engine/` and unit-tested with hand-verified math before being wrapped.

- [x] Reserve-pool state on Judge: **not a stored state** — `getJudgeReserveState`/`getIdleCheckedInReserves` (`src/lib/judging/reservePool.ts`) derive InReservePool/CheckedIn/Deployed from `Judge.isReserve` + `JudgeCheckIn` + `Panel` rows for the round, rather than a fourth thing to keep in sync (same "derive, don't duplicate" call as Section 2's dropped `PositionHistory`)
- [x] No-show sweep + unresponsive sweep (`src/lib/judging/noShowSweep.ts`) — plain, directly-callable functions rather than actual Inngest functions, since Inngest itself isn't installed until Section 8 (same deferral as Section 4's `proxy.ts`); `sweepUnresponsive` needed a real `Round.scheduledEndAt` field (new — never guesses a duration) to measure its grace period from. Both write a **system-actor audit entry** (`actorUserId: null`) when they flag anyone.
- [x] Hot-swap (`src/lib/judging/hotSwap.ts`): `getHotSwapCandidates` (checked-in idle reserves only, each annotated with a re-run of `judgeAllocation.ts`'s own `hasClash` — exported for reuse, not reimplemented) + `hotSwapJudge` (throws on an unacknowledged clash, proceeds and flags one acknowledged via `acknowledgeClash: true`, writes the audit entry, preserves chair status onto the incoming judge)
- [x] Degraded-panel logic (`src/lib/judging/degradedPanel.ts`): `checkPanelStatus` derives collapsed/blocked at read time from the section's actual non-removed `Panel` count against new `Division.panelSize`/`minimumPanelSize` settings; `markJudgeDepartedMidRound` marks the panel `LEFT_MID_ROUND` (new `PanelStatus` value) and writes explicit partial placeholder Ballots for the unreached speakers only
- [x] Judge fatigue caps (`src/lib/judging/fatigue.ts`): `isJudgeAtFatigueCap` (same-day Panel count vs. `Judge.maxRoundsPerDay`) feeding `getAvailableJudgesForRound`, which also excludes recused judges
- [x] Self-reported recusal (`src/lib/judging/recusal.ts`): `recuseJudge` — idempotent, models recusal as a new `JudgeCheckIn` status (`RECUSED`) rather than a separate flag
- [x] Live calibration flag (`src/lib/judging/calibrationCheck.ts`): `runCalibrationCheck` re-derives each judge's in-room speaker ranking from cached `Ballot.judgeTotal`, excludes any judge with an incomplete (partial) ballot set from the comparison, and sets `Ballot.calibrationFlag` on outliers only
- [x] 27 new tests across 6 files, all DB-integration style against real seeded-shape fixtures (`src/lib/judging/testFixtures.ts`, shared across this section and Section 6's tests)

**Definition of done:** confirmed — `noShowSweep.test.ts` flags a checked-in-false judge via the sweep function; `hotSwap.test.ts` confirms a swap re-runs the clash check and logs an audit entry.

---

## Section 6 — Publishing & state machine backend

*Implements: docs/05*

- [x] Tournament state transitions (`src/lib/publishing/tournamentState.ts`): `canTransitionTournamentState` (pure, a plain adjacency map of the docs/05 §1 diagram) + `transitionTournamentState` (DB wrapper, audit-logged) — Draft→Active→Concluded→Archived plus the Draft→Archived cancel shortcut; any other transition throws
- [x] Round-level independent gates (`src/lib/publishing/gates.ts`): `releaseDraws`/`releaseResults`/`releaseStandings` — one-directional (matches docs/05 §2's diagram, no un-release path; a targeted `Embargo` is how one entity's visibility gets withdrawn instead). `releaseStandings` refuses to release before that same round's own Results have (docs/05 §2's "computation respects release state," enforced at the write path, not just left as a read-time convention)
- [x] Per-entity embargo + release-state-aware reads (`src/lib/publishing/embargo.ts`): `placeEmbargo`/`liftEmbargo`, plus `getVisibleRoundResults` (empty until Results release, filters out actively-embargoed speakers) and `getVisibleStandings` (cumulative total computed only from rounds whose *own* Results have released, up to the latest round whose Standings gate has released, excluding any embargoed speaker's contribution entirely — the concrete implementation of docs/05 §2's new "computation respects release state" principle from this session's judge-feedback addendum)
- [x] Scheduled auto-publish (`src/lib/publishing/scheduledRelease.ts`): new `ScheduledRelease` model (round, gate, releaseAt, cancelledAt?, executedAt?) + `scheduleGateRelease`/`cancelScheduledRelease`/`executeDueScheduledReleases` — the firing logic is complete and tested now; Section 8's Inngest cron just has to call `executeDueScheduledReleases` on a tick once Inngest is installed. A schedule whose precondition no longer holds when it comes due (e.g. standings scheduled before results ever released) is left pending, not thrown
- [x] Lock trigger + immutability (`src/lib/publishing/locking.ts`): new `Division.lockTrigger` (`ON_RESULTS_RELEASE` default | `ON_ALL_BALLOTS_SUBMITTED`) — **Results release always locks unconditionally** (design simplification made mid-session: the trigger only controls whether locking can *also* happen earlier, via `checkAndLockIfAllBallotsSubmitted`, not whether release implies lock — this keeps "resultsState RELEASED + lockedAt null" meaning exactly one thing, see next bullet). `assertRoundNotLocked`/`isRoundLocked` are the guard primitives; `editBallotScore` is a minimal real mutation built to prove the lock end-to-end (Section 10 owns the full scorecard submission flow)
- [x] Super Admin unlock escalation (`unlockRoundForCorrection` in `locking.ts`) — requires a reason, audit-logged; because release always locks, a released round with `lockedAt: null` can only mean an active unlock-for-correction window, so `editBallotScore` re-locks automatically the moment the correction lands, closing that window without a separate "are we done yet" signal
- [x] Shared `AuditLogEntry` writer (`src/lib/audit/log.ts`, `writeAuditLog`) — used by every function in Sections 5 and 6 from the start, and retrofitted onto Section 4's `merge.ts` (already had inline creates, now calls the shared writer), `claims/service.ts` (`attemptClaim`'s both outcomes, `resolveClaimDispute`, `generateClaimCode` — previously wrote no audit entries at all), and `tokens/service.ts` (`revokeToken`/`reissueToken` gained an optional `performedByUserId`, logged when given). **Schema change enabling this**: `AuditLogEntry.actorUserId` is now nullable (system-originated actions — sweeps, scheduled-release firing — log with a null actor rather than being skipped or inventing one) — this also happens to close the previously-flagged gap where a `User` who'd ever performed an audited action couldn't be hard-deleted (Prisma's default `onDelete` for the now-optional relation is `SetNull`, not `Restrict`)
- [x] Retention job (`src/lib/publishing/retention.ts`): `anonymizeUnclaimedRosterPii(cutoffDate)` — anonymizes (never deletes) name/email/guardianEmail on unclaimed (`userId: null`) Speaker/Judge rows in Archived tournaments past the cutoff; competitive result rows are untouched since nothing cascades off a Speaker/Judge PII edit. Inngest wiring deferred to Section 8 same as the sweeps above.
- [x] 35 new tests across 6 files (`src/lib/publishing/`), all DB-integration style, reusing Section 5's shared test fixtures

**Definition of done:** confirmed — a round advances through all three gates independently via direct function calls (`gates.test.ts`); `locking.test.ts` confirms a locked round rejects `editBallotScore` and that the Super Admin escalation path (unlock → edit → auto re-lock) works end to end with a correctly recomputed `judgeTotal`; every mutation across both sections produces exactly one `AuditLogEntry` (verified per-function, not just asserted).

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

- **[2026-07-24]** — Sections 5 (Judging contingencies backend) and 6 (Publishing & state machine backend) complete, built together since Section 6's shared audit-log writer and locking primitives were needed by Section 5's new mutating actions from the start. Two new schema migrations: `20260724060000_judging_and_publishing_backend` (`Division.panelSize`/`minimumPanelSize`/`lockTrigger`, `Round.scheduledEndAt`, `PanelStatus.LEFT_MID_ROUND`, `JudgeCheckInStatus.RECUSED`, new `ScheduledRelease` model) and `20260724063000_nullable_audit_actor` (`AuditLogEntry.actorUserId` made nullable — a side effect worth noting: this also closes the Section-4-flagged gap where a `User` who'd ever performed an audited action blocked hard-deletion, since Prisma's default `onDelete` for the now-optional relation is `SetNull`, not `Restrict`). Two new pure rules-engine modules (`panelDegradation.ts`, `calibration.ts`, hand-verified Spearman-correlation math) plus seven new DB-backed service modules under `src/lib/judging/` and `src/lib/publishing/`, all detailed in the Section 5/6 checklists above. A real design simplification made mid-session: Results release now **always** locks a round unconditionally, regardless of the configured lock trigger — the trigger only gates whether locking can *also* happen earlier — because that's what makes "released + unlocked can only mean an active Super Admin correction window" hold as a clean invariant for `editBallotScore`'s auto-relock, instead of needing a second signal to track it. Retrofitted the shared audit writer onto `merge.ts`, `claims/service.ts` (which previously wrote no audit entries at all for claim confirm/dispute/code-generation), and `tokens/service.ts` (`revokeToken`/`reissueToken` gained an optional actor param) — deliberately did *not* retrofit `issueToken` itself, since zero-auth self-service issuance has no natural actor and forcing one would be an API change for its own sake, not a real gap. One test-infrastructure bug caught and fixed along the way: a shared test fixture helper (`src/lib/judging/testFixtures.ts`, reused by both sections' tests) deleted its Tournament before its scoped AuditLogEntry rows, and since that FK auto-nulls on delete (not cascades), the rows were silently orphaned instead of cleaned up — surfaced as a flaky `findFirstOrThrow` picking up a stale row from an earlier run; fixed by reordering cleanup, and by switching the fixture's uniqueness scheme from `Date.now()+counter` (collides across the multiple test files vitest runs concurrently, each in its own process with its own counter) to `randomUUID()`. 62 new tests (37 files, 228 total), all green; full suite/lint/build/format re-verified clean. Docs got light touch-ups (docs/02 §4/§5 now name the concrete Division settings and JudgeCheckIn status backing them; docs/05 §2/§4 now describe `ScheduledRelease` and the "release always locks" relationship) rather than large rewrites, since docs/02 and docs/05 already described these mechanics conceptually before this session. **Not yet committed** — do that next, then move to Section 7 (Cross-tournament ecosystem backend).
- **[2026-07-24]** — Cross-cutting addendum (schema + Section 3 rules-engine + docs), prompted by a real PS judge's 9-point domain-knowledge dump the user relayed, covering things the original plan hadn't modeled: (1) **base score** — rubrics can start speakers from a nonzero floor, criteria points are the remainder allocated on top (docs/01 §4, `Rubric.baseScore`); (2) **power vs. random pairing formalized as a schema-level, per-round-overridable toggle** (`Division.drawMethod`/`Round.drawMethodOverride`, `resolveDrawMethod`/`toSeedMethod` bridging onto the existing high-high/high-low seed logic, docs/01 §11); (3) **ballot modes** — Democracy (independent ballots averaged, the existing default) vs. Strict (one panel-consensus score, conventionally the chair's), `Division.ballotMode`/`Round.ballotModeOverride`, `computeRoundScoreForMode` (docs/01 §4); (4) **tie permissiveness as an organizer setting** for prelims only — outrounds always force sequential ranks, never configurable (`Division.allowTiesInPrelims`, `resolveRankMethod`, docs/01 §7); (5)+(6) **judge feedback & judge breaks** — new `JudgeFeedback` model (speaker→judge and judge→judge ratings) plus `judgeFeedback.ts` (cumulative average, sample-size tie-break, `applyJudgeBreak`), documented as new docs/02 §7; (7) **initial judge allocation formalized** — new `judgeAllocation.ts` (clash-filter → chair-eligibility-weighted first slot → randomize the rest) fills a real gap docs/02 had never covered (it only ever described post-assignment contingencies), documented as new docs/02 §1, with the rest of docs/02 renumbered §2–§6 accordingly; (8) **CAP/OrgComm terminology** mapped onto the existing Tab Staff tier + Grouped RBAC rather than new privilege levels (docs/03, new callout after the Tab Staff role definition); (9) **standings computation must respect release state, not just display** — a held round's numbers can feed internal-only uses (e.g. power-matching's next-round seeding) but must never leak into any competitor/public-facing cumulative figure before that round's own gate releases (docs/05 §2, new paragraph). One schema migration (`20260724051742_judge_feedback_and_settings`), 28 new rules-engine tests (154 total), one real TS build error caught only by `pnpm build` (`noUncheckedIndexedAccess` rejecting a destructuring swap in the new Fisher-Yates shuffle — fixed with an explicit temp variable), full suite/lint/build/format all re-verified green afterward. Seed data extended with 3 sample `JudgeFeedback` rows. **Not yet committed** — do that next. All 9 points from the judge's list are now reflected in docs, schema, and code, per the user's explicit "before we go on" instruction; next action is to resume Section 5 (Judging contingencies backend), which now has real pure-logic groundwork to wrap (see the note added at the top of Section 5 above) rather than starting from nothing.
- **[2026-07-24]** — Section 4 (Identity & access backend) complete. Auth.js v5 beta wired (Prisma adapter, Resend email provider, database sessions); Grouped RBAC permission system (`can`/`getUserGrants`/`userCan`) replacing the originally-planned "one function per capability" approach, tested both as pure logic and against the real seeded Groups from the Section 2 RBAC addendum; zero-auth token service (permanent by default, matching the Section 2 token revision) with QR delivery; the full claim flow (email-match suggestion, claim-code, dispute detection, tab-staff dispute resolution); account merge/undo (needed a new `User.mergedIntoUserId`/`mergedAt`/`mergeSnapshot` schema addition for precise, snapshot-based reversibility); guardian consent gate. Two schema migrations added this section (`claimCode` on Speaker/Judge; account-merge fields on User) via the by-now-standard `migrate diff` + `migrate deploy` non-interactive pattern — no surprises this time. Deliberately deferred: `proxy.ts` route guards (no real routes to protect yet — Section 9's job) and custom Auth.js pages (same reason). Found a real gap for later: `AuditLogEntry.actorUserId` has no cascade, so Section 7's account-deletion flow will need to handle that FK before it can hard-delete a `User`. 41 new tests (all DB-integration style except the pure `permissions.ts`/`crypto.ts` units), 126 total, everything green; full build/lint re-verified. **Not yet committed** — do that next, then move to Section 5 (Judging contingencies backend).

- **[2026-07-23]** — Section 3 addendum, on top of the already-committed rules engine: added **partial breaks** (top-N-per-room auto-advance + a bubble round for the rest, a real speech-tournament mechanic docs/01 hadn't covered — now documented in §8) and **point-in-time break-config overrides** (tab staff can override the configured default break size/partial-break shape for one specific stage, without touching the stored default — also now in docs/01 §8). Both live in `breaksAndFinals.ts` as pure additive functions (`splitForPartialBreak`, `resolvePartialBreak`, `resolveBreakConfig`, `resolvePartialBreakConfig`) — no existing signature changed. Also strengthened the existing multi-stage chaining test from 2 hops to 3 (prelims → quarters → semis → finals, 32→8→4→2) since that was raised directly. 10 new tests, 63 total, all green; full suite/lint/build re-verified. **Not yet committed** — do that next, then move to Section 4 (Identity & access backend).
- **[2026-07-23]** — Section 3 (Core rules engine) complete and committed (`4558b6b`). All 12 modules under `src/lib/rules-engine/` written and tested — 53 tests across 13 files, all green, zero DB/Next.js coupling (pure functions operating on plain data, exactly as planned). Every worked example in docs/01 is now encoded as an assertion, not just prose. Two implementation notes worth knowing for later sections: (1) `sectionAllocation.ts` got a `roomTieBreak` option ("fill-first"/"least-filled") added ahead of schedule, because implementing high-high vs. high-low power-matching in `drawMethods.ts` turned out to need a room-*selection* preference, not just a seeding-*order* change the way docs/01 §11 frames it at the prose level — this is a documented interpretation, flagged as such in both files' comments and in the Section 3 checklist above, not a silent deviation. (2) Two of docs/01 §14's six edge cases (late-scratch ripple effect, waitlist-after-check-in-closes) genuinely can't be unit-tested at this pure-logic layer since they depend on round/check-in state that doesn't exist until Section 4+ wires the DB in — noted explicitly in `edgeCases.spec.ts` rather than silently dropped.
- **[2026-07-23]** — Post-Section-2 design revision, on top of the already-committed schema: (1) replaced the ad-hoc role tables (`TournamentCollaborator`, `InstitutionCoordinator`, `CircuitAdmin`, `User.isSuperAdmin`) with **Grouped RBAC** (`Group`/`Permission`/`GroupPermission`/`GroupMembership`) so organizers can create custom groups and assign permissions themselves, not just use hardcoded roles; (2) made zero-auth `AccessToken.expiresAt` nullable and permanent-by-default (a token now only ever ends via organizer revocation) — updated docs/04, docs/07, and the glossary to match, since this reverses a stated design principle, not just an implementation detail. New migration applied via `prisma migrate diff` + `migrate deploy` (non-interactive-safe — see the new "Prisma 7 gotchas" bullets). Also hit Prisma's built-in AI-agent guard on `migrate reset` — it refuses outright until the user explicitly consents; got that consent, reset+reseeded, verified all four default groups and the null-expiry token behavior directly. Everything rebuilds/lints/tests clean. **Not yet committed** — do that next, then continue to Section 3 (core rules engine).
- **[2026-07-23]** — Section 2 (Database & Prisma schema) complete and committed. Full schema written (`prisma/schema.prisma`), migrated against the local Postgres DB, seeded, and spot-checked. **Prisma 7 landed bigger changes than the plan assumed** — read the new "Prisma 7 gotchas" callout under Section 2 before touching the schema again (driver adapters are now mandatory, generator/output/config-file conventions all changed, and hand-written migration SQL needs a schema-native equivalent or `migrate dev` will loop on phantom drift). A few entities came out shaped differently than originally planned (`Speaker`/`Judge` instead of one `RosterEntry`; `PositionHistory` dropped as derived-not-stored; `RoundResult`, `GuardianLink`, `CrossTournamentRating` added) — the Section 2 checklist above now describes what was actually built, not the original guess. One deferred item: the `searchInstitutions` Server Action itself waits for whichever section first builds a registration form (Section 9 or 11) — the trigram index it needs is already in place. Next action: Section 3 (core rules engine) — pure-logic algorithms in `src/lib/rules-engine/`, unit-testable against docs/01's worked examples with no DB involved.
- **[2026-07-23]** — Section 1 (Project bootstrap) essentially complete: Next.js 16 app scaffolded and merged into the existing repo, TS strict, Prettier/ESLint, shadcn/ui initialized and themed from `branding.config.ts`, Vitest + Playwright both installed with a passing placeholder test each, Sentry wired manually (wizard needs a TTY this environment doesn't have). Two items need the user directly and are left unchecked: (1) `vercel login` + `vercel link` — interactive browser auth; (2) a real Sentry DSN — needs a Sentry project created. Everything else in Section 1 is checked off. **Not yet committed** — do that next (git add the new app files + PLAN.md/docs changes, commit "Project bootstrap"), then move on to Section 2 (Database & Prisma schema); local Postgres role/db already exist (see Section 2's first checklist item) so that part is a head start.
- **[unstarted]** — Plan created and approved. No sections started yet. Next action: begin Section 1 (project bootstrap).

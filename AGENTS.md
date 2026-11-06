# PS Tab — Architecture & Development Guidelines

## 1. Execution Environment & Tooling
- **OS / Subsystem**: Run all project management, Python commands, and tests in **WSL**.
- **Package & Environment Manager**: Use **`ruv`** (WSL wrapper around `uv`).
  - Never call `uv` directly; always invoke through `ruv` inside WSL (e.g. `wsl bash -lic "ruv <command>"`).
  - Virtual environments are automatically managed in the Linux filesystem (`~/.virtualenvs/`) via `.ruv`.
  - Task runner: `taskipy` is installed. Run tasks with `ruv run task dev`, `ruv run task worker`, or `ruv run task test`.

## 2. Technology Stack
- **Backend Core**: Python 3.12+, FastAPI, SQLAlchemy 2 (async) / SQLModel, Alembic
- **Database**: PostgreSQL
- **Worker / Task Queue**: `arq` (async Redis job queue)
- **Cache & Key-Value Store**: Redis
- **Frontend / Monolith SSR**: Jinja2 templates, HTMX (for dynamic server-driven UI), Alpine.js (for client-side UI state), Tailwind CSS
- **Serialization**: MessagePack (`msgpack`) as the default serialization engine for API routes, Redis caching, and background job payloads
- **Identifiers**: Time-ordered ULIDs / TypeIDs (e.g. `tourn_...`, `div_...`, `spkr_...`, `bal_...`) for B-tree index efficiency and type safety
- **Responsive Design**: Mobile-first and desktop-optimized UI views for competitors, judges, and tab staff.

## 3. Core Tabulation Rules & Domain Model
- Refer to `docs/01-tournament-mechanics.md` through `docs/08-cross-tournament-ecosystem.md` as the single source of truth for tournament mechanics, judging contingencies, RBAC, zero-auth access, and state publishing gates.

## 4. UI/UX & Design System Rules
- **Typography**: Never use `font-mono`. Always use `font-sans` / `font-body` (Onest) for body text, numbers, codes, and badges, or `font-heading` (Bricolage Grotesque) for titles and display metrics.
- **Alerts & Feedback**: Always use the system Toast notification system (`window.showToast(message, type)` or URL `?msg=...` toast detection). Never render static banner alerts that push or shift page content down.
- **Creation Forms & Modals**: For adding or configuring new records (criteria, speakers, judges, schedule items, files), use responsive modals / dialogs (`x-data="{ modalOpen: false }"`) triggered by action buttons, avoiding static stacked forms that crowd or block content on mobile.
- **Responsive Design**: Ensure mobile-first layout with collapsible navigation rails and responsive grid cards.

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

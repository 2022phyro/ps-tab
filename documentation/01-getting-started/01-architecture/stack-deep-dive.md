---
title: Technology Stack Deep-Dive
badge: Architecture
---

# Technology Stack Deep-Dive

Kwuo is engineered as a high-efficiency **monolith server-side rendered (SSR)** application designed to maintain sub-second response times even when campus Wi-Fi networks are congested.

---

## 1. Backend Core

* **FastAPI**: Provides asynchronous endpoint dispatch, dependency injection, and automatic OpenAPI validation.
* **SQLAlchemy 2.0 (Async)**: Coupled with `asyncpg` for non-blocking database queries against PostgreSQL.
* **TypeID Identifiers**: Time-ordered, type-prefixed identifiers (`tourn_...`, `spkr_...`, `bal_...`) ensuring index locality and eliminating B-tree index fragmentation.

---

## 2. Dynamic Monolith SSR

Rather than maintaining a decoupled single-page application with heavy client-side hydration, Kwuo leverages:
* **Jinja2**: Server-side template rendering for immediate first-paint on mobile devices.
* **HTMX**: Powers seamless, partial-page swaps (`hx-post`, `hx-swap`) without full page reloads.
* **Alpine.js**: Manages lightweight reactive client-side state (modals, countdown timers, mobile navigation drawers).

---

## 3. Worker & Binary Serialization

```
HTTP Client ──(HTML / HTMX)──> FastAPI ──(asyncpg)──> PostgreSQL
                                  │
                             (MsgPack)
                                  ▼
                              Redis / ARQ Worker
```

* **ARQ**: Asynchronous task queue running on Redis for computationally intensive operations like dynamic room plan generation and large CSV roster imports.
* **MessagePack (`msgpack`)**: Binary serialization format used across internal caches, worker payloads, and data APIs for maximum throughput.

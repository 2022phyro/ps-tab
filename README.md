# Kwuo (kwuo) — Public Speaking Tabulation Platform

*Kwuo* ("Speak") is a high-resilience public speaking tournament tabulation engine built with:
- **Backend**: FastAPI, PostgreSQL, SQLAlchemy 2 (async), Alembic
- **Worker**: ARQ (async Redis task queue)
- **Frontend**: Jinja2 + HTMX + Alpine.js + Tailwind CSS
- **Cache**: Redis
- **Serialization**: MessagePack (`msgpack`)
- **IDs**: Time-ordered ULIDs

## Running the Application

Using `ruv` inside WSL:

```bash
# Start FastAPI development server with hot-reload
ruv run task dev

# Start ARQ background worker
ruv run task worker
```


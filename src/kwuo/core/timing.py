"""Request execution timing and database query counting middleware for Kwuo."""

import time
import logging
from typing import Tuple
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from sqlalchemy import event
from kwuo.core.database import engine

logger = logging.getLogger("kwuo.perf")

# Context variable holding mutable dict for current request's stats
_perf_stats: ContextVar[dict] = ContextVar("perf_stats")

# Attach SQLAlchemy event listeners once to engine.sync_engine
_listeners_attached = False

def attach_query_counter():
    global _listeners_attached
    if _listeners_attached:
        return
    
    sync_engine = getattr(engine, "sync_engine", engine)

    @event.listens_for(sync_engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("query_start_time", []).append(time.perf_counter())

    @event.listens_for(sync_engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        try:
            stats = _perf_stats.get()
        except LookupError:
            return
        start_times = conn.info.get("query_start_time", [])
        if start_times:
            dur = (time.perf_counter() - start_times.pop()) * 1000.0  # ms
            stats["db_duration"] += dur
        stats["query_count"] += 1

    _listeners_attached = True


attach_query_counter()


class PerformanceTimingMiddleware(BaseHTTPMiddleware):
    """Measures total request duration and records database query counts.
    
    Attaches a Server-Timing header (app, db, sql_count) and logs warnings
    if thresholds are exceeded.
    """

    QUERY_COUNT_WARN_THRESHOLD = 15
    REQUEST_DURATION_WARN_MS = 200.0

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        stats = {"query_count": 0, "db_duration": 0.0}
        _perf_stats.set(stats)
        start_time = time.perf_counter()

        response = await call_next(request)

        total_dur_ms = (time.perf_counter() - start_time) * 1000.0
        query_count = stats["query_count"]
        db_dur_ms = stats["db_duration"]

        # Attach Server-Timing header for browser DevTools
        timing_header = f"total;dur={total_dur_ms:.1f}, db;dur={db_dur_ms:.1f}, queries;desc=\"count\";dur={query_count}"
        response.headers["Server-Timing"] = timing_header
        response.headers["X-Query-Count"] = str(query_count)
        response.headers["X-Response-Time-Ms"] = f"{total_dur_ms:.1f}"

        # Warn in console if performance budget exceeded (skip static files)
        if not request.url.path.startswith("/static"):
            if query_count > self.QUERY_COUNT_WARN_THRESHOLD or total_dur_ms > self.REQUEST_DURATION_WARN_MS:
                logger.warning(
                    f"⚠️ [PERF BUDGET EXCEEDED] {request.method} {request.url.path} - "
                    f"Time: {total_dur_ms:.1f}ms (DB: {db_dur_ms:.1f}ms) | Queries: {query_count}"
                )

        return response

"""SQLAlchemy 2 async pagination utilities for Kwuo."""

from typing import TypeVar, Generic, Sequence, Optional, Dict, Any
from dataclasses import dataclass
from sqlalchemy import select, func
from sqlalchemy.sql import Select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


@dataclass
class Page(Generic[T]):
    items: Sequence[T]
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool

    @property
    def next_page(self) -> Optional[int]:
        return self.page + 1 if self.has_next else None

    @property
    def prev_page(self) -> Optional[int]:
        return self.page - 1 if self.has_prev else None

    def page_range(self, window: int = 2) -> list[int]:
        """Generate windowed page numbers around current page for clean UI pagination."""
        start = max(1, self.page - window)
        end = min(self.total_pages, self.page + window)
        return list(range(start, end + 1))


async def paginate(
    session: AsyncSession,
    stmt: Select,
    page: int = 1,
    page_size: int = 50,
) -> Page[Any]:
    """Execute query with SQL COUNT(*) and LIMIT/OFFSET for pagination."""
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 200:
        page_size = 50

    # 1. Total count query wrapping the original select statement's subquery
    count_subquery = stmt.order_by(None).subquery()
    count_stmt = select(func.count()).select_from(count_subquery)
    total_items = (await session.execute(count_stmt)).scalar() or 0

    # 2. Paginated rows query
    offset = (page - 1) * page_size
    paginated_stmt = stmt.offset(offset).limit(page_size)
    result = await session.execute(paginated_stmt)
    items = result.scalars().all()

    total_pages = max(1, (total_items + page_size - 1) // page_size) if total_items > 0 else 1

    return Page(
        items=items,
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )

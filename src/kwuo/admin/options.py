"""Django-inspired ModelAdmin base classes for Kwuo Admin."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Type
from sqlalchemy import select, func, or_, desc, asc, cast, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


@dataclass
class ActionItem:
    name: str
    description: str
    handler: Optional[Callable] = None


class ModelAdmin:
    """Base class defining administration options and behavior for a model."""

    model: Type[Any]
    category: str = "General"
    slug: str
    verbose_name: str
    verbose_name_plural: str
    list_display: Sequence[str] = ("id",)
    list_filter: Sequence[str] = ()
    search_fields: Sequence[str] = ()
    ordering: Sequence[str] = ("id",)
    list_per_page: int = 20
    readonly_fields: Sequence[str] = ("id", "created_at", "updated_at")
    fields: Optional[Sequence[str]] = None
    actions: List[str] = ["delete_selected"]

    def __init__(self, model: Type[Any]):
        self.model = model
        if not hasattr(self, "slug"):
            self.slug = model.__tablename__.replace("_", "-")
        if not hasattr(self, "verbose_name"):
            self.verbose_name = model.__name__
        if not hasattr(self, "verbose_name_plural"):
            self.verbose_name_plural = f"{self.verbose_name}s"

    def get_list_display(self) -> Sequence[str]:
        return self.list_display

    def get_search_fields(self) -> Sequence[str]:
        return self.search_fields

    def get_list_filter(self) -> Sequence[str]:
        return self.list_filter

    def get_ordering(self) -> Sequence[str]:
        return self.ordering

    def get_available_actions(self) -> List[ActionItem]:
        actions = []
        if "delete_selected" in self.actions:
            actions.append(ActionItem(name="delete_selected", description="Delete selected " + self.verbose_name_plural.lower()))
        return actions

    async def get_queryset(self, db: AsyncSession):
        """Base query for the model. Can be overridden for eager loading."""
        return select(self.model)

    async def get_object(self, db: AsyncSession, object_id: Any) -> Optional[Any]:
        """Fetch a single model instance by primary key with configured query relationships."""
        stmt = await self.get_queryset(db)
        stmt = stmt.where(self.model.id == object_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def count_total(self, db: AsyncSession) -> int:
        """Count total instances in database."""
        stmt = select(func.count()).select_from(self.model)
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def get_paginated_list(
        self,
        db: AsyncSession,
        search_query: Optional[str] = None,
        filters: Optional[Dict[str, str]] = None,
        ordering_param: Optional[str] = None,
        page: int = 1,
    ) -> Tuple[List[Any], int, int]:
        """Return (items, total_count, total_pages) matching criteria."""
        stmt = await self.get_queryset(db)

        # Apply search query
        if search_query and self.search_fields:
            search_filters = []
            for field_name in self.search_fields:
                if hasattr(self.model, field_name):
                    column = getattr(self.model, field_name)
                    search_filters.append(cast(column, String).ilike(f"%{search_query.strip()}%"))
            if search_filters:
                stmt = stmt.where(or_(*search_filters))

        # Apply list_filters
        if filters:
            for k, v in filters.items():
                if k in self.list_filter and hasattr(self.model, k):
                    column = getattr(self.model, k)
                    # Support boolean filters
                    if v.lower() in ("true", "1", "yes"):
                        stmt = stmt.where(column == True)
                    elif v.lower() in ("false", "0", "no"):
                        stmt = stmt.where(column == False)
                    elif v.lower() == "none" or v == "":
                        stmt = stmt.where(column.is_(None))
                    else:
                        stmt = stmt.where(column == v)

        # Count filtered records
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_count = (await db.execute(count_stmt)).scalar() or 0

        # Apply ordering
        order_col = ordering_param if ordering_param else (self.ordering[0] if self.ordering else "id")
        is_desc = order_col.startswith("-")
        clean_col = order_col.lstrip("-")
        if hasattr(self.model, clean_col):
            col_attr = getattr(self.model, clean_col)
            stmt = stmt.order_by(desc(col_attr) if is_desc else asc(col_attr))

        # Apply pagination
        per_page = self.list_per_page
        offset = (page - 1) * per_page
        stmt = stmt.offset(offset).limit(per_page)

        result = await db.execute(stmt)
        items = list(result.scalars().all())
        total_pages = max(1, (total_count + per_page - 1) // per_page)
        return items, total_count, total_pages

    def format_cell_value(self, item: Any, field_name: str) -> Any:
        """Format an attribute or method on the model instance for table display."""
        # Check custom method on ModelAdmin first
        if hasattr(self, field_name):
            attr = getattr(self, field_name)
            if callable(attr):
                return attr(item)
            return attr

        # Check attribute on model instance
        if hasattr(item, field_name):
            val = getattr(item, field_name)
            if callable(val):
                return val()
            if isinstance(val, bool):
                return val
            if isinstance(val, datetime):
                return val.strftime("%Y-%m-%d %H:%M")
            return val
        return ""

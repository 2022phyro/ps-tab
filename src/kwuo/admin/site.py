"""Django-esque AdminSite registry for Kwuo."""

from typing import Any, Dict, List, Optional, Type
from sqlalchemy.ext.asyncio import AsyncSession
from kwuo.admin.options import ModelAdmin


class AdminSite:
    """Central registry and controller for Kwuo admin models."""

    def __init__(self, name: str = "Kwuo Administration"):
        self.name = name
        self._registry: Dict[str, ModelAdmin] = {}

    def register(self, model: Type[Any], admin_class: Optional[Type[ModelAdmin]] = None, **kwargs) -> None:
        """Register a model with an optional custom ModelAdmin subclass."""
        if admin_class is None:
            admin_obj = ModelAdmin(model)
        else:
            admin_obj = admin_class(model)

        for k, v in kwargs.items():
            setattr(admin_obj, k, v)

        self._registry[admin_obj.slug] = admin_obj

    def get_model_admin(self, slug: str) -> Optional[ModelAdmin]:
        return self._registry.get(slug)

    def get_all_admins(self) -> List[ModelAdmin]:
        return list(self._registry.values())

    async def get_app_sections(self, db: AsyncSession) -> List[Dict[str, Any]]:
        """Return categorized apps and models with counts for the admin index."""
        categories: Dict[str, List[Dict[str, Any]]] = {}

        for slug, model_admin in self._registry.items():
            cat = model_admin.category
            count = await model_admin.count_total(db)
            model_info = {
                "name": model_admin.verbose_name,
                "name_plural": model_admin.verbose_name_plural,
                "slug": model_admin.slug,
                "admin_url": f"/admin/{model_admin.slug}",
                "add_url": f"/admin/{model_admin.slug}/add",
                "count": count,
            }
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(model_info)

        return [
            {"name": cat_name, "models": models}
            for cat_name, models in categories.items()
        ]


# Default singleton instance
admin_site = AdminSite()

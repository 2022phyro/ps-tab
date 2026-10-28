"""TypeID utilities and SQLAlchemy type integration for Kwuo."""

from typing import Any, Optional
from sqlalchemy.types import TypeDecorator, String
from typeid import TypeID


def generate_typeid(prefix: str) -> str:
    """Generate a type-prefixed, time-sortable TypeID string (e.g. tourn_01h455...)."""
    return str(TypeID(prefix=prefix))


class TypeIDType(TypeDecorator):
    """SQLAlchemy column type for storing TypeIDs as Strings (e.g. VARCHAR(36)).
    
    Provides validation and conversion to/from TypeID.
    """
    impl = String(36)
    cache_ok = True

    def __init__(self, prefix: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.prefix = prefix

    def process_bind_param(self, value: Optional[Any], dialect: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, TypeID):
            return str(value)
        # Ensure it's a string
        val_str = str(value)
        if not val_str.startswith(f"{self.prefix}_"):
            raise ValueError(f"Invalid TypeID prefix: expected '{self.prefix}_', got '{val_str}'")
        return val_str

    def process_result_value(self, value: Optional[str], dialect: Any) -> Optional[str]:
        return value

"""TypeID utilities and SQLAlchemy type integration for Kwuo."""

from typing import Any, Optional, Union, Sequence
from sqlalchemy.types import TypeDecorator, String
from typeid import TypeID


def generate_typeid(prefix: str) -> str:
    """Generate a type-prefixed, time-sortable TypeID string (e.g. user_01h455...)."""
    return str(TypeID(prefix=prefix))


class TypeIDType(TypeDecorator):
    """SQLAlchemy column type for storing TypeIDs as Strings (e.g. VARCHAR(36)).
    
    Provides validation and conversion to/from TypeID.
    Supports single prefix or list of acceptable prefixes (e.g. ("user", "usr")).
    """
    impl = String(36)
    cache_ok = True

    def __init__(self, prefix: Union[str, Sequence[str]], *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if isinstance(prefix, str):
            self.prefixes = (prefix,)
            self.primary_prefix = prefix
        else:
            self.prefixes = tuple(prefix)
            self.primary_prefix = prefix[0]

    def process_bind_param(self, value: Optional[Any], dialect: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, TypeID):
            return str(value)
        # Ensure it's a string
        val_str = str(value)
        allowed_prefixes = tuple(f"{p}_" for p in self.prefixes)
        if not val_str.startswith(allowed_prefixes):
            raise ValueError(f"Invalid TypeID prefix: expected one of {self.prefixes}, got '{val_str}'")
        return val_str

    def process_result_value(self, value: Optional[str], dialect: Any) -> Optional[str]:
        return value

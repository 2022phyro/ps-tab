"""MessagePack serialization utilities and custom Starlette response for Kwuo."""

from typing import Any
import msgpack
from fastapi import Response


def packb(obj: Any) -> bytes:
    """Serialize a Python object into MessagePack binary format."""
    return msgpack.packb(obj, use_bin_type=True)


def unpackb(data: bytes) -> Any:
    """Deserialize MessagePack binary data into a Python object."""
    return msgpack.unpackb(data, raw=False)


class MsgPackResponse(Response):
    """FastAPI/Starlette Response class that serializes content to MessagePack."""
    media_type = "application/x-msgpack"

    def render(self, content: Any) -> bytes:
        if content is None:
            return b""
        if isinstance(content, bytes):
            return content
        return packb(content)

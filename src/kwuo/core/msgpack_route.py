"""Custom APIRoute providing default MessagePack serialization and transparent body deserialization."""

from typing import Callable
from fastapi.routing import APIRoute
from fastapi import Request, Response
from kwuo.core.msgpack import MsgPackResponse, unpackb


class MsgPackRoute(APIRoute):
    """An APIRoute that defaults outgoing responses to MessagePack and automatically
    unpacks incoming application/x-msgpack payloads for Pydantic models.
    """

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("response_class", MsgPackResponse)
        super().__init__(*args, **kwargs)

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            content_type = request.headers.get("content-type", "")

            if "application/x-msgpack" in content_type or "application/msgpack" in content_type:
                body = await request.body()
                if body:
                    unpacked_data = unpackb(body)

                    async def custom_json():
                        return unpacked_data

                    request.json = custom_json

            return await original_route_handler(request)

        return custom_route_handler

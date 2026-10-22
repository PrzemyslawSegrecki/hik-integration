"""Authenticated reverse proxy to go2rtc under /go2rtc, so go2rtc credentials never reach the browser."""

import asyncio
from contextlib import suppress

import httpx
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .config import Go2rtcTarget

PREFIX = "/go2rtc"
# Hop-by-hop headers and headers the proxy sets itself.
SKIPPED_REQUEST_HEADERS = {"host", "connection", "keep-alive", "transfer-encoding", "upgrade", "authorization", "cookie"}
SKIPPED_RESPONSE_HEADERS = {"connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length"}


def upstream_path(path: str, query: str) -> str:
    rest = path[len(PREFIX) :] or "/"
    return f"{rest}?{query}" if query else rest


class Go2rtcProxy:
    def __init__(self, target: Go2rtcTarget, http: httpx.AsyncClient):
        self.target = target
        self.http = http

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": self.target.auth_header} if self.target.auth_header else {}

    async def handle_http(self, request: Request) -> StreamingResponse:
        headers = {key: value for key, value in request.headers.items() if key not in SKIPPED_REQUEST_HEADERS}
        upstream = self.http.build_request(
            request.method,
            self.target.target + upstream_path(request.url.path, request.url.query),
            headers={**headers, **self.auth_headers()},
            content=await request.body(),
        )
        response = await self.http.send(upstream, stream=True)
        return StreamingResponse(
            response.aiter_bytes(),
            status_code=response.status_code,
            headers={key: value for key, value in response.headers.items() if key not in SKIPPED_RESPONSE_HEADERS},
            background=BackgroundTask(response.aclose),
        )

    async def handle_websocket(self, websocket: WebSocket) -> None:
        ws_target = self.target.target.replace("http", "ws", 1)
        url = ws_target + upstream_path(websocket.url.path, websocket.url.query)
        try:
            # go2rtc checks the WebSocket Origin; present the request as same-origin.
            upstream = await connect(url, additional_headers=self.auth_headers(), origin=self.target.target)  # type: ignore[arg-type]
        except Exception:
            await websocket.close(code=1011)
            return

        await websocket.accept()
        async with upstream:

            async def client_to_upstream() -> None:
                with suppress(WebSocketDisconnect, ConnectionClosed):
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        if message.get("text") is not None:
                            await upstream.send(message["text"])
                        elif message.get("bytes") is not None:
                            await upstream.send(message["bytes"])

            async def upstream_to_client() -> None:
                with suppress(WebSocketDisconnect, ConnectionClosed, RuntimeError):
                    async for data in upstream:
                        if isinstance(data, str):
                            await websocket.send_text(data)
                        else:
                            await websocket.send_bytes(data)

            tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()

        with suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close()

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from .auth import AuthMiddleware, Authenticator
from .config import Config, load_config_from_environment
from .diagnostics import Diagnostics
from .doorbell import Doorbell
from .go2rtc_proxy import PREFIX as GO2RTC_PREFIX
from .go2rtc_proxy import Go2rtcProxy
from .hikvision import HikvisionClient

PUBLIC_DIR = Path(__file__).resolve().parents[1] / "public"
PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


class Broadcaster:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.tasks: set[asyncio.Task[None]] = set()

    async def send(self, client: WebSocket, raw: str) -> None:
        try:
            await client.send_text(raw)
        except Exception:
            self.clients.discard(client)

    def __call__(self, event: dict[str, Any]) -> None:
        if not self.clients:
            return
        raw = json.dumps(event)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for client in list(self.clients):
            task = loop.create_task(self.send(client, raw))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)


async def report_failure(doorbell: Doorbell, action: Callable[[], Awaitable[Response]], failure: str) -> Response:
    try:
        return await action()
    except Exception as error:
        doorbell.log("error", str(error) or failure)
        return JSONResponse({"ok": False}, status_code=502)


def create_app(
    config: Config,
    hik: HikvisionClient | None = None,
    http: httpx.AsyncClient | None = None,
    public_dir: Path = PUBLIC_DIR,
    poll: bool = True,
) -> FastAPI:
    env = config.env
    hik = hik or HikvisionClient(config)
    # No read timeout: proxied go2rtc responses may be long-lived streams.
    http = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None))
    broadcaster = Broadcaster()
    doorbell = Doorbell(config, hik, broadcaster)
    diagnostics = Diagnostics(config, hik, http)
    go2rtc = Go2rtcProxy(config.go2rtc, http) if config.go2rtc else None

    async def log_startup_checks() -> None:
        result = await diagnostics.run()
        for check in result.checks:
            hint = f" -> {check.hint}" if check.hint else ""
            doorbell.log("info" if check.ok else "warn", f"[check] {check.id}: {check.message}{hint}")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        doorbell.log("info", f"Server listening on http://localhost:{env.PORT}")
        if env.AUTH_DISABLED:
            doorbell.log("warn", "AUTH_DISABLED=true - anyone who can reach this server can open the door")
        tasks = [asyncio.create_task(log_startup_checks())]
        if poll:
            tasks.append(asyncio.create_task(doorbell.poll_forever()))
        try:
            yield
        finally:
            for task in [*tasks, *doorbell.background_tasks]:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            await hik.close()
            await http.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.doorbell = doorbell

    app.add_middleware(AuthMiddleware, authenticator=Authenticator(env))
    if env.UI_ORIGIN:
        origins = ["*"] if env.UI_ORIGIN == "*" else [env.UI_ORIGIN]
        # Added last so it runs first and answers CORS preflights before authentication.
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    @app.get("/api/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/diagnostics")
    async def get_diagnostics() -> dict[str, object]:
        return (await diagnostics.run()).to_json()

    @app.get("/api/state")
    async def get_state() -> dict[str, object]:
        return doorbell.state.to_json()

    @app.post("/api/events/ring")
    async def ring() -> dict[str, object]:
        doorbell.manual_ring()
        return doorbell.state.to_json()

    @app.post("/api/actions/accept")
    async def accept(request: Request) -> Response:
        if not doorbell.can_accept():
            return JSONResponse({"ok": False, "reason": "call_not_ringing"}, status_code=409)
        try:
            body = await request.json()
        except ValueError:
            body = None
        speaker = body.get("speaker") if isinstance(body, dict) else None

        async def run() -> Response:
            await doorbell.accept(speaker if isinstance(speaker, str) else "local-client")
            return JSONResponse(doorbell.state.to_json())

        return await report_failure(doorbell, run, "Failed to answer call")

    @app.post("/api/actions/open-door")
    async def open_door() -> Response:
        async def run() -> Response:
            await doorbell.open_door()
            return JSONResponse({"ok": True})

        return await report_failure(doorbell, run, "Failed to open door")

    @app.post("/api/actions/reject")
    async def reject() -> Response:
        async def run() -> Response:
            await doorbell.reject()
            return JSONResponse({"ok": True})

        return await report_failure(doorbell, run, "Failed to reject call")

    @app.post("/api/actions/hangup")
    async def hangup() -> Response:
        async def run() -> Response:
            await doorbell.hangup()
            return JSONResponse({"ok": True})

        return await report_failure(doorbell, run, "Failed to hangup call")

    @app.post("/api/actions/reset")
    async def reset() -> dict[str, object]:
        doorbell.reset()
        return doorbell.state.to_json()

    @app.api_route("/api/{rest:path}", methods=PROXY_METHODS, include_in_schema=False)
    async def api_not_found(rest: str) -> Response:
        return JSONResponse({"ok": False, "reason": "not_found"}, status_code=404)

    @app.websocket("/ws")
    async def state_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        broadcaster.clients.add(websocket)
        try:
            await websocket.send_json({"type": "state", "payload": doorbell.state.to_json()})
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            broadcaster.clients.discard(websocket)

    if go2rtc:

        @app.api_route(GO2RTC_PREFIX + "/{rest:path}", methods=PROXY_METHODS, include_in_schema=False)
        async def go2rtc_http(request: Request, rest: str) -> Response:
            return await go2rtc.handle_http(request)

        @app.websocket(GO2RTC_PREFIX + "/{rest:path}")
        async def go2rtc_websocket(websocket: WebSocket, rest: str) -> None:
            await go2rtc.handle_websocket(websocket)

    index = public_dir / "index.html"
    if index.is_file():
        @app.get("/{rest:path}", include_in_schema=False)
        async def frontend(rest: str) -> FileResponse:
            candidate = (public_dir / rest).resolve()
            if rest and candidate.is_file() and candidate.is_relative_to(public_dir.resolve()):
                return FileResponse(candidate)
            return FileResponse(index)

    else:

        @app.get("/{rest:path}", include_in_schema=False)
        async def frontend_missing(rest: str) -> Response:
            return JSONResponse(
                {
                    "ok": False,
                    "reason": "frontend_not_built",
                    "message": "Frontend dev server should be available at http://localhost:5173 or http://localhost:5174.",
                },
                status_code=503,
            )

    return app


def create_app_from_environment() -> FastAPI:
    return create_app(load_config_from_environment())

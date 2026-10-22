from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hik_server.app import create_app
from hik_server.config import Config

from .conftest import FakeHik

BEARER = {"Authorization": "Bearer tok-123"}


def go2rtc_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/streams":
        return httpx.Response(200, json={"doorbell": {}, "seen-auth": request.headers.get("authorization")})
    return httpx.Response(404)


@pytest.fixture
def public_dir(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "rtc-player.html").write_text("<html>player</html>")
    return tmp_path


@pytest.fixture
def client(make_config: Callable[..., Config], fake_hik: FakeHik, public_dir: Path) -> Iterator[TestClient]:
    app = create_app(
        make_config(),
        hik=fake_hik,  # type: ignore[arg-type]
        http=httpx.AsyncClient(transport=httpx.MockTransport(go2rtc_handler)),
        public_dir=public_dir,
        poll=False,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_health_is_public_and_everything_else_needs_auth(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200

    response = client.get("/api/state")
    assert response.status_code == 401
    assert response.json() == {"ok": False, "reason": "unauthorized"}
    assert response.headers["www-authenticate"].startswith("Basic")

    assert client.get("/").status_code == 401
    assert client.get("/go2rtc/api/streams").status_code == 401


def test_state_uses_the_web_ui_wire_format(client: TestClient) -> None:
    state = client.get("/api/state", headers=BEARER).json()
    assert state["callState"] == "idle"
    assert state["wsUrl"] == "/ws"
    assert state["streamUrl"].startswith("/rtc-player.html?go2rtc=%2Fgo2rtc")
    assert set(state) == {
        "callState", "source", "lastEventAt", "lastRingAt", "lastActionAt",
        "activeSpeaker", "popupVisible", "streamUrl", "wsUrl",
    }


def test_query_token_is_remembered_in_a_cookie(client: TestClient) -> None:
    response = client.get("/?overlay=1&token=tok-123")
    assert response.status_code == 200
    assert "hik_token=tok-123" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert client.get("/api/state").status_code == 200


def test_call_flow(client: TestClient, fake_hik: FakeHik) -> None:
    assert client.post("/api/actions/accept", headers=BEARER).status_code == 409

    client.post("/api/events/ring", headers=BEARER)
    accepted = client.post("/api/actions/accept", headers=BEARER, json={"speaker": "home-assistant"}).json()
    assert accepted["callState"] == "answered_local"
    assert accepted["activeSpeaker"] == "home-assistant"

    assert client.post("/api/actions/open-door", headers=BEARER).json() == {"ok": True}
    assert client.post("/api/actions/hangup", headers=BEARER).json() == {"ok": True}
    assert client.get("/api/state", headers=BEARER).json()["callState"] == "ended"
    assert fake_hik.calls[:3] == ["answer_call", "hangup_call_signal", "open_door"]


def test_device_errors_become_502(client: TestClient, fake_hik: FakeHik) -> None:
    fake_hik.fail = {"open_door"}
    response = client.post("/api/actions/open-door", headers=BEARER)
    assert response.status_code == 502
    assert response.json() == {"ok": False}


def test_websocket_sends_state_and_requires_auth(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws"):
            pass

    with client.websocket_connect("/ws", headers=BEARER) as socket:
        assert socket.receive_json()["type"] == "state"
        client.post("/api/events/ring", headers=BEARER)
        event = socket.receive_json()
        assert event["type"] == "state"
        assert event["payload"]["callState"] == "ringing"


def test_go2rtc_proxy_adds_server_side_credentials(client: TestClient) -> None:
    streams = client.get("/go2rtc/api/streams", headers=BEARER).json()
    assert "doorbell" in streams
    assert streams["seen-auth"].startswith("Basic ")


def test_diagnostics(client: TestClient) -> None:
    result = client.get("/api/diagnostics", headers=BEARER).json()
    by_id = {check["id"]: check for check in result["checks"]}
    assert by_id["stream"]["ok"] is True
    assert by_id["auth"]["message"] == "Authentication enabled (password + token)"


def test_serves_frontend_files_with_spa_fallback(client: TestClient) -> None:
    assert client.get("/rtc-player.html", headers=BEARER).text == "<html>player</html>"
    assert client.get("/some/route", headers=BEARER).text == "<html>app</html>"
    assert client.get("/../etc/passwd", headers=BEARER).text == "<html>app</html>"
    assert client.get("/api/unknown", headers=BEARER).status_code == 404


def test_local_network_clients_skip_login_but_tunnel_requests_do_not(
    make_config: Callable[..., Config], fake_hik: FakeHik, public_dir: Path
) -> None:
    app = create_app(make_config(TRUST_LOCAL_NETWORK="true"), hik=fake_hik, public_dir=public_dir, poll=False)  # type: ignore[arg-type]
    with TestClient(app, client=("192.168.1.20", 50000)) as lan:
        assert lan.get("/api/state").status_code == 200
        with lan.websocket_connect("/ws") as socket:
            assert socket.receive_json()["type"] == "state"
        assert lan.get("/api/state", headers={"CF-Connecting-IP": "203.0.113.7"}).status_code == 401
        assert lan.get("/api/state", headers={"CF-Connecting-IP": "203.0.113.7", **BEARER}).status_code == 200

import base64
import binascii
import hmac
import ipaddress
from collections.abc import Mapping
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Env

TOKEN_COOKIE = "hik_token"
PUBLIC_PATHS = {"/api/health"}
# Requests relayed by a proxy or tunnel (Cloudflare adds CF-Connecting-IP / CF-Ray) are never
# treated as local, even though the proxy itself connects from a private address.
PROXY_HEADERS = ("cf-connecting-ip", "cf-ray", "x-forwarded-for", "x-real-ip", "forwarded")
COOKIE_MAX_AGE = 365 * 24 * 60 * 60


def safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def read_cookie(header: str | None, name: str) -> str | None:
    if not header:
        return None
    cookie: SimpleCookie = SimpleCookie()
    try:
        cookie.load(header)
    except Exception:
        return None
    morsel = cookie.get(name)
    return morsel.value if morsel else None


def is_local_address(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_private or address.is_loopback or address.is_link_local


def query_token(query_string: str) -> str | None:
    values = parse_qs(query_string).get("token")
    return values[0] if values else None


class Authenticator:
    def __init__(self, env: Env):
        self.env = env

    def token_matches(self, candidate: str | None) -> bool:
        return candidate is not None and self.env.APP_TOKEN is not None and safe_equal(candidate, self.env.APP_TOKEN)

    def has_valid_token(self, headers: Mapping[str, str], query_string: str) -> bool:
        authorization = headers.get("authorization", "")
        candidates = [
            authorization[7:] if authorization.startswith("Bearer ") else None,
            query_token(query_string),
            read_cookie(headers.get("cookie"), TOKEN_COOKIE),
        ]
        return any(self.token_matches(candidate) for candidate in candidates)

    def has_valid_basic_auth(self, headers: Mapping[str, str]) -> bool:
        authorization = headers.get("authorization", "")
        if not self.env.APP_PASSWORD or not authorization.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode()
        except (binascii.Error, UnicodeDecodeError):
            return False
        username, separator, password = decoded.partition(":")
        if not separator:
            return False
        # Evaluate both comparisons to avoid leaking which part was wrong.
        user_ok = safe_equal(username, self.env.APP_USERNAME)
        password_ok = safe_equal(password, self.env.APP_PASSWORD)
        return user_ok and password_ok

    def is_trusted_local(self, headers: Mapping[str, str], client_host: str | None) -> bool:
        return (
            self.env.TRUST_LOCAL_NETWORK
            and is_local_address(client_host)
            and not any(header in headers for header in PROXY_HEADERS)
        )

    def is_authorized(self, headers: Mapping[str, str], query_string: str = "", client_host: str | None = None) -> bool:
        return (
            self.env.AUTH_DISABLED
            or self.is_trusted_local(headers, client_host)
            or self.has_valid_token(headers, query_string)
            or self.has_valid_basic_auth(headers)
        )


def scope_headers(scope: Scope) -> dict[str, str]:
    return {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]}


class AuthMiddleware:
    """Protects every HTTP and WebSocket route except PUBLIC_PATHS."""

    def __init__(self, app: ASGIApp, authenticator: Authenticator):
        self.app = app
        self.auth = authenticator

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        headers = scope_headers(scope)
        query_string = scope.get("query_string", b"").decode("latin-1")
        client = scope.get("client")
        client_host = client[0] if client else None

        if not self.auth.is_authorized(headers, query_string, client_host):
            if scope["type"] == "websocket":
                await self.reject_websocket(scope, receive, send)
            else:
                await self.reject_http(send)
            return

        # A valid ?token= (e.g. Home Assistant iframe, Windows client popup) is remembered
        # in a cookie so that follow-up requests for assets, the API and /ws are authorized too.
        token = query_token(query_string)
        if scope["type"] == "http" and self.auth.token_matches(token):
            assert token is not None
            secure = scope.get("scheme") == "https" or headers.get("x-forwarded-proto") == "https"
            cookie = self.token_cookie(token, secure)

            async def send_with_cookie(message: Message) -> None:
                if message["type"] == "http.response.start":
                    message["headers"] = [*message.get("headers", []), (b"set-cookie", cookie.encode("latin-1"))]
                await send(message)

            await self.app(scope, receive, send_with_cookie)
            return

        await self.app(scope, receive, send)

    @staticmethod
    def token_cookie(token: str, secure: bool) -> str:
        cookie: SimpleCookie = SimpleCookie()
        cookie[TOKEN_COOKIE] = token
        morsel = cookie[TOKEN_COOKIE]
        morsel["path"] = "/"
        morsel["max-age"] = COOKIE_MAX_AGE
        morsel["httponly"] = True
        morsel["samesite"] = "None" if secure else "Lax"
        if secure:
            morsel["secure"] = True
        return morsel.OutputString()

    async def reject_http(self, send: Send) -> None:
        headers = [(b"content-type", b"application/json")]
        if self.auth.env.APP_PASSWORD:
            headers.append((b"www-authenticate", b'Basic realm="Hik Doorbell", charset="UTF-8"'))
        await send({"type": "http.response.start", "status": 401, "headers": headers})
        await send({"type": "http.response.body", "body": b'{"ok":false,"reason":"unauthorized"}'})

    @staticmethod
    async def reject_websocket(scope: Scope, receive: Receive, send: Send) -> None:
        await receive()  # websocket.connect
        if "websocket.http.response" in scope.get("extensions", {}):
            await send({"type": "websocket.http.response.start", "status": 401, "headers": []})
            await send({"type": "websocket.http.response.body", "body": b""})
        else:
            await send({"type": "websocket.close", "code": 1008})

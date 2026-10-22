import base64
from collections.abc import Callable

import pytest

from hik_server.auth import Authenticator
from hik_server.config import Config, load_config


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


@pytest.fixture
def auth(make_config: Callable[..., Config]) -> Authenticator:
    return Authenticator(make_config().env)


def test_rejects_requests_without_credentials(auth: Authenticator) -> None:
    assert not auth.is_authorized({})


def test_accepts_correct_basic_auth_and_rejects_a_wrong_password(auth: Authenticator) -> None:
    assert auth.is_authorized({"authorization": basic("admin", "secret")})
    assert not auth.is_authorized({"authorization": basic("admin", "nope")})
    assert not auth.is_authorized({"authorization": basic("other", "secret")})
    assert not auth.is_authorized({"authorization": "Basic not-base64!"})


def test_accepts_the_token_as_bearer_header_query_parameter_or_cookie(auth: Authenticator) -> None:
    assert auth.is_authorized({"authorization": "Bearer tok-123"})
    assert auth.is_authorized({}, "overlay=1&token=tok-123")
    assert auth.is_authorized({"cookie": "a=b; hik_token=tok-123"})


def test_rejects_a_wrong_token(auth: Authenticator) -> None:
    assert not auth.is_authorized({"authorization": "Bearer tok-1234"})
    assert not auth.is_authorized({}, "token=x")


def test_disabled_auth_lets_everyone_in(make_config: Callable[..., Config]) -> None:
    auth = Authenticator(make_config(AUTH_DISABLED="true").env)
    assert auth.is_authorized({})


@pytest.fixture
def lan_auth(make_config: Callable[..., Config]) -> Authenticator:
    return Authenticator(make_config(TRUST_LOCAL_NETWORK="true").env)


@pytest.mark.parametrize("host", ["192.168.1.20", "10.0.0.5", "172.17.0.1", "127.0.0.1", "::1", "fe80::1", "::ffff:192.168.1.2"])
def test_trusted_local_network_needs_no_login(lan_auth: Authenticator, host: str) -> None:
    assert lan_auth.is_authorized({}, client_host=host)


@pytest.mark.parametrize("host", ["8.8.8.8", "100.64.0.1", "2001:4860::1", "testclient", None])
def test_public_addresses_still_need_a_token(lan_auth: Authenticator, host: str | None) -> None:
    assert not lan_auth.is_authorized({}, client_host=host)
    assert lan_auth.is_authorized({"authorization": "Bearer tok-123"}, client_host=host)


@pytest.mark.parametrize("header", ["cf-connecting-ip", "cf-ray", "x-forwarded-for", "x-real-ip", "forwarded"])
def test_requests_relayed_by_a_proxy_or_tunnel_are_not_local(lan_auth: Authenticator, header: str) -> None:
    # cloudflared on the same host connects from a private address but adds Cloudflare headers.
    assert not lan_auth.is_authorized({header: "203.0.113.7"}, client_host="172.18.0.5")


def test_local_network_is_not_trusted_unless_enabled(auth: Authenticator) -> None:
    assert not auth.is_authorized({}, client_host="192.168.1.20")


def test_trusting_the_local_network_is_enough_configuration() -> None:
    env = load_config({"HIK_IP": "1.2.3.4", "HIK_PASSWORD": "x", "TRUST_LOCAL_NETWORK": "true"}).env
    assert Authenticator(env).is_authorized({}, client_host="192.168.1.2")
    assert not Authenticator(env).is_authorized({"authorization": "Bearer "}, client_host="8.8.8.8")

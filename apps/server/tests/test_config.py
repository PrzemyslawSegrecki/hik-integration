import base64
from collections.abc import Callable

import pytest

from hik_server.config import Config, ConfigError, load_config


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def test_moves_go2rtc_credentials_from_the_url_into_a_server_side_auth_header(make_config: Callable[..., Config]) -> None:
    config = make_config()
    assert config.go2rtc is not None
    assert config.go2rtc.target == "http://go2rtc:1984"
    assert config.go2rtc.auth_header == basic("rtc", "p@ss")


def test_explicit_go2rtc_credentials_win_over_the_url(make_config: Callable[..., Config]) -> None:
    config = make_config(GO2RTC_USERNAME="other", GO2RTC_PASSWORD="pw")
    assert config.go2rtc is not None
    assert config.go2rtc.auth_header == basic("other", "pw")


def test_never_exposes_go2rtc_credentials_in_the_stream_url(make_config: Callable[..., Config]) -> None:
    stream_url = make_config().stream_url
    assert "go2rtc=%2Fgo2rtc" in stream_url
    assert "src=doorbell" in stream_url
    assert "media=video%2Baudio%2Bmicrophone" in stream_url
    assert "rtc:" not in stream_url
    assert "p%40ss" not in stream_url


def test_without_go2rtc_there_is_no_stream(make_config: Callable[..., Config]) -> None:
    config = make_config(GO2RTC_URL="")
    assert config.go2rtc is None
    assert config.stream_url == ""


def test_defaults_and_derived_values(make_config: Callable[..., Config]) -> None:
    config = make_config(AUTH_DISABLED="")
    assert config.env.PORT == 8090
    assert config.env.AUTH_DISABLED is False
    assert config.env.HIK_ACCEPT_STRATEGY == "answer_hangup"
    assert config.isapi_base == "http://127.0.0.2/ISAPI"


def test_reports_missing_required_values() -> None:
    with pytest.raises(ConfigError) as error:
        load_config({"APP_TOKEN": "x", "HIK_IP": "  "})
    assert "HIK_IP: HIK_IP is required (IP address of the doorbell)" in error.value.issues
    assert "HIK_PASSWORD: HIK_PASSWORD is required (doorbell admin password)" in error.value.issues


def test_requires_some_authentication() -> None:
    with pytest.raises(ConfigError, match="Set APP_PASSWORD and/or APP_TOKEN"):
        load_config({"HIK_IP": "1.2.3.4", "HIK_PASSWORD": "x"})
    assert load_config({"HIK_IP": "1.2.3.4", "HIK_PASSWORD": "x", "AUTH_DISABLED": "true"}).env.AUTH_DISABLED


def test_rejects_an_unknown_accept_strategy() -> None:
    with pytest.raises(ConfigError, match="HIK_ACCEPT_STRATEGY"):
        load_config({"HIK_IP": "1.2.3.4", "HIK_PASSWORD": "x", "APP_TOKEN": "t", "HIK_ACCEPT_STRATEGY": "nope"})

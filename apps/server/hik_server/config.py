import base64
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

REQUIRED_MESSAGES = {
    "HIK_IP": "HIK_IP is required (IP address of the doorbell)",
    "HIK_PASSWORD": "HIK_PASSWORD is required (doorbell admin password)",
}


@dataclass(frozen=True)
class Go2rtcTarget:
    target: str
    auth_header: str | None


class Env(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    PORT: int = 8090
    UI_ORIGIN: str | None = None

    APP_USERNAME: str = "admin"
    APP_PASSWORD: str | None = None
    APP_TOKEN: str | None = None
    AUTH_DISABLED: bool = False
    TRUST_LOCAL_NETWORK: bool = False

    HIK_IP: str
    HIK_USERNAME: str = "admin"
    HIK_PASSWORD: str
    HIK_DOOR_INDEX: int = 1
    HIK_ISAPI_BASE: str | None = None
    HIK_CALLSTATUS_POLL_MS: int = 1000
    HIK_ACCEPT_STRATEGY: Literal["local_only", "answer_hangup"] = "answer_hangup"
    HIK_ACCEPT_DELAY_MS: int = 500
    HIK_IGNORE_IDLE_AFTER_ACCEPT_MS: int = 120000
    HIK_ENDCALL_RETRY_DELAY_MS: int = 1500

    GO2RTC_URL: str | None = None
    # Deprecated alias of GO2RTC_URL, kept so existing .env files keep working.
    GO2RTC_PUBLIC_URL: str | None = None
    GO2RTC_USERNAME: str | None = None
    GO2RTC_PASSWORD: str | None = None
    GO2RTC_STREAM_NAME: str = "doorbell"
    GO2RTC_MEDIA: str = "video+audio+microphone"

    @model_validator(mode="before")
    @classmethod
    def drop_empty_values(cls, data: object) -> object:
        if not isinstance(data, Mapping):
            return data
        return {key: value.strip() for key, value in data.items() if isinstance(value, str) and value.strip() != ""}

    @model_validator(mode="after")
    def require_auth(self) -> "Env":
        if not (self.AUTH_DISABLED or self.TRUST_LOCAL_NETWORK or self.APP_PASSWORD or self.APP_TOKEN):
            raise ValueError(
                "Set APP_PASSWORD and/or APP_TOKEN to protect the app "
                "(or TRUST_LOCAL_NETWORK=true / AUTH_DISABLED=true for a trusted LAN only)"
            )
        return self


@dataclass(frozen=True)
class Config:
    env: Env
    isapi_base: str
    stream_url: str
    go2rtc: Go2rtcTarget | None


class ConfigError(Exception):
    def __init__(self, issues: list[str]):
        super().__init__("\n".join(issues))
        self.issues = issues


def parse_go2rtc(env: Env) -> Go2rtcTarget | None:
    raw = env.GO2RTC_URL or env.GO2RTC_PUBLIC_URL
    if not raw:
        return None

    url = urlsplit(raw)
    username = env.GO2RTC_USERNAME or (unquote(url.username) if url.username else None)
    password = env.GO2RTC_PASSWORD or (unquote(url.password) if url.password else None)
    host = url.hostname or ""
    netloc = f"[{host}]" if ":" in host else host
    if url.port:
        netloc += f":{url.port}"
    target = urlunsplit((url.scheme, netloc, url.path, url.query, "")).rstrip("/")

    auth_header = None
    if username:
        credentials = base64.b64encode(f"{username}:{password or ''}".encode()).decode()
        auth_header = f"Basic {credentials}"
    return Go2rtcTarget(target=target, auth_header=auth_header)


def load_config(environ: Mapping[str, str | None]) -> Config:
    try:
        env = Env.model_validate(environ)
    except ValidationError as error:
        issues = []
        for issue in error.errors():
            field = ".".join(str(part) for part in issue["loc"]) or "env"
            message = REQUIRED_MESSAGES.get(field) if issue["type"] == "missing" else None
            issues.append(f"{field}: {message or issue['msg'].removeprefix('Value error, ')}")
        raise ConfigError(issues) from None

    go2rtc = parse_go2rtc(env)
    # The browser only ever talks to go2rtc through the authenticated /go2rtc proxy,
    # so go2rtc credentials never leave the server.
    stream_url = (
        f"/rtc-player.html?go2rtc={quote('/go2rtc', safe='')}"
        f"&src={quote(env.GO2RTC_STREAM_NAME, safe='')}&media={quote(env.GO2RTC_MEDIA, safe='')}"
        if go2rtc
        else ""
    )
    return Config(
        env=env,
        isapi_base=env.HIK_ISAPI_BASE or f"http://{env.HIK_IP}/ISAPI",
        stream_url=stream_url,
        go2rtc=go2rtc,
    )


def load_config_from_environment() -> Config:
    # Like dotenv in Node: real environment variables win over the .env file.
    environ = {**dotenv_values(ENV_FILE), **os.environ}
    try:
        return load_config(environ)
    except ConfigError as error:
        print("Invalid configuration (check your .env file):", file=sys.stderr)
        for issue in error.issues:
            print(f"  - {issue}", file=sys.stderr)
        sys.exit(1)

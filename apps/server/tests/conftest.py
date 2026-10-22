from collections.abc import Callable
from typing import Any

import pytest

from hik_server.config import Config, load_config
from hik_server.hikvision import AudioChannel, DeviceInfo

BASE_ENV = {
    "HIK_IP": "127.0.0.2",
    "HIK_PASSWORD": "doorbell-pass",
    "APP_USERNAME": "admin",
    "APP_PASSWORD": "secret",
    "APP_TOKEN": "tok-123",
    "AUTH_DISABLED": "false",
    "GO2RTC_URL": "http://rtc:p%40ss@go2rtc:1984/",
    "HIK_ACCEPT_DELAY_MS": "0",
    "HIK_ENDCALL_RETRY_DELAY_MS": "0",
}


@pytest.fixture
def make_config() -> Callable[..., Config]:
    def make(**overrides: str) -> Config:
        return load_config({**BASE_ENV, **overrides})

    return make


class FakeHik:
    """Records ISAPI calls; call_status/channels drive what the device reports."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.call_status: str | Exception = "idle"
        self.channels: list[AudioChannel] = []
        self.fail: set[str] = set()

    async def record(self, name: str) -> str:
        self.calls.append(name)
        if name in self.fail:
            raise RuntimeError(f"{name} failed")
        return ""

    async def get_call_status(self) -> str:
        if isinstance(self.call_status, Exception):
            raise self.call_status
        return self.call_status

    async def safe_get_call_status(self) -> str:
        return self.call_status if isinstance(self.call_status, str) else "error"

    async def get_device_info(self) -> DeviceInfo:
        return DeviceInfo(device_name="Door", model="DS-KV8113-WME1(C)", firmware_version="V2.2.78")

    async def get_two_way_audio_channels(self) -> list[AudioChannel]:
        return self.channels

    async def close_all_active_two_way_audio_channels(self) -> list[str]:
        await self.record("close_channels")
        return [channel.id for channel in self.channels if channel.id and channel.enabled == "true"]

    def __getattr__(self, name: str) -> Callable[[], Any]:
        if name.startswith("_"):
            raise AttributeError(name)

        async def action() -> str:
            return await self.record(name)

        return action

    async def close(self) -> None:
        pass


@pytest.fixture
def fake_hik() -> FakeHik:
    return FakeHik()

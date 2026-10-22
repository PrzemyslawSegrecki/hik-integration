import asyncio
from collections.abc import Awaitable
from typing import TypeVar

import httpx

from .config import Config
from .hikvision import HikvisionClient, IsapiError
from .models import DiagnosticCheck, DiagnosticsResult

TIMEOUT_S = 5.0

T = TypeVar("T")


def error_message(error: BaseException) -> str:
    if isinstance(error, TimeoutError):
        return f"timeout after {int(TIMEOUT_S * 1000)} ms"
    message = str(error)
    if isinstance(error, IsapiError):
        return message
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


async def with_timeout(awaitable: Awaitable[T]) -> T:
    return await asyncio.wait_for(awaitable, TIMEOUT_S)


class Diagnostics:
    def __init__(self, config: Config, hik: HikvisionClient, http: httpx.AsyncClient):
        self.config = config
        self.hik = hik
        self.http = http

    async def check_doorbell(self) -> DiagnosticCheck:
        try:
            info = await with_timeout(self.hik.get_device_info())
        except Exception as error:
            message = error_message(error)
            hint = (
                "Check HIK_USERNAME / HIK_PASSWORD"
                if "401" in message
                else "Check HIK_IP and that this server can reach the doorbell on port 80"
            )
            return DiagnosticCheck(id="doorbell", ok=False, message=f"Cannot reach ISAPI: {message}", hint=hint)

        parts = [info.model, info.firmware_version and f"fw {info.firmware_version}"]
        name = ", ".join(part for part in parts if part)
        suffix = f" ({name})" if name else ""
        return DiagnosticCheck(id="doorbell", ok=True, message=f"Connected to {self.config.env.HIK_IP}{suffix}")

    async def check_call_status(self) -> DiagnosticCheck:
        try:
            status = await with_timeout(self.hik.get_call_status())
        except Exception as error:
            return DiagnosticCheck(
                id="callStatus",
                ok=False,
                message=f"Cannot read callStatus: {error_message(error)}",
                hint="The device may not support /ISAPI/VideoIntercom/callStatus (ring detection will not work)",
            )
        return DiagnosticCheck(id="callStatus", ok=True, message=f"callStatus = {status}")

    async def check_go2rtc(self) -> list[DiagnosticCheck]:
        go2rtc = self.config.go2rtc
        if not go2rtc:
            return [
                DiagnosticCheck(
                    id="go2rtc",
                    ok=False,
                    message="GO2RTC_URL is not set - video and two-way audio are disabled",
                    hint="Set GO2RTC_URL to your go2rtc address, e.g. http://192.168.1.10:1984",
                )
            ]

        try:
            headers = {"Authorization": go2rtc.auth_header} if go2rtc.auth_header else {}
            response = await with_timeout(self.http.get(f"{go2rtc.target}/api/streams", headers=headers))
            if response.status_code == 401:
                return [
                    DiagnosticCheck(
                        id="go2rtc",
                        ok=False,
                        message="go2rtc rejected credentials (401)",
                        hint="Check GO2RTC_USERNAME / GO2RTC_PASSWORD",
                    )
                ]
            if response.is_error:
                return [DiagnosticCheck(id="go2rtc", ok=False, message=f"go2rtc responded with {response.status_code}")]
            streams = response.json() or {}
        except Exception as error:
            return [
                DiagnosticCheck(
                    id="go2rtc",
                    ok=False,
                    message=f"Cannot reach go2rtc: {error_message(error)}",
                    hint="Check GO2RTC_URL - it must be reachable from this server",
                )
            ]

        name = self.config.env.GO2RTC_STREAM_NAME
        names = list(streams)
        has_stream = name in names
        return [
            DiagnosticCheck(id="go2rtc", ok=True, message=f"Connected to {go2rtc.target}"),
            DiagnosticCheck(
                id="stream",
                ok=has_stream,
                message=f'Stream "{name}" found' if has_stream else f'Stream "{name}" not found in go2rtc',
                hint=None
                if has_stream
                else f"Available: {', '.join(names) or 'none'}. Set GO2RTC_STREAM_NAME or add the stream to go2rtc.yaml",
            ),
        ]

    def check_auth(self) -> DiagnosticCheck:
        env = self.config.env
        if env.AUTH_DISABLED:
            return DiagnosticCheck(
                id="auth",
                ok=False,
                message="Authentication is disabled (AUTH_DISABLED=true)",
                hint="Never expose this server to the internet in this mode",
            )
        options = (("password", env.APP_PASSWORD), ("token", env.APP_TOKEN), ("no login on local network", env.TRUST_LOCAL_NETWORK))
        modes = " + ".join(mode for mode, enabled in options if enabled)
        return DiagnosticCheck(id="auth", ok=True, message=f"Authentication enabled ({modes})")

    async def run(self) -> DiagnosticsResult:
        doorbell, go2rtc = await asyncio.gather(self.check_doorbell(), self.check_go2rtc())
        call_status = (
            await self.check_call_status()
            if doorbell.ok
            else DiagnosticCheck(id="callStatus", ok=False, message="Skipped - doorbell is not reachable")
        )
        checks = [doorbell, call_status, *go2rtc, self.check_auth()]
        return DiagnosticsResult(ok=all(check.ok for check in checks), checks=checks)

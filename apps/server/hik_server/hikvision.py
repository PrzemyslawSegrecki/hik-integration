import asyncio
import json
import re
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Config

REQUEST_TIMEOUT_S = 10.0


class IsapiError(Exception):
    pass


@dataclass(frozen=True)
class AudioChannel:
    id: str | None
    enabled: str | None


@dataclass(frozen=True)
class DeviceInfo:
    device_name: str | None
    model: str | None
    firmware_version: str | None


class HikvisionDigestAuth(httpx.DigestAuth):
    """Digest auth that survives Hikvision's nonce expiry.

    The device rejects an expired nonce with a bare 401 without a new challenge. Plain
    httpx.DigestAuth then keeps reusing the dead nonce, and enough consecutive failures
    make the device lock out the client IP. Here a 401 drops the cached challenge and the
    request is repeated through a fresh challenge.
    """

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        if self._last_challenge:
            request.headers["Authorization"] = self._build_auth_header(request, self._last_challenge)
            response = yield request
            if response.status_code != 401:
                return
            self._last_challenge = None
            del request.headers["Authorization"]
        yield from super().auth_flow(request)


def xml_value(xml: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>([^<]*)</{tag}>", xml)
    return match.group(1) if match else None


def call_signal(cmd_type: str) -> str:
    return json.dumps({"CallSignal": {"cmdType": cmd_type}})


class HikvisionClient:
    def __init__(self, config: Config, transport: httpx.AsyncBaseTransport | None = None):
        self.door_index = config.env.HIK_DOOR_INDEX
        self.http = httpx.AsyncClient(
            base_url=config.isapi_base,
            auth=HikvisionDigestAuth(config.env.HIK_USERNAME, config.env.HIK_PASSWORD),
            timeout=REQUEST_TIMEOUT_S,
            transport=transport,
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def request(self, method: str, path: str, body: str | None = None, content_type: str = "application/xml") -> str:
        headers = {"Content-Type": content_type} if body is not None else None
        response = await self.http.request(method, path, content=body, headers=headers)
        if response.is_error:
            raise IsapiError(f"ISAPI {path} failed: {response.status_code} {response.text}")
        return response.text

    async def put_call_signal(self, cmd_type: str) -> str:
        return await self.request("PUT", "/VideoIntercom/callSignal?format=json", call_signal(cmd_type), "application/json")

    async def open_door(self) -> str:
        return await self.request(
            "PUT",
            f"/AccessControl/RemoteControl/door/{self.door_index}",
            "<RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>",
        )

    async def reject_call(self) -> str:
        return await self.put_call_signal("reject")

    async def answer_call(self) -> str:
        return await self.put_call_signal("answer")

    async def hangup_call_signal(self) -> str:
        return await self.put_call_signal("hangUp")

    async def delete_all_rings(self) -> str:
        return await self.request("DELETE", "/VideoIntercom/ring")

    async def close_two_way_audio(self) -> str:
        return await self.close_two_way_audio_channel("1")

    async def close_two_way_audio_channel(self, channel_id: str) -> str:
        return await self.request("PUT", f"/System/TwoWayAudio/channels/{channel_id}/close", "")

    async def get_two_way_audio_channels(self) -> list[AudioChannel]:
        payload: dict[str, Any] = json.loads(await self.request("GET", "/System/TwoWayAudio/channels?format=json"))
        raw = (payload.get("TwoWayAudioChannelList") or {}).get("TwoWayAudioChannel")
        if not raw:
            return []
        items = raw if isinstance(raw, list) else [raw]
        return [AudioChannel(id=item.get("id"), enabled=item.get("enabled")) for item in items]

    async def close_all_active_two_way_audio_channels(self) -> list[str]:
        channels = await self.get_two_way_audio_channels()
        active = [channel.id for channel in channels if channel.id and channel.enabled == "true"]
        results = await asyncio.gather(
            *(self.close_two_way_audio_channel(channel_id) for channel_id in active), return_exceptions=True
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise IsapiError(f"Failed to close {len(failures)} active audio channel(s)")
        return active

    async def get_call_status(self) -> str:
        payload: dict[str, Any] = json.loads(await self.request("GET", "/VideoIntercom/callStatus?format=json"))
        status = (payload.get("CallStatus") or {}).get("status")
        return status if isinstance(status, str) else "unknown"

    async def safe_get_call_status(self) -> str:
        try:
            return await self.get_call_status()
        except Exception:
            return "error"

    async def get_device_info(self) -> DeviceInfo:
        xml = await self.request("GET", "/System/deviceInfo")
        return DeviceInfo(
            device_name=xml_value(xml, "deviceName"),
            model=xml_value(xml, "model"),
            firmware_version=xml_value(xml, "firmwareVersion"),
        )

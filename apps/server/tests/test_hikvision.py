from collections.abc import Callable

import httpx
import pytest

from hik_server.config import Config
from hik_server.hikvision import HikvisionClient, IsapiError

CHALLENGE = 'Digest realm="DS", qop="auth", nonce="{nonce}", opaque="o"'


class DigestDevice:
    """Minimal device that requires digest auth and invalidates its nonce on demand."""

    def __init__(self) -> None:
        self.nonce = "n1"
        self.requests: list[tuple[str, str, bool]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        authorization = request.headers.get("authorization", "")
        authorized = f'nonce="{self.nonce}"' in authorization
        self.requests.append((request.method, request.url.path, authorized))
        if not authorization:
            return httpx.Response(401, headers={"WWW-Authenticate": CHALLENGE.format(nonce=self.nonce)})
        if not authorized:
            # Like the real device: an expired nonce gets a bare 401 without a new challenge.
            return httpx.Response(401)
        if request.url.path.endswith("/callStatus"):
            return httpx.Response(200, json={"CallStatus": {"status": "ring"}})
        if request.url.path.endswith("/TwoWayAudio/channels"):
            return httpx.Response(200, json={"TwoWayAudioChannelList": {"TwoWayAudioChannel": {"id": "1", "enabled": "true"}}})
        return httpx.Response(200, text="<ResponseStatus><statusCode>1</statusCode></ResponseStatus>")


async def test_recovers_from_a_stale_digest_nonce(make_config: Callable[..., Config]) -> None:
    device = DigestDevice()
    client = HikvisionClient(make_config(), transport=httpx.MockTransport(device.handler))

    assert await client.get_call_status() == "ring"
    device.nonce = "n2"
    assert await client.get_call_status() == "ring"

    assert [authorized for _, _, authorized in device.requests] == [False, True, False, False, True]
    await client.close()


async def test_wrong_password_fails_after_one_fresh_challenge(make_config: Callable[..., Config]) -> None:
    requests: list[bool] = []

    def reject_all(request: httpx.Request) -> httpx.Response:
        authorized = "authorization" in request.headers
        requests.append(authorized)
        if not authorized:
            return httpx.Response(401, headers={"WWW-Authenticate": CHALLENGE.format(nonce="n1")})
        return httpx.Response(401)

    client = HikvisionClient(make_config(), transport=httpx.MockTransport(reject_all))
    for _ in range(2):
        with pytest.raises(IsapiError, match="401"):
            await client.get_call_status()

    assert requests == [False, True, True, False, True]
    await client.close()


async def test_sends_commands_to_the_configured_paths(make_config: Callable[..., Config]) -> None:
    device = DigestDevice()
    client = HikvisionClient(make_config(HIK_DOOR_INDEX="2"), transport=httpx.MockTransport(device.handler))

    await client.open_door()
    channels = await client.get_two_way_audio_channels()

    authorized = [(method, path) for method, path, ok in device.requests if ok]
    assert authorized == [
        ("PUT", "/ISAPI/AccessControl/RemoteControl/door/2"),
        ("GET", "/ISAPI/System/TwoWayAudio/channels"),
    ]
    assert [(channel.id, channel.enabled) for channel in channels] == [("1", "true")]
    await client.close()

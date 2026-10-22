import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from hik_server.config import Config
from hik_server.doorbell import Doorbell
from hik_server.hikvision import AudioChannel

from .conftest import FakeHik


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def events() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def doorbell(make_config: Callable[..., Config], fake_hik: FakeHik, events: list[dict[str, Any]], clock: Clock) -> Doorbell:
    return Doorbell(make_config(), fake_hik, events.append, clock)  # type: ignore[arg-type]


def states(events: list[dict[str, Any]]) -> list[str]:
    return [event["payload"]["callState"] for event in events if event["type"] == "state"]


async def test_follows_the_device_from_ringing_back_to_idle(doorbell: Doorbell, fake_hik: FakeHik, events: list[dict[str, Any]]) -> None:
    fake_hik.call_status = "ring"
    await doorbell.sync_call_status()
    await doorbell.sync_call_status()
    fake_hik.call_status = "idle"
    await doorbell.sync_call_status()

    assert states(events) == ["ringing", "idle"]
    assert events[0]["payload"]["popupVisible"] is True
    assert events[0]["payload"]["source"] == "hikvision:callStatus"
    assert events[0]["payload"]["lastRingAt"] is not None


async def test_accept_answers_and_hangs_up_the_device_signal(doorbell: Doorbell, fake_hik: FakeHik) -> None:
    doorbell.manual_ring()
    assert doorbell.can_accept()
    await doorbell.accept("windows-client")

    assert fake_hik.calls == ["answer_call", "hangup_call_signal"]
    assert doorbell.state.call_state == "answered_local"
    assert doorbell.state.active_speaker == "windows-client"


async def test_local_only_strategy_does_not_touch_the_device(make_config: Callable[..., Config], fake_hik: FakeHik) -> None:
    doorbell = Doorbell(make_config(HIK_ACCEPT_STRATEGY="local_only"), fake_hik, lambda _event: None)  # type: ignore[arg-type]
    doorbell.manual_ring()
    await doorbell.accept("browser")
    assert fake_hik.calls == []
    assert doorbell.state.call_state == "answered_local"


async def test_ignores_device_idle_while_answered_locally(doorbell: Doorbell, fake_hik: FakeHik, clock: Clock) -> None:
    doorbell.manual_ring()
    await doorbell.accept("browser")

    fake_hik.call_status = "idle"
    await doorbell.sync_call_status()
    assert doorbell.state.call_state == "answered_local"

    doorbell.reset()
    assert doorbell.state.call_state == "answered_local"

    clock.now += 121
    doorbell.last_observed_call_status = "unknown"
    await doorbell.sync_call_status()
    assert doorbell.state.call_state == "idle"  # type: ignore[comparison-overlap]


async def test_reject_while_ringing_sends_reject(doorbell: Doorbell, fake_hik: FakeHik) -> None:
    doorbell.manual_ring()
    await doorbell.reject()
    assert fake_hik.calls == ["reject_call"]
    assert doorbell.state.call_state == "ended"
    assert doorbell.state.popup_visible is False


async def test_hangup_cleans_up_the_device_and_retries(doorbell: Doorbell, fake_hik: FakeHik, events: list[dict[str, Any]]) -> None:
    fake_hik.channels = [AudioChannel(id="1", enabled="true"), AudioChannel(id="2", enabled="false")]
    doorbell.manual_ring()
    await doorbell.accept("browser")
    fake_hik.calls.clear()

    await doorbell.hangup()
    assert fake_hik.calls == ["hangup_call_signal", "delete_all_rings", "close_channels"]
    assert doorbell.state.call_state == "ended"

    await asyncio.gather(*doorbell.background_tasks)
    assert fake_hik.calls[3:] == ["hangup_call_signal", "delete_all_rings", "close_channels"]
    messages = [event["payload"]["message"] for event in events if event["type"] == "log"]
    assert any("Closed active audio channels: 1" in message for message in messages)
    assert any("channels=1:true,2:false" in message for message in messages)


async def test_hangup_continues_when_device_steps_fail(doorbell: Doorbell, fake_hik: FakeHik, events: list[dict[str, Any]]) -> None:
    fake_hik.fail = {"hangup_call_signal", "delete_all_rings"}
    await doorbell.hangup()
    await asyncio.gather(*doorbell.background_tasks)

    assert doorbell.state.call_state == "ended"
    messages = [event["payload"]["message"] for event in events if event["type"] == "log"]
    assert "hangUp failed: hangup_call_signal failed" in messages
    assert any("hangUp=false, deleteRing=false" in message for message in messages)


async def test_reports_poll_failures_only_occasionally(doorbell: Doorbell, fake_hik: FakeHik, events: list[dict[str, Any]]) -> None:
    fake_hik.call_status = RuntimeError("401")
    for _ in range(20):
        await doorbell.sync_call_status()

    logs = [event["payload"]["message"] for event in events if event["type"] == "log"]
    assert logs == ["callStatus poll failed (10x): 401", "callStatus poll failed (20x): 401"]

    assert doorbell.poll_interval() == 30.0

    fake_hik.call_status = "idle"
    await doorbell.sync_call_status()
    assert doorbell.call_status_poll_failures == 0
    assert doorbell.poll_interval() == 1.0

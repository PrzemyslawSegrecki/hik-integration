import asyncio
import sys
import time
from collections.abc import Callable
from typing import Any, Literal

from .config import Config
from .hikvision import HikvisionClient
from .models import DoorbellState, LogLevel, now_iso

RINGING_STATUSES = {"ringing", "ring"}
IDLE_STATUSES = {"idle", "dismissed", "reject", "hangup"}
# While the device keeps failing (unreachable, wrong password), poll slowly: repeated
# failed logins make Hikvision devices lock out the client IP.
FAILURE_BACKOFF_AFTER = 3
FAILURE_BACKOFF_S = 30.0

Broadcast = Callable[[dict[str, Any]], None]


def print_log(level: LogLevel, message: str, at: str) -> None:
    stream = sys.stdout if level == "info" else sys.stderr
    print(f"[{at}] {message}", file=stream, flush=True)


class Doorbell:
    """Call state machine: follows the device callStatus and runs the user's actions."""

    def __init__(self, config: Config, hik: HikvisionClient, broadcast: Broadcast, clock: Callable[[], float] = time.monotonic):
        self.env = config.env
        self.hik = hik
        self.broadcast = broadcast
        self.clock = clock
        self.state = DoorbellState(stream_url=config.stream_url, ws_url="/ws")
        self.ignore_idle_until = 0.0
        self.last_observed_call_status = "unknown"
        self.call_status_poll_failures = 0
        self.background_tasks: set[asyncio.Task[None]] = set()

    def apply_state(self, **changes: Any) -> None:
        for key, value in changes.items():
            setattr(self.state, key, value)
        self.state.last_event_at = now_iso()

    def sync_state(self, source: str) -> None:
        self.state.source = source
        self.broadcast({"type": "state", "payload": self.state.to_json()})

    def log(self, level: LogLevel, message: str) -> None:
        at = now_iso()
        self.broadcast({"type": "log", "payload": {"level": level, "message": message, "at": at}})
        print_log(level, message, at)

    def end_call(self, source: str) -> None:
        self.apply_state(call_state="ended", popup_visible=False, active_speaker=None, last_action_at=now_iso())
        self.sync_state(source)

    def in_ignore_idle_window(self) -> bool:
        return self.state.call_state == "answered_local" and self.clock() < self.ignore_idle_until

    async def sync_call_status(self) -> None:
        try:
            call_status = await self.hik.get_call_status()
        except Exception as error:
            self.call_status_poll_failures += 1
            message = f"callStatus poll failed ({self.call_status_poll_failures}x): {error}"
            if self.call_status_poll_failures == 1:
                print_log("warn", message, now_iso())
            elif self.call_status_poll_failures % 10 == 0:
                self.log("warn", message)
            return

        self.call_status_poll_failures = 0
        if call_status == self.last_observed_call_status:
            return
        self.last_observed_call_status = call_status

        if call_status in RINGING_STATUSES:
            self.apply_state(call_state="ringing", popup_visible=True, last_ring_at=now_iso())
            self.sync_state("hikvision:callStatus")
            return

        if call_status in IDLE_STATUSES:
            if self.in_ignore_idle_window():
                return
            self.apply_state(call_state="idle", popup_visible=False, active_speaker=None)
            self.sync_state("hikvision:callStatus")
            return

        self.log("info", f"Observed Hikvision callStatus={call_status}")

    def poll_interval(self) -> float:
        if self.call_status_poll_failures >= FAILURE_BACKOFF_AFTER:
            return FAILURE_BACKOFF_S
        return self.env.HIK_CALLSTATUS_POLL_MS / 1000

    async def poll_forever(self) -> None:
        while True:
            started = time.monotonic()
            await self.sync_call_status()
            await asyncio.sleep(max(0.0, self.poll_interval() - (time.monotonic() - started)))

    def manual_ring(self) -> None:
        self.apply_state(call_state="ringing", popup_visible=True, last_ring_at=now_iso())
        self.sync_state("manual-ring")

    def can_accept(self) -> bool:
        return self.state.call_state == "ringing"

    async def accept(self, speaker: str) -> None:
        self.ignore_idle_until = self.clock() + self.env.HIK_IGNORE_IDLE_AFTER_ACCEPT_MS / 1000
        if self.env.HIK_ACCEPT_STRATEGY == "answer_hangup":
            await self.hik.answer_call()
            await asyncio.sleep(self.env.HIK_ACCEPT_DELAY_MS / 1000)
            await self.hik.hangup_call_signal()

        self.apply_state(call_state="answered_local", popup_visible=True, active_speaker=speaker, last_action_at=now_iso())
        self.sync_state("accept")

    async def open_door(self) -> None:
        await self.hik.open_door()
        self.apply_state(last_action_at=now_iso())
        self.sync_state("open-door")

    async def reject(self) -> None:
        self.ignore_idle_until = 0.0
        if self.state.call_state == "answered_local":
            await self.run_end_call_cleanup("reject")
        else:
            await self.hik.reject_call()
        self.end_call("reject")

    async def hangup(self) -> None:
        self.ignore_idle_until = 0.0
        await self.run_end_call_cleanup("hangup")
        self.end_call("hangup")

    def reset(self) -> None:
        if self.in_ignore_idle_window():
            return
        self.ignore_idle_until = 0.0
        self.apply_state(call_state="idle", popup_visible=False, active_speaker=None, last_action_at=now_iso())
        self.sync_state("reset")

    async def cleanup_active_audio_channels(self) -> None:
        try:
            closed = await self.hik.close_all_active_two_way_audio_channels()
            if closed:
                self.log("info", f"Closed active audio channels: {', '.join(closed)}")
        except Exception as error:
            self.log("warn", str(error) or "Failed to cleanup active audio channels")
            try:
                await self.hik.close_two_way_audio()
            except Exception:
                pass

    async def audio_channels_summary(self) -> str:
        try:
            channels = await self.hik.get_two_way_audio_channels()
        except Exception:
            return "error"
        if not channels:
            return "none"
        return ",".join(f"{channel.id or '?'}:{channel.enabled or 'unknown'}" for channel in channels)

    async def describe_device(self) -> str:
        status = await self.hik.safe_get_call_status()
        channels = await self.audio_channels_summary()
        return f"callStatus={status}, channels={channels}"

    async def run_end_call_cleanup(self, reason: Literal["reject", "hangup"]) -> None:
        self.log("info", f"End-call cleanup start ({reason}), {await self.describe_device()}")

        hangup_ok = False
        ring_delete_ok = False
        try:
            await self.hik.hangup_call_signal()
            hangup_ok = True
        except Exception as error:
            self.log("warn", f"hangUp failed: {error}")

        try:
            await self.hik.delete_all_rings()
            ring_delete_ok = True
        except Exception as error:
            self.log("warn", f"delete ring failed: {error}")

        await self.cleanup_active_audio_channels()
        self.log(
            "info",
            f"End-call cleanup done ({reason}), hangUp={str(hangup_ok).lower()}, "
            f"deleteRing={str(ring_delete_ok).lower()}, {await self.describe_device()}",
        )

        task = asyncio.create_task(self.retry_end_call_cleanup(reason))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def retry_end_call_cleanup(self, reason: Literal["reject", "hangup"]) -> None:
        await asyncio.sleep(self.env.HIK_ENDCALL_RETRY_DELAY_MS / 1000)
        self.log("info", f"End-call cleanup retry start ({reason}), {await self.describe_device()}")
        # Repeated hangUp / ring deletion may fail with invalid-state errors once the call is gone.
        for action in (self.hik.hangup_call_signal, self.hik.delete_all_rings):
            try:
                await action()
            except Exception:
                pass
        await self.cleanup_active_audio_channels()
        self.log("info", f"End-call cleanup retry done ({reason}), {await self.describe_device()}")


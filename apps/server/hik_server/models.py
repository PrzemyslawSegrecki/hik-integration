"""Wire format shared with the web UI. Mirrors apps/web/src/types.ts - keep both in sync."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

CallState = Literal["idle", "ringing", "answered_local", "ended"]
LogLevel = Literal["info", "warn", "error"]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, validate_assignment=True)

    def to_json(self) -> dict[str, object]:
        return self.model_dump(by_alias=True, exclude_none=False)


class DoorbellState(CamelModel):
    call_state: CallState = "idle"
    source: str = "bootstrap"
    last_event_at: str | None = None
    last_ring_at: str | None = None
    last_action_at: str | None = None
    active_speaker: str | None = None
    popup_visible: bool = False
    stream_url: str = ""
    ws_url: str = ""


class DiagnosticCheck(BaseModel):
    id: Literal["doorbell", "callStatus", "go2rtc", "stream", "auth"]
    ok: bool
    message: str
    hint: str | None = None

    def to_json(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)


class DiagnosticsResult(BaseModel):
    ok: bool
    checks: list[DiagnosticCheck]

    def to_json(self) -> dict[str, object]:
        return {"ok": self.ok, "checks": [check.to_json() for check in self.checks]}

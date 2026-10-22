// Wire format of the server API. Mirrored by apps/server/hik_server/models.py - keep both in sync.

export type CallState = "idle" | "ringing" | "answered_local" | "ended";

export interface DoorbellState {
  callState: CallState;
  source: string;
  lastEventAt: string | null;
  lastRingAt: string | null;
  lastActionAt: string | null;
  activeSpeaker: string | null;
  popupVisible: boolean;
  streamUrl: string;
  wsUrl: string;
}

export interface StateChangeEvent {
  type: "state";
  payload: DoorbellState;
}

export interface LogEvent {
  type: "log";
  payload: {
    level: "info" | "warn" | "error";
    message: string;
    at: string;
  };
}

export type SocketEvent = StateChangeEvent | LogEvent;

export interface DiagnosticCheck {
  id: "doorbell" | "callStatus" | "go2rtc" | "stream" | "auth";
  ok: boolean;
  message: string;
  hint?: string;
}

export interface DiagnosticsResult {
  ok: boolean;
  checks: DiagnosticCheck[];
}

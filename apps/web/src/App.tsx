import { useEffect, useMemo, useRef, useState } from "react";
import type { DiagnosticCheck, DiagnosticsResult, DoorbellState, LogEvent as LogEventMessage, SocketEvent } from "./types";
import { HoldToOpenButton } from "./HoldToOpenButton";
import { buildStreamUrl } from "./streamUrl";

type LogEvent = LogEventMessage["payload"];

type RingtoneHandle = {
  masterGain: GainNode;
  oscillators: OscillatorNode[];
  intervalId: number;
};

const fallbackState: DoorbellState = {
  callState: "idle",
  source: "bootstrap",
  lastEventAt: null,
  lastRingAt: null,
  lastActionAt: null,
  activeSpeaker: null,
  popupVisible: false,
  streamUrl: "",
  wsUrl: "/ws"
};

async function post(path: string, body?: unknown) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: body ? JSON.stringify(body) : undefined
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json().catch(() => undefined);
}

export function App() {
  const [state, setState] = useState<DoorbellState>(fallbackState);
  const [status, setStatus] = useState("Łączenie z backendem...");
  const [busy, setBusy] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [recentEvents, setRecentEvents] = useState<LogEvent[]>([]);
  const [diagnostics, setDiagnostics] = useState<DiagnosticCheck[] | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const ringtoneRef = useRef<RingtoneHandle | null>(null);
  const ringingRef = useRef(false);
  const isOverlay = new URLSearchParams(window.location.search).get("overlay") === "1";

  const stopRingtone = () => {
    const ringtone = ringtoneRef.current;
    if (!ringtone) return;

    window.clearInterval(ringtone.intervalId);
    ringtone.masterGain.gain.cancelScheduledValues(audioContextRef.current?.currentTime ?? 0);
    ringtone.masterGain.gain.value = 0.0001;
    ringtone.oscillators.forEach((oscillator) => oscillator.stop());
    ringtone.masterGain.disconnect();
    ringtoneRef.current = null;
  };

  const scheduleRingBurst = (context: AudioContext, masterGain: GainNode, startAt: number) => {
    const envelope = [
      [0, 0.0001],
      [0.02, 0.07],
      [0.22, 0.05],
      [0.34, 0.0001],
      [0.46, 0.0001],
      [0.5, 0.07],
      [0.7, 0.05],
      [0.82, 0.0001]
    ] as const;

    masterGain.gain.cancelScheduledValues(startAt);
    envelope.forEach(([offset, value]) => {
      masterGain.gain.linearRampToValueAtTime(value, startAt + offset);
    });
  };

  const startRingtone = () => {
    if (ringtoneRef.current) return;

    const AudioContextCtor = window.AudioContext ?? (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) return;

    const context = audioContextRef.current ?? new AudioContextCtor();
    audioContextRef.current = context;
    if (context.state !== "running") return;

    const masterGain = context.createGain();
    masterGain.gain.value = 0.0001;
    masterGain.connect(context.destination);

    const frequencies = [480, 620];
    const oscillators = frequencies.map((frequency) => {
      const oscillator = context.createOscillator();
      oscillator.type = "sine";
      oscillator.frequency.value = frequency;
      oscillator.connect(masterGain);
      oscillator.start();
      return oscillator;
    });

    const cycleSeconds = 2.8;
    const startCycle = () => scheduleRingBurst(context, masterGain, context.currentTime + 0.02);
    startCycle();
    const intervalId = window.setInterval(startCycle, cycleSeconds * 1000);

    ringtoneRef.current = { masterGain, oscillators, intervalId };
  };

  useEffect(() => {
    fetch("/api/state")
      .then((res) => res.json())
      .then((payload) => {
        setState(payload);
        setStatus("Gotowe");
      })
      .catch(() => setStatus("Brak połączenia z backendem"));

    const socket = new WebSocket(`${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`);
    socket.addEventListener("message", (event) => {
      const data = JSON.parse(event.data) as SocketEvent;
      if (data.type === "state") {
        setState(data.payload);
      }
      if (data.type === "log") {
        const logEvent = data.payload;
        setStatus(logEvent.message);
        setRecentEvents((prev) => [logEvent, ...prev].slice(0, 5));
      }
    });

    const unlockAudio = () => {
      const AudioContextCtor = window.AudioContext ?? (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextCtor) return;

      const context = audioContextRef.current ?? new AudioContextCtor();
      audioContextRef.current = context;
      void context.resume().then(() => {
        if (ringingRef.current) {
          startRingtone();
        }
      });
    };

    window.addEventListener("pointerdown", unlockAudio, { passive: true });
    window.addEventListener("keydown", unlockAudio);

    return () => {
      socket.close();
      window.removeEventListener("pointerdown", unlockAudio);
      window.removeEventListener("keydown", unlockAudio);
      stopRingtone();
      void audioContextRef.current?.close();
      audioContextRef.current = null;
    };
  }, []);

  const title = useMemo(() => {
    if (state.callState === "ringing") return "Ktoś dzwoni do furtki";
    if (state.callState === "answered_local") return "Rozmowa aktywna";
    if (state.callState === "ended") return "Połączenie zakończone";
    return "Wideodomofon gotowy";
  }, [state.callState]);

  const runDiagnostics = async () => {
    setDiagnostics(null);
    const response = await fetch("/api/diagnostics");
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    const payload = (await response.json()) as DiagnosticsResult;
    setDiagnostics(payload.checks);
  };

  const handle = async (label: string, fn: () => Promise<unknown>) => {
    try {
      setBusy(label);
      await fn();
    } finally {
      setBusy(null);
    }
  };

  const hidden = isOverlay && !state.popupVisible && state.callState === "idle";
  const canAccept = state.callState === "ringing";
  const canReject = state.callState === "ringing" || state.callState === "answered_local";

  const streamUrl = useMemo(() => {
    if (!state.streamUrl) return "";
    return buildStreamUrl(state.streamUrl, state.callState, window.location.origin);
  }, [state.streamUrl, state.callState]);

  const isActiveCall = state.callState === "answered_local";
  const isRinging = state.callState === "ringing";

  useEffect(() => {
    ringingRef.current = isRinging;
    if (isRinging) {
      startRingtone();
    } else {
      stopRingtone();
    }
  }, [isRinging]);
  const headerColor = isActiveCall ? "text-accept" : isRinging ? "text-yellow-400" : "text-white";
  const headerShadow = isActiveCall ? "drop-shadow-[0_0_10px_rgba(0,255,102,0.5)]" : isRinging ? "drop-shadow-[0_0_20px_rgba(255,196,71,0.8)]" : "";

  return (
    <main className={`relative w-full h-full flex flex-col justify-between ${hidden ? "hidden" : ""}`}>
      {/* Fullscreen Video Background */}
      <div className="absolute inset-0 -z-10 overflow-hidden">
        {streamUrl ? (
          <iframe
            title="Doorbell stream"
            src={streamUrl}
            allow="camera; microphone; fullscreen; autoplay"
            className="w-full h-full border-0 object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-gray-900 text-gray-400 text-center p-8">
            Brak streamu wideo. Skonfiguruj GO2RTC_PUBLIC_URL.
          </div>
        )}
      </div>

      {/* Ringing Border Effect */}
      {isRinging && (
        <div className="ring-frame z-0">
          <div className="ring-frame-sweep" />
        </div>
      )}

      {/* Header */}
      <header className="p-6 md:p-8 flex justify-between items-start z-10">
        <div className="flex gap-3 items-center">
          {isActiveCall && <span className="w-2 h-2 rounded-full bg-accept animate-pulse" />}
          {isRinging && <span className="w-3 h-3 rounded-full bg-yellow-400 animate-ping" />}
          <h1 className={`font-display font-bold text-2xl md:text-3xl lg:text-4xl uppercase tracking-widest ${headerColor} ${headerShadow} ${isRinging ? "animate-pulse" : ""}`}>
            {title}
          </h1>
        </div>

        {/* Menu Button */}
        <button
          aria-label="Menu"
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="flex shrink-0 items-center justify-center rounded-full w-20 h-20 md:w-24 md:h-24 bg-white/10 hover:bg-white/20 transition-colors border border-white/10 text-white focus:outline-none focus:ring-2 focus:ring-white/50"
        >
          <span className="material-symbols-outlined text-4xl md:text-5xl">
            {sidebarOpen ? "close" : "menu"}
          </span>
        </button>
      </header>

      {/* Sidebar */}
      <aside
        className={`fixed top-0 right-0 h-full w-full md:w-96 glass-panel z-50 transform transition-transform duration-300 ${
          sidebarOpen ? "translate-x-0" : "translate-x-full"
        } overflow-y-auto`}
      >
        <div className="p-6 md:p-8">
          <div className="flex justify-between items-center mb-8">
            <h2 className="font-display text-2xl font-bold">Menu</h2>
            <button
              onClick={() => setSidebarOpen(false)}
              className="p-2 rounded-full hover:bg-white/10 transition-colors"
              aria-label="Zamknij menu"
            >
              <span className="material-symbols-outlined text-3xl">close</span>
            </button>
          </div>

          {/* Status Section */}
          <section className="mb-8">
            <h3 className="font-display text-lg font-semibold mb-3 text-primary">Status</h3>
            <div className="bg-white/5 rounded-lg p-4 border border-white/10">
              <div className="flex items-center gap-2 mb-2">
                <span className={`w-3 h-3 rounded-full ${state.callState === "idle" ? "bg-gray-500" : state.callState === "ringing" ? "bg-yellow-400" : state.callState === "answered_local" ? "bg-accept" : "bg-red-500"}`} />
                <span className="font-semibold capitalize">{state.callState.replace("_", " ")}</span>
              </div>
              <p className="text-sm text-gray-300">{status}</p>
            </div>
          </section>

          {/* Recent Events Section */}
          <section className="mb-8">
            <h3 className="font-display text-lg font-semibold mb-3 text-primary">Ostatnie zdarzenia</h3>
            <div className="space-y-2">
              {recentEvents.length === 0 ? (
                <div className="bg-white/5 rounded-lg p-4 border border-white/10 text-sm text-gray-400">
                  Brak zdarzeń
                </div>
              ) : (
                recentEvents.map((event, index) => (
                  <div key={`${event.at}-${index}`} className="bg-white/5 rounded-lg p-3 border border-white/10">
                    <div className="flex items-start gap-2">
                      <span className={`material-symbols-outlined text-sm ${event.level === "error" ? "text-reject" : event.level === "warn" ? "text-yellow-400" : "text-primary"}`}>
                        {event.level === "error" ? "error" : event.level === "warn" ? "warning" : "info"}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-gray-400 mb-1">{new Date(event.at).toLocaleTimeString("pl-PL")}</p>
                        <p className="text-sm break-words">{event.message}</p>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>

          {/* Source Section */}
          <section className="mb-8">
            <h3 className="font-display text-lg font-semibold mb-3 text-primary">Źródło</h3>
            <div className="bg-white/5 rounded-lg p-4 border border-white/10">
              <p className="text-sm font-mono">{state.source}</p>
              {state.lastRingAt && (
                <p className="text-xs text-gray-400 mt-2">
                  Ostatni dzwonek: {new Date(state.lastRingAt).toLocaleString("pl-PL")}
                </p>
              )}
              {state.lastActionAt && (
                <p className="text-xs text-gray-400 mt-1">
                  Ostatnia akcja: {new Date(state.lastActionAt).toLocaleString("pl-PL")}
                </p>
              )}
            </div>
          </section>

          {/* Debug Actions */}
          <section>
            <h3 className="font-display text-lg font-semibold mb-3 text-primary">Debugowanie</h3>
            <div className="flex flex-col gap-2">
              <button
                onClick={() => handle("diagnostics", runDiagnostics)}
                disabled={busy !== null}
                className="w-full py-2 px-4 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-colors text-sm disabled:opacity-50"
              >
                {busy === "diagnostics" ? "Sprawdzanie..." : "Test połączenia"}
              </button>
              {diagnostics && (
                <ul className="space-y-2 mb-2">
                  {diagnostics.map((check) => (
                    <li key={check.id} className="bg-white/5 rounded-lg p-3 border border-white/10 flex items-start gap-2">
                      <span className={`material-symbols-outlined text-sm ${check.ok ? "text-accept" : "text-reject"}`}>
                        {check.ok ? "check_circle" : "error"}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm break-words">{check.message}</p>
                        {check.hint && <p className="text-xs text-gray-400 mt-1 break-words">{check.hint}</p>}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              <button
                onClick={() => handle("ring", () => post("/api/events/ring"))}
                disabled={busy !== null}
                className="w-full py-2 px-4 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-colors text-sm disabled:opacity-50"
              >
                Symuluj dzwonek
              </button>
              <button
                onClick={() => handle("reset", () => post("/api/actions/reset"))}
                disabled={busy !== null}
                className="w-full py-2 px-4 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-colors text-sm disabled:opacity-50"
              >
                Resetuj stan
              </button>
            </div>
          </section>
        </div>
      </aside>

      {/* Bottom Action Bar */}
      <footer className="w-full p-6 md:p-8 pb-8 md:pb-12 flex justify-center items-end z-10">
        <div className="flex items-center gap-4 md:gap-6 glass-panel px-4 md:px-5 py-4 md:py-5 rounded-full shadow-2xl">
          {/* Accept Button */}
          <button
            aria-label="Odbierz rozmowę"
            onClick={() => handle("accept", () => post("/api/actions/accept", { speaker: isOverlay ? "home-assistant" : "windows-client" }))}
            disabled={busy !== null || !canAccept}
            className="flex shrink-0 items-center justify-center rounded-full w-20 h-20 md:w-24 md:h-24 bg-answer hover:bg-answer/80 hover:shadow-neon-answer transition-all text-white border border-transparent focus:outline-none focus:ring-2 focus:ring-answer/50 disabled:opacity-40 disabled:cursor-not-allowed disabled:grayscale"
          >
            <span className="material-symbols-outlined text-4xl md:text-5xl">call</span>
          </button>

          {/* Reject Button */}
          <button
            aria-label="Odrzuć / Zakończ rozmowę"
            onClick={() => handle("reject", () => post("/api/actions/reject"))}
            disabled={busy !== null || !canReject}
            className="flex shrink-0 items-center justify-center rounded-full w-20 h-20 md:w-24 md:h-24 bg-reject hover:bg-reject/80 hover:shadow-neon-reject transition-all text-white border border-transparent focus:outline-none focus:ring-2 focus:ring-reject/50 disabled:opacity-40 disabled:cursor-not-allowed disabled:grayscale"
          >
            <span className="material-symbols-outlined text-4xl md:text-5xl">call_end</span>
          </button>

          {/* Open Gate Button */}
          <HoldToOpenButton disabled={busy !== null} onOpen={() => void handle("open", () => post("/api/actions/open-door"))} />
        </div>
      </footer>
    </main>
  );
}

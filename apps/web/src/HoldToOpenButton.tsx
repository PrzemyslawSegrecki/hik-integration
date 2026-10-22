import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import { GATE_HOLD_MS, createHoldGesture } from "./holdGesture";

const RING_RADIUS = 46;
const RING_LENGTH = 2 * Math.PI * RING_RADIUS;
const HINT_MS = 1800;

type Props = {
  disabled: boolean;
  onOpen: () => void;
};

// Opening the gate needs a ~1 s press, so a stray tap on a touch screen cannot open it.
export function HoldToOpenButton({ disabled, onOpen }: Props) {
  const [holding, setHolding] = useState(false);
  const [hint, setHint] = useState(false);
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;

  const gestureRef = useRef(
    createHoldGesture(GATE_HOLD_MS, () => {
      setHolding(false);
      onOpenRef.current();
    })
  );
  const hintTimerRef = useRef<number | undefined>(undefined);

  useEffect(
    () => () => {
      gestureRef.current.cancel();
      window.clearTimeout(hintTimerRef.current);
    },
    []
  );

  useEffect(() => {
    if (disabled) {
      gestureRef.current.cancel();
      setHolding(false);
    }
  }, [disabled]);

  const start = () => {
    if (disabled || !gestureRef.current.start()) return;
    setHint(false);
    setHolding(true);
  };

  const release = () => {
    if (!gestureRef.current.cancel()) return;
    setHolding(false);
    setHint(true);
    window.clearTimeout(hintTimerRef.current);
    hintTimerRef.current = window.setTimeout(() => setHint(false), HINT_MS);
  };

  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    start();
  };

  const isActivationKey = (event: KeyboardEvent) => event.key === "Enter" || event.key === " ";

  return (
    <div className="relative">
      <span
        role="status"
        className={`pointer-events-none absolute -top-12 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-black/80 px-3 py-1 text-sm text-white transition-opacity duration-200 ${
          hint ? "opacity-100" : "opacity-0"
        }`}
      >
        Przytrzymaj, aby otworzyć
      </span>

      <button
        type="button"
        aria-label="Otwórz bramę (przytrzymaj)"
        title="Przytrzymaj, aby otworzyć"
        disabled={disabled}
        onPointerDown={onPointerDown}
        onPointerUp={release}
        onPointerCancel={release}
        onLostPointerCapture={release}
        onKeyDown={(event) => {
          if (!isActivationKey(event) || event.repeat) return;
          event.preventDefault();
          start();
        }}
        onKeyUp={(event) => {
          if (isActivationKey(event)) release();
        }}
        onBlur={release}
        onContextMenu={(event) => event.preventDefault()}
        className={`relative flex touch-none select-none items-center justify-center rounded-full w-20 h-20 md:w-24 md:h-24 bg-primary text-background-dark font-display font-bold hover:bg-white hover:text-black hover:shadow-neon-primary transition-all duration-300 focus:outline-none focus:ring-4 focus:ring-primary/50 disabled:opacity-40 disabled:cursor-not-allowed [-webkit-touch-callout:none] ${
          holding ? "scale-95 shadow-neon-primary" : ""
        }`}
      >
        <svg className="pointer-events-none absolute inset-0 h-full w-full -rotate-90" viewBox="0 0 100 100" aria-hidden="true">
          <circle
            cx="50"
            cy="50"
            r={RING_RADIUS}
            fill="none"
            stroke="currentColor"
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={RING_LENGTH}
            strokeDashoffset={holding ? 0 : RING_LENGTH}
            style={{
              transition: `stroke-dashoffset ${holding ? GATE_HOLD_MS : 150}ms linear`
            }}
          />
        </svg>
        <span className="material-symbols-outlined relative text-4xl md:text-5xl">key</span>
      </button>
    </div>
  );
}

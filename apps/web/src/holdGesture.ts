export const GATE_HOLD_MS = 1000;

export interface HoldGesture {
  /** Starts the countdown; returns false if one is already running. */
  start(): boolean;
  /** Stops the countdown; returns true if it was released before completing. */
  cancel(): boolean;
}

export function createHoldGesture(durationMs: number, onComplete: () => void): HoldGesture {
  let timer: ReturnType<typeof setTimeout> | null = null;

  return {
    start() {
      if (timer !== null) return false;
      timer = setTimeout(() => {
        timer = null;
        onComplete();
      }, durationMs);
      return true;
    },
    cancel() {
      if (timer === null) return false;
      clearTimeout(timer);
      timer = null;
      return true;
    }
  };
}

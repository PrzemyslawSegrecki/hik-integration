import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createHoldGesture } from "./holdGesture";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

test("fires only after being held for the full duration", () => {
  const onComplete = vi.fn();
  const gesture = createHoldGesture(1000, onComplete);

  gesture.start();
  vi.advanceTimersByTime(999);
  expect(onComplete).not.toHaveBeenCalled();
  vi.advanceTimersByTime(1);
  expect(onComplete).toHaveBeenCalledOnce();
  expect(gesture.cancel()).toBe(false);
});

test("releasing early cancels and reports it", () => {
  const onComplete = vi.fn();
  const gesture = createHoldGesture(1000, onComplete);

  gesture.start();
  vi.advanceTimersByTime(500);
  expect(gesture.cancel()).toBe(true);
  vi.advanceTimersByTime(1000);
  expect(onComplete).not.toHaveBeenCalled();
});

test("a second start while holding does not restart the countdown", () => {
  const onComplete = vi.fn();
  const gesture = createHoldGesture(1000, onComplete);

  expect(gesture.start()).toBe(true);
  vi.advanceTimersByTime(600);
  expect(gesture.start()).toBe(false);
  vi.advanceTimersByTime(400);
  expect(onComplete).toHaveBeenCalledOnce();
});

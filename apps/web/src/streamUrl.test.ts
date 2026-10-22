import { expect, test } from "vitest";
import { buildStreamUrl } from "./streamUrl";

test("uses video-only preview after the call ends", () => {
  const result = buildStreamUrl("/rtc-player.html?src=doorbell", "ended");
  const url = new URL(result, "http://localhost");

  expect(url.searchParams.get("media")).toBe("video");
  expect(url.searchParams.get("session")).toBe("passive");
});

test("keeps preview muted before pickup while the bell is ringing", () => {
  const result = buildStreamUrl("/rtc-player.html?src=doorbell", "ringing");
  const url = new URL(result, "http://localhost");

  expect(url.searchParams.get("media")).toBe("video");
  expect(url.searchParams.get("session")).toBe("passive");
});

test("keeps two-way media during active local talk", () => {
  const result = buildStreamUrl("/rtc-player.html?src=doorbell", "answered_local");
  const url = new URL(result, "http://localhost");

  expect(url.searchParams.get("media")).toBe("video+audio+microphone");
  expect(url.searchParams.get("session")).toBe("talk");
});

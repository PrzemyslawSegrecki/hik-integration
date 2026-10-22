import type { CallState } from "./types";

export function buildStreamUrl(rawStreamUrl: string, callState: CallState, origin = "http://localhost") {
  const url = new URL(rawStreamUrl, origin);

  if (callState === "answered_local") {
    url.searchParams.set("media", "video+audio+microphone");
    url.searchParams.set("session", "talk");
  } else {
    url.searchParams.set("media", "video");
    url.searchParams.set("session", "passive");
  }

  url.searchParams.set("autostart", "1");
  return `${url.pathname}${url.search}`;
}

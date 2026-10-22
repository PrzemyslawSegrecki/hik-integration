# Hik Doorbell

**English** · [Polski](README.pl.md)

A local web UI for Hikvision video intercoms (tested on the `DS-KV8113-WME1(C)`): answer calls,
talk two-way and open the gate from a browser, a Windows PC or Home Assistant.
No cloud - the server talks to the doorbell directly over ISAPI on your network.

Your phone can keep receiving calls through the Hik-Connect app; this project runs alongside it.

> Unofficial project, not affiliated with or endorsed by Hikvision. It can open a door or gate:
> read [Security](#security) before exposing it beyond your LAN, and use it at your own risk.

## Features

- **Ring popup** - full-screen camera view and a ring sound
- **Answer / Reject / Hang up** - two-way audio over WebRTC (go2rtc)
- **Open the gate** - hold the button to open
- **Windows client** - tray app with autostart and a full-screen popup on ring
- **Home Assistant** - call-state sensor, gate button, optional popup on dashboards
- **Connection test** - checks the doorbell, go2rtc and the stream and tells you what to fix
- Works offline (the UI has no CDN dependencies)

## Requirements

- A Hikvision intercom with ISAPI enabled and an admin account, reachable from the server
- A machine with Docker (home server, NAS, Raspberry Pi, Home Assistant host...)
- [go2rtc](https://github.com/AlexxIT/go2rtc) for video and audio - use an existing one or run the bundled one

## Quick start

```bash
git clone https://github.com/PrzemyslawSegrecki/hik-integration.git hik-doorbell
cd hik-doorbell
cp .env.example .env
```

Edit `.env`. Only these are required:

| Variable | Description |
|---|---|
| `HIK_IP`, `HIK_USERNAME`, `HIK_PASSWORD` | address and admin account of the doorbell |
| `APP_PASSWORD` and/or `APP_TOKEN` | access to the app (see [Security](#security)) |
| `GO2RTC_URL` | go2rtc address as seen from the server - without it there is no video or talk |

All variables are described in [.env.example](.env.example).

**You already run go2rtc** (e.g. as a Home Assistant add-on): set `GO2RTC_URL` and `GO2RTC_STREAM_NAME`, then

```bash
docker compose up -d
```

**You don't have go2rtc**: set `GO2RTC_URL=http://go2rtc:1984` and `DOCKER_HOST_IP` (the LAN IP of this machine).
The doorbell stream is already defined in [go2rtc.yaml](go2rtc.yaml):

```bash
docker compose --profile go2rtc up -d
```

Open `http://<server>:8090`, log in (`APP_USERNAME` / `APP_PASSWORD`) and click
**Menu → Debug → Connection test**.

> A doorbell password with special characters may need URL-encoding in go2rtc (`%40` instead of `@`, etc.).

### Prebuilt image instead of building

GitHub Actions publishes a multi-arch image (`amd64`, `arm64`) to GHCR. In `.env`:

```bash
HIK_DOORBELL_IMAGE=ghcr.io/przemyslawsegrecki/hik-integration:latest
```

then `docker compose pull && docker compose up -d`.

### Updating

```bash
git pull
docker compose up -d --build
```

## Windows client

Download the installer from **Releases**. On first start enter the server address and `APP_TOKEN`.
Details: [apps/windows/README.md](apps/windows/README.md) (Polish).

## Home Assistant

Call-state sensor, gate button and dashboard popup, with no extra integration:
[docs/home-assistant.md](docs/home-assistant.md) (Polish).

## Security

The app can open a gate, so **every request except `GET /api/health` requires authentication**:

- `APP_PASSWORD` - browser login (HTTP Basic, user `APP_USERNAME`)
- `APP_TOKEN` - for the Windows client, Home Assistant and other devices:
  `Authorization: Bearer <token>` header or `?token=<token>` in the URL (remembered in a cookie)

`TRUST_LOCAL_NETWORK=true` lets devices on the local network (private IPs) in without logging in.
Requests that arrive through a proxy or tunnel (e.g. Cloudflare - `CF-Connecting-IP`, `X-Forwarded-For`
headers) still need the token or password, so this is safe behind a Cloudflare Tunnel as well.
Do not use it if you forward a router port straight to the app without a proxy.

The server refuses to start without any of these settings. `AUTH_DISABLED=true` turns authentication off
completely - only for a trusted network with no internet access.

The browser never talks to go2rtc directly: signalling goes through `/go2rtc` on this server, so the
go2rtc password stays on the server and go2rtc itself does not have to be exposed.

When exposing the app to the internet use HTTPS (Cloudflare Tunnel or a reverse proxy with a certificate);
browsers require it for the microphone anyway. Clients other than browsers behind Cloudflare must send a `User-Agent`.

Found a vulnerability? See [SECURITY.md](SECURITY.md).

## Troubleshooting

Start with **Connection test** in the UI, or the logs: `docker compose logs hik-doorbell` (`[check]` lines).

| Symptom | Check |
|---|---|
| Server exits with `Invalid configuration` | missing variables are listed in the log |
| `Cannot reach ISAPI` | `HIK_IP`; can the server reach the doorbell on port 80 |
| `401` from the doorbell | `HIK_USERNAME` / `HIK_PASSWORD`. Several failed logins lock your IP out for ~30 min |
| No video | `GO2RTC_URL`, `GO2RTC_STREAM_NAME`; does the stream play in the go2rtc panel |
| Video but no microphone | HTTPS; microphone permission in the browser / Windows |
| Works on LAN, not from outside | WebRTC needs go2rtc port `8555` (or STUN/TURN) reachable |
| Popup does not close after a call | see [How it works](#how-it-works); tune the `HIK_*_MS` variables |

## How it works

```
doorbell ──ISAPI──▶ backend (Docker) ──WebSocket──▶ browser / Windows client / HA
   │                    │
   └──RTSP/ISAPI──▶ go2rtc ◀──/go2rtc proxy── WebRTC in the browser
```

- The backend polls the doorbell's `callStatus` every second and broadcasts the state
  (`idle`, `ringing`, `answered_local`, `ended`).
- **Answer** - while ringing the backend runs `answer → delay → hangUp`
  (`HIK_ACCEPT_STRATEGY=answer_hangup`, `HIK_ACCEPT_DELAY_MS`) to free the doorbell's audio channel,
  then the WebRTC call starts through go2rtc.
- **Reject** - `callSignal reject` while ringing; during a call the same as Hang up.
- **Hang up** - `hangUp`, `DELETE /VideoIntercom/ring`, closing active `TwoWayAudio` channels, repeated after
  `HIK_ENDCALL_RETRY_DELAY_MS` because the panel can report state late.
- **Open gate** - `PUT /ISAPI/AccessControl/RemoteControl/door/<HIK_DOOR_INDEX>`.

More detail (call states, authentication, the doorbell's digest-auth quirks, go2rtc): [docs/architektura.md](docs/architektura.md) (Polish).
ISAPI notes: [docs/hikvision-video-intercom-isapi-developer-guide.txt](docs/hikvision-video-intercom-isapi-developer-guide.txt).

## API

Everything except `/api/health` requires authentication.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | public health check |
| `GET` | `/api/state` | current state |
| `GET` | `/api/diagnostics` | doorbell and go2rtc connection test |
| `POST` | `/api/events/ring` | test ring |
| `POST` | `/api/actions/accept` | answer |
| `POST` | `/api/actions/reject` | reject |
| `POST` | `/api/actions/hangup` | hang up |
| `POST` | `/api/actions/open-door` | open the gate |
| `POST` | `/api/actions/reset` | reset state |
| `WS` | `/ws` | `state` and `log` events |
| * | `/go2rtc/*` | go2rtc proxy (HTTP and WebSocket) |

## Development

Needs Node.js 22+ and [uv](https://docs.astral.sh/uv/) (Python 3.12+ for the backend).

```bash
npm ci
uv sync --directory apps/server
npm run dev        # frontend http://localhost:5173 (proxies to the backend), backend http://localhost:8090
npm test           # vitest + pytest
npm run typecheck  # tsc + mypy
```

Layout: `apps/server` (FastAPI backend), `apps/web` (React, Vite, Tailwind), `apps/windows` (Tauri client),
`docs` (architecture, Home Assistant, ISAPI notes). See [CONTRIBUTING.md](CONTRIBUTING.md).

Known limitations: reliability of ending a call and of audio depends on the doorbell's firmware; mostly tested
on the `DS-KV8113-WME1(C)` (firmware V2.2.78). Reports from other models are welcome - please include model and firmware.

## License

[MIT](LICENSE)

# AGENTS.md

Guidelines for AI coding agents working on this repository. Code, comments and commits are in English.

## Project

Local web UI for Hikvision video intercoms (tested on `DS-KV8113-WME1(C)`): ring popup, answer / reject /
hang up, two-way audio through go2rtc (WebRTC), gate opening. See [README.md](README.md).

- `apps/server` - Python 3.12+ (FastAPI, uvicorn, httpx with digest auth, managed by `uv`). Package `hik_server/`:
  `app.py` (routes, WebSocket), `doorbell.py` (call state machine), `hikvision.py` (ISAPI), `auth.py`,
  `config.py` (`.env`), `go2rtc_proxy.py`, `diagnostics.py`.
- `apps/web` - React + Vite + Tailwind 3, no CDN (the UI must work offline). The API format lives in
  `apps/web/src/types.ts` and `apps/server/hik_server/models.py` - change both together.
- `apps/windows` - Tauri 1.x (Rust) tray client. Built by CI or `apps/windows/build.bat` on Windows.
- `docs/` - architecture, Home Assistant, ISAPI notes.

## Commands

```bash
npm ci
uv sync --directory apps/server
npm run dev          # web :5173, server :8090 (needs .env in the repo root)
npm test             # vitest + pytest
npm run typecheck    # tsc + mypy (strict)
npm run build
```

Before committing: `npm run typecheck && npm test && npm run build`.

## Secrets and configuration

- All configuration is in `.env` (see `.env.example`). `.env` is git-ignored: never commit it and never print
  its values in answers or logs.
- Never put passwords, tokens, or URLs with credentials in code, docs or examples. Use placeholders
  and documentation address ranges (`192.168.1.x`).
- Do not enable `proxy_headers` in uvicorn: "local network" detection relies on the absence of proxy headers.
- The doorbell locks out a client IP after several failed logins (~30 min). Never poll it in a loop on auth errors.
- Changes to call handling need testing on a real doorbell; say so in the PR if you could not.

## Working rules

- Match the surrounding style (typed Python for `mypy --strict`, TypeScript `strict`, few comments).
- New server logic gets a test in `apps/server/tests/test_*.py`.
- No CDN dependencies in the UI.
- Commit messages: imperative mood, English.

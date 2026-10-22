# Hik Doorbell

[English](README.md) · **Polski**

Lokalny interfejs dla wideodomofonów Hikvision (testowane na `DS-KV8113-WME1(C)`):
odbieranie rozmów, rozmowa dwukierunkowa i otwieranie furtki z przeglądarki, z komputera z Windows
i z Home Assistant. Bez chmury - serwer rozmawia z domofonem bezpośrednio przez ISAPI w Twojej sieci.

Telefon dalej może odbierać przez aplikację Hik-Connect; ten projekt działa obok niej.

## Funkcje

- **Popup przy dzwonku** - pełnoekranowy obraz z kamery i sygnał dzwonka
- **Odbierz / Odrzuć / Zakończ** - rozmowa dwukierunkowa przez WebRTC (go2rtc)
- **Otwórz furtkę** - jednym przyciskiem
- **Klient Windows** - działa w zasobniku, autostart, okno na pełnym ekranie przy dzwonku
- **Home Assistant** - sensor stanu rozmowy, przycisk furtki, opcjonalny popup na dashboardach
- **Test połączenia** - sprawdza domofon, go2rtc i strumień, podpowiada, co poprawić

## Wymagania

- domofon Hikvision z ISAPI (konto admina) w sieci lokalnej
- komputer z Dockerem (np. serwer domowy, NAS, Raspberry Pi, host Home Assistant)
- [go2rtc](https://github.com/AlexxIT/go2rtc) dla obrazu i dźwięku - możesz użyć istniejącego
  albo uruchomić go razem z aplikacją

## Szybki start

```bash
git clone https://github.com/PrzemyslawSegrecki/hik-integration.git hik-doorbell
cd hik-doorbell
cp .env.example .env
```

Uzupełnij `.env` - wymagane są tylko:

| Zmienna | Opis |
|---|---|
| `HIK_IP`, `HIK_USERNAME`, `HIK_PASSWORD` | adres i konto admina domofonu |
| `APP_PASSWORD` i/lub `APP_TOKEN` | dostęp do aplikacji (zobacz [Bezpieczeństwo](#bezpieczeństwo)) |
| `GO2RTC_URL` | adres go2rtc widziany z serwera - bez niego nie ma obrazu i rozmowy |

Opis wszystkich zmiennych jest w [.env.example](.env.example).

**Masz już go2rtc** (np. w Home Assistant) - ustaw `GO2RTC_URL` i `GO2RTC_STREAM_NAME`, potem:

```bash
docker compose up -d
```

**Nie masz go2rtc** - ustaw `GO2RTC_URL=http://go2rtc:1984` i `DOCKER_HOST_IP` (adres IP tego komputera w LAN).
Strumień domofonu jest już opisany w [go2rtc.yaml](go2rtc.yaml):

```bash
docker compose --profile go2rtc up -d
```

Otwórz `http://<serwer>:8090`, zaloguj się (`APP_USERNAME` / `APP_PASSWORD`)
i w **Menu → Debugowanie** kliknij **Test połączenia**.

> Hasło domofonu ze znakami specjalnymi może wymagać zakodowania w go2rtc (`%40` zamiast `@` itd.).

### Gotowy obraz zamiast budowania

GitHub Actions publikuje obraz dla `amd64` i `arm64` w GHCR. Ustaw w `.env`:

```bash
HIK_DOORBELL_IMAGE=ghcr.io/przemyslawsegrecki/hik-integration:latest
```

i uruchom `docker compose pull && docker compose up -d`.

### Aktualizacja

```bash
git pull
docker compose up -d --build
```

## Klient Windows

Pobierz instalator z zakładki **Releases**. Przy pierwszym uruchomieniu podaj adres serwera i `APP_TOKEN`.
Szczegóły: [apps/windows/README.md](apps/windows/README.md).

## Home Assistant

Sensor stanu rozmowy, przycisk furtki i popup na dashboardach - bez dodatkowych integracji:
[docs/home-assistant.md](docs/home-assistant.md).

## Bezpieczeństwo

Aplikacja może otworzyć furtkę, dlatego **każde zapytanie poza `GET /api/health` wymaga logowania**:

- `APP_PASSWORD` - logowanie w przeglądarce (HTTP Basic, użytkownik `APP_USERNAME`)
- `APP_TOKEN` - dla klienta Windows, Home Assistant i innych urządzeń: nagłówek
  `Authorization: Bearer <token>` albo `?token=<token>` w adresie (zapamiętywany w ciasteczku)

`TRUST_LOCAL_NETWORK=true` - urządzenia z sieci lokalnej (prywatne adresy IP) nie muszą się logować.
Zapytania przez proxy lub tunel (np. Cloudflare - nagłówki `CF-Connecting-IP`, `X-Forwarded-For`) dalej
wymagają tokenu lub hasła, więc to ustawienie jest bezpieczne także przy wystawieniu aplikacji do internetu
przez Cloudflare Tunnel. Nie używaj go, jeśli przekierowujesz port na routerze bez proxy.

Bez żadnej z tych zmiennych serwer nie wystartuje. `AUTH_DISABLED=true` wyłącza logowanie całkowicie -
tylko dla zaufanej sieci bez dostępu z internetu.

Przeglądarka nigdy nie łączy się z go2rtc bezpośrednio: sygnalizacja idzie przez `/go2rtc` na tym serwerze,
więc hasło do go2rtc zostaje na serwerze, a samego API go2rtc nie trzeba wystawiać do internetu.

Wystawiając aplikację do internetu używaj HTTPS (np. Cloudflare Tunnel albo reverse proxy z certyfikatem).
Mikrofon w przeglądarce i tak wymaga HTTPS (poza `localhost`).

## Rozwiązywanie problemów

Zacznij od **Test połączenia** w UI albo logów: `docker compose logs hik-doorbell` (linie `[check]`).

| Objaw | Co sprawdzić |
|---|---|
| Serwer nie startuje, `Invalid configuration` | brakujące zmienne są wypisane w logu |
| `Cannot reach ISAPI` | `HIK_IP`, czy serwer widzi domofon na porcie 80 |
| `401` od domofonu | `HIK_USERNAME` / `HIK_PASSWORD` |
| Brak obrazu | `GO2RTC_URL`, `GO2RTC_STREAM_NAME`; czy strumień działa w panelu go2rtc |
| Obraz jest, mikrofon nie działa | HTTPS; uprawnienia mikrofonu w przeglądarce / Windows |
| Obraz działa w LAN, nie działa z zewnątrz | WebRTC potrzebuje dostępu do portu `8555` go2rtc lub serwera STUN/TURN |
| Popup nie znika po rozmowie | zobacz [Jak to działa](#jak-to-działa) - opóźnienia ustawisz zmiennymi `HIK_*_MS` |

## Jak to działa

```
domofon ──ISAPI──▶ backend (Docker) ──WebSocket──▶ przeglądarka / klient Windows / HA
   │                    │
   └──RTSP/ISAPI──▶ go2rtc ◀──/go2rtc proxy── WebRTC w przeglądarce
```

- Backend co sekundę odpytuje `callStatus` domofonu i rozsyła stan (`idle`, `ringing`, `answered_local`, `ended`).
- **Odbierz** - gdy domofon dzwoni, backend wykonuje `answer → opóźnienie → hangUp`
  (`HIK_ACCEPT_STRATEGY=answer_hangup`, `HIK_ACCEPT_DELAY_MS`), żeby zwolnić kanał audio,
  i uruchamia rozmowę WebRTC przez go2rtc.
- **Odrzuć** - podczas dzwonienia `callSignal reject`; w trakcie rozmowy to samo co Zakończ.
- **Zakończ** - `hangUp`, `DELETE /VideoIntercom/ring`, zamknięcie aktywnych kanałów `TwoWayAudio`,
  powtórzone po `HIK_ENDCALL_RETRY_DELAY_MS`, bo panel potrafi zgłaszać stan z opóźnieniem.
  Backend loguje `callStatus` i kanały audio przed i po.
- **Otwórz furtkę** - `PUT /ISAPI/AccessControl/RemoteControl/door/<HIK_DOOR_INDEX>`.

Szczegóły (stany rozmowy, logowanie, pułapki digest auth domofonu, go2rtc): [docs/architektura.md](docs/architektura.md).
Notatki z dokumentacji ISAPI: [docs/hikvision-video-intercom-isapi-developer-guide.txt](docs/hikvision-video-intercom-isapi-developer-guide.txt).

## API

Wszystkie poza `/api/health` wymagają logowania.

| Metoda | Ścieżka | Opis |
|---|---|---|
| `GET` | `/api/health` | publiczny health check |
| `GET` | `/api/state` | aktualny stan |
| `GET` | `/api/diagnostics` | test połączenia z domofonem i go2rtc |
| `POST` | `/api/events/ring` | testowy dzwonek |
| `POST` | `/api/actions/accept` | odbierz |
| `POST` | `/api/actions/reject` | odrzuć |
| `POST` | `/api/actions/hangup` | zakończ |
| `POST` | `/api/actions/open-door` | otwórz furtkę |
| `POST` | `/api/actions/reset` | wyzeruj stan |
| `WS` | `/ws` | zdarzenia `state` i `log` |
| * | `/go2rtc/*` | proxy do go2rtc (HTTP i WebSocket) |

## Rozwój

Wymagane: Node.js 22+ i [uv](https://docs.astral.sh/uv/) (Python 3.12+ dla backendu).

```bash
npm install
uv sync --directory apps/server
npm run dev        # frontend http://localhost:5173 (proxy do backendu), backend http://localhost:8090
npm test           # testy (vitest + pytest)
npm run typecheck  # tsc + mypy
```

Struktura:

- `apps/server` - backend w Pythonie: FastAPI, WebSocket, ISAPI, proxy go2rtc
- `apps/web` - interfejs (React, Vite, Tailwind)
- `apps/windows` - klient Windows (Tauri)
- `docs` - [architektura](docs/architektura.md), Home Assistant, notatki ISAPI

Znane ograniczenia: stabilność kończenia rozmowy i audio zależy od firmware domofonu;
testowane głównie na `DS-KV8113-WME1(C)`. Zgłoszenia z innych modeli mile widziane.

## Licencja

[MIT](LICENSE)

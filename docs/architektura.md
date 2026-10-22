# Architektura

Jak działa Hik Doorbell od środka: z jakich części się składa, co dzieje się przy dzwonku, jak działa
logowanie i jakie pułapki ma domofon. Instalację opisuje [README](../README.pl.md).

## Części systemu

```
                        ┌──────────────────────── serwer (Docker, port 8090) ───────────────────────┐
  domofon Hikvision     │                                                                            │
  ISAPI :80  ◀──digest──┤  hik_server (Python, FastAPI)                                              │
                        │   - co 1 s pyta o callStatus          ──WebSocket /ws──▶  przeglądarka      │
                        │   - wykonuje odbierz/odrzuć/furtkę                        klient Windows    │
                        │   - logowanie, diagnostyka            ◀──REST /api/*────  Home Assistant    │
                        │   - proxy /go2rtc ──────────┐                                              │
                        └─────────────────────────────┼──────────────────────────────────────────────┘
                                                      ▼
  domofon RTSP :554 ──▶  go2rtc (osobny program)  ◀── WebRTC (obraz, dźwięk, mikrofon) ── przeglądarka
```

| Część | Gdzie | Co robi |
|---|---|---|
| **Serwer** | `apps/server` (Python 3.12+, FastAPI, uvicorn) | Rozmawia z domofonem przez ISAPI, trzyma stan rozmowy, rozsyła go po WebSocket, pilnuje dostępu. |
| **Interfejs WWW** | `apps/web` (React, Vite, Tailwind) | Ekran z obrazem z kamery i przyciskami. Serwer podaje zbudowane pliki. Działa bez internetu (bez CDN). |
| **Odtwarzacz** | `apps/web/public/rtc-player.html` | Strona w ramce (iframe) łącząca się z go2rtc przez WebRTC. |
| **Klient Windows** | `apps/windows` (Tauri 1, Rust) | Ikona w zasobniku, przy dzwonku okno na pełnym ekranie z interfejsem WWW. |
| **Home Assistant** | `docs/home-assistant*.yaml` | Czujnik stanu i skrypt furtki, czytane z REST API serwera. |
| **go2rtc** | osobno (dodatek HA albo kontener z `docker-compose.yml`) | Zamienia RTSP z domofonu na WebRTC dla przeglądarki i przesyła głos z powrotem do domofonu. |

### Moduły serwera (`apps/server/hik_server/`)

| Plik | Odpowiada za |
|---|---|
| `__main__.py` | Start uvicorna (`python -m hik_server`, z `--reload` w trybie dev). |
| `config.py` | Wczytanie i sprawdzenie `.env` (pydantic). Błędne ustawienia = czytelny komunikat i wyjście. |
| `app.py` | Trasy HTTP, WebSocket `/ws`, serwowanie interfejsu, start odpytywania i diagnostyki. |
| `doorbell.py` | Maszyna stanów rozmowy i akcje (odbierz, odrzuć, zakończ, furtka). |
| `hikvision.py` | Klient ISAPI z poprawionym logowaniem digest (`HikvisionDigestAuth`). |
| `auth.py` | Logowanie: token, hasło, sieć lokalna. Middleware chroni HTTP i WebSocket. |
| `go2rtc_proxy.py` | Proxy `/go2rtc/*` (HTTP i WebSocket) z dopisywaniem hasła go2rtc po stronie serwera. |
| `diagnostics.py` | „Test połączenia” i linie `[check]` w logu przy starcie. |
| `models.py` | Format danych wysyłanych do interfejsu. Musi zgadzać się z `apps/web/src/types.ts`. |

## Stany rozmowy

```
            domofon: ring                 przycisk Odbierz
   idle ───────────────────▶ ringing ───────────────────────▶ answered_local
    ▲                          │                                   │
    │ domofon: idle            │ Odrzuć                            │ Odrzuć / Zakończ
    │ (albo Reset)             ▼                                   ▼
    └──────────────────────── ended ◀──────────────────────────────┘
```

- **idle**: nikt nie dzwoni.
- **ringing**: domofon zgłosił `ring`/`ringing`. Interfejs pokazuje popup i gra dzwonek.
- **answered_local**: rozmowę odebrano w tej aplikacji, nie w telefonie.
- **ended**: rozmowa zakończona, popup zamknięty. Stan wraca do `idle`, gdy domofon zgłosi zmianę na
  `idle` (np. po odrzuceniu dzwonka) albo po **Reset** w menu. Kolejny dzwonek przechodzi prosto do `ringing`.

Serwer co `HIK_CALLSTATUS_POLL_MS` (domyślnie 1 s) pyta o `GET /ISAPI/VideoIntercom/callStatus`.
Reaguje tylko na **zmianę** odpowiedzi, a każdą zmianę stanu wysyła do wszystkich podłączonych klientów
jako zdarzenie `{"type": "state", ...}` przez `/ws`.

### Odbieranie

Domofon nie pozwala „przejąć” rozmowy przez WebRTC, dopóki sam ją prowadzi. Dlatego **Odbierz** robi
`answer` → czeka `HIK_ACCEPT_DELAY_MS` → `hangUp`. To zwalnia kanał audio domofonu, a rozmowa idzie dalej
przez go2rtc. Domofon zgłasza wtedy `idle`, więc przez `HIK_IGNORE_IDLE_AFTER_ACCEPT_MS` (domyślnie 2 min)
serwer ignoruje `idle` i nie zamyka popupu w trakcie rozmowy.

Ustawienie `HIK_ACCEPT_STRATEGY=local_only` pomija komendy do domofonu i zmienia tylko stan w aplikacji.

### Kończenie

**Zakończ** (i **Odrzuć** w trakcie rozmowy) wykonuje sprzątanie:

1. `PUT callSignal hangUp`,
2. `DELETE /VideoIntercom/ring`,
3. zamknięcie wszystkich aktywnych kanałów `TwoWayAudio`,
4. to samo jeszcze raz po `HIK_ENDCALL_RETRY_DELAY_MS`, bo domofon potrafi zgłaszać stan z opóźnieniem.

Przed i po każdym kroku w logu jest `callStatus` i stan kanałów audio. Pomaga to przy badaniu
niezawodności kończenia rozmowy.

**Odrzuć** podczas dzwonienia wysyła tylko `callSignal reject`.

### Furtka

`PUT /ISAPI/AccessControl/RemoteControl/door/<HIK_DOOR_INDEX>`. W interfejsie przycisk trzeba
**przytrzymać przez 1 sekundę** (myszką, palcem albo Enter/spacją). Wokół przycisku wypełnia się kółko,
a zbyt krótkie kliknięcie pokazuje podpowiedź. Chroni to przed przypadkowym otwarciem na ekranie dotykowym.
Logika odliczania jest w `apps/web/src/holdGesture.ts`, przycisk w `HoldToOpenButton.tsx`.
REST API (`POST /api/actions/open-door`, np. z HA) otwiera od razu.

## Logowanie do aplikacji

Każde zapytanie poza `GET /api/health` przechodzi przez `AuthMiddleware` (`auth.py`). Dotyczy to też
plików interfejsu, WebSocketu `/ws` i proxy `/go2rtc`. Zapytanie przechodzi, gdy spełnia **którykolwiek**
z warunków:

| Sposób | Ustawienie | Kto z tego korzysta |
|---|---|---|
| Sieć lokalna | `TRUST_LOCAL_NETWORK=true` | przeglądarki w domu |
| Token | `APP_TOKEN`: nagłówek `Authorization: Bearer`, `?token=` w adresie albo ciasteczko `hik_token` | klient Windows, HA, dostęp z internetu |
| Hasło | `APP_PASSWORD`: HTTP Basic, użytkownik `APP_USERNAME` | przeglądarka, gdy nie ma tokenu |
| Brak logowania | `AUTH_DISABLED=true` | tylko sieć bez dostępu z internetu |

Token podany raz w adresie (`?token=...`) serwer zapamiętuje w ciasteczku `hik_token` (HttpOnly, rok).
Dzięki temu dalsze zapytania strony, `/ws` i odtwarzacza też są zalogowane.

### Jak serwer rozpoznaje sieć lokalną

Zapytanie jest „lokalne”, gdy **oba** warunki są spełnione:

1. **Adres, z którego przyszło połączenie, jest prywatny**: `10.x`, `172.16–31.x`, `192.168.x`,
   `127.x`, IPv6 `fc00::/7`, `fe80::/10`, `::1`. Adresy CGNAT (`100.64.0.0/10`) nie są uznawane za lokalne.
2. **Zapytanie nie ma nagłówków proxy**: `CF-Connecting-IP`, `CF-Ray`, `X-Forwarded-For`, `X-Real-IP`,
   `Forwarded`.

Drugi warunek chroni tunel Cloudflare. `cloudflared` działa w tej samej sieci co serwer, więc łączy się
z adresu prywatnego, ale zawsze dokleja nagłówki `CF-*`. Takie zapytanie musi mieć token.

Serwer bierze adres prosto z połączenia TCP. uvicorn działa z `proxy_headers=False`, więc nie podmienia
adresu na wartość z `X-Forwarded-For`, i nie da się podszyć pod sieć lokalną fałszywym nagłówkiem.

**Nie włączaj `TRUST_LOCAL_NETWORK`, jeśli przekierowujesz port 8090 na routerze bez proxy.** Zależnie od
konfiguracji routera połączenia z internetu mogą wtedy przychodzić z prywatnego adresu routera.

## Logowanie do domofonu (digest)

ISAPI wymaga logowania HTTP Digest. Domofon `DS-KV8113-WME1(C)` (fw V2.2.78) ma dwie cechy, które trzeba
znać:

1. **Wygasły nonce dostaje „gołe” 401.** Jednorazowy klucz (nonce) wygasa po kilku sekundach. Domofon
   odrzuca go odpowiedzią 401 **bez** nagłówka `WWW-Authenticate` z nowym kluczem. Standardowe biblioteki
   tego nie obsługują: stara wersja w Node gubiła przez to co 4. zapytanie (~15 błędów na minutę), a
   `httpx.DigestAuth` próbowałby w nieskończoność starym kluczem.
2. **Kilka nieudanych logowań z rzędu blokuje adres IP klienta na ~30 minut.** Blokada dotyczy tylko tego
   jednego adresu. Inne komputery w sieci działają dalej.

`HikvisionDigestAuth` (`hikvision.py`) po każdym 401 odrzuca zapamiętany klucz, pobiera nowy
(zapytanie bez logowania) i powtarza zapytanie. Przy prawdziwie złym haśle kończy się to jednym błędem
na zapytanie, bez pętli.

Dodatkowo po 3 nieudanych odpytaniach z rzędu serwer zwalnia odpytywanie do raz na 30 s
(`FAILURE_BACKOFF_*` w `doorbell.py`), żeby złe hasło nie zablokowało serwera.

> Testując ręcznie (curl, skrypty), nie odpytuj domofonu w pętli, gdy dostajesz 401. Po zablokowaniu
> trzeba czekać około pół godziny.

## Obraz i dźwięk (go2rtc)

Przeglądarka nie odtworzy RTSP. go2rtc pobiera z domofonu obraz i dźwięk (RTSP) i kanał zwrotny audio
(`isapi://`), a przeglądarce wystawia WebRTC.

- Przeglądarka **nigdy nie łączy się z go2rtc bezpośrednio**. Sygnalizacja WebRTC idzie przez
  WebSocket `/go2rtc/api/ws` na serwerze aplikacji, a serwer dopisuje hasło go2rtc (`Authorization: Basic`)
  i nagłówek `Origin`, którego wymaga go2rtc. Hasło go2rtc nie trafia do przeglądarki ani do `/api/state`.
- Sam strumień audio i wideo płynie już bezpośrednio między przeglądarką a go2rtc (port `8555`).
  Z zewnątrz może to wymagać STUN/TURN.
- **Mikrofon w przeglądarce działa tylko przez HTTPS** (albo `localhost`). Pod adresem
  `http://<serwer>:8090` widać i słychać gościa, ale nie można do niego mówić. Do rozmów używaj adresu
  HTTPS albo klienta Windows skonfigurowanego na adres HTTPS.

`streamUrl` w stanie wskazuje na `rtc-player.html?go2rtc=/go2rtc&src=<strumień>&media=...`. Interfejs
przełącza `media` w zależności od stanu: przed odebraniem tylko obraz, w rozmowie obraz, dźwięk i mikrofon.

## Klienci

- **Przeglądarka**: łączy się z `/ws`, pokazuje popup przy `ringing`. Tryb `?overlay=1` (dla HA i klienta
  Windows) ukrywa interfejs, gdy nic się nie dzieje.
- **Klient Windows**: trzyma własne połączenie WebSocket z `/ws` (z `User-Agent`, bo Cloudflare blokuje
  zapytania bez niego). Przy `ringing` pokazuje okno na pełnym ekranie z `/?overlay=1&token=...`.
  Wymaga tokenu w ustawieniach, nawet gdy działa w sieci lokalnej.
- **Home Assistant**: odpytuje `GET /api/state` z tokenem w nagłówku i wywołuje `POST /api/actions/open-door`.
  Szczegóły: [home-assistant.md](home-assistant.md).
- **Dotyk**: wszystkie przyciski działają palcem. Efekty `hover` są tylko dla myszy
  (`hoverOnlyWhenSupported` w Tailwind), żeby nie zostawały podświetlone po dotknięciu.

## Testy

```bash
npm test           # vitest (interfejs) + pytest (serwer)
npm run typecheck  # tsc + mypy --strict
```

Testy serwera (`apps/server/tests/`) używają atrapy domofonu, więc nie łączą się z prawdziwym urządzeniem.
`test_hikvision.py` symuluje zachowanie digest opisane wyżej (gołe 401 przy wygasłym kluczu).
Zmiany w kończeniu rozmowy i odbieraniu trzeba dodatkowo sprawdzić na prawdziwym domofonie.

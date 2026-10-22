# Hikvision Doorbell Windows Client

Klient Windows dla systemu wideodomofonu Hikvision. Działa w tle i wyskakuje na fullscreen gdy ktoś dzwoni.

## Funkcjonalności

- **Autostart z systemem** - Uruchamia się automatycznie przy logowaniu do Windows
- **System tray** - Działa w zasobniku systemowym (obok zegara)
- **Fullscreen popup** - Gdy ktoś dzwoni, wyskakuje pełnoekranowe okno na głównym monitorze
- **WebSocket** - Nasłuchuje zdarzeń z serwera w czasie rzeczywistym
- **Reconnect** - Automatycznie łączy się ponownie po utracie połączenia

## Architektura

- Frontend: Tauri (Rust + WebView2)
- Połączenie: WebSocket do serwera (`/ws`, token w nagłówku `Authorization: Bearer`)
- Autostart: Rejestr Windows

## Wymagania

- Windows 10/11
- WebView2 Runtime (instaluje się automatycznie)
- Rust (do kompilacji)

## Instalacja

Pobierz instalator (`.msi` albo `-setup.exe`) z zakładki **Releases** repozytorium i uruchom go.
Instalatory buduje GitHub Actions dla każdego tagu `v*`.

## Budowanie samodzielnie

Wymagania: [Rust](https://rustup.rs) i [Node.js](https://nodejs.org).

```bat
build.bat
```

Instalatory trafią do `src-tauri	argeteleaseundle\msi\` i `...undle
sis\`.

Tryb deweloperski:

```bat
npx @tauri-apps/cli@1 dev
```

## Konfiguracja

Przy pierwszym uruchomieniu otwiera się okno **Ustawienia**:

- **Adres serwera** - ten sam, pod którym otwierasz aplikację w przeglądarce
- **Token** - wartość `APP_TOKEN` z pliku `.env` na serwerze
- **Uruchamiaj razem z Windows** - autostart (domyślnie włączony)

Przycisk **Testuj połączenie** sprawdza adres i token. **Zapisz** testuje, zapisuje i uruchamia klienta ponownie.
Ustawienia otworzysz później z menu ikony w zasobniku.

Pliki: `%APPDATA%\hik-client\config.json` (ustawienia) i `%APPDATA%\hik-client\debug.log` (logi).

## Struktura plików

```
apps/windows/
├── src-tauri/
│   ├── src/
│   │   └── main.rs          # Główna logika aplikacji
│   ├── icons/               # Ikony aplikacji
│   ├── Cargo.toml          # Zależności Rust
│   ├── build.rs            # Skrypt build
│   └── tauri.conf.json     # Konfiguracja Tauri
├── dist/index.html          # Okno ustawień
├── build.bat               # Skrypt budowania
└── README.md              # Ta dokumentacja
```

## Jak to działa

1. **Start aplikacji:**
   - Aplikacja startuje przy logowaniu do Windows (autostart)
   - Główne okno jest ukryte
   - Pokazuje się tylko ikona w system tray

2. **Menu tray:**
   - Pokaż/Ukryj - Przełącza widoczność głównego okna
   - Test połączenia - Otwiera aplikację w głównym oknie
   - Ustawienia - Adres serwera, token, autostart
   - Zakończ - Zamyka aplikację

3. **Gdy ktoś dzwoni:**
   - Serwer wysyła zdarzenie WebSocket `callState: ringing`
   - Aplikacja otwiera fullscreen popup na głównym monitorze
   - Popup pokazuje interfejs wideodomofonu
   - Można odebrać lub odrzucić połączenie

4. **Po zakończeniu:**
   - Serwer wysyła `callState: idle` lub `ended`
   - Popup się zamyka
   - Aplikacja wraca do traya

## Rozwiązywanie problemów

**Brak dźwięku w mikrofonie:**
- Sprawdź czy używasz HTTPS (http nie pozwala na mikrofon)
- Sprawdź uprawnienia mikrofonu w Windows

**Nie łączy się z serwerem:**
- Sprawdź czy serwer CasaOS działa
- Sprawdź połączenie sieciowe
- Sprawdź firewall (porty 8090/443)

**Brak autostartu:**
- Sprawdź Rejestr Windows: `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`
- Sprawdź czy ścieżka do exe jest poprawna

## Bezpieczeństwo

- Aplikacja łączy się tylko z skonfigurowanym serwerem HTTPS
- WebSocket używa WSS (szyfrowany)
- Autostart dodaje się tylko dla bieżącego użytkownika (nie system-wide)

## Następne kroki

- [ ] Opcja wyboru monitora dla popupu
- [ ] Dźwięk powiadomienia przy dzwonku
- [ ] Aktualizacje OTA

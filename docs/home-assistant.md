# Integracja z Home Assistant

Backend sam wykrywa dzwonek (odpytuje domofon przez ISAPI), więc Home Assistant nie potrzebuje
żadnej dodatkowej integracji Hikvision. HA tylko czyta stan z backendu i pokazuje jego interfejs.

## Co dostajesz

- `sensor.domofon_stan_rozmowy` - `idle`, `ringing`, `answered_local`, `ended`
- `sensor.domofon_ostatni_dzwonek` - czas ostatniego dzwonka
- `script.hik_doorbell_open_door` - otwarcie furtki (np. przycisk na dashboardzie)
- opcjonalnie pełnoekranowy popup na każdym dashboardzie (wymaga `browser_mod` z HACS)

## Kroki

1. W `.env` backendu ustaw `APP_TOKEN` (patrz [.env.example](../.env.example)).
2. Skopiuj [home-assistant-package.yaml](home-assistant-package.yaml) do `/config/packages/hik_doorbell.yaml`.
   Jeśli nie masz jeszcze katalogu `packages`, dodaj do `configuration.yaml`:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

3. W pakiecie zamień `BACKEND_URL` na adres backendu (np. `http://192.168.1.10:8090`)
   i `APP_TOKEN` na token. Do `secrets.yaml` dodaj:

   ```yaml
   hik_doorbell_auth_header: "Bearer <APP_TOKEN>"
   ```

4. Jeśli nie używasz `browser_mod`, usuń z pakietu sekcję `automation`.
5. Uruchom ponownie Home Assistant.
6. Opcjonalnie dodaj widok z [lovelace-doorbell-view.yaml](lovelace-doorbell-view.yaml)
   albo dashboard typu **Strona internetowa** z adresem `BACKEND_URL/?overlay=1&token=APP_TOKEN`.

## Uwagi

- Token w adresie iframe jest zapamiętywany w ciasteczku. Działa to, gdy Home Assistant i backend
  są pod tym samym adresem IP/domeną albo oba po HTTPS. HA po HTTPS nie wyświetli iframe z backendem po HTTP.
- Mikrofon w przeglądarce (rozmowa) wymaga HTTPS, poza `localhost`.

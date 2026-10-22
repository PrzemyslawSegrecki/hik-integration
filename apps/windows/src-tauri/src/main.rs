#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::fs::OpenOptions;
use std::io::Write;
use std::panic;
use std::path::PathBuf;
use std::time::Duration;

use auto_launch::AutoLaunch;
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use tauri::{
    AppHandle, CustomMenuItem, Manager, SystemTray, SystemTrayEvent, SystemTrayMenu,
    WindowBuilder, WindowUrl,
};
use tokio_tungstenite::tungstenite::client::IntoClientRequest;

const SETTINGS_WINDOW: &str = "settings";

fn default_true() -> bool {
    true
}

#[derive(Clone, Serialize, Deserialize)]
struct ClientConfig {
    server_url: String,
    token: String,
    #[serde(default = "default_true")]
    autostart: bool,
}

impl Default for ClientConfig {
    fn default() -> Self {
        Self { server_url: String::new(), token: String::new(), autostart: true }
    }
}

impl ClientConfig {
    fn validate(&self) -> Result<(), String> {
        let url = self.server_url.trim();
        if !(url.starts_with("http://") || url.starts_with("https://")) {
            return Err("Adres serwera musi zaczynać się od http:// lub https://".into());
        }
        if self.token.trim().is_empty() {
            return Err("Podaj token (APP_TOKEN z pliku .env serwera)".into());
        }
        Ok(())
    }

    fn base_url(&self) -> &str {
        self.server_url.trim().trim_end_matches('/')
    }

    fn token(&self) -> &str {
        self.token.trim()
    }

    fn app_url(&self, overlay: bool) -> String {
        let overlay = if overlay { "overlay=1&" } else { "" };
        format!("{}/?{}token={}", self.base_url(), overlay, percent_encode(self.token()))
    }

    fn ws_url(&self) -> String {
        let base = self.base_url();
        let ws_base = if let Some(rest) = base.strip_prefix("https://") {
            format!("wss://{rest}")
        } else if let Some(rest) = base.strip_prefix("http://") {
            format!("ws://{rest}")
        } else {
            base.to_string()
        };
        format!("{ws_base}/ws")
    }
}

fn percent_encode(value: &str) -> String {
    value
        .bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => (b as char).to_string(),
            _ => format!("%{b:02X}"),
        })
        .collect()
}

fn app_data_dir() -> PathBuf {
    dirs::config_dir()
        .or_else(dirs::data_local_dir)
        .map(|p| p.join("hik-client"))
        .unwrap_or_else(|| PathBuf::from("."))
}

fn config_path() -> PathBuf {
    app_data_dir().join("config.json")
}

/// Reads %APPDATA%\hik-client\config.json. Returns None when missing or incomplete.
fn read_config() -> Option<ClientConfig> {
    let path = config_path();
    let raw = std::fs::read_to_string(&path).ok()?;
    match serde_json::from_str::<ClientConfig>(&raw) {
        Ok(config) if config.validate().is_ok() => Some(config),
        Ok(_) => {
            log_to_file(&format!("Config at {} is incomplete", path.display()));
            None
        }
        Err(e) => {
            log_to_file(&format!("Failed to parse config {}: {}", path.display(), e));
            None
        }
    }
}

fn write_config(config: &ClientConfig) -> Result<(), String> {
    std::fs::create_dir_all(app_data_dir()).map_err(|e| e.to_string())?;
    let json = serde_json::to_string_pretty(config).map_err(|e| e.to_string())?;
    std::fs::write(config_path(), json).map_err(|e| e.to_string())
}

fn apply_autostart(enabled: bool) {
    let exe_path = std::env::current_exe()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_default();
    let auto = AutoLaunch::new("hik-windows-client", &exe_path, &[] as &[&str]);
    let result = if enabled { auto.enable() } else { auto.disable() };
    match result {
        Ok(_) => log_to_file(&format!("Autostart {}", if enabled { "enabled" } else { "disabled" })),
        Err(e) => log_to_file(&format!("Autostart error: {}", e)),
    }
}

fn log_to_file(msg: &str) {
    let log_path = app_data_dir().join("debug.log");

    if let Some(parent) = log_path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&log_path) {
        let timestamp = chrono::Local::now().format("%Y-%m-%d %H:%M:%S");
        let _ = writeln!(file, "[{}] {}", timestamp, msg);
    }
}

/// WebSocket handshake with the token. A User-Agent is required: Cloudflare bot rules
/// reject requests without one (403 "Bots are not allowed").
fn ws_request(
    url: &str,
    token: &str,
) -> Result<tokio_tungstenite::tungstenite::handshake::client::Request, String> {
    let mut request = url.into_client_request().map_err(|e| e.to_string())?;
    let headers = request.headers_mut();
    let auth = format!("Bearer {token}").parse().map_err(|_| "Nieprawidłowy token".to_string())?;
    headers.insert("Authorization", auth);
    let user_agent = concat!("HikDoorbellClient/", env!("CARGO_PKG_VERSION"));
    headers.insert("User-Agent", user_agent.parse().map_err(|_| "Invalid User-Agent".to_string())?);
    Ok(request)
}

#[tauri::command]
fn get_config() -> ClientConfig {
    std::fs::read_to_string(config_path())
        .ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
        .unwrap_or_default()
}

/// Opens the server WebSocket with the token - the same call the client makes in the background.
#[tauri::command]
async fn test_connection(config: ClientConfig) -> Result<String, String> {
    use tokio_tungstenite::tungstenite::Error;

    config.validate()?;
    let request = ws_request(&config.ws_url(), config.token())?;

    match tokio::time::timeout(Duration::from_secs(8), tokio_tungstenite::connect_async(request)).await {
        Err(_) => Err("Brak odpowiedzi serwera (timeout)".into()),
        Ok(Ok((mut ws, _))) => {
            let _ = ws.close(None).await;
            Ok("Połączono z serwerem".into())
        }
        Ok(Err(Error::Http(response))) if response.status().as_u16() == 401 => {
            Err("Serwer odrzucił token (401)".into())
        }
        Ok(Err(Error::Http(response))) => Err(format!("Serwer odpowiedział kodem {}", response.status())),
        Ok(Err(e)) => Err(format!("Nie można połączyć: {e}")),
    }
}

#[tauri::command]
fn save_config(app: AppHandle, config: ClientConfig) -> Result<(), String> {
    config.validate()?;
    let config = ClientConfig {
        server_url: config.base_url().to_string(),
        token: config.token().to_string(),
        autostart: config.autostart,
    };
    write_config(&config)?;
    apply_autostart(config.autostart);
    log_to_file("Config saved, restarting");
    app.restart();
    Ok(())
}

fn open_settings(app: &AppHandle) {
    if let Some(window) = app.get_window(SETTINGS_WINDOW) {
        let _ = window.show();
        let _ = window.set_focus();
        return;
    }

    let result = WindowBuilder::new(app, SETTINGS_WINDOW, WindowUrl::App("index.html".into()))
        .title("Hik Doorbell - ustawienia")
        .inner_size(460.0, 540.0)
        .resizable(false)
        .center()
        .build();

    if let Err(e) = result {
        log_to_file(&format!("Failed to open settings window: {}", e));
    }
}

fn build_tray(configured: bool) -> SystemTray {
    let mut menu = SystemTrayMenu::new();
    if configured {
        menu = menu
            .add_item(CustomMenuItem::new("toggle", "Pokaż"))
            .add_item(CustomMenuItem::new("test", "Test połączenia"));
    }
    menu = menu
        .add_item(CustomMenuItem::new("settings", "Ustawienia"))
        .add_native_item(tauri::SystemTrayMenuItem::Separator)
        .add_item(CustomMenuItem::new("quit", "Zakończ"));
    SystemTray::new().with_menu(menu)
}

fn main() {
    log_to_file("Application starting");

    panic::set_hook(Box::new(|info| {
        let msg = if let Some(s) = info.payload().downcast_ref::<&str>() {
            s.to_string()
        } else if let Some(s) = info.payload().downcast_ref::<String>() {
            s.clone()
        } else {
            "Unknown panic".to_string()
        };
        log_to_file(&format!("PANIC: {} at {:?}", msg, info.location()));
    }));

    let client_config = read_config();
    let configured = client_config.is_some();

    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![get_config, test_connection, save_config])
        .system_tray(build_tray(configured))
        .on_system_tray_event({
            let client_config = client_config.clone();
            move |app, event| match event {
                SystemTrayEvent::MenuItemClick { id, .. } => {
                    let item_handle = app.tray_handle().get_item(&id);
                    match id.as_str() {
                        "quit" => {
                            log_to_file("Quit requested");
                            std::process::exit(0);
                        }
                        "settings" => open_settings(app),
                        "toggle" => {
                            if let Some(window) = app.get_window("main") {
                                if window.is_visible().unwrap_or(false) {
                                    let _ = window.hide();
                                    let _ = item_handle.set_title("Pokaż");
                                } else {
                                    let _ = window.show();
                                    let _ = window.set_focus();
                                    let _ = item_handle.set_title("Ukryj");
                                }
                            }
                        }
                        "test" => {
                            if let (Some(window), Some(config)) = (app.get_window("main"), &client_config) {
                                let _ = window.show();
                                let _ = window.set_focus();
                                let url = config.app_url(false);
                                let _ = window.eval(&format!("window.location.href = '{url}'"));
                            }
                        }
                        _ => {}
                    }
                }
                SystemTrayEvent::DoubleClick { .. } => match app.get_window("main") {
                    Some(window) => {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                    None => open_settings(app),
                },
                _ => {}
            }
        })
        .on_window_event(move |event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event.event() {
                if event.window().label() == SETTINGS_WINDOW {
                    // Without a saved config there is nothing to run in the background.
                    if !configured {
                        std::process::exit(0);
                    }
                    return;
                }
                let _ = event.window().hide();
                api.prevent_close();
            }
        })
        .setup(move |app| {
            let app_handle = app.handle();

            let Some(client_config) = client_config else {
                log_to_file("No valid config, opening settings");
                open_settings(&app_handle);
                return Ok(());
            };

            WindowBuilder::new(&app_handle, "main", WindowUrl::External(client_config.app_url(false).parse()?))
                .title("Hikvision Doorbell")
                .inner_size(1200.0, 800.0)
                .visible(false)
                .accept_first_mouse(true)
                .build()?;

            WindowBuilder::new(&app_handle, "popup", WindowUrl::External(client_config.app_url(true).parse()?))
                .title("Ktoś dzwoni!")
                .fullscreen(true)
                .always_on_top(true)
                .visible(false)
                .accept_first_mouse(true)
                .build()?;

            apply_autostart(client_config.autostart);

            let ws_handle = app_handle.clone();
            tauri::async_runtime::spawn(async move {
                start_websocket_listener(ws_handle, client_config).await;
            });

            log_to_file("Setup completed successfully");
            Ok(())
        })
        .run(tauri::generate_context!())
        .map_err(|e| {
            log_to_file(&format!("Tauri run error: {}", e));
            e
        })
        .expect("error while running tauri application");
}

async fn start_websocket_listener(app_handle: AppHandle, client_config: ClientConfig) {
    let ws_url = client_config.ws_url();
    log_to_file(&format!("WebSocket listener starting, connecting to {ws_url}"));

    loop {
        match connect_and_listen(&app_handle, &ws_url, client_config.token()).await {
            Ok(_) => log_to_file("WebSocket connection closed, reconnecting in 5s..."),
            Err(e) => log_to_file(&format!("WebSocket error: {}, reconnecting in 5s...", e)),
        }
        tokio::time::sleep(Duration::from_secs(5)).await;
    }
}

async fn connect_and_listen(
    app_handle: &AppHandle,
    url: &str,
    token: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    log_to_file(&format!("Connecting to WebSocket: {}", url));
    let request = ws_request(url, token)?;

    let (ws_stream, _) = tokio_tungstenite::connect_async(request).await?;
    log_to_file("WebSocket connected");

    let (_, mut read) = ws_stream.split();

    while let Some(msg) = read.next().await {
        match msg {
            Ok(tokio_tungstenite::tungstenite::Message::Text(text)) => {
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(&text) {
                    if let Some(state) = json.get("payload").and_then(|p| p.get("callState")) {
                        let call_state = state.as_str().unwrap_or("");
                        log_to_file(&format!("Call state: {}", call_state));

                        match call_state {
                            "ringing" => show_popup(app_handle),
                            "idle" | "ended" => hide_popup(app_handle),
                            _ => {}
                        }
                    }
                }
            }
            Ok(tokio_tungstenite::tungstenite::Message::Close(_)) => {
                log_to_file("WebSocket closed by server");
                break;
            }
            Err(e) => {
                log_to_file(&format!("WebSocket error in loop: {}", e));
                break;
            }
            _ => {}
        }
    }

    Ok(())
}

fn show_popup(app_handle: &AppHandle) {
    if let Some(popup) = app_handle.get_window("popup") {
        // Show and focus the window with proper ordering for touch support
        let _ = popup.set_always_on_top(true);
        let _ = popup.show();
        let _ = popup.set_focus();
        log_to_file("Popup shown and focused");
    } else {
        log_to_file("ERROR: Popup window not found!");
    }
}

fn hide_popup(app_handle: &AppHandle) {
    if let Some(popup) = app_handle.get_window("popup") {
        let _ = popup.hide();
    }
}

use std::{
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::Path,
    sync::{atomic::{AtomicBool, Ordering}, Mutex},
    time::{Duration, Instant},
};

use tauri::{Manager, WindowEvent};
use tauri_plugin_shell::{process::{CommandChild, CommandEvent}, ShellExt};

struct DesktopState {
    child: Mutex<Option<CommandChild>>,
    status: Mutex<String>,
    quitting: AtomicBool,
}

impl Default for DesktopState {
    fn default() -> Self {
        Self {
            child: Mutex::new(None),
            status: Mutex::new("starting".into()),
            quitting: AtomicBool::new(false),
        }
    }
}

#[tauri::command]
fn backend_status(state: tauri::State<'_, DesktopState>) -> String {
    state.status.lock().unwrap().clone()
}

fn set_status(app: &tauri::AppHandle, value: &str) {
    *app.state::<DesktopState>().status.lock().unwrap() = value.into();
}

fn show_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn log_desktop(data_dir: &Path, message: &str) {
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .append(true).create(true).open(data_dir.join("logs").join("desktop.log"))
    {
        let _ = writeln!(file, "{message}");
    }
}

fn port_address() -> SocketAddr {
    "127.0.0.1:17800".parse().unwrap()
}

fn port_occupied() -> bool {
    TcpStream::connect_timeout(&port_address(), Duration::from_millis(300)).is_ok()
}

fn healthy() -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(&port_address(), Duration::from_millis(400)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    if stream.write_all(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n").is_err() {
        return false;
    }
    let mut result = String::new();
    stream.read_to_string(&mut result).is_ok()
        && result.starts_with("HTTP/1.1 200")
        && result.contains("\"status\":\"ok\"")
}

fn stop_backend(app: &tauri::AppHandle) {
    let state = app.state::<DesktopState>();
    state.quitting.store(true, Ordering::SeqCst);
    if let Ok(data_dir) = app.path().app_data_dir() {
        let _ = std::fs::write(data_dir.join("backend.shutdown"), b"quit");
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline && healthy() {
            std::thread::sleep(Duration::from_millis(100));
        }
    }
    let child = state.child.lock().unwrap().take();
    if let Some(child) = child {
        let _ = child.kill();
    }
}

fn start_backend(app: tauri::AppHandle) {
    std::thread::spawn(move || {
        let data_dir = match app.path().app_data_dir() {
            Ok(path) => path,
            Err(_) => {
                set_status(&app, "无法定位 Nexa 用户数据目录。");
                show_main(&app);
                return;
            }
        };
        if std::fs::create_dir_all(data_dir.join("logs")).is_err() {
            set_status(&app, "无法创建 Nexa 用户数据目录。");
            show_main(&app);
            return;
        }
        if port_occupied() {
            log_desktop(&data_dir, "Port 17800 is already in use");
            set_status(&app, "端口 17800 已被占用。请关闭占用该端口的程序后重启 Nexa。");
            show_main(&app);
            return;
        }
        let command = match app.shell().sidecar("nexa-backend") {
            Ok(command) => command,
            Err(error) => {
                log_desktop(&data_dir, &format!("Sidecar lookup failed: {error}"));
                set_status(&app, "Nexa Backend 文件缺失。请重新安装 Nexa。");
                show_main(&app);
                return;
            }
        };
        let data_dir_arg = data_dir.to_string_lossy().into_owned();
        let (mut receiver, child) = match command.args(["--data-dir", data_dir_arg.as_str()]).spawn() {
            Ok(result) => result,
            Err(error) => {
                log_desktop(&data_dir, &format!("Sidecar spawn failed: {error}"));
                set_status(&app, "Nexa Backend 启动失败。请查看 logs/backend.log。");
                show_main(&app);
                return;
            }
        };
        app.state::<DesktopState>().child.lock().unwrap().replace(child);
        log_desktop(&data_dir, "Backend sidecar spawned");

        let monitor_app = app.clone();
        let monitor_dir = data_dir.clone();
        tauri::async_runtime::spawn(async move {
            while let Some(event) = receiver.recv().await {
                if let CommandEvent::Terminated(payload) = event {
                    log_desktop(&monitor_dir, &format!("Backend exited with code {:?}", payload.code));
                    let state = monitor_app.state::<DesktopState>();
                    state.child.lock().unwrap().take();
                    if !state.quitting.load(Ordering::SeqCst) {
                        set_status(&monitor_app, "Nexa Backend 已停止。请退出并重新启动 Nexa，详情见 logs/backend.log。");
                        show_main(&monitor_app);
                    }
                    break;
                }
            }
        });

        let deadline = Instant::now() + Duration::from_secs(25);
        while Instant::now() < deadline {
            if app.state::<DesktopState>().status.lock().unwrap().as_str() != "starting" {
                return;
            }
            if healthy() {
                set_status(&app, "ready");
                log_desktop(&data_dir, "Backend is ready");
                show_main(&app);
                return;
            }
            std::thread::sleep(Duration::from_millis(250));
        }
        log_desktop(&data_dir, "Backend readiness timed out");
        stop_backend(&app);
        set_status(&app, "Nexa Backend 启动超时。请查看 logs/backend.log；数据库迁移失败时请先备份 nexa.db。");
        show_main(&app);
    });
}

fn setup_tray(app: &tauri::App) -> tauri::Result<()> {
    use tauri::{menu::{Menu, MenuItem}, tray::TrayIconBuilder};
    let open = MenuItem::with_id(app, "open", "打开 Nexa", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "退出 Nexa", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &quit])?;
    let mut builder = TrayIconBuilder::new()
        .menu(&menu)
        .tooltip("Nexa")
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => show_main(app),
            "quit" => {
                stop_backend(app);
                app.exit(0);
            }
            _ => {}
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if app.state::<DesktopState>().status.lock().unwrap().as_str() != "starting" {
                show_main(app);
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .manage(DesktopState::default())
        .invoke_handler(tauri::generate_handler![backend_status])
        .setup(|app| {
            setup_tray(app)?;
            start_backend(app.handle().clone());
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                if !window.state::<DesktopState>().quitting.load(Ordering::SeqCst) {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build Nexa Desktop");
    app.run(|app, event| {
        match event {
            tauri::RunEvent::ExitRequested { api, .. }
                if !app.state::<DesktopState>().quitting.load(Ordering::SeqCst) => api.prevent_exit(),
            tauri::RunEvent::Exit => stop_backend(app),
            _ => {}
        }
    });
}

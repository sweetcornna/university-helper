mod port;
pub use port::parse_listening_port;

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Managed state: holds the sidecar handle so we can reap it on exit / before restart.
struct SidecarProcess(Mutex<Option<CommandChild>>);

/// Kill the sidecar if still running. Idempotent (uses `Option::take`).
/// Called from `RunEvent::ExitRequested` and before an updater relaunch so the
/// loopback port is free again (Tauri does NOT auto-reap sidecars).
fn kill_sidecar(app: &AppHandle) {
    if let Some(state) = app.try_state::<SidecarProcess>() {
        match state.0.lock() {
            Ok(mut guard) => {
                if let Some(child) = guard.take() {
                    let _ = child.kill();
                }
            }
            Err(err) => eprintln!("[uh-desktop] sidecar state lock poisoned: {err}"),
        }
    }
}

fn json_string(value: &str) -> String {
    match serde_json::to_string(value) {
        Ok(encoded) => encoded,
        Err(_) => "\"Startup error\"".to_string(),
    }
}

fn show_startup_error(app: &AppHandle, message: impl AsRef<str>) {
    let message = message.as_ref();
    eprintln!("[uh-desktop] startup error: {message}");

    let Some(splash) = app.get_webview_window("splash") else {
        return;
    };

    let message = json_string(message);
    let script = format!(
        r##"
(() => {{
  document.body.innerHTML = "";
  document.body.style.background = "#0b1020";
  document.body.style.color = "#e6e8ef";
  document.body.style.fontFamily = "system-ui, sans-serif";
  document.body.style.display = "grid";
  document.body.style.placeItems = "center";
  const root = document.createElement("main");
  root.style.maxWidth = "380px";
  root.style.padding = "28px";
  root.style.textAlign = "center";
  const title = document.createElement("h1");
  title.textContent = "学道启动失败";
  title.style.fontSize = "22px";
  title.style.margin = "0 0 12px";
  const body = document.createElement("p");
  body.textContent = {message};
  body.style.opacity = "0.78";
  body.style.lineHeight = "1.55";
  body.style.margin = "0";
  root.append(title, body);
  document.body.append(root);
}})();
"##
    );

    if let Err(err) = splash.eval(&script) {
        eprintln!("[uh-desktop] failed to render startup error: {err}");
    }
}

fn http_response_is_ok(response: &[u8]) -> bool {
    response.starts_with(b"HTTP/1.1 200 ") || response.starts_with(b"HTTP/1.0 200 ")
}

fn loopback_http_ok(addr: SocketAddr, path: &str) -> bool {
    let mut stream = match TcpStream::connect_timeout(&addr, Duration::from_millis(250)) {
        Ok(stream) => stream,
        Err(_) => return false,
    };

    let _ = stream.set_read_timeout(Some(Duration::from_millis(750)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(750)));

    let request = format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }

    let mut response = [0_u8; 32];
    match stream.read(&mut response) {
        Ok(n) => http_response_is_ok(&response[..n]),
        Err(_) => false,
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = match tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            // 1. Spawn the workstream-D sidecar. Name matches `externalBin`/the triple base.
            let app_handle = app.handle().clone();
            let sidecar = match app.shell().sidecar("uh-backend") {
                Ok(command) => command,
                Err(err) => {
                    show_startup_error(
                        &app_handle,
                        format!("无法定位本地后端组件 uh-backend：{err}"),
                    );
                    return Ok(());
                }
            };
            let (mut rx, child) = match sidecar.spawn() {
                Ok(spawned) => spawned,
                Err(err) => {
                    show_startup_error(
                        &app_handle,
                        format!("无法启动本地后端组件 uh-backend：{err}"),
                    );
                    return Ok(());
                }
            };

            // 2. Keep the child so we can kill it on exit.
            app.manage(SidecarProcess(Mutex::new(Some(child))));

            // 3. Read stdout until we see the readiness line, then open the real window.
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) => {
                            let line = String::from_utf8_lossy(&bytes);
                            if let Some(p) = parse_listening_port(&line) {
                                // The sidecar prints the token after importing the ASGI
                                // app, but before uvicorn finishes binding and serving
                                // routes. Wait for real HTTP 200 responses so the
                                // webview never lands on a half-ready blank page.
                                let addr = SocketAddr::from(([127, 0, 0, 1], p));
                                let mut ready = false;
                                for _ in 0..600 {
                                    if loopback_http_ok(addr, "/health")
                                        && loopback_http_ok(addr, "/")
                                    {
                                        ready = true;
                                        break;
                                    }
                                    std::thread::sleep(Duration::from_millis(100));
                                }
                                if !ready {
                                    eprintln!("[uh-backend] 127.0.0.1:{p} never became reachable");
                                }
                                let url = format!("http://127.0.0.1:{p}");
                                let h = handle.clone();
                                let parsed_url = match url.parse() {
                                    Ok(url) => url,
                                    Err(err) => {
                                        show_startup_error(
                                            &h,
                                            format!("本地后端地址无效 {url}：{err}"),
                                        );
                                        break;
                                    }
                                };
                                // Window creation must run on the main thread.
                                let h_for_error = h.clone();
                                if let Err(err) = handle.run_on_main_thread(move || {
                                    let build_result = WebviewWindowBuilder::new(
                                        &h,
                                        "main",
                                        WebviewUrl::External(parsed_url),
                                    )
                                    .title("学道")
                                    .inner_size(1280.0, 832.0)
                                    .min_inner_size(960.0, 640.0)
                                    .center()
                                    .build();
                                    if let Err(err) = build_result {
                                        show_startup_error(&h, format!("无法创建主窗口：{err}"));
                                        return;
                                    }

                                    if let Some(splash) = h.get_webview_window("splash") {
                                        let _ = splash.close();
                                    }
                                }) {
                                    show_startup_error(
                                        &h_for_error,
                                        format!("无法调度主窗口创建：{err}"),
                                    );
                                }
                                break; // got the port; stop scanning stdout
                            }
                        }
                        CommandEvent::Stderr(bytes) => {
                            eprintln!("[uh-backend] {}", String::from_utf8_lossy(&bytes));
                        }
                        CommandEvent::Error(err) => {
                            eprintln!("[uh-backend] error: {err}");
                            show_startup_error(&handle, format!("本地后端启动输出错误：{err}"));
                            break;
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[uh-backend] terminated before readiness: {payload:?}");
                            show_startup_error(
                                &handle,
                                format!("本地后端在启动完成前退出：{payload:?}"),
                            );
                            break;
                        }
                        _ => {}
                    }
                }
            });

            // 4. Background auto-update check (Rust-side; frees the port before relaunch).
            let h2 = app.handle().clone();
            tauri::async_runtime::spawn(check_for_updates(h2));

            Ok(())
        })
        .build(tauri::generate_context!())
    {
        Ok(app) => app,
        Err(err) => {
            eprintln!("[uh-desktop] error while building 学道 desktop app: {err}");
            return;
        }
    };

    app.run(|app_handle, event| {
        if let RunEvent::ExitRequested { .. } = event {
            // THE FOOTGUN: sidecars are not auto-reaped — kill it ourselves.
            kill_sidecar(app_handle);
        }
    });
}

/// Check GitHub Releases for an update; on install, kill the sidecar then relaunch.
async fn check_for_updates(app: AppHandle) {
    use tauri_plugin_updater::UpdaterExt;

    let updater = match app.updater() {
        Ok(u) => u,
        Err(e) => {
            eprintln!("updater unavailable: {e}");
            return;
        }
    };
    match updater.check().await {
        Ok(Some(update)) => {
            if let Err(e) = update
                .download_and_install(|_chunk, _total| {}, || {})
                .await
            {
                eprintln!("update install failed: {e}");
                return;
            }
            kill_sidecar(&app); // free the loopback port before relaunch
            app.restart();
        }
        Ok(None) => { /* already up to date */ }
        Err(e) => eprintln!("update check failed: {e}"),
    }
}

#[cfg(test)]
mod tests {
    use super::http_response_is_ok;

    #[test]
    fn recognizes_successful_http_response_status_lines() {
        assert!(http_response_is_ok(
            b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\n"
        ));
        assert!(http_response_is_ok(b"HTTP/1.0 200 OK\r\n\r\n"));
    }

    #[test]
    fn rejects_non_successful_or_malformed_http_response_status_lines() {
        assert!(!http_response_is_ok(
            b"HTTP/1.1 503 Service Unavailable\r\n"
        ));
        assert!(!http_response_is_ok(b"HTTP/1.1 404 Not Found\r\n"));
        assert!(!http_response_is_ok(b""));
        assert!(!http_response_is_ok(b"not http"));
    }
}

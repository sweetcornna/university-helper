mod port;
pub use port::parse_listening_port;

use std::sync::Mutex;

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
        if let Some(child) = state.0.lock().unwrap().take() {
            let _ = child.kill();
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            // 1. Spawn the workstream-D sidecar. Name matches `externalBin`/the triple base.
            let sidecar = app
                .shell()
                .sidecar("binaries/uh-backend")
                .expect("failed to create `uh-backend` sidecar command");
            let (mut rx, child) = sidecar
                .spawn()
                .expect("failed to spawn `uh-backend` sidecar");

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
                                // The sidecar prints the token BEFORE uvicorn finishes
                                // binding, so wait until the loopback socket actually
                                // accepts a connection — otherwise the webview lands on
                                // a connection-refused page and the splash is already
                                // gone. Poll TCP connect (no HTTP dep) for up to ~20s.
                                let addr = std::net::SocketAddr::from(([127, 0, 0, 1], p));
                                let mut ready = false;
                                for _ in 0..200 {
                                    if std::net::TcpStream::connect_timeout(
                                        &addr,
                                        std::time::Duration::from_millis(200),
                                    )
                                    .is_ok()
                                    {
                                        ready = true;
                                        break;
                                    }
                                    std::thread::sleep(std::time::Duration::from_millis(100));
                                }
                                if !ready {
                                    eprintln!("[uh-backend] 127.0.0.1:{p} never became reachable");
                                }
                                let url = format!("http://127.0.0.1:{p}");
                                let h = handle.clone();
                                // Window creation must run on the main thread.
                                handle
                                    .run_on_main_thread(move || {
                                        WebviewWindowBuilder::new(
                                            &h,
                                            "main",
                                            WebviewUrl::External(
                                                url.parse().expect("valid loopback url"),
                                            ),
                                        )
                                        .title("学道")
                                        .inner_size(1280.0, 832.0)
                                        .min_inner_size(960.0, 640.0)
                                        .center()
                                        .build()
                                        .expect("failed to build main window");

                                        if let Some(splash) = h.get_webview_window("splash") {
                                            let _ = splash.close();
                                        }
                                    })
                                    .expect("failed to schedule window creation");
                                break; // got the port; stop scanning stdout
                            }
                        }
                        CommandEvent::Stderr(bytes) => {
                            eprintln!("[uh-backend] {}", String::from_utf8_lossy(&bytes));
                        }
                        CommandEvent::Error(err) => {
                            eprintln!("[uh-backend] error: {err}");
                            break;
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[uh-backend] terminated before readiness: {payload:?}");
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
        .expect("error while building 学道 desktop app")
        .run(|app_handle, event| {
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

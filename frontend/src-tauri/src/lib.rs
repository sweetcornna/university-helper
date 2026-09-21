mod port;
pub use port::parse_listening_port;

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::Path;
use std::sync::{
    atomic::{AtomicBool, AtomicU16, Ordering},
    Arc, Mutex,
};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Managed state: holds the sidecar handle so we can reap it on exit / before restart.
struct SidecarProcess(Mutex<Option<CommandChild>>);

const STARTUP_TIMEOUT: Duration = Duration::from_secs(60);
const HTTP_CONNECT_TIMEOUT: Duration = Duration::from_millis(250);
const HTTP_IO_TIMEOUT: Duration = Duration::from_millis(750);
const BACKEND_RETRY_DELAY: Duration = Duration::from_millis(100);
const WATCHDOG_POLL_INTERVAL: Duration = Duration::from_millis(100);
/// Let the main window appear before a possible update prompt.
const UPDATE_CHECK_DELAY: Duration = Duration::from_secs(8);
/// Bounds the update *check*; downloads are not time-limited by the plugin.
const UPDATE_CHECK_TIMEOUT: Duration = Duration::from_secs(20);
/// After a graceful stop request, how long the sidecar gets before it is killed.
const SIDECAR_STOP_GRACE: Duration = Duration::from_millis(1500);
const LOG_FILE_NAME: &str = "desktop.log";
const LOG_MAX_BYTES: u64 = 1024 * 1024;
const UPDATE_NOTES_MAX_CHARS: usize = 600;

/// Exactly one startup branch may claim completion. The watchdog, sidecar
/// event reader, and HTTP readiness task intentionally share this arbiter.
#[derive(Clone, Default)]
struct StartupCompletion(Arc<AtomicBool>);

impl StartupCompletion {
    fn new() -> Self {
        Self::default()
    }

    fn try_complete(&self) -> bool {
        self.0
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
    }

    fn is_complete(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }
}

/// Append a line to `<app log dir>/desktop.log` (rotated at 1 MB) and stderr.
/// Release builds on Windows have no console, so stderr alone is invisible.
fn log_event(app: &AppHandle, message: impl AsRef<str>) {
    let message = message.as_ref();
    eprintln!("[uh-desktop] {message}");
    let Ok(dir) = app.path().app_log_dir() else {
        return;
    };
    append_log_line(&dir, message);
}

fn append_log_line(dir: &Path, message: &str) {
    if std::fs::create_dir_all(dir).is_err() {
        return;
    }
    let path = dir.join(LOG_FILE_NAME);
    if let Ok(meta) = std::fs::metadata(&path) {
        if meta.len() > LOG_MAX_BYTES {
            let _ = std::fs::rename(&path, dir.join(format!("{LOG_FILE_NAME}.1")));
        }
    }
    let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
    else {
        return;
    };
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .unwrap_or_default();
    let _ = writeln!(file, "{seconds} {message}");
}

/// Stop the sidecar if it is still running. Idempotent (uses `Option::take`).
/// Called from `RunEvent::ExitRequested`, on startup failures and right before
/// the updater exits the app (Tauri does NOT auto-reap sidecars).
///
/// The sidecar is a PyInstaller onefile binary: the process we spawned is a
/// bootloader whose child runs the real backend. Killing only the bootloader
/// leaves that child running, so the whole tree is stopped instead. The backend
/// also watches `UH_PARENT_PID` and exits by itself if this ever fails.
fn kill_sidecar(app: &AppHandle) {
    let Some(state) = app.try_state::<SidecarProcess>() else {
        return;
    };
    let child = match state.0.lock() {
        Ok(mut guard) => guard.take(),
        Err(err) => {
            log_event(app, format!("sidecar state lock poisoned: {err}"));
            return;
        }
    };
    if let Some(child) = child {
        stop_process_tree(child.pid());
        let _ = child.kill();
    }
}

#[cfg(unix)]
fn stop_process_tree(pid: u32) {
    let Ok(pid) = libc::pid_t::try_from(pid) else {
        return;
    };
    // The bootloader forwards SIGTERM to its Python child, which lets uvicorn
    // shut down cleanly (closing local.db) before the hard kill that follows.
    // SAFETY: plain FFI calls with a pid we spawned; no memory is shared.
    unsafe {
        if libc::kill(pid, libc::SIGTERM) != 0 {
            return;
        }
    }
    let deadline = Instant::now() + SIDECAR_STOP_GRACE;
    while Instant::now() < deadline {
        // SAFETY: signal 0 only probes whether the process still exists.
        if unsafe { libc::kill(pid, 0) } != 0 {
            return;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

#[cfg(windows)]
fn stop_process_tree(pid: u32) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let _ = std::process::Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .creation_flags(CREATE_NO_WINDOW)
        .status();
}

#[cfg(not(any(unix, windows)))]
fn stop_process_tree(_pid: u32) {}

fn json_string(value: &str) -> String {
    match serde_json::to_string(value) {
        Ok(encoded) => encoded,
        Err(_) => "\"Startup error\"".to_string(),
    }
}

fn show_startup_error(app: &AppHandle, message: impl AsRef<str>) {
    let message = message.as_ref();
    log_event(app, format!("startup error: {message}"));

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
        log_event(app, format!("failed to render startup error: {err}"));
    }
}

fn complete_startup_error(
    app: &AppHandle,
    completion: &StartupCompletion,
    message: impl AsRef<str>,
) -> bool {
    complete_startup_once(completion, || {
        show_startup_error(app, message);
        kill_sidecar(app);
    })
}

fn complete_startup_once<F>(completion: &StartupCompletion, effect: F) -> bool
where
    F: FnOnce(),
{
    if !completion.try_complete() {
        return false;
    }
    effect();
    true
}

fn complete_startup_success(
    app: &AppHandle,
    completion: &StartupCompletion,
    deadline: Instant,
    port: u16,
) {
    let url = format!("http://127.0.0.1:{port}");
    let parsed_url = match url.parse() {
        Ok(url) => url,
        Err(err) => {
            complete_startup_error(app, completion, format!("本地后端地址无效 {url}：{err}"));
            return;
        }
    };

    if Instant::now() >= deadline {
        complete_startup_error(app, completion, startup_timeout_message(port));
        return;
    }

    let handle = app.clone();
    let handle_for_error = handle.clone();
    let main_thread_completion = completion.clone();
    if let Err(err) = app.run_on_main_thread(move || {
        // Queueing is not completion: the callback must run before the absolute
        // deadline and win against the watchdog/termination branches.
        if Instant::now() >= deadline {
            complete_startup_error(
                &handle,
                &main_thread_completion,
                startup_timeout_message(port),
            );
            return;
        }
        complete_startup_once(&main_thread_completion, || {
            let build_result =
                WebviewWindowBuilder::new(&handle, "main", WebviewUrl::External(parsed_url))
                    .title("学道")
                    .inner_size(1280.0, 832.0)
                    .min_inner_size(960.0, 640.0)
                    .center()
                    .build();
            if let Err(err) = build_result {
                show_startup_error(&handle, format!("无法创建主窗口：{err}"));
                kill_sidecar(&handle);
                return;
            }

            if let Some(splash) = handle.get_webview_window("splash") {
                let _ = splash.close();
            }
        });
    }) {
        complete_startup_error(
            &handle_for_error,
            completion,
            format!("无法调度主窗口创建：{err}"),
        );
    }
}

fn run_startup_watchdog<N, S, F>(
    deadline: Instant,
    completion: StartupCompletion,
    mut now: N,
    mut sleep: S,
    on_timeout: F,
) where
    N: FnMut() -> Instant,
    S: FnMut(Duration),
    F: FnOnce(),
{
    loop {
        if completion.is_complete() {
            return;
        }

        let remaining = deadline.saturating_duration_since(now());
        if remaining.is_zero() {
            complete_startup_once(&completion, on_timeout);
            return;
        }
        sleep(remaining.min(WATCHDOG_POLL_INTERVAL));
    }
}

fn startup_timeout_message(port: u16) -> String {
    if port == 0 {
        "本地后端在规定时间内未报告监听地址".to_string()
    } else {
        format!("本地后端 127.0.0.1:{port} 在规定时间内未能响应")
    }
}

fn http_response_is_ok(response: &[u8]) -> bool {
    response.starts_with(b"HTTP/1.1 200 ") || response.starts_with(b"HTTP/1.0 200 ")
}

fn clamped_timeout(remaining: Duration, maximum: Duration) -> Option<Duration> {
    if remaining.is_zero() {
        None
    } else {
        Some(remaining.min(maximum))
    }
}

fn deadline_timeout(deadline: Instant, maximum: Duration) -> Option<Duration> {
    clamped_timeout(deadline.saturating_duration_since(Instant::now()), maximum)
}

fn write_all_before_deadline<W, S, N>(
    writer: &mut W,
    bytes: &[u8],
    deadline: Instant,
    mut set_timeout: S,
    mut now: N,
) -> bool
where
    W: Write,
    S: FnMut(&W, Duration) -> bool,
    N: FnMut() -> Instant,
{
    let mut offset = 0;
    while offset < bytes.len() {
        let Some(timeout) =
            clamped_timeout(deadline.saturating_duration_since(now()), HTTP_IO_TIMEOUT)
        else {
            return false;
        };
        if !set_timeout(writer, timeout) {
            return false;
        }

        match writer.write(&bytes[offset..]) {
            Ok(0) | Err(_) => return false,
            Ok(written) => offset += written,
        }
    }

    now() < deadline
}

fn http_response_may_be_ok(response: &[u8]) -> bool {
    const OK_PREFIXES: [&[u8]; 2] = [b"HTTP/1.1 200 ", b"HTTP/1.0 200 "];
    OK_PREFIXES
        .iter()
        .any(|prefix| response.starts_with(prefix) || prefix.starts_with(response))
}

fn loopback_http_ok(addr: SocketAddr, path: &str, deadline: Instant) -> bool {
    let Some(connect_timeout) = deadline_timeout(deadline, HTTP_CONNECT_TIMEOUT) else {
        return false;
    };
    let mut stream = match TcpStream::connect_timeout(&addr, connect_timeout) {
        Ok(stream) => stream,
        Err(_) => return false,
    };

    let request = format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
    if !write_all_before_deadline(
        &mut stream,
        request.as_bytes(),
        deadline,
        |stream, timeout| stream.set_write_timeout(Some(timeout)).is_ok(),
        Instant::now,
    ) {
        return false;
    }

    let mut response = [0_u8; 32];
    let mut received = 0;
    while received < response.len() {
        let Some(read_timeout) = deadline_timeout(deadline, HTTP_IO_TIMEOUT) else {
            return false;
        };
        if stream.set_read_timeout(Some(read_timeout)).is_err() {
            return false;
        }

        match stream.read(&mut response[received..]) {
            Ok(0) | Err(_) => return false,
            Ok(count) => {
                received += count;
                let status = &response[..received];
                if http_response_is_ok(status) {
                    return Instant::now() < deadline;
                }
                if !http_response_may_be_ok(status) {
                    return false;
                }
            }
        }
    }
    false
}

fn wait_for_backend_ready<P, S, N>(
    addr: SocketAddr,
    deadline: Instant,
    mut probe: P,
    mut sleep: S,
    mut now: N,
) -> bool
where
    P: FnMut(SocketAddr, &str, Instant) -> bool,
    S: FnMut(Duration),
    N: FnMut() -> Instant,
{
    loop {
        if now() >= deadline {
            return false;
        }

        if probe(addr, "/health", deadline) {
            if now() >= deadline {
                return false;
            }
            if probe(addr, "/", deadline) {
                return now() < deadline;
            }
        }

        let Some(delay) = clamped_timeout(
            deadline.saturating_duration_since(now()),
            BACKEND_RETRY_DELAY,
        ) else {
            return false;
        };
        sleep(delay);
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = match tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // 1. Spawn the workstream-D sidecar. Name matches `externalBin`/the triple base.
            let app_handle = app.handle().clone();
            let sidecar = match app.shell().sidecar("uh-backend") {
                // The backend exits on its own when this process disappears.
                Ok(command) => command.env("UH_PARENT_PID", std::process::id().to_string()),
                Err(err) => {
                    show_startup_error(
                        &app_handle,
                        format!("无法定位本地后端组件 uh-backend：{err}"),
                    );
                    return Ok(());
                }
            };
            // The stdout marker and both HTTP probes spend one shared wall-clock
            // budget, measured from immediately before the sidecar is spawned.
            let startup_deadline = Instant::now() + STARTUP_TIMEOUT;
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

            // 3. Race one absolute watchdog against stdout termination/errors and
            // HTTP readiness. Only the branch that claims `completion` may touch
            // the visible startup outcome or reap the sidecar.
            let completion = StartupCompletion::new();
            let observed_port = Arc::new(AtomicU16::new(0));

            let watchdog_handle = app.handle().clone();
            let watchdog_completion = completion.clone();
            let watchdog_port = observed_port.clone();
            tauri::async_runtime::spawn_blocking(move || {
                run_startup_watchdog(
                    startup_deadline,
                    watchdog_completion,
                    Instant::now,
                    std::thread::sleep,
                    || {
                        let port = watchdog_port.load(Ordering::Acquire);
                        show_startup_error(&watchdog_handle, startup_timeout_message(port));
                        kill_sidecar(&watchdog_handle);
                    },
                );
            });

            // Keep reading events after the marker while the blocking readiness
            // task runs, so an early sidecar termination can win immediately.
            let handle = app.handle().clone();
            let event_completion = completion.clone();
            let event_port = observed_port.clone();
            tauri::async_runtime::spawn(async move {
                let mut readiness_started = false;
                while let Some(event) = rx.recv().await {
                    if event_completion.is_complete() {
                        break;
                    }

                    match event {
                        CommandEvent::Stdout(bytes) => {
                            let line = String::from_utf8_lossy(&bytes);
                            if !readiness_started {
                                if let Some(p) = parse_listening_port(&line) {
                                    readiness_started = true;
                                    event_port.store(p, Ordering::Release);

                                    // The sidecar prints the token after importing the ASGI
                                    // app, but before uvicorn finishes binding and serving
                                    // routes. Wait for real HTTP 200 responses so the
                                    // webview never lands on a half-ready blank page.
                                    let addr = SocketAddr::from(([127, 0, 0, 1], p));
                                    let ready_handle = handle.clone();
                                    let ready_completion = event_completion.clone();
                                    tauri::async_runtime::spawn(async move {
                                        let ready =
                                            match tauri::async_runtime::spawn_blocking(move || {
                                                wait_for_backend_ready(
                                                    addr,
                                                    startup_deadline,
                                                    loopback_http_ok,
                                                    std::thread::sleep,
                                                    Instant::now,
                                                )
                                            })
                                            .await
                                            {
                                                Ok(ready) => ready,
                                                Err(err) => {
                                                    log_event(
                                                        &ready_handle,
                                                        format!(
                                                            "backend readiness task failed: {err}"
                                                        ),
                                                    );
                                                    false
                                                }
                                            };

                                        if ready {
                                            complete_startup_success(
                                                &ready_handle,
                                                &ready_completion,
                                                startup_deadline,
                                                p,
                                            );
                                        } else {
                                            complete_startup_error(
                                                &ready_handle,
                                                &ready_completion,
                                                startup_timeout_message(p),
                                            );
                                        }
                                    });
                                }
                            }
                        }
                        CommandEvent::Stderr(bytes) => {
                            log_event(
                                &handle,
                                format!(
                                    "[uh-backend] {}",
                                    String::from_utf8_lossy(&bytes).trim_end()
                                ),
                            );
                        }
                        CommandEvent::Error(err) => {
                            log_event(&handle, format!("[uh-backend] error: {err}"));
                            complete_startup_error(
                                &handle,
                                &event_completion,
                                format!("本地后端启动输出错误：{err}"),
                            );
                            break;
                        }
                        CommandEvent::Terminated(payload) => {
                            log_event(
                                &handle,
                                format!("[uh-backend] terminated before readiness: {payload:?}"),
                            );
                            complete_startup_error(
                                &handle,
                                &event_completion,
                                format!("本地后端在启动完成前退出：{payload:?}"),
                            );
                            break;
                        }
                        _ => {}
                    }
                }

                if !event_completion.is_complete() {
                    complete_startup_error(&handle, &event_completion, "本地后端启动输出已关闭");
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

/// Text of the "new version" prompt; release notes are shortened to keep the
/// native dialog readable.
fn format_update_prompt(current: &str, latest: &str, notes: Option<&str>) -> String {
    let mut text = format!("学道 {latest} 已发布，你现在用的是 {current}。\n\n");
    if let Some(notes) = notes.map(str::trim).filter(|notes| !notes.is_empty()) {
        let mut shortened: String = notes.chars().take(UPDATE_NOTES_MAX_CHARS).collect();
        if notes.chars().count() > UPDATE_NOTES_MAX_CHARS {
            shortened.push('…');
        }
        text.push_str(&shortened);
        text.push_str("\n\n");
    }
    text.push_str("更新会下载新版本并重启学道，正在运行的任务会中断。要现在更新吗？");
    text
}

/// Check GitHub Releases for an update and ask before installing it.
async fn check_for_updates(app: AppHandle) {
    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
    use tauri_plugin_updater::UpdaterExt;

    let _ = tauri::async_runtime::spawn_blocking(|| std::thread::sleep(UPDATE_CHECK_DELAY)).await;

    let exit_handle = app.clone();
    let updater = match app
        .updater_builder()
        .timeout(UPDATE_CHECK_TIMEOUT)
        // On Windows the installer is launched and the process exits inside
        // download_and_install, so the sidecar must be stopped here; replacing
        // the hook also replaces the default cleanup, which is called explicitly.
        .on_before_exit(move || {
            kill_sidecar(&exit_handle);
            exit_handle.cleanup_before_exit();
        })
        .build()
    {
        Ok(updater) => updater,
        Err(err) => {
            log_event(&app, format!("updater unavailable: {err}"));
            return;
        }
    };

    let update = match updater.check().await {
        Ok(Some(update)) => update,
        Ok(None) => return,
        Err(err) => {
            log_event(&app, format!("update check failed: {err}"));
            return;
        }
    };

    log_event(
        &app,
        format!(
            "update available: {} -> {}",
            update.current_version, update.version
        ),
    );
    let prompt = format_update_prompt(
        &update.current_version,
        &update.version,
        update.body.as_deref(),
    );
    let dialog_handle = app.clone();
    let accepted = tauri::async_runtime::spawn_blocking(move || {
        dialog_handle
            .dialog()
            .message(prompt)
            .title("学道有新版本")
            .kind(MessageDialogKind::Info)
            .buttons(MessageDialogButtons::OkCancelCustom(
                "现在更新".to_string(),
                "稍后".to_string(),
            ))
            .blocking_show()
    })
    .await
    .unwrap_or(false);

    if !accepted {
        log_event(&app, "update postponed by the user");
        return;
    }

    if let Err(err) = update
        .download_and_install(|_chunk, _total| {}, || {})
        .await
    {
        log_event(&app, format!("update install failed: {err}"));
        app.dialog()
            .message(format!(
                "更新没有装上：{err}\n\n可以稍后重启学道再试，或到 GitHub Releases 下载最新安装包。"
            ))
            .title("学道更新失败")
            .kind(MessageDialogKind::Error)
            .show(|_| {});
        return;
    }
    log_event(&app, "update installed; restarting");
    kill_sidecar(&app); // free the loopback port before relaunch
    app.restart();
}

#[cfg(test)]
mod tests {
    use super::{
        append_log_line, clamped_timeout, complete_startup_once, format_update_prompt,
        http_response_is_ok, loopback_http_ok, run_startup_watchdog, wait_for_backend_ready,
        write_all_before_deadline, StartupCompletion, LOG_FILE_NAME, UPDATE_NOTES_MAX_CHARS,
    };
    use std::cell::Cell;
    use std::io::{self, Read, Write};
    use std::net::{SocketAddr, TcpListener};
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Barrier,
    };
    use std::time::{Duration, Instant};

    fn bind_loopback_listener() -> Option<(TcpListener, SocketAddr)> {
        let listener = match TcpListener::bind(("127.0.0.1", 0)) {
            Ok(listener) => listener,
            Err(_) => return None,
        };
        let addr = match listener.local_addr() {
            Ok(addr) => addr,
            Err(_) => return None,
        };
        Some((listener, addr))
    }

    struct PartialWriter {
        max_chunk: usize,
        output: Vec<u8>,
    }

    impl Write for PartialWriter {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            let count = bytes.len().min(self.max_chunk);
            self.output.extend_from_slice(&bytes[..count]);
            Ok(count)
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

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

    #[test]
    fn backend_readiness_succeeds_after_a_retry_when_both_routes_are_ready() {
        let addr = SocketAddr::from(([127, 0, 0, 1], 1234));
        let started_at = Instant::now();
        let now = Cell::new(started_at);
        let mut health_calls = 0;
        let mut root_calls = 0;
        let mut sleeps = 0;

        let ready = wait_for_backend_ready(
            addr,
            started_at + Duration::from_secs(1),
            |_addr, path, _deadline| match path {
                "/health" => {
                    health_calls += 1;
                    health_calls >= 2
                }
                "/" => {
                    root_calls += 1;
                    root_calls >= 1
                }
                _ => false,
            },
            |duration| {
                sleeps += 1;
                now.set(now.get() + duration);
            },
            || now.get(),
        );

        assert!(ready);
        assert_eq!(health_calls, 2);
        assert_eq!(root_calls, 1);
        assert_eq!(sleeps, 1);
    }

    #[test]
    fn backend_readiness_clamps_retry_sleep_to_the_absolute_deadline() {
        let addr = SocketAddr::from(([127, 0, 0, 1], 1234));
        let started_at = Instant::now();
        let now = Cell::new(started_at);
        let mut health_calls = 0;
        let mut root_calls = 0;
        let mut sleeps = Vec::new();

        let ready = wait_for_backend_ready(
            addr,
            started_at + Duration::from_millis(250),
            |_addr, path, _deadline| {
                if path == "/health" {
                    health_calls += 1;
                } else {
                    root_calls += 1;
                }
                now.set(now.get() + Duration::from_millis(200));
                false
            },
            |duration| {
                sleeps.push(duration);
                now.set(now.get() + duration);
            },
            || now.get(),
        );

        assert!(!ready);
        assert_eq!(health_calls, 1);
        assert_eq!(root_calls, 0);
        assert_eq!(sleeps, vec![Duration::from_millis(50)]);
        assert_eq!(now.get(), started_at + Duration::from_millis(250));
    }

    #[test]
    fn backend_readiness_rejects_root_success_that_arrives_at_the_deadline() {
        let addr = SocketAddr::from(([127, 0, 0, 1], 1234));
        let started_at = Instant::now();
        let now = Cell::new(started_at);
        let mut health_calls = 0;
        let mut root_calls = 0;
        let unexpected_sleeps = Cell::new(0);

        let ready = wait_for_backend_ready(
            addr,
            started_at + Duration::from_millis(250),
            |_addr, path, _deadline| {
                if path == "/health" {
                    health_calls += 1;
                    now.set(now.get() + Duration::from_millis(50));
                } else {
                    root_calls += 1;
                    now.set(now.get() + Duration::from_millis(200));
                }
                true
            },
            |_| unexpected_sleeps.set(unexpected_sleeps.get() + 1),
            || now.get(),
        );

        assert!(!ready);
        assert_eq!(health_calls, 1);
        assert_eq!(root_calls, 1);
        assert_eq!(unexpected_sleeps.get(), 0);
        assert_eq!(now.get(), started_at + Duration::from_millis(250));
    }

    #[test]
    fn startup_watchdog_completes_when_no_marker_arrives() {
        let completion = StartupCompletion::new();
        let started_at = Instant::now();
        let now = Cell::new(started_at);
        let timeout_calls = Cell::new(0);

        run_startup_watchdog(
            started_at + Duration::from_secs(2),
            completion.clone(),
            || now.get(),
            |duration| now.set(now.get() + duration),
            || timeout_calls.set(timeout_calls.get() + 1),
        );

        assert_eq!(now.get(), started_at + Duration::from_secs(2));
        assert_eq!(timeout_calls.get(), 1);
        assert!(completion.is_complete());
        assert!(!completion.try_complete());
    }

    #[test]
    fn startup_deadline_race_runs_exactly_one_complete_side_effect() {
        let completion = StartupCompletion::new();
        let barrier = Arc::new(Barrier::new(4));
        let create_main_calls = Arc::new(AtomicUsize::new(0));
        let show_error_calls = Arc::new(AtomicUsize::new(0));
        let kill_calls = Arc::new(AtomicUsize::new(0));

        let contenders: Vec<_> = (0..3)
            .map(|kind| {
                let completion = completion.clone();
                let barrier = barrier.clone();
                let create_main_calls = create_main_calls.clone();
                let show_error_calls = show_error_calls.clone();
                let kill_calls = kill_calls.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    complete_startup_once(&completion, || {
                        if kind == 0 {
                            create_main_calls.fetch_add(1, Ordering::SeqCst);
                        } else {
                            show_error_calls.fetch_add(1, Ordering::SeqCst);
                            kill_calls.fetch_add(1, Ordering::SeqCst);
                        }
                    })
                })
            })
            .collect();

        barrier.wait();
        let mut winners = 0;
        let mut join_errors = 0;
        for thread in contenders {
            match thread.join() {
                Ok(true) => winners += 1,
                Ok(false) => {}
                Err(_) => join_errors += 1,
            }
        }

        assert_eq!(winners, 1);
        assert_eq!(join_errors, 0);
        assert!(completion.is_complete());
        let create_main_calls = create_main_calls.load(Ordering::SeqCst);
        let show_error_calls = show_error_calls.load(Ordering::SeqCst);
        let kill_calls = kill_calls.load(Ordering::SeqCst);
        assert_eq!(create_main_calls + show_error_calls, 1);
        assert_eq!(show_error_calls, kill_calls);
    }

    #[test]
    fn socket_timeout_is_clamped_to_remaining_startup_budget() {
        assert_eq!(
            clamped_timeout(Duration::from_millis(100), Duration::from_millis(250)),
            Some(Duration::from_millis(100))
        );
        assert_eq!(
            clamped_timeout(Duration::from_secs(1), Duration::from_millis(250)),
            Some(Duration::from_millis(250))
        );
        assert_eq!(
            clamped_timeout(Duration::ZERO, Duration::from_millis(250)),
            None
        );
    }

    #[test]
    fn bounded_writer_accepts_partial_writes_and_reapplies_timeout() {
        let started_at = Instant::now();
        let timeout_calls = Cell::new(0);
        let mut writer = PartialWriter {
            max_chunk: 2,
            output: Vec::new(),
        };

        let written = write_all_before_deadline(
            &mut writer,
            b"abcdef",
            started_at + Duration::from_secs(1),
            |_writer, timeout| {
                assert!(timeout <= Duration::from_millis(750));
                timeout_calls.set(timeout_calls.get() + 1);
                true
            },
            || started_at,
        );

        assert!(written);
        assert_eq!(writer.output, b"abcdef");
        assert_eq!(timeout_calls.get(), 3);
    }

    #[test]
    fn loopback_probe_stays_bounded_when_server_stalls_after_connect() {
        let listener = bind_loopback_listener();
        assert!(listener.is_some());
        let Some((listener, addr)) = listener else {
            return;
        };
        let server = std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut request = [0_u8; 128];
                let _ = stream.read(&mut request);
                std::thread::sleep(Duration::from_millis(500));
                let _ = stream.write(b"HTTP/1.1 200 OK\r\n\r\n");
            }
        });

        let started_at = Instant::now();
        let ready = loopback_http_ok(addr, "/health", started_at + Duration::from_millis(80));
        let elapsed = started_at.elapsed();
        let server_joined = match server.join() {
            Ok(()) => true,
            Err(_) => false,
        };

        assert!(!ready);
        assert!(elapsed < Duration::from_millis(350));
        assert!(server_joined);
    }

    #[test]
    fn loopback_probe_accepts_fragmented_status_before_deadline() {
        let listener = bind_loopback_listener();
        assert!(listener.is_some());
        let Some((listener, addr)) = listener else {
            return;
        };
        let server = std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let _ = stream.set_nodelay(true);
                let mut request = [0_u8; 128];
                let _ = stream.read(&mut request);
                if stream.write_all(b"HTTP/1.1 ").is_ok() {
                    let _ = stream.flush();
                    std::thread::sleep(Duration::from_millis(30));
                    let _ = stream.write_all(b"200 OK\r\ncontent-length: 0\r\n\r\n");
                }
            }
        });

        let started_at = Instant::now();
        let ready = loopback_http_ok(addr, "/health", started_at + Duration::from_millis(500));
        let elapsed = started_at.elapsed();
        let server_joined = match server.join() {
            Ok(()) => true,
            Err(_) => false,
        };

        assert!(ready);
        assert!(elapsed < Duration::from_millis(500));
        assert!(server_joined);
    }

    #[test]
    fn update_prompt_names_both_versions_and_warns_about_restart() {
        let text = format_update_prompt("1.4.6", "1.4.7", Some("- 修复注册失败"));
        assert!(text.contains("1.4.7"));
        assert!(text.contains("1.4.6"));
        assert!(text.contains("- 修复注册失败"));
        assert!(text.contains("任务会中断"));
    }

    #[test]
    fn update_prompt_skips_empty_notes_and_truncates_long_ones() {
        let empty = format_update_prompt("1.4.6", "1.4.7", Some("   "));
        assert!(!empty.contains("\n\n\n"));

        let long_notes = "字".repeat(UPDATE_NOTES_MAX_CHARS + 50);
        let long = format_update_prompt("1.4.6", "1.4.7", Some(&long_notes));
        assert!(long.contains('…'));
        assert!(long.chars().filter(|c| *c == '字').count() == UPDATE_NOTES_MAX_CHARS);
    }

    #[test]
    fn log_lines_are_appended_and_rotated() {
        let dir = std::env::temp_dir().join(format!("uh-desktop-log-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        append_log_line(&dir, "first");
        append_log_line(&dir, "second");
        let content = std::fs::read_to_string(dir.join(LOG_FILE_NAME)).unwrap_or_default();
        assert!(content.contains("first") && content.contains("second"));

        let big = vec![b'x'; 1024 * 1024 + 10];
        assert!(std::fs::write(dir.join(LOG_FILE_NAME), big).is_ok());
        append_log_line(&dir, "after rotation");
        let rotated = dir.join(format!("{LOG_FILE_NAME}.1"));
        assert!(rotated.exists());
        let fresh = std::fs::read_to_string(dir.join(LOG_FILE_NAME)).unwrap_or_default();
        assert!(fresh.contains("after rotation") && fresh.len() < 100);
        let _ = std::fs::remove_dir_all(&dir);
    }
}

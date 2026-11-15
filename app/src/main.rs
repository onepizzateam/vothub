// VOTHUB desktop tab: pulls the cloud-built feed at 07:00 / 19:00 local time,
// backs off an hour when the machine is busy, and can be halted with one click.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    fs,
    io::Read,
    path::PathBuf,
    sync::{Arc, Mutex},
    thread,
    time::Duration,
};

use chrono::{Duration as Days, Local, NaiveDate, TimeZone, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Manager, PhysicalPosition, PhysicalSize, State, WebviewWindow};

const SLOT_HOURS: [u32; 2] = [7, 19];
const KEEP_SECS: i64 = 4 * 86_400; // local storage never holds anything older
const DEFER_SECS: i64 = 3_600; // busy machine -> try again in an hour
const CLOUD_LAG_RETRY: i64 = 600; // cloud scan not published yet -> look again in 10 min
const ERROR_RETRY: i64 = 900;
const CPU_BUSY_PCT: f32 = 60.0;
const MEM_BUSY_FRAC: f64 = 0.90;
const MAX_FEED_BYTES: u64 = 4 * 1024 * 1024;
const RUN_KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";
/// Feed used until another repo is set under STATION (forks: change this).
const DEFAULT_REPO: &str = "onepizzateam/vothub";

#[derive(Serialize, Deserialize, Clone, Default)]
#[serde(default)]
struct Cfg {
    repo: String,      // "owner/name" of the GitHub repo that hosts the feed
    paused_until: i64, // 0 = running, -1 = halted indefinitely, else unix seconds
    next_sync: i64,
    last_ok: i64,
    status: String,
    autostart: bool,
    autostart_decided: bool,
}

struct Shared {
    cfg: Cfg,
    feed: Option<Value>,
    dir: PathBuf,
    syncing: bool,
    force: bool,
}

type St = Arc<Mutex<Shared>>;

fn now() -> i64 {
    Utc::now().timestamp()
}

fn slot(day: NaiveDate, hour: u32) -> i64 {
    day.and_hms_opt(hour, 0, 0)
        .and_then(|naive| Local.from_local_datetime(&naive).earliest())
        .map(|d| d.timestamp())
        .unwrap_or(0)
}

fn slots_around(t: i64) -> Vec<i64> {
    let today = Local.timestamp_opt(t, 0).earliest().unwrap_or_else(Local::now).date_naive();
    let mut all = Vec::new();
    for offset in -1..=1 {
        for hour in SLOT_HOURS {
            all.push(slot(today + Days::days(offset), hour));
        }
    }
    all
}

fn prev_slot(t: i64) -> i64 {
    slots_around(t).into_iter().filter(|s| *s <= t).max().unwrap_or(t)
}

fn next_slot(t: i64) -> i64 {
    slots_around(t).into_iter().filter(|s| *s > t).min().unwrap_or(t + 43_200)
}

fn save(sh: &Shared) {
    if let Ok(text) = serde_json::to_string(&sh.cfg) {
        let _ = fs::write(sh.dir.join("state.json"), text);
    }
}

fn valid_repo(repo: &str) -> bool {
    let ok = |part: &str| {
        !part.is_empty()
            && part.len() <= 100
            && part.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
    };
    let mut parts = repo.split('/');
    matches!((parts.next(), parts.next(), parts.next()), (Some(a), Some(b), None) if ok(a) && ok(b))
}

fn feed_url(repo: &str) -> Option<String> {
    if let Ok(url) = std::env::var("VOTHUB_FEED_URL") {
        return Some(url); // development override
    }
    valid_repo(repo).then(|| format!("https://raw.githubusercontent.com/{repo}/data/feed.json.gz"))
}

fn decode(bytes: &[u8]) -> Result<Value, String> {
    let mut text = String::new();
    if bytes.starts_with(&[0x1f, 0x8b]) {
        flate2::read::GzDecoder::new(bytes)
            .take(32 * 1024 * 1024)
            .read_to_string(&mut text)
            .map_err(|e| e.to_string())?;
    } else {
        text = String::from_utf8_lossy(bytes).into_owned();
    }
    let feed: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    if feed.get("gen").and_then(Value::as_i64).is_none() || !feed["issues"].is_array() {
        return Err("not a vothub feed".into());
    }
    Ok(feed)
}

fn download(url: &str) -> Result<Vec<u8>, String> {
    let resp = ureq::get(url)
        .timeout(Duration::from_secs(30))
        .set("User-Agent", "vothub-tab")
        .call()
        .map_err(|e| match e {
            ureq::Error::Status(404, _) => "feed not found (has the scan run yet?)".to_string(),
            ureq::Error::Status(code, _) => format!("http {code}"),
            other => other.to_string(),
        })?;
    let mut buf = Vec::new();
    resp.into_reader()
        .take(MAX_FEED_BYTES)
        .read_to_end(&mut buf)
        .map_err(|e| e.to_string())?;
    Ok(buf)
}

/// Why a sync should not run right now, if the laptop is already working hard.
fn busy_reason() -> Option<String> {
    let mut sys = sysinfo::System::new();
    sys.refresh_cpu_usage();
    let mut total = 0.0;
    for _ in 0..3 {
        thread::sleep(Duration::from_millis(1200));
        sys.refresh_cpu_usage();
        total += sys.global_cpu_usage();
    }
    let cpu = total / 3.0;
    if cpu > CPU_BUSY_PCT {
        return Some(format!("CPU AT {cpu:.0}%"));
    }
    sys.refresh_memory();
    let mem = sys.used_memory() as f64 / sys.total_memory().max(1) as f64;
    if mem > MEM_BUSY_FRAC {
        return Some(format!("MEMORY AT {:.0}%", mem * 100.0));
    }
    use windows_sys::Win32::System::Power::{GetSystemPowerStatus, SYSTEM_POWER_STATUS};
    let mut power: SYSTEM_POWER_STATUS = unsafe { std::mem::zeroed() };
    if unsafe { GetSystemPowerStatus(&mut power) } != 0
        && power.ACLineStatus == 0
        && power.BatteryLifePercent <= 20
    {
        return Some(format!("BATTERY AT {}%", power.BatteryLifePercent));
    }
    None
}

fn is_paused(cfg: &Cfg, t: i64) -> bool {
    cfg.paused_until == -1 || cfg.paused_until > t
}

fn scheduler(st: St) {
    loop {
        thread::sleep(Duration::from_secs(5));
        let t = now();
        let (url, forced) = {
            let mut sh = st.lock().unwrap();
            if sh.cfg.paused_until > 0 && sh.cfg.paused_until <= t {
                sh.cfg.paused_until = 0; // timed halt ran out
                sh.cfg.status = "RESUMED".into();
                save(&sh);
            }
            if is_paused(&sh.cfg, t) {
                sh.force = false;
                continue; // halted: no network, no probing, nothing
            }
            let Some(url) = feed_url(&sh.cfg.repo) else {
                sh.cfg.status = "NO FEED CONFIGURED".into();
                continue;
            };
            if sh.cfg.next_sync == 0 {
                // first run, or woke up after missing a slot
                sh.cfg.next_sync = if sh.cfg.last_ok < prev_slot(t) { t } else { next_slot(t) };
            }
            if !sh.force && t < sh.cfg.next_sync {
                continue;
            }
            let forced = sh.force;
            sh.force = false;
            sh.syncing = true;
            (url, forced)
        };

        // The load check and the download both run without holding the lock.
        let outcome = match (!forced).then(busy_reason).flatten() {
            Some(reason) => Err((DEFER_SECS, format!("DEFERRED 1H // {reason}"))),
            None => download(&url)
                .and_then(|bytes| decode(&bytes).map(|feed| (bytes, feed)))
                .map_err(|e| (ERROR_RETRY, format!("LINK ERROR // {e}"))),
        };

        let mut sh = st.lock().unwrap();
        let t = now();
        sh.syncing = false;
        match outcome {
            Err((wait, status)) => {
                sh.cfg.next_sync = t + wait;
                sh.cfg.status = status;
            }
            Ok((bytes, feed)) => {
                let gen = feed["gen"].as_i64().unwrap_or(0);
                sh.cfg.last_ok = t;
                if t - gen > KEEP_SECS {
                    let _ = fs::remove_file(sh.dir.join("feed.json.gz"));
                    sh.feed = None;
                    sh.cfg.status = "CLOUD FEED IS OVER 4 DAYS OLD".into();
                    sh.cfg.next_sync = next_slot(t);
                } else {
                    let _ = fs::write(sh.dir.join("feed.json.gz"), &bytes);
                    sh.feed = Some(feed);
                    let due = prev_slot(t);
                    if gen < due - 2 * 3_600 && t - due < 2 * 3_600 {
                        sh.cfg.status = "WAITING FOR CLOUD SCAN".into();
                        sh.cfg.next_sync = t + CLOUD_LAG_RETRY;
                    } else {
                        sh.cfg.status = "SIGNAL LOCKED".into();
                        sh.cfg.next_sync = next_slot(t);
                    }
                }
            }
        }
        save(&sh);
    }
}

fn place(win: &WebviewWindow, expanded: bool) {
    let monitor = win.current_monitor().ok().flatten().or_else(|| win.primary_monitor().ok().flatten());
    let Some(monitor) = monitor else { return };
    let (size, origin, scale) = (monitor.size(), monitor.position(), monitor.scale_factor());
    let taskbar = (56.0 * scale) as i32;
    let margin = (12.0 * scale) as i32;
    let (w, h, x, y);
    if expanded {
        w = (size.width as f64 * 0.90) as u32;
        h = ((size.height as i32 - taskbar) as f64 * 0.92) as u32;
        x = origin.x + (size.width as i32 - w as i32) / 2;
        y = origin.y + (size.height as i32 - taskbar - h as i32) / 2;
    } else {
        // a quarter of each dimension = one sixteenth of the screen
        w = size.width / 4;
        h = size.height / 4;
        x = origin.x + size.width as i32 - w as i32 - margin;
        y = origin.y + size.height as i32 - h as i32 - margin - taskbar;
    }
    let _ = win.set_always_on_top(!expanded);
    let _ = win.set_skip_taskbar(!expanded);
    let _ = win.set_size(PhysicalSize::new(w, h));
    let _ = win.set_position(PhysicalPosition::new(x, y));
}

fn apply_autostart(on: bool) -> Result<(), String> {
    use winreg::{enums::*, RegKey};
    let (key, _) = RegKey::predef(HKEY_CURRENT_USER)
        .create_subkey(RUN_KEY)
        .map_err(|e| e.to_string())?;
    if on {
        let exe = std::env::current_exe().map_err(|e| e.to_string())?;
        key.set_value("VotHub", &format!("\"{}\"", exe.display())).map_err(|e| e.to_string())
    } else {
        match key.delete_value("VotHub") {
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e.to_string()),
            _ => Ok(()),
        }
    }
}

// ------------------------------------------------------------------ commands
#[tauri::command]
fn status(st: State<St>) -> Value {
    let sh = st.lock().unwrap();
    let t = now();
    json!({
        "now": t,
        "repo": sh.cfg.repo,
        "paused": is_paused(&sh.cfg, t),
        "paused_until": sh.cfg.paused_until,
        "next_sync": sh.cfg.next_sync,
        "last_ok": sh.cfg.last_ok,
        "status": sh.cfg.status,
        "syncing": sh.syncing,
        "autostart": sh.cfg.autostart,
        "gen": sh.feed.as_ref().and_then(|f| f["gen"].as_i64()).unwrap_or(0),
    })
}

#[tauri::command]
fn get_feed(st: State<St>) -> Option<Value> {
    st.lock().unwrap().feed.clone()
}

#[tauri::command]
fn set_mode(window: WebviewWindow, expanded: bool) {
    place(&window, expanded);
}

/// minutes <= 0 halts until manually resumed.
#[tauri::command]
fn halt(st: State<St>, minutes: i64) {
    let mut sh = st.lock().unwrap();
    sh.cfg.paused_until = if minutes <= 0 { -1 } else { now() + minutes.min(60 * 24 * 30) * 60 };
    sh.cfg.status = "HALTED BY OPERATOR".into();
    sh.force = false;
    save(&sh);
}

#[tauri::command]
fn resume(st: State<St>) {
    let mut sh = st.lock().unwrap();
    sh.cfg.paused_until = 0;
    sh.cfg.next_sync = 0; // re-evaluate: catch up if a slot was missed while halted
    sh.cfg.status = "RESUMED".into();
    save(&sh);
}

#[tauri::command]
fn sync_now(st: State<St>) -> Result<(), String> {
    let mut sh = st.lock().unwrap();
    if is_paused(&sh.cfg, now()) {
        return Err("halted".into());
    }
    sh.force = true;
    Ok(())
}

#[tauri::command]
fn set_repo(st: State<St>, repo: String) -> Result<(), String> {
    let repo = repo
        .trim()
        .trim_start_matches("https://github.com/")
        .trim_end_matches('/')
        .to_string();
    if !valid_repo(&repo) {
        return Err("expected owner/name".into());
    }
    let mut sh = st.lock().unwrap();
    sh.cfg.repo = repo;
    sh.cfg.next_sync = 0;
    sh.force = !is_paused(&sh.cfg, now());
    save(&sh);
    Ok(())
}

#[tauri::command]
fn set_autostart(st: State<St>, on: bool) -> Result<(), String> {
    apply_autostart(on)?;
    let mut sh = st.lock().unwrap();
    sh.cfg.autostart = on;
    sh.cfg.autostart_decided = true;
    save(&sh);
    Ok(())
}

/// Opens an issue from the feed in the default browser. The URL is rebuilt
/// here from validated parts, never taken from the page.
#[tauri::command]
fn open_issue(st: State<St>, repo_index: usize, number: u64) -> Result<(), String> {
    let repo = {
        let sh = st.lock().unwrap();
        sh.feed
            .as_ref()
            .and_then(|f| f["repos"][repo_index][0].as_str().map(str::to_owned))
            .ok_or("unknown repo")?
    };
    if !valid_repo(&repo) {
        return Err("bad repo name".into());
    }
    let url = format!("https://github.com/{repo}/issues/{number}");
    std::process::Command::new("rundll32")
        .args(["url.dll,FileProtocolHandler", &url])
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn quit(app: AppHandle) {
    app.exit(0);
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(win) = app.get_webview_window("main") {
                let _ = win.show();
                let _ = win.set_focus();
            }
        }))
        .setup(|app| {
            let dir = app.path().app_data_dir()?;
            fs::create_dir_all(&dir)?;
            let mut cfg: Cfg = fs::read_to_string(dir.join("state.json"))
                .ok()
                .and_then(|text| serde_json::from_str(&text).ok())
                .unwrap_or_default();
            cfg.next_sync = 0;
            if !valid_repo(&cfg.repo) {
                cfg.repo = DEFAULT_REPO.into();
            }

            // Stored feed is the gzip the cloud produced; drop it once it ages out.
            let feed_path = dir.join("feed.json.gz");
            let feed = fs::read(&feed_path).ok().and_then(|bytes| decode(&bytes).ok()).filter(|feed| {
                now() - feed["gen"].as_i64().unwrap_or(0) <= KEEP_SECS
            });
            if feed.is_none() {
                let _ = fs::remove_file(&feed_path);
            }

            // It is a startup app: register once on the first installed run.
            if !cfg.autostart_decided && !cfg!(debug_assertions) {
                cfg.autostart = apply_autostart(true).is_ok();
                cfg.autostart_decided = true;
            }

            let shared = Shared { cfg, feed, dir, syncing: false, force: false };
            save(&shared);
            let st: St = Arc::new(Mutex::new(shared));
            app.manage(st.clone());
            thread::spawn(move || scheduler(st));

            if let Some(win) = app.get_webview_window("main") {
                place(&win, false);
                let _ = win.show();
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            status, get_feed, set_mode, halt, resume, sync_now, set_repo, set_autostart, open_issue, quit
        ])
        .run(tauri::generate_context!())
        .expect("vothub failed to start");
}

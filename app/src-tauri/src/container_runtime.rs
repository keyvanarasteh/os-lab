//! Acquire a verified host container installer when Docker/Podman is absent. The system installer
//! and its licence remain interactive; the app never silently changes host virtualization.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

const DOWNLOAD: &str = r#"
import hashlib, os, sys, urllib.request
url, expected, target = sys.argv[1:]
part = target + '.part'
h = hashlib.sha256()
if os.path.isfile(target):
    with open(target, 'rb') as existing:
        for chunk in iter(lambda: existing.read(1024 * 1024), b''):
            h.update(chunk)
    if h.hexdigest() == expected:
        sys.exit(0)
h = hashlib.sha256()
try:
    with urllib.request.urlopen(url, timeout=60) as response, open(part, 'wb') as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk: break
            h.update(chunk)
            out.write(chunk)
    if h.hexdigest() != expected:
        raise RuntimeError('installer SHA-256 does not match Docker release notes')
    os.replace(part, target)
except Exception:
    if os.path.exists(part): os.remove(part)
    raise
"#;

pub struct Installer {
    pub url: &'static str,
    pub sha256: &'static str,
    pub name: &'static str,
}

pub fn installer() -> Option<Installer> {
    match (std::env::consts::OS, std::env::consts::ARCH) {
        ("macos", "aarch64") => Some(Installer {
            url: "https://desktop.docker.com/mac/main/arm64/245422/Docker.dmg",
            sha256: "9c6f13ce4edda2abf20d801552b6acb96acd3d64b3e91b50c4484353802758b5",
            name: "Docker-Desktop-4.98.0-arm64.dmg",
        }),
        ("macos", "x86_64") => Some(Installer {
            url: "https://desktop.docker.com/mac/main/amd64/245422/Docker.dmg",
            sha256: "96b53f9a4a807b6be6207d18f360b9778ff481e1d94b5027bdf1ae2a22d837cb",
            name: "Docker-Desktop-4.98.0-amd64.dmg",
        }),
        ("windows", "x86_64") => Some(Installer {
            url: "https://desktop.docker.com/win/main/amd64/245422/Docker%20Desktop%20Installer.exe",
            sha256: "cd6273d9eaa4f07fa7593fc6813d37e1004381cebc3f26047a2554fa5db24388",
            name: "Docker-Desktop-4.98.0-amd64.exe",
        }),
        _ => None,
    }
}

pub fn augment_path() {
    let mut paths: Vec<PathBuf> = std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default()).collect();
    if cfg!(target_os = "macos") {
        paths.extend([PathBuf::from("/opt/homebrew/bin"), PathBuf::from("/usr/local/bin"), PathBuf::from("/opt/podman/bin")]);
        if let Some(home) = std::env::var_os("HOME") {
            paths.push(PathBuf::from(home).join(".docker/bin"));
        }
    } else if cfg!(target_os = "windows") {
        if let Some(programs) = std::env::var_os("ProgramFiles") {
            paths.push(PathBuf::from(programs).join("Docker/Docker/resources/bin"));
        }
        if let Some(local) = std::env::var_os("LOCALAPPDATA") {
            paths.push(PathBuf::from(local).join("Programs/DockerDesktop/resources/bin"));
        }
    }
    if let Ok(path) = std::env::join_paths(paths) {
        std::env::set_var("PATH", path);
    }
}

pub fn is_ready() -> bool {
    ["docker", "podman"].iter().any(|name| works(name, &["info"]) && works(name, &["compose", "version"]))
}

pub fn cli_present() -> bool {
    ["docker", "podman"].iter().any(|name| Command::new(name).arg("--version")
        .stdout(Stdio::null()).stderr(Stdio::null()).status().is_ok_and(|status| status.success()))
}

#[derive(serde::Serialize)]
pub struct Status {
    pub ready: bool,
    pub cli_present: bool,
    pub can_download: bool,
    pub recovery: Option<String>,
    pub detail: String,
}

fn output(name: &str, args: &[&str]) -> Option<String> {
    let result = Command::new(name).args(args).output().ok()?;
    result.status.success().then(|| String::from_utf8_lossy(&result.stdout).trim().to_owned())
}

fn podman_machine() -> Option<String> {
    let list = output("podman", &["machine", "list", "--format", "json"])?;
    let rows: serde_json::Value = serde_json::from_str(&list).ok()?;
    rows.as_array()?.iter().find_map(|row| row.get("Name").or_else(|| row.get("name"))?.as_str().map(str::to_owned))
}

fn missing_colima_storage() -> Option<String> {
    let home = std::env::var_os("HOME")?;
    let path = PathBuf::from(home).join(".colima");
    if fs::symlink_metadata(&path).ok()?.file_type().is_symlink() && !path.exists() {
        let target = fs::read_link(&path).ok()?;
        return Some(format!("Colima's data folder ({}) is unavailable. Reconnect its storage volume, then retry.", target.display()));
    }
    None
}

fn desktop_executable() -> Option<PathBuf> {
    if cfg!(target_os = "windows") {
        for variable in ["ProgramFiles", "ProgramW6432", "LOCALAPPDATA"] {
            if let Some(base) = std::env::var_os(variable) {
                let suffix = if variable == "LOCALAPPDATA" { "Programs/DockerDesktop/Docker Desktop.exe" } else { "Docker/Docker/Docker Desktop.exe" };
                let path = PathBuf::from(base).join(suffix);
                if path.is_file() { return Some(path); }
            }
        }
    }
    None
}

pub fn status() -> Status {
    let docker_engine = works("docker", &["info"]);
    let podman_engine = works("podman", &["info"]);
    let ready = (docker_engine && works("docker", &["compose", "version"]))
        || (podman_engine && works("podman", &["compose", "version"]));
    let cli_present = cli_present();
    let can_download = installer().is_some();
    if ready {
        return Status { ready, cli_present, can_download, recovery: None, detail: String::new() };
    }
    if docker_engine || podman_engine {
        return Status { ready, cli_present, can_download: false, recovery: None,
            detail: "A container engine is running, but its Compose command is missing. Install the Compose plugin for Docker or Podman, then retry.".into() };
    }
    let (recovery, detail, no_engine) = match std::env::consts::OS {
        "macos" => {
            let context = output("docker", &["context", "show"]).unwrap_or_default();
            if context == "colima" {
                if let Some(problem) = missing_colima_storage() {
                    if podman_machine().is_some() {
                        (Some("podman".into()), format!("{problem} An existing Podman machine can be started instead."), false)
                    } else { (None, problem, false) }
                } else if cli_present && output("colima", &["version"]).is_some() {
                    (Some("colima".into()), "Colima is installed. os-lab can start it and recheck the container engine.".into(), false)
                } else { (None, "The selected Docker context is Colima, but Colima is unavailable. Reconnect it or choose another engine.".into(), false) }
            } else if Command::new("open").args(["-Ra", "Docker"]).stdout(Stdio::null()).stderr(Stdio::null()).status().is_ok_and(|s| s.success()) {
                (Some("desktop".into()), "Docker Desktop is installed. os-lab can open it and wait for the engine.".into(), false)
            } else if output("colima", &["version"]).is_some() && missing_colima_storage().is_none() {
                (Some("colima".into()), "Colima is installed. os-lab can start it and recheck the container engine.".into(), false)
            } else if podman_machine().is_some() {
                (Some("podman".into()), "An existing Podman machine is available. os-lab can start it.".into(), false)
            } else {
                (None, "No installed container engine can be started automatically. Get Docker Desktop or configure a Colima or Podman machine.".into(), true)
            }
        }
        "windows" => {
            if desktop_executable().is_some() {
                (Some("desktop".into()), "Docker Desktop is installed. os-lab can open it and wait for the engine.".into(), false)
            } else if podman_machine().is_some() {
                (Some("podman".into()), "An existing Podman machine is available. os-lab can start it.".into(), false)
            } else {
                (None, "No installed container engine can be started automatically. Get Docker Desktop or configure a Podman machine.".into(), true)
            }
        }
        "linux" => {
            if output("podman", &["--version"]).is_some()
                && output("systemctl", &["--user", "list-unit-files", "podman.socket", "--no-legend"]).is_some_and(|s| s.contains("podman.socket")) {
                (Some("podman-socket".into()), "os-lab can start the existing Podman user socket.".into(), false)
            } else if output("docker", &["--version"]).is_some()
                && Command::new("pkexec").arg("--version").stdout(Stdio::null()).stderr(Stdio::null()).status().is_ok_and(|s| s.success())
                && output("systemctl", &["list-unit-files", "docker.service", "--no-legend"]).is_some_and(|s| s.contains("docker.service")) {
                (Some("docker-service".into()), "os-lab can request authorization to start the Docker service.".into(), false)
            } else {
                (None, "No running engine was found. Start Docker or Podman, then retry.".into(), false)
            }
        }
        _ => (None, "No running container engine was found.".into(), false),
    };
    // Offer the Docker Desktop download only when no engine is installed at all. An engine that is
    // installed but unavailable (disconnected Colima volume, stopped machine) needs recovery, not a download.
    let can_download = can_download && no_engine && recovery.is_none();
    Status { ready, cli_present, can_download, recovery, detail }
}

fn run_bounded(program: &str, args: &[&str], timeout: Duration) -> Result<(), String> {
    let mut child = Command::new(program).args(args).stdout(Stdio::null()).stderr(Stdio::null())
        .spawn().map_err(|e| format!("Could not start {program}: {e}"))?;
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(exit)) if exit.success() => return Ok(()),
            Ok(Some(exit)) => return Err(format!("{program} exited with {exit}. Check its own logs, then retry.")),
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(250)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("{program} did not finish within {} seconds.", timeout.as_secs()));
            }
        }
    }
}

/// Start a backend already installed on the host after an explicit launcher action. Colima may
/// initialize its default VM; Podman is limited to an existing named machine.
pub fn recover() -> Result<String, String> {
    let initial = status();
    if initial.ready { return Ok("The container runtime is ready.".into()); }
    match initial.recovery.as_deref() {
        Some("colima") => run_bounded("colima", &["start"], Duration::from_secs(180))?,
        Some("podman") => {
            let machine = podman_machine().ok_or("No existing Podman machine was found")?;
            run_bounded("podman", &["machine", "start", &machine], Duration::from_secs(180))?;
        }
        Some("desktop") if cfg!(target_os = "macos") => run_bounded("open", &["-a", "Docker"], Duration::from_secs(15))?,
        Some("desktop") => {
            let exe = desktop_executable().ok_or("Docker Desktop is no longer installed")?;
            Command::new(exe).stdout(Stdio::null()).stderr(Stdio::null()).spawn()
                .map_err(|e| format!("Could not open Docker Desktop: {e}"))?;
        }
        Some("podman-socket") => run_bounded("systemctl", &["--user", "start", "podman.socket"], Duration::from_secs(30))?,
        Some("docker-service") => run_bounded("pkexec", &["systemctl", "start", "docker.service"], Duration::from_secs(120))?,
        _ => return Err(initial.detail),
    }
    let deadline = Instant::now() + Duration::from_secs(60);
    while Instant::now() < deadline {
        if is_ready() { return Ok("The container runtime is ready.".into()); }
        std::thread::sleep(Duration::from_secs(2));
    }
    Err("The engine started, but Docker or Podman with Compose did not become ready. Check its status and retry.".into())
}

fn works(name: &str, args: &[&str]) -> bool {
    let Ok(mut child) = Command::new(name).args(args).stdout(Stdio::null()).stderr(Stdio::null()).spawn() else {
        return false;
    };
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return status.success(),
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return false;
            }
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(100)),
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
                return false;
            }
        }
    }
}

pub fn download(python: &str, data_dir: &Path) -> Result<PathBuf, String> {
    let spec = installer().ok_or("No managed container installer is available for this platform")?;
    let dir = data_dir.join("installers");
    fs::create_dir_all(&dir).map_err(|e| format!("Could not create installer folder: {e}"))?;
    let dest = dir.join(spec.name);
    let mut cmd = Command::new(python);
    if python == "py" { cmd.arg("-3"); }
    let output = cmd.arg("-c").arg(DOWNLOAD).arg(spec.url).arg(spec.sha256).arg(&dest)
        .output().map_err(|e| format!("Could not download Docker Desktop: {e}"))?;
    if !output.status.success() {
        return Err(format!("Docker Desktop download failed: {}", String::from_utf8_lossy(&output.stderr).trim()));
    }
    Ok(dest)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn supported_installer_has_pinned_https_url_and_digest() {
        if let Some(spec) = installer() {
            assert!(spec.url.starts_with("https://desktop.docker.com/"));
            assert_eq!(spec.sha256.len(), 64);
            assert!(spec.sha256.chars().all(|c| c.is_ascii_hexdigit()));
        }
    }
}

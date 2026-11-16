//! App-managed Python bootstrap. Release builds ship a pinned uv helper, which downloads a
//! managed CPython into app data only when the user asks for it in the launcher.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

pub fn path_file(data_dir: &Path) -> PathBuf {
    data_dir.join("python-path.txt")
}

pub fn helper_name() -> Result<&'static str, String> {
    match (std::env::consts::OS, std::env::consts::ARCH) {
        ("macos", "aarch64") => Ok("uv-aarch64-apple-darwin"),
        ("macos", "x86_64") => Ok("uv-x86_64-apple-darwin"),
        ("windows", "x86_64") => Ok("uv-x86_64-pc-windows-msvc.exe"),
        ("linux", "x86_64") => Ok("uv-x86_64-unknown-linux-gnu"),
        ("linux", "aarch64") => Ok("uv-aarch64-unknown-linux-gnu"),
        (os, arch) => Err(format!("App-managed Python is unavailable on {os}/{arch}")),
    }
}

pub fn saved_python(data_dir: &Path) -> Option<String> {
    let text = fs::read_to_string(path_file(data_dir)).ok()?;
    let path = Path::new(text.trim());
    if !within_dir(path, &data_dir.join("python")) {
        return None;
    }
    Some(path.to_string_lossy().into_owned())
}

fn within_dir(path: &Path, dir: &Path) -> bool {
    if !path.is_absolute() || !path.is_file() {
        return false;
    }
    match (path.canonicalize(), dir.canonicalize()) {
        (Ok(file), Ok(root)) => file.starts_with(root),
        _ => false,
    }
}

pub fn install(helper: &Path, data_dir: &Path) -> Result<String, String> {
    if !helper.is_file() {
        return Err(format!("The Python setup helper is missing ({}). Rebuild the installer with stage-python-helper.mjs.", helper.display()));
    }
    fs::create_dir_all(data_dir).map_err(|e| format!("Could not create app data directory: {e}"))?;
    let install_dir = data_dir.join("python");
    let cache_dir = data_dir.join("python-cache");
    let output = Command::new(helper)
        .args(["python", "install", "3.12", "--no-bin", "--no-registry", "--no-config", "--system-certs"])
        .env("UV_PYTHON_INSTALL_DIR", &install_dir)
        .env("UV_CACHE_DIR", &cache_dir)
        .current_dir(data_dir)
        .output()
        .map_err(|e| format!("Could not run Python setup helper: {e}"))?;
    if !output.status.success() {
        return Err(format!("Python download failed: {}", String::from_utf8_lossy(&output.stderr).trim()));
    }
    let found = Command::new(helper)
        .args(["python", "find", "3.12", "--managed-python", "--no-python-downloads", "--no-project", "--no-config"])
        .env("UV_PYTHON_INSTALL_DIR", &install_dir)
        .env("UV_CACHE_DIR", &cache_dir)
        .current_dir(data_dir)
        .output()
        .map_err(|e| format!("Could not locate installed Python: {e}"))?;
    if !found.status.success() {
        return Err(format!("Could not locate installed Python: {}", String::from_utf8_lossy(&found.stderr).trim()));
    }
    let python = String::from_utf8_lossy(&found.stdout).trim().to_owned();
    let path = Path::new(&python);
    if !within_dir(path, &install_dir) {
        return Err("Python setup returned an unexpected interpreter path".to_string());
    }
    fs::write(path_file(data_dir), &python).map_err(|e| format!("Could not save Python path: {e}"))?;
    Ok(python)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn saved_python_rejects_missing_and_external_paths() {
        let dir = std::env::temp_dir().join(format!("os-lab-python-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        assert!(saved_python(&dir).is_none());
        fs::write(path_file(&dir), "/bin/sh").unwrap();
        assert!(saved_python(&dir).is_none());
        fs::remove_dir_all(&dir).unwrap();
    }
}

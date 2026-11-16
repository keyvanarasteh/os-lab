#!/usr/bin/env bash
# Pre-flight (docker-android-cheat-sheet.md §0): OS / KVM / docker / ports / disk.
# Run before `make up`. Exit code 0 = safe to proceed.
set -uo pipefail

FAIL=0
ok()   { echo "  [ok]   $*"; }
bad()  { echo "  [FAIL] $*"; FAIL=1; }
warn() { echo "  [warn] $*"; }

ENV_FILE="${LAB_ENV_FILE:-.env}"
if [[ "${LAB_ENV_LOADED:-0}" != "1" && -f "$ENV_FILE" ]]; then
  set -a
  . "$ENV_FILE"
  set +a
fi
MODE="${LAB_MODE:-dynamic}"
STATIC=0
[[ "$MODE" == "static" ]] && STATIC=1

echo "== pre-flight checks =="
echo "mode: $MODE"

# --- OS / virtualization ------------------------------------------------
OS="$(uname -s)"
ARCH="$(uname -m)"
echo "host: $OS $ARCH"

case "$OS" in
  Linux)
    if [[ "$STATIC" -eq 1 ]]; then
      ok "static mode: /dev/kvm not required"
    elif [[ -e /dev/kvm ]]; then
      if [[ -r /dev/kvm && -w /dev/kvm ]] || [[ "$(id -u)" -eq 0 ]]; then
        ok "/dev/kvm present and accessible"
      else
        bad "/dev/kvm not accessible by $(id -un) — add user to the kvm group and re-login (sudo make setup)"
      fi
    else
      bad "/dev/kvm missing — enable VT-x/AMD-V in BIOS, then: sudo modprobe kvm kvm_intel (or kvm_amd)"
    fi
    if [[ "$STATIC" -eq 0 ]] && command -v kvm-ok >/dev/null 2>&1; then
      kvm-ok || bad "kvm-ok failed — see cheat sheet §0"
    fi
    ;;
  Darwin)
    if [[ "$STATIC" -eq 1 ]]; then
      warn "static mode runs in Docker Desktop without KVM"
    else
      warn "macOS cannot run docker-android natively (Docker Desktop exposes no /dev/kvm)."
      warn "Use an Ubuntu VM with nested virtualization per ../docker-android-cheat-sheet.md §3–§4."
      warn "Apple Silicon: x86 emulator images run under QEMU TCG — impractically slow."
      FAIL=1
    fi
    ;;
  MINGW*|CYGWIN*|MSYS*)
    if [[ "$STATIC" -eq 1 ]]; then
      warn "static mode runs in Docker Desktop without KVM"
    else
      warn "Windows: run inside WSL2 with nestedVirtualization=true (Win11 only) — cheat sheet §2."
      FAIL=1
    fi
    ;;
esac

[[ "$ARCH" == "x86_64" ]] || warn "arch=$ARCH — docker-android images are x86/x86_64"

# --- container runtime --------------------------------------------------
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  ok "docker: $(docker --version 2>/dev/null || echo present) with Compose"
elif command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  ok "podman: $(podman --version 2>/dev/null || echo present) with Compose"
else
  bad "no working Docker or Podman engine with Compose (run: sudo make setup)"
fi

if [[ "$STATIC" -eq 1 ]]; then
  ok "static mode: adb not required"
elif command -v adb >/dev/null 2>&1; then
  ok "adb: $(adb version 2>/dev/null | head -1)"
else
  warn "adb not found (sudo apt install adb, or: make platform-tools)"
fi

# --- port availability ---------------------------------------------------
if [[ "$STATIC" -eq 1 ]]; then
  PORTS=(8000 8080 8081)
else
  PORTS=(6080 5554 5555 8000 8080 8081)
fi
for p in "${PORTS[@]}"; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$p") 2>/dev/null; then
    exec 3>&- 3<&- 2>/dev/null
    bad "port $p already in use — stop the conflicting service or edit docker-compose.yml"
  else
    ok "port $p free"
  fi
done

# --- disk -----------------------------------------------------------------
AVAIL_MB="$(df -Pm . 2>/dev/null | awk 'NR==2 {print $4}')"
MIN_MB=10240
[[ "$STATIC" -eq 1 ]] && MIN_MB=5120
if [[ -n "${AVAIL_MB:-}" && "$AVAIL_MB" -lt "$MIN_MB" ]]; then
  bad "only ${AVAIL_MB} MB free — need ≥ $((MIN_MB / 1024)) GB"
else
  ok "disk: ${AVAIL_MB:-?} MB free"
fi

echo "== pre-flight done: $([[ $FAIL -eq 0 ]] && echo PASS || echo FAIL) =="
exit "$FAIL"


#!/usr/bin/env bash
set -euo pipefail

# OS-14: Node.js ve Python arac zinciri yukleyici

NODE_MAJOR=22
MODE="${1:---check}"

log() {
    echo "[OS-14] $*"
}

check_versions() {
    log "Sistem kontrol ediliyor..."

    if command -v node >/dev/null 2>&1; then
        log "Node.js: $(node --version)"
    else
        log "Node.js kurulu degil."
    fi

    if command -v npm >/dev/null 2>&1; then
        log "npm: $(npm --version)"
    else
        log "npm kurulu degil."
    fi

    if command -v python3 >/dev/null 2>&1; then
        log "Python 3: $(python3 --version)"
    else
        log "Python 3 kurulu degil."
    fi

    if command -v python >/dev/null 2>&1; then
        log "python: $(python --version)"
    else
        log "python komutu bulunamadi."
    fi
}

install_tools() {
    if [[ $EUID -ne 0 ]]; then
        echo "Kurulum icin sudo kullanin."
        exit 1
    fi

    if ! command -v apt-get >/dev/null 2>&1; then
        echo "Bu betik Ubuntu/Debian icindir."
        exit 1
    fi

    log "Paket listesi guncelleniyor..."
    apt-get update

    log "Temel paketler kuruluyor..."
    apt-get install -y curl ca-certificates python3 \
        python3-pip python-is-python3

    log "NodeSource deposu hazirlaniyor..."
    curl -fsSL \
        "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" \
        -o /tmp/os14-nodesource.sh

    bash /tmp/os14-nodesource.sh

    log "Node.js kuruluyor..."
    apt-get install -y nodejs

    log "Kurulum tamamlandi."
    check_versions
}

case "$MODE" in
    --check)
        check_versions
        ;;
    --install)
        install_tools
        ;;
    *)
        echo "Kullanim: $0 --check | --install"
        exit 1
        ;;
esac

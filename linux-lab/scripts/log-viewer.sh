#!/bin/bash
# OS-29 log viewer: menu to view, page, search, follow and count a log.
# Usage: log-viewer.sh [LOG_FILE]   (default /var/log/syslog, journald if absent)

if [ "$#" -ge 1 ]; then
    LOG_FILE="$1"
    USE_JOURNAL=0
elif [ -f /var/log/syslog ]; then
    LOG_FILE="/var/log/syslog"
    USE_JOURNAL=0
elif command -v journalctl >/dev/null 2>&1; then
    LOG_FILE="journalctl"
    USE_JOURNAL=1
else
    LOG_FILE="/var/log/syslog"
    USE_JOURNAL=0
fi

if [ "$USE_JOURNAL" -eq 0 ]; then
    if [ ! -f "$LOG_FILE" ]; then
        echo "Hata: Log dosyasi bulunamadi: $LOG_FILE"
        exit 1
    fi
    if [ ! -r "$LOG_FILE" ]; then
        echo "Hata: Log dosyasi okunamiyor: $LOG_FILE (sudo ile veya adm grubundan okuyun)"
        exit 1
    fi
fi

# Log lines are untrusted: drop terminal control bytes (ESC, CSI/OSC starts, etc.) but keep tab/newline.
clean() {
    LC_ALL=C tr -d '\000-\010\013\014\016-\037\177'
}

emit() { # all lines of the log
    if [ "$USE_JOURNAL" -eq 1 ]; then
        journalctl --no-pager -o short 2>/dev/null
    else
        cat -- "$LOG_FILE"
    fi
}

while true; do
    echo "===== OS-29 LOG VIEWER ====="
    echo "Kaynak: $LOG_FILE"
    echo "1 - Ilk 20 kaydi goster"
    echo "2 - Son 20 kaydi goster"
    echo "3 - Canli log takibi"
    echo "4 - Kayit sayisini goster"
    echo "5 - Sayfa sayfa gez"
    echo "6 - Ara"
    echo "7 - Cikis"
    if ! read -r -p "Seciminiz: " secim; then
        echo
        exit 0
    fi

    case "$secim" in
        1) emit | head -n 20 | clean ;;
        2) emit | tail -n 20 | clean ;;
        3)
            if [ "$USE_JOURNAL" -eq 1 ]; then
                journalctl --no-pager -n 20 -f 2>/dev/null | clean
            else
                tail -n 20 -F -- "$LOG_FILE" | clean
            fi
            ;;
        4) emit | wc -l ;;
        5) emit | clean | ${PAGER:-less} ;;
        6)
            if ! read -r -p "Aranacak metin: " aranan; then
                echo
                exit 0
            fi
            if [ -z "$aranan" ]; then
                echo "Bos arama"
            else
                emit | clean | grep -n -i -F -e "$aranan" || echo "Eslesme yok"
            fi
            ;;
        7) exit 0 ;;
        *) echo "Gecersiz secim" ;;
    esac
done

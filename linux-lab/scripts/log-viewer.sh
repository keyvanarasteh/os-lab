#!/bin/bash

LOG_FILE="${1:-/var/log/syslog}"

if [ ! -f "$LOG_FILE" ]; then
    echo "Hata: Log dosyasi bulunamadi: $LOG_FILE"
    exit 1
fi

while true; do
    echo "===== OS-29 LOG VIEWER ====="
    echo "1 - Ilk 20 kaydi goster"
    echo "2 - Son 20 kaydi goster"
    echo "3 - Canli log takibi"
    echo "4 - Kayit sayisini goster"
    echo "5 - Cikis"
    read -r -p "Seciminiz: " secim

    case "$secim" in
        1) head -n 20 "$LOG_FILE" ;;
        2) tail -n 20 "$LOG_FILE" ;;
        3) tail -n 20 -F "$LOG_FILE" ;;
        4) wc -l "$LOG_FILE" ;;
        5) exit 0 ;;
        *) echo "Gecersiz secim" ;;
    esac
done

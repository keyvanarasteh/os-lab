#!/usr/bin/env bash
# PENT-05 — Binary hardening verification (readelf tabanlı mitigation denetimi)
#
# Kullanım:
#   pent-05-hardening-audit.sh [--json] <ELF dosyası>...
#   pent-05-hardening-audit.sh -h|--help
#
# İkili başına kontroller:
#   NX       GNU_STACK segmenti çalıştırılabilir değil (RW, RWE değil)
#   PIE      ELF tipi DYN (ASLR kod segmentine de uygulanabilir); paylaşımlı kütüphane = dso
#   CANARY   __stack_chk_fail sembolü var (-fstack-protector*)
#   RELRO    GNU_RELRO + BIND_NOW = full, yalnız GNU_RELRO = partial, hiçbiri = none
#   FORTIFY  __*_chk sembolleri var (-D_FORTIFY_SOURCE) [bilgi amaçlı, sonucu etkilemez]
# Sistem kontrolü:
#   ASLR     /proc/sys/kernel/randomize_va_space (2 = full, 1 = partial, 0 = off)
#
# Çıkış kodu: 0 = hepsi sağlam, 1 = en az bir zayıflık, 2 = kullanım/dosya/araç hatası
# Ortam: PENT05_READELF (varsayılan: readelf), PENT05_ASLR_FILE (testler için)
set -euo pipefail

READELF="${PENT05_READELF:-readelf}"
ASLR_FILE="${PENT05_ASLR_FILE:-/proc/sys/kernel/randomize_va_space}"

usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; }

JSON=0
FILES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --json) JSON=1 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; FILES+=("$@"); break ;;
    -*) echo "bilinmeyen seçenek: $1" >&2; usage >&2; exit 2 ;;
    *) FILES+=("$1") ;;
  esac
  shift
done

if [ "${#FILES[@]}" -eq 0 ]; then usage >&2; exit 2; fi
if ! command -v "$READELF" >/dev/null 2>&1; then
  echo "hata: '$READELF' bulunamadı (Debian/Ubuntu: sudo apt install binutils)" >&2
  exit 2
fi

aslr_state() {
  local v
  if [ -r "$ASLR_FILE" ]; then
    v="$(tr -d '[:space:]' < "$ASLR_FILE")"
    case "$v" in
      2) echo full ;; 1) echo partial ;; 0) echo off ;; *) echo unknown ;;
    esac
  else
    echo unknown
  fi
}

json_str() {
  local s="$1"
  s="${s//\\/\\\\}"; s="${s//\"/\\\"}"
  printf '"%s"' "$s"
}

# audit_one <dosya> — sonuçları R_* değişkenlerine yazar
audit_one() {
  local f="$1" hdr prog dyn syms stack
  R_ERR=""; R_TYPE=""; R_NX=no; R_PIE=no; R_CANARY=no; R_RELRO=none
  R_FORTIFY=0; R_MISSING=()

  if [ ! -f "$f" ]; then R_ERR="dosya bulunamadı"; return; fi
  if ! hdr="$("$READELF" -h -W "$f" 2>/dev/null)"; then R_ERR="ELF dosyası değil"; return; fi
  prog="$("$READELF" -l -W "$f" 2>/dev/null || true)"
  dyn="$("$READELF" -d -W "$f" 2>/dev/null || true)"
  syms="$("$READELF" -s -W "$f" 2>/dev/null || true)"

  R_TYPE="$(awk -F: '/^ *Type:/{gsub(/^ +/, "", $2); split($2, a, " "); print a[1]; exit}' <<<"$hdr")"

  # NX: GNU_STACK yoksa çoğu mimaride yığın çalıştırılabilir kabul edilir.
  stack="$(awk '$1 == "GNU_STACK" {print; exit}' <<<"$prog")"
  case "$stack" in
    "") R_NX=no ;;
    *RWE*) R_NX=no ;;
    *) R_NX=yes ;;
  esac

  # PIE: DYN + INTERP = PIE çalıştırılabilir; INTERP yoksa paylaşımlı kütüphane (dso).
  case "$R_TYPE" in
    DYN) if awk '$1 == "INTERP" {f = 1} END {exit !f}' <<<"$prog"; then R_PIE=yes; else R_PIE=dso; fi ;;
    *) R_PIE=no ;;
  esac

  if awk '$1 == "GNU_RELRO" {f = 1} END {exit !f}' <<<"$prog"; then
    if grep -qE '\(BIND_NOW\)|\(FLAGS\).*BIND_NOW|Flags:.*\bNOW\b' <<<"$dyn"; then R_RELRO=full; else R_RELRO=partial; fi
  fi

  if grep -qE '__stack_chk_fail|__stack_chk_guard|__intel_security_cookie' <<<"$syms"; then R_CANARY=yes; fi

  R_FORTIFY="$( (grep -oE '__[a-z0-9_]+_chk\b' <<<"$syms" || true) | sort -u | wc -l | tr -d ' ')"

  [ "$R_NX" = yes ] || R_MISSING+=("nx")
  [ "$R_PIE" = no ] && R_MISSING+=("pie")
  [ "$R_CANARY" = yes ] || R_MISSING+=("canary")
  [ "$R_RELRO" = full ] || R_MISSING+=("relro")
  return 0
}

advice() {
  case "$1" in
    nx)     echo "NX kapalı: yığın çalıştırılabilir. Düzeltme: -Wl,-z,noexecstack (execstack kullanmayın)" ;;
    pie)    echo "PIE yok: kod segmenti sabit adreste, ROP kolaylaşır. Düzeltme: -fPIE -pie" ;;
    canary) echo "Stack canary yok: yığın taşması fark edilmez. Düzeltme: -fstack-protector-strong" ;;
    relro)  echo "RELRO tam değil: GOT üzerine yazılabilir. Düzeltme: -Wl,-z,relro,-z,now" ;;
  esac
}

ASLR="$(aslr_state)"
WEAK=0; ERRORS=0
ROWS=()

for f in "${FILES[@]}"; do
  audit_one "$f"
  if [ -n "$R_ERR" ]; then
    ERRORS=$((ERRORS + 1)); verdict=error
  elif [ "${#R_MISSING[@]}" -gt 0 ]; then
    WEAK=$((WEAK + 1)); verdict=weak
  else
    verdict=hardened
  fi
  missing="${R_MISSING[*]:-}"
  ROWS+=("$f|$R_ERR|$R_TYPE|$R_NX|$R_PIE|$R_CANARY|$R_RELRO|$R_FORTIFY|$verdict|$missing")
done

if [ "$JSON" = 1 ]; then
  printf '{"tool":"pent-05-hardening-audit","aslr":"%s","binaries":[' "$ASLR"
  sep=""
  for row in "${ROWS[@]}"; do
    IFS='|' read -r f err type nx pie canary relro fortify verdict missing <<<"$row"
    printf '%s{"file":%s,' "$sep" "$(json_str "$f")"
    if [ "$verdict" = error ]; then
      printf '"verdict":"error","error":%s}' "$(json_str "$err")"
    else
      printf '"elf_type":%s,"nx":%s,"pie":"%s","canary":%s,"relro":"%s","fortify_functions":%s,"verdict":"%s","missing":[' \
        "$(json_str "$type")" "$([ "$nx" = yes ] && echo true || echo false)" "$pie" \
        "$([ "$canary" = yes ] && echo true || echo false)" "$relro" "$fortify" "$verdict"
      msep=""
      for m in $missing; do printf '%s"%s"' "$msep" "$m"; msep=","; done
      printf ']}'
    fi
    sep=","
  done
  printf '],"weak":%d,"errors":%d}\n' "$WEAK" "$ERRORS"
else
  echo "PENT-05 Binary Hardening Denetimi"
  echo "Sistem ASLR (randomize_va_space): $ASLR"
  echo
  printf '%-28s %-6s %-6s %-7s %-8s %-8s %s\n' DOSYA NX PIE CANARY RELRO FORTIFY SONUC
  for row in "${ROWS[@]}"; do
    IFS='|' read -r f err type nx pie canary relro fortify verdict missing <<<"$row"
    name="$(basename "$f")"
    if [ "$verdict" = error ]; then
      printf '%-28s HATA: %s\n' "$name" "$err"
      continue
    fi
    case "$verdict" in hardened) v=SAGLAM ;; *) v=ZAYIF ;; esac
    printf '%-28s %-6s %-6s %-7s %-8s %-8s %s\n' "$name" "$nx" "$pie" "$canary" "$relro" "$fortify" "$v"
  done
  for row in "${ROWS[@]}"; do
    IFS='|' read -r f err type nx pie canary relro fortify verdict missing <<<"$row"
    [ "$verdict" = weak ] || continue
    echo
    echo "[$(basename "$f")]"
    for m in $missing; do echo "  - $(advice "$m")"; done
    [ "$fortify" = 0 ] && echo "  - (bilgi) FORTIFY yok: -O2 -D_FORTIFY_SOURCE=2 ile derleyin"
  done
  case "$ASLR" in
    off) echo; echo "[sistem] ASLR kapalı. Düzeltme: sudo sysctl -w kernel.randomize_va_space=2" ;;
    partial) echo; echo "[sistem] ASLR kısmi (heap rastgele değil). Önerilen değer: 2" ;;
    unknown) echo; echo "[sistem] ASLR durumu okunamadı (Linux dışı sistem ya da /proc yok)" ;;
  esac
fi

if [ "$ERRORS" -gt 0 ]; then exit 2; fi
if [ "$WEAK" -gt 0 ] || [ "$ASLR" = off ]; then exit 1; fi
exit 0
